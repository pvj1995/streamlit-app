from __future__ import annotations

import hashlib
import json
import textwrap
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from tourism_dashboard.ai import (
    generate_region_ai_commentary,
    get_cached_ai_commentary,
    store_cached_ai_commentary,
)
from tourism_dashboard.analytics import (
    build_top_bottom_group_sections,
    build_market_ai_context,
    compute_market_structure_for_subset,
    compute_region_aggregates,
    compute_market_growth_for_subset,
    aggregate_indicator_with_rules,
    get_market_cols_for_year,
    get_top_bottom_reference_indicators,
)
from tourism_dashboard.assets import (
    get_button_image_path,
    prepare_group_button_image,
    render_ai_section_header,
)
from tourism_dashboard.config import (
    AGG_RULES,
    GROUP_COLOR_EMOJI,
    INDIKATORJI_Z_INDEKSI,
    INDIKATORJI_Z_OPOMBO,
    MARKET_COLOR_MAP,
    MARKET_PREFIX,
    SKUPNO_OPOZORILO_AGREGACIJA,
)
from tourism_dashboard.formatting import (
    ColumnWidth,
    format_indicator_value_map,
    format_indicator_value_tables,
    format_pct,
    format_si_number,
    is_rate_like,
    is_percent_like,
    make_localized_column_config,
)
from tourism_dashboard.helpers import get_secret_value, shorten_label, col_for_year
from tourism_dashboard.maps import (
    MUNICIPAL_DISPLAY_SIMPLIFY_TOLERANCE,
    build_region_geojson_from_municipalities,
    build_simplified_municipality_geojson,
    cache_key_for_municipalities_map,
    cache_key_for_regions_map,
    render_map_municipalities,
    render_map_regions,
)
from tourism_dashboard.models import DashboardContext


if TYPE_CHECKING:
    from streamlit_image_select import image_select
else:
    try:
        from streamlit_image_select import image_select
    except Exception:
        image_select = None


def show_shared_warning_if_needed_indicator(indicator_name: str):
    if indicator_name not in INDIKATORJI_Z_OPOMBO:
        return
    st.warning(SKUPNO_OPOZORILO_AGREGACIJA["title"], icon="⚠️")


def show_shared_warning_if_needed_map(indicator_name: str):
    if indicator_name not in INDIKATORJI_Z_OPOMBO:
        return
    st.warning(SKUPNO_OPOZORILO_AGREGACIJA["text"], icon="⚠️")


def green_metric(label, value):
    st.markdown(
        f"""
        <div style="
            padding: 0.75rem;
            border-radius: 0.5rem;
            background-color: #f0fdf4;
            border: 1px solid #16a34a;
            text-align: center;
        ">
            <div style="color:#15803d; font-size:0.85rem;">{label}</div>
            <div style="color:#166534; font-size:1.5rem; font-weight:600;">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def green_metric_small(label, value):
    st.markdown(
        f"""
        <div style="
            margin-top: 0.35rem;
            padding: 0.45rem 0.55rem;
            border-radius: 0.45rem;
            background-color: #f0fdf4;
            border: 1px solid #16a34a;
            line-height: 1.15;
        ">
            <div style="color:#15803d; font-size:0.75rem;">{label}</div>
            <div style="color:#166534; font-size:1.05rem; font-weight:600;">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_filtered_indicator_groups(
    indicator_cols: list[str],
    grouped_indicators: dict[str, list[str]],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    grouped_filtered: dict[str, list[str]] = {}
    indicator_to_group: dict[str, str] = {}
    indicator_set = set(indicator_cols)

    for group_name, items in grouped_indicators.items():
        filtered = [indicator for indicator in items if indicator in indicator_set]
        if not filtered:
            continue
        grouped_filtered[group_name] = filtered
        for indicator in filtered:
            indicator_to_group.setdefault(indicator, group_name)

    return grouped_filtered, indicator_to_group


def build_group_selector_specs(
    indicator_cols: list[str],
    grouped_filtered: dict[str, list[str]],
) -> list[dict[str, Any]]:
    return [
        {"key": "__all__", "label": "Vsi kazalniki", "count": len(indicator_cols)},
        {
            "key": "Družbeni kazalniki",
            "label": "Družbeni kazalniki",
            "count": len(grouped_filtered.get("Družbeni kazalniki", [])),
        },
        {
            "key": "Okoljski kazalniki",
            "label": "Okoljski kazalniki",
            "count": len(grouped_filtered.get("Okoljski kazalniki", [])),
        },
        {
            "key": "Ekonomski nastanitveni in tržni turistični kazalniki",
            "label": "Nastanitveni\nin tržni",
            "count": len(grouped_filtered.get("Ekonomski nastanitveni in tržni turistični kazalniki", [])),
        },
        {
            "key": "Ekonomsko poslovni kazalniki turistične dejavnosti",
            "label": "Ekon.\nposlovni",
            "count": len(grouped_filtered.get("Ekonomsko poslovni kazalniki turistične dejavnosti", [])),
        },
    ]


def render_group_selector(
    group_col: str,
    indicator_cols: list[str],
    grouped_filtered: dict[str, list[str]],
) -> str:
    selector_state_key = f"sel_group_img_{group_col}"
    if selector_state_key not in st.session_state:
        st.session_state[selector_state_key] = "__all__"

    group_specs = build_group_selector_specs(indicator_cols, grouped_filtered)
    valid_group_keys = {spec["key"] for spec in group_specs}
    if st.session_state[selector_state_key] not in valid_group_keys:
        st.session_state[selector_state_key] = "__all__"

    st.markdown("**Skupina kazalnikov**")

    selector_images = []
    image_selector_ready = image_select is not None
    for spec in group_specs:
        image_path = get_button_image_path(spec["key"])
        if not image_path.exists():
            image_selector_ready = False
            selector_images.append("")
            continue
        prepared_path = prepare_group_button_image(str(image_path), "")
        selector_images.append(prepared_path or str(image_path))

    default_idx = next(
        (index for index, spec in enumerate(group_specs) if spec["key"] == st.session_state[selector_state_key]),
        0,
    )

    if image_selector_ready:
        image_select_fn = image_select
        selected_value = image_select_fn(
            label="",
            images=selector_images,
            index=default_idx,
            use_container_width=False,
            return_value="index",
            key=f"sel_group_img_component_{group_col}",
        )

        selected_idx = default_idx
        if isinstance(selected_value, int) and 0 <= selected_value < len(group_specs):
            selected_idx = selected_value

        candidate = group_specs[selected_idx]
        if candidate["key"] == "__all__" or candidate["count"] > 0:
            st.session_state[selector_state_key] = candidate["key"]
    else:
        st.warning(
            "Manjka komponenta `streamlit-image-select` ali ena od slik za gumbe. "
            "Uporabljam rezervni izbor."
        )
        fallback_options: list[str] = [str(spec["key"]) for spec in group_specs]
        fallback_labels: dict[str, str] = {
            "__all__": f"Vsi kazalniki ({len(indicator_cols)})",
            "Družbeni kazalniki": f"Družbeni kazalniki ({len(grouped_filtered.get('Družbeni kazalniki', []))})",
            "Okoljski kazalniki": f"Okoljski kazalniki ({len(grouped_filtered.get('Okoljski kazalniki', []))})",
            "Ekonomski nastanitveni in tržni turistični kazalniki": (
                "Ekonomski nastanitveni in tržni turistični kazalniki "
                f"({len(grouped_filtered.get('Ekonomski nastanitveni in tržni turistični kazalniki', []))})"
            ),
            "Ekonomsko poslovni kazalniki turistične dejavnosti": (
                "Ekonomsko poslovni kazalniki turistične dejavnosti "
                f"({len(grouped_filtered.get('Ekonomsko poslovni kazalniki turistične dejavnosti', []))})"
            ),
        }

        def format_fallback_group_label(key: str) -> str:
            return fallback_labels[key] if key in fallback_labels else key

        selected_fallback = st.selectbox(
            "Skupina kazalnikov",
            options=fallback_options,
            index=default_idx,
            format_func=format_fallback_group_label,
            key=f"sel_group_ind_{group_col}",
        )
        st.session_state[selector_state_key] = selected_fallback

    return st.session_state[selector_state_key]


def build_region_indicator_table(
    region_df: pd.DataFrame,
    indicator: str,
    region_total,
    view_title: str,
) -> pd.DataFrame:
    table = pd.DataFrame(
        {
            "Občina": region_df["Občine"].astype(str),
            "Vrednost": region_df[indicator].astype(float).apply(lambda value: format_indicator_value_tables(indicator, value)),
        }
    )

    if region_total and not np.isnan(region_total) and region_total != 0 and not is_rate_like(indicator):
        if indicator in INDIKATORJI_Z_INDEKSI:
            table[f"Indeks {view_title}"] = round((table["Vrednost"] / region_total) * 100, 1)
        else:
            table[f"Delež {view_title} (%)"] = round(table["Vrednost"] / region_total, 3)

    return table.sort_values("Vrednost", ascending=False, na_position="last")


def format_indicator_option_label(indicator: str, indicator_to_group: dict[str, str]) -> str:
    group_name = indicator_to_group[indicator] if indicator in indicator_to_group else ""
    emoji = GROUP_COLOR_EMOJI[group_name] if group_name in GROUP_COLOR_EMOJI else "•"
    return f"{emoji} {indicator}"


def prepend_rank_column(df: pd.DataFrame, column_name: str = "#") -> pd.DataFrame:
    ranked_df = df.reset_index(drop=True).copy()
    ranked_df.insert(0, column_name, np.arange(1, len(ranked_df) + 1))
    return ranked_df


def prefix_rank_to_label_column(df: pd.DataFrame, label_column: str) -> pd.DataFrame:
    ranked_df = df.reset_index(drop=True).copy()
    ranked_df[label_column] = [
        f"{index}. {value}"
        for index, value in enumerate(ranked_df[label_column].astype(str), start=1)
    ]
    return ranked_df


def ranked_column_config(
    df: pd.DataFrame,
    *,
    source_columns: dict[str, str] | None = None,
    rank_column_name: str = "#",
    width_overrides: dict[str, ColumnWidth] | None = None,
) -> dict[str, Any]:
    width_overrides = width_overrides or {}
    column_config = make_localized_column_config(
        df,
        source_columns=source_columns,
        width_overrides=width_overrides,
    )
    if rank_column_name in df.columns:
        column_config[rank_column_name] = st.column_config.NumberColumn(
            rank_column_name,
            help="Rang",
            format="%d",
            width=width_overrides.get(rank_column_name, "small"),
        )
    return column_config


def render_ranked_dataframe(
    df: pd.DataFrame,
    *,
    source_columns: dict[str, str] | None = None,
    width_overrides: dict[str, ColumnWidth] | None = None,
    use_container_width: str = 'stretch',
    hide_index: bool = True,
    height: int | None = None,
) -> None:
    ranked_df = prepend_rank_column(df)
    dataframe_kwargs: dict[str, Any] = {
        "width": use_container_width,
        "hide_index": hide_index,
        "column_config": ranked_column_config(
            ranked_df,
            source_columns=source_columns,
            width_overrides=width_overrides,
        ),
    }
    if height is not None:
        dataframe_kwargs["height"] = height

    st.dataframe(
        ranked_df,
        **dataframe_kwargs,
    )


def _session_geojson_cache(key: str) -> dict[str, dict[str, Any] | None]:
    cache = st.session_state.get(key)
    if not isinstance(cache, dict):
        cache = {}
        st.session_state[key] = cache
    return cast(dict[str, dict[str, Any] | None], cache)


def _get_display_geojson(ctx: DashboardContext) -> dict[str, Any] | None:
    geojson_obj = cast(dict[str, Any] | None, getattr(ctx, "geojson_obj", None))
    geojson_prepared = bool(getattr(ctx, "geojson_prepared", False))
    geojson_signature = cast(str | None, getattr(ctx, "geojson_signature", None))

    if geojson_obj is None or geojson_prepared:
        return geojson_obj
    cache_key = (
        f"{geojson_signature or 'no_geojson'}|municipal_display|"
        f"{MUNICIPAL_DISPLAY_SIMPLIFY_TOLERANCE}"
    )
    cache = _session_geojson_cache("_municipal_display_geojson_cache")
    display_geojson = cache.get(cache_key)
    if display_geojson is None:
        display_geojson = build_simplified_municipality_geojson(
            geojson_obj,
            tolerance=MUNICIPAL_DISPLAY_SIMPLIFY_TOLERANCE,
        )
        cache[cache_key] = display_geojson
    return display_geojson


def _get_regions_geojson(
    *,
    ctx: DashboardContext,
    municipality_to_region: dict[str, str],
    group_col: str,
) -> dict[str, Any] | None:
    if ctx.geojson_obj is None or ctx.geojson_name_prop is None:
        return None
    cache_key = f"{ctx.data_signature}|{ctx.geojson_signature or 'no_geojson'}|{group_col}"
    cache = _session_geojson_cache("_regions_geojson_cache")
    regions_geojson = cache.get(cache_key)
    if regions_geojson is None:
        regions_geojson = build_region_geojson_from_municipalities(
            ctx.geojson_obj,
            ctx.geojson_name_prop,
            municipality_to_region,
            group_col=group_col,
        )
        cache[cache_key] = regions_geojson
    return regions_geojson


def wrap_market_chart_label(label: str, width: int = 18) -> str:
    wrapped = textwrap.wrap(
        str(label),
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return "<br>".join(wrapped) if wrapped else str(label)


def normalize_market_display_label(label: str) -> str:
    mapping = {
        "DACH trgi": "DACH trgi (nemško govoreči trgi: D, A in CH)",
    }
    return mapping.get(str(label).strip(), str(label).strip())


def shorten_market_axis_label(label: str) -> str:
    return str(label).split("(", 1)[0].strip()


def format_growth_label(value: float) -> str:
    if pd.isna(value):
        return "—"
    return format_pct(float(value) * 100.0, 1)


def render_market_growth_chart(growth_df: pd.DataFrame, title: str) -> None:
    if growth_df.empty:
        st.info("Za izbran prikaz ni dovolj podatkov o rasti po trgih.")
        return

    chart_df = growth_df.copy().dropna(subset=["Rast_raw"])
    if chart_df.empty:
        st.info("Za izbran prikaz ni dovolj podatkov o rasti po trgih.")
        return

    chart_df["Trg"] = chart_df["Trg"].apply(normalize_market_display_label)
    chart_df = chart_df.sort_values("Rast_raw", ascending=False).reset_index(drop=True)
    chart_df["Trg_chart"] = chart_df["Trg"].apply(shorten_market_axis_label).apply(wrap_market_chart_label)
    chart_df["Rast_prikaz"] = chart_df["Rast_raw"]
    chart_df["Rast_label"] = chart_df["Rast_raw"].apply(format_growth_label)

    max_abs_growth = float(np.nanmax(np.abs(chart_df["Rast_raw"].values)))
    if not np.isfinite(max_abs_growth) or max_abs_growth <= 0:
        max_abs_growth = 0.05
    axis_padding = max(max_abs_growth * 0.1, 0.02)
    axis_limit = max_abs_growth + axis_padding

    st.markdown(f"**{title}**")
    fig = px.bar(
        chart_df,
        x="Trg_chart",
        y="Rast_prikaz",
        color="Trg",
        color_discrete_map=MARKET_COLOR_MAP,
        text="Rast_label",
        custom_data=["Trg", "Rast_label"],
    )
    fig.update_traces(
        cliponaxis=False,
        textposition="outside",
        hovertemplate="<b>%{customdata[0]}</b><br>Rast: %{customdata[1]}<extra></extra>",
    )
    fig.update_layout(
        margin=dict(t=20, b=20, l=10, r=10),
        showlegend=False,
        xaxis_title="Trgi",
        yaxis_title="Rast prenočitev",
        uniformtext_minsize=10,
        uniformtext_mode="hide",
    )
    fig.update_xaxes(tickangle=0, automargin=True)
    fig.update_yaxes(
        range=[-axis_limit, axis_limit],
        tickformat=".0%",
        zeroline=True,
        zerolinewidth=1,
    )
    st.plotly_chart(fig, width='stretch')


def render_market_growth_table(growth_df: pd.DataFrame) -> None:
    if growth_df.empty:
        st.info("Za izbran prikaz ni dovolj podatkov o rasti po trgih.")
        return

    table = growth_df.copy().dropna(subset=["Rast_raw"])
    if table.empty:
        st.info("Za izbran prikaz ni dovolj podatkov o rasti po trgih.")
        return

    table["Trg"] = table["Trg"].apply(normalize_market_display_label)
    table = table.sort_values("Rast_raw", ascending=False).reset_index(drop=True)
    table["Rast (%)"] = table["Rast_raw"].apply(format_growth_label)
    render_ranked_dataframe(table[["Trg", "Rast (%)"]])


def wrap_generic_chart_label(label: str, width: int = 18) -> str:
    wrapped = textwrap.wrap(
        str(label),
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return "<br>".join(wrapped) if wrapped else str(label)


def _reference_label(reference_name: str, indicator: str, value: float) -> str:
    return f"{reference_name}: {format_indicator_value_map(indicator, value)}"


def _add_reference_line(
    fig: Any,
    *,
    orientation: str,
    indicator: str,
    value: float | None,
    label: str,
    color: str,
) -> None:
    if value is None or pd.isna(value):
        return
    if orientation == "h":
        fig.add_vline(
            x=float(value),
            line_color=color,
            line_dash="dash",
            line_width=3,
        )
    else:
        fig.add_hline(
            y=float(value),
            line_color=color,
            line_dash="dash",
            line_width=3,
        )


def _add_reference_legend_entry(
    fig: Any,
    *,
    label: str,
    indicator: str,
    value: float | None,
    color: str,
) -> None:
    if value is None or pd.isna(value):
        return
    fig.add_trace(
        go.Scatter(
            x=[None],
            y=[None],
            mode="lines",
            line=dict(color=color, width=3, dash="dash"),
            name=_reference_label(label, indicator, float(value)),
            showlegend=True,
            hoverinfo="skip",
        )
    )


def should_use_share_pie_chart(indicator: str, values: pd.Series) -> bool:
    if is_rate_like(indicator) or indicator in INDIKATORJI_Z_INDEKSI:
        return False
    numeric_values = pd.to_numeric(values, errors="coerce").dropna()
    if numeric_values.empty:
        return False
    if (numeric_values < 0).any():
        return False
    return float(numeric_values.sum()) > 0


def should_use_horizontal_chart(labels: pd.Series) -> bool:
    label_texts = labels.astype(str).tolist()
    return len(label_texts) > 8 or max((len(label) for label in label_texts), default=0) > 18


def render_comparison_indicator_chart(
    *,
    chart_df: pd.DataFrame,
    label_col: str,
    value_col: str,
    indicator: str,
    title: str,
    slovenia_value: float | None = None,
    area_reference_value: float | None = None,
    area_reference_label: str = "Območje",
) -> None:
    plot_df = chart_df[[label_col, value_col]].copy()
    plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce")
    plot_df = plot_df.dropna(subset=[value_col])
    if plot_df.empty:
        st.info("Za izbrani kazalnik ni dovolj podatkov za grafični prikaz.")
        return

    st.markdown(f"**{title}**")

    if should_use_share_pie_chart(indicator, plot_df[value_col]):
        plot_df = plot_df.sort_values(value_col, ascending=False).reset_index(drop=True)
        total_value = float(plot_df[value_col].sum())
        if total_value <= 0:
            st.info("Za izbrani kazalnik ni dovolj podatkov za tortni prikaz.")
            return

        plot_df["Share"] = plot_df[value_col] / total_value
        plot_df["Value_label"] = plot_df[value_col].apply(lambda value: format_indicator_value_map(indicator, value))
        plot_df["Share_label"] = plot_df["Share"].apply(lambda value: format_pct(float(value) * 100.0, 1))
        plot_df["Hover_label"] = plot_df.apply(
            lambda row: (
                f"<b>{row[label_col]}</b><br>"
                f"Delež: {row['Share_label']}<br>"
                f"Vrednost: {row['Value_label']}"
            ),
            axis=1,
        )

        pie_colors = px.colors.sequential.Blues[2:] + px.colors.sequential.Purples[2:]
        fig = px.pie(
            plot_df,
            names=label_col,
            values="Share",
            color=label_col,
            color_discrete_sequence=pie_colors,
        )
        fig.update_traces(
            textposition="inside",
            textinfo="percent",
            customdata=plot_df[["Hover_label"]].to_numpy(),
            hovertemplate="%{customdata[0]}<extra></extra>",
        )
        fig.update_layout(
            margin=dict(t=20, b=10, l=10, r=10),
            legend_title_text=label_col,
            showlegend=True,
        )
        st.plotly_chart(fig, width="stretch")
        return

    plot_df = plot_df.sort_values(value_col, ascending=False).reset_index(drop=True)
    plot_df["Value_label"] = plot_df[value_col].apply(lambda value: format_indicator_value_map(indicator, value))
    orientation = "h" if should_use_horizontal_chart(plot_df[label_col]) else "v"

    if orientation == "h":
        fig = px.bar(
            plot_df,
            x=value_col,
            y=label_col,
            orientation="h",
            text="Value_label",
            custom_data=[label_col, "Value_label"],
        )
        fig.update_traces(
            marker_color="#2563eb",
            textposition="auto",
            hovertemplate="<b>%{customdata[0]}</b><br>Vrednost: %{customdata[1]}<extra></extra>",
        )
        fig.update_layout(
            margin=dict(t=20, b=10, l=10, r=10),
            showlegend=False,
            height=max(380, 42 * len(plot_df) + 80),
            xaxis_title=indicator,
            yaxis_title=None,
        )
        fig.update_yaxes(autorange="reversed")
        if is_percent_like(indicator):
            fig.update_xaxes(tickformat=".0%")
    else:
        plot_df["Chart_label"] = plot_df[label_col].apply(wrap_generic_chart_label)
        fig = px.bar(
            plot_df,
            x="Chart_label",
            y=value_col,
            text="Value_label",
            custom_data=[label_col, "Value_label"],
        )
        fig.update_traces(
            marker_color="#2563eb",
            cliponaxis=False,
            textposition="outside",
            hovertemplate="<b>%{customdata[0]}</b><br>Vrednost: %{customdata[1]}<extra></extra>",
        )
        fig.update_layout(
            margin=dict(t=20, b=10, l=10, r=10),
            showlegend=False,
            height=430,
            xaxis_title=None,
            yaxis_title=indicator,
            uniformtext_minsize=10,
            uniformtext_mode="hide",
        )
        fig.update_xaxes(tickangle=0, automargin=True)
        if is_percent_like(indicator):
            fig.update_yaxes(tickformat=".0%")

    _add_reference_line(
        fig,
        orientation=orientation,
        indicator=indicator,
        value=area_reference_value,
        label=area_reference_label,
        color="#f59e0b",
    )
    _add_reference_legend_entry(
        fig,
        label=area_reference_label,
        indicator=indicator,
        value=area_reference_value,
        color="#f59e0b",
    )
    _add_reference_line(
        fig,
        orientation=orientation,
        indicator=indicator,
        value=slovenia_value,
        label="Slovenija",
        color="#dc2626",
    )
    _add_reference_legend_entry(
        fig,
        label="Slovenija",
        indicator=indicator,
        value=slovenia_value,
        color="#dc2626",
    )

    if (area_reference_value is not None and not pd.isna(area_reference_value)) or (
        slovenia_value is not None and not pd.isna(slovenia_value)
    ):
        fig.update_layout(legend_title_text="Reference", showlegend=True)

    st.plotly_chart(fig, width="stretch")


def render_market_structure_distribution(
    *,
    selected_group: str,
    group_col: str,
    mode: str,
    selected_year: int,
    df_source: pd.DataFrame,
    numeric_df: pd.DataFrame,
) -> None:
    subset = numeric_df[numeric_df[group_col] == selected_group].copy()
    if subset.empty:
        st.info("Ni podatkov za izbrano območje.")
        return

    structure_df = compute_market_structure_for_subset(
        subset,
        df_source=df_source,
        selected_year=selected_year,
    )
    if structure_df.empty:
        st.warning("Manjkajo prenočitve SKUPAJ (utež) ali so 0, zato strukture ne morem izračunati.")
        return

    market_cols_year, market_labels_year = get_market_cols_for_year(df_source, selected_year)
    base_weight_col = col_for_year("Prenočitve turistov SKUPAJ - 2024", selected_year)

    if mode == "Celotno območje":
        st.markdown(f"### {selected_group}")
        chart_col, table_col = st.columns([1.2, 1])
        with chart_col:
            st.markdown("**Tortni prikaz (normalizirano na 100%)**")
            pie_df = structure_df.sort_values("Delež_norm", ascending=False)
            pie_df["Trg_short"] = pie_df["Trg"].apply(lambda value: shorten_label(value, 24))
            fig = px.pie(
                pie_df,
                names="Trg_short",
                values="Delež_norm",
                color="Trg",
                color_discrete_map=MARKET_COLOR_MAP,
                hole=0.4,
            )
            fig.update_traces(
                textposition="inside",
                textinfo="percent+label",
                hovertemplate="<b>%{customdata[0]}</b><br>Delež: %{percent}<extra></extra>",
                customdata=pie_df[["Trg"]].values,
            )
            fig.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                showlegend=True,
                legend_title_text="Trgi",
            )
            st.plotly_chart(fig, width="stretch")

        with table_col:
            st.markdown("**Tabela**")
            table = structure_df.copy()
            table["Delež (%)"] = table["Delež_norm"]
            table = table[["Trg", "Delež (%)"]].sort_values("Delež (%)", ascending=False)
            render_ranked_dataframe(
                table,
                source_columns=None,
            )

        st.caption(
            "Opomba: deleži so izračunani uteženo glede na celotno število prenočitev "
            "in nato normalizirani na 100% (zaradi zaokroževanja/manjkajočih trgov)."
        )
        return

    st.markdown(f"### Občine znotraj območja: {selected_group}")
    municipality_df = subset[["Občine", base_weight_col] + market_cols_year].copy().rename(columns={"Občine": "Občina"})
    chosen_muni = st.selectbox(
        "Izberi občino",
        municipality_df["Občina"].dropna().astype(str).tolist(),
        index=0,
        key=f"trgi_muni_{group_col}_{selected_year}",
    )

    municipality_row = municipality_df[municipality_df["Občina"] == chosen_muni].iloc[0]
    municipality_values = [
        {"Trg": label, "Delež": float(municipality_row[column]) if pd.notna(municipality_row[column]) else np.nan}
        for column, label in zip(market_cols_year, market_labels_year)
    ]
    municipality_structure = pd.DataFrame(municipality_values).dropna()
    municipality_total = float(municipality_structure["Delež"].sum()) if not municipality_structure.empty else 0.0
    municipality_structure["Delež_norm"] = (
        municipality_structure["Delež"] / municipality_total if municipality_total > 0 else np.nan
    )

    chart_col, table_col = st.columns([1.2, 1])
    with chart_col:
        st.markdown(f"**{chosen_muni} – tortni prikaz (normalizirano na 100%)**")
        pie_df = municipality_structure.sort_values("Delež_norm", ascending=False)
        pie_df["Trg_short"] = pie_df["Trg"].apply(lambda value: shorten_label(value, 24))
        fig = px.pie(
            pie_df,
            names="Trg_short",
            values="Delež_norm",
            color="Trg",
            color_discrete_map=MARKET_COLOR_MAP,
            hole=0.4,
        )
        fig.update_traces(
            textposition="inside",
            textinfo="percent+label",
            hovertemplate="<b>%{customdata[0]}</b><br>Delež: %{percent}<extra></extra>",
            customdata=pie_df[["Trg"]].values,
        )
        fig.update_layout(
            margin=dict(t=10, b=10, l=10, r=10),
            showlegend=True,
            legend_title_text="Trgi",
        )
        st.plotly_chart(fig, width='stretch')

    with table_col:
        st.markdown("**Tabela**")
        table = municipality_structure.copy()
        table["Delež (%)"] = municipality_structure["Delež_norm"]
        table = table[["Trg", "Delež (%)"]].sort_values("Delež (%)", ascending=False)
        render_ranked_dataframe(
            table,
        )

    st.markdown("**Tabela občin (povzetek)**")

    def top_market(row: pd.Series) -> tuple[str, float]:
        pairs = [
            (label, row[column])
            for column, label in zip(market_cols_year, market_labels_year)
            if pd.notna(row[column])
        ]
        if not pairs:
            return "—", np.nan
        return max(pairs, key=lambda pair: pair[1])

    tops = municipality_df.copy()
    tops["Top trg"] = tops.apply(lambda row: top_market(row)[0], axis=1)
    tops["Top trg delež (%)"] = tops.apply(
        lambda row: top_market(row)[1] if pd.notna(top_market(row)[1]) else np.nan,
        axis=1,
    )
    tops_view = tops[["Občina", base_weight_col, "Top trg", "Top trg delež (%)"]].copy()
    tops_view = tops_view.sort_values(base_weight_col, ascending=False, na_position="last")
    render_ranked_dataframe(
        tops_view,
    )


def render_market_growth_distribution(
    *,
    selected_group: str,
    group_col: str,
    mode: str,
    growth_numeric_df: pd.DataFrame | None,
) -> None:
    if growth_numeric_df is None or growth_numeric_df.empty:
        st.warning("V delovnem listu 'Rast prenočitev po trgih' ni podatkov za prikaz rasti po trgih.")
        return

    period_options = {
        "2025/2019": (2019, 2025),
        "2025/2024": (2024, 2025),
    }
    selected_period = st.radio(
        "Primerjalno obdobje",
        options=list(period_options.keys()),
        horizontal=True,
        key=f"trgi_growth_period_{group_col}",
    )
    base_year, target_year = period_options[selected_period]

    subset = growth_numeric_df[growth_numeric_df[group_col] == selected_group].copy()
    if subset.empty:
        st.info("Ni podatkov za izbrano območje.")
        return

    st.caption(
        "Rast je izračunana neposredno iz dejanskega števila prenočitev po trgih "
        f"({target_year} glede na {base_year})"
    )

    if mode == "Celotno območje":
        growth_df = compute_market_growth_for_subset(
            subset,
            base_year=base_year,
            target_year=target_year,
        )
        st.markdown(f"### {selected_group}")
        chart_col, table_col = st.columns([1.4, 1])
        with chart_col:
            render_market_growth_chart(
                growth_df,
                f"Rast števila prenočitev po trgih ({selected_period})",
            )
        with table_col:
            st.markdown("**Tabela**")
            render_market_growth_table(growth_df)
        return

    st.markdown(f"### Občine znotraj območja: {selected_group}")
    municipality_names = subset["Občine"].dropna().astype(str).tolist()
    chosen_muni = st.selectbox(
        "Izberi občino",
        municipality_names,
        index=0,
        key=f"trgi_growth_muni_{group_col}_{selected_period}",
    )
    municipality_subset = subset[subset["Občine"].astype(str) == chosen_muni].copy()
    growth_df = compute_market_growth_for_subset(
        municipality_subset,
        base_year=base_year,
        target_year=target_year,
    )

    chart_col, table_col = st.columns([1.4, 1])
    with chart_col:
        render_market_growth_chart(
            growth_df,
            f"{chosen_muni} – rast števila prenočitev po trgih ({selected_period})",
        )
    with table_col:
        st.markdown("**Tabela**")
        render_market_growth_table(growth_df)


def render_region_top_bottom_and_ai(
    selected_region: str,
    group_col: str,
    group_sections: list[dict[str, Any]],
    market_ai_context: dict[str, Any] | None = None,
) -> None:
    if not group_sections:
        st.info("Za Top/Bottom analizo po skupinah ni na voljo dovolj kazalnikov.")
        return

    st.markdown("---")
    st.subheader("**Najboljši/Najslabši kazalniki po skupinah**")
    st.caption(
        "Vsaka skupina kazalnikov ima ločeno razvrstitev. Za kumulativne "
        "kazalnike je uporabljen odmik deleža kazalnika glede na referenčni delež "
        "regije (o.t.), da velikost območja ne izkrivlja rezultatov. Za ostale "
        "kazalnike je prikazan neposredni odmik od vrednosti Slovenije, samo "
        "razvrščanje pa je standardizirano glede na tipični razpon kazalnika med "
        "območji iste ravni."
    )

    tab_labels = [
        f"{GROUP_COLOR_EMOJI.get(section['group'], '•')} {section['group']} ({section['limit']}/{section['limit']})"
        for section in group_sections
    ]
    group_tabs = st.tabs(tab_labels)
    table_cols = [
        "Kazalnik",
        "Smer kazalnika",
        "Vrednost območja", 
        "Osnova (Slovenija)", 
        "Enota odstopanja",]

    for tab, section in zip(group_tabs, group_sections):
        with tab:
            best_col, worst_col = st.columns(2)
            with best_col:
                st.markdown(f"**Najboljši {section['group']}**")
                render_ranked_dataframe(section["best_df"][table_cols])
            with worst_col:
                st.markdown(f"**Najslabši {section['group']}**")
                render_ranked_dataframe(section["worst_df"][table_cols])
            show_shared_warning_if_needed_map(section['group'])

    st.markdown("---")
    render_ai_section_header()

    ai_signature_raw = json.dumps(
        {
            "prompt_version": "market_structure_v1",
            "region": selected_region,
            "groups": [
                {
                    "group": section["group"],
                    "top": section["top_rows"],
                    "bottom": section["bottom_rows"],
                }
                for section in group_sections
            ],
            "market_context": market_ai_context,
        },
        ensure_ascii=False,
    )
    ai_signature = hashlib.md5(ai_signature_raw.encode("utf-8")).hexdigest()[:12]
    ai_payload_hash = hashlib.sha256(ai_signature_raw.encode("utf-8")).hexdigest()
    ai_cache_key = ai_payload_hash
    ai_state_key = f"ai_comment_{group_col}_{selected_region}_{ai_signature}"

    existing_ai_payload = st.session_state.get(ai_state_key, {})
    existing_error_text = str(existing_ai_payload.get("error") or "").lower()
    should_retry_timeout_fallback = (
        existing_ai_payload.get("source") == "fallback"
        and ("timed out" in existing_error_text or "read timeout" in existing_error_text)
    )

    if ai_state_key not in st.session_state or should_retry_timeout_fallback:
        cached_payload = get_cached_ai_commentary(ai_cache_key)
        if cached_payload:
            st.session_state[ai_state_key] = {
                "text": cached_payload.get("text", ""),
                "source": "db_cache",
                "error": None,
            }
        else:
            with st.spinner("Generiram komentar in priporočila..."):
                ai_text, ai_source, ai_error = generate_region_ai_commentary(
                    selected_region,
                    group_sections,
                    market_analysis=market_ai_context,
                )
            st.session_state[ai_state_key] = {
                "text": ai_text,
                "source": ai_source,
                "error": ai_error,
            }
            if ai_source == "ai" and ai_text:
                store_cached_ai_commentary(
                    ai_cache_key,
                    payload_hash=ai_payload_hash,
                    region_name=selected_region,
                    group_name=group_col,
                    text=ai_text,
                    model=str(get_secret_value("OPENAI_MODEL", "gpt-5.4") or "gpt-5.4"),
                )

    ai_payload = st.session_state.get(ai_state_key, {})
    if ai_payload.get("source") == "db_cache":
        st.caption("AI komentar je prebran iz trajnega podatkovnega cache-a.")
    elif ai_payload.get("source") == "fallback":
        error_text = str(ai_payload.get("error") or "")
        if "insufficient_quota" in error_text:
            st.caption("OPENAI_API_KEY nima več razpoložljive kvote. Prikazan je samodejni komentar na osnovi kazalnikov.")
        elif "HTTP 429" in error_text:
            st.caption("AI klic je omejen zaradi preveč zahtevkov (rate limit). Prikazan je samodejni komentar na osnovi kazalnikov.")
        else:
            st.caption("OPENAI_API_KEY ni nastavljen ali AI klic ni uspel. Prikazan je samodejni komentar na osnovi kazalnikov.")

    if ai_payload.get("error"):
        st.caption(f"Podrobnosti: {ai_payload['error']}")
    if ai_payload.get("text"):
        st.markdown(ai_payload["text"])


def render_view(view_title: str, group_col: str, ctx: DashboardContext) -> None:
    st.caption(f"**Pogled:** {view_title}")

    indicator_cols = ctx.indicator_cols
    grouped_filtered, indicator_to_group = build_filtered_indicator_groups(indicator_cols, ctx.grouped_indicators)

    df_regions = ctx.numeric_df[ctx.numeric_df[group_col].notna()].copy()
    regions = sorted(df_regions[group_col].dropna().unique().tolist())
    regions_with_all = ["Vsa območja"] + regions

    numeric_df = df_regions
    df_slo_total_num = ctx.numeric_df.iloc[0][indicator_cols]
    municipality_to_region = {
        municipality: region
        for municipality, region in zip(df_regions["__obcina_norm__"], df_regions[group_col])
    }

    selected_region = st.selectbox(group_col, regions_with_all, index=0, key=f"sel_group_{group_col}")

    st.markdown("---")
    selector_col, map_indicator_col = st.columns([1, 1], gap="large")
    with selector_col:
        selected_group_key = render_group_selector(group_col, indicator_cols, grouped_filtered)

    group_indicator_cols = indicator_cols if selected_group_key == "__all__" else grouped_filtered.get(selected_group_key, [])
    if not group_indicator_cols:
        group_indicator_cols = indicator_cols

    with map_indicator_col:
        st.markdown("<div style='min-height: 10rem;'></div>", unsafe_allow_html=True)
        map_indicator = st.selectbox(
            "Kazalnik za zemljevid",
            group_indicator_cols,
            index=0,
            key=f"sel_ind_{group_col}",
            format_func=lambda indicator: format_indicator_option_label(indicator, indicator_to_group),
        )
        show_shared_warning_if_needed_indicator(map_indicator)

    dash_inds = []
    if ctx.dashboard_mode:
        dash_inds = st.multiselect(
            "Kazalniki za dashboard (do 6)",
            group_indicator_cols,
            default=group_indicator_cols[:0] if len(group_indicator_cols) >= 4 else group_indicator_cols,
            max_selections=6,
            placeholder="Izberi kazalnik",
            key=f"dash_{group_col}",
            format_func=lambda indicator: format_indicator_option_label(indicator, indicator_to_group),
        )

    agg_needed = [map_indicator] + [indicator for indicator in dash_inds if indicator != map_indicator]
    region_agg = compute_region_aggregates(numeric_df, regions, agg_needed, AGG_RULES, group_col=group_col)
    region_agg_by_group = region_agg.set_index(group_col)
    region_to_value_map = dict(zip(region_agg[group_col], region_agg[map_indicator]))
    display_geojson_obj = _get_display_geojson(ctx)
    regions_geojson = (
        _get_regions_geojson(
            ctx=ctx,
            municipality_to_region=municipality_to_region,
            group_col=group_col,
        )
        if selected_region == "Vsa območja"
        else None
    )

    group_sections = []
    if selected_region == "Vsa območja":
        st.subheader("Primerjava območij")
        sort_col, direction_col = st.columns([2, 1])
        with sort_col:
            sort_indicator = st.selectbox(
                "Razvrsti po",
                agg_needed,
                index=0,
                key=f"compare_sort_{group_col}",
                format_func=lambda indicator: format_indicator_option_label(indicator, indicator_to_group),
            )
        with direction_col:
            sort_direction = st.radio(
                "Smer",
                ["Padajoče", "Naraščajoče"],
                horizontal=True,
                key=f"compare_sort_dir_{group_col}",
            )

        cols_to_show = [group_col] + agg_needed
        show_df = region_agg[cols_to_show].copy()
        sort_ascending = sort_direction == "Naraščajoče"
        show_df = show_df.sort_values(sort_indicator, ascending=sort_ascending, na_position="last")
        for column in cols_to_show[1:]:
            show_df[column] = show_df[column].apply(lambda value: format_indicator_value_tables(column, value))
        show_df = prefix_rank_to_label_column(show_df, group_col)
        comparison_widths: dict[str, ColumnWidth] = {group_col: "large"}
        for column in agg_needed:
            comparison_widths[column] = "medium"

        st.dataframe(
            show_df,
            width='stretch',
            height=260,
            hide_index=True,
            column_config=make_localized_column_config(show_df, width_overrides=comparison_widths),
        )
        st.caption(
            "Rang v tabeli sledi izbiri »Razvrsti po«. "
            "Če tabelo dodatno razvrščaš s klikom na glavo stolpca, se prikazani rang ne posodobi."
        )

        chart_indicator = map_indicator
        if len(agg_needed) > 1:
            chart_indicator = st.selectbox(
                "Kazalnik za primerjalni graf območij",
                agg_needed,
                index=agg_needed.index(map_indicator),
                key=f"compare_chart_indicator_{group_col}",
                format_func=lambda indicator: format_indicator_option_label(indicator, indicator_to_group),
            )

        chart_df = region_agg[[group_col, chart_indicator]].copy()
        render_comparison_indicator_chart(
            chart_df=chart_df,
            label_col=group_col,
            value_col=chart_indicator,
            indicator=chart_indicator,
            title="Grafična primerjava območij",
            slovenia_value=df_slo_total_num.get(chart_indicator, np.nan),
        )

        _, _, kpi_col = st.columns([1, 2, 1])
        with kpi_col:
            green_metric(
                f" Celotna Slovenija - {map_indicator}",
                format_indicator_value_map(map_indicator, df_slo_total_num.get(map_indicator, np.nan)),
            )
    else:
        st.subheader("Povzetek izbranega območja")
        region_df = numeric_df[numeric_df[group_col] == selected_region].copy()
        region_total = region_agg_by_group.at[selected_region, map_indicator]
        sl_total = df_slo_total_num.get(map_indicator, np.nan)

        share_si = np.nan
        kpi_text_main = "Odstopanje od Slovenije"

        if (not is_rate_like(map_indicator)) and sl_total and not np.isnan(sl_total) and sl_total != 0:
            share_si = (region_total / sl_total) * 100.0

        if map_indicator in INDIKATORJI_Z_INDEKSI:
            kpi_text_main = "Primerjalni indeks s Slovenijo"
            kpi_value_main = format_si_number(share_si, 1)
        else:
            kpi_text_main = "Delež v Sloveniji"
            kpi_value_main = format_pct(share_si, 1)

        left_kpi, right_kpi = st.columns([1.2, 1])
        with left_kpi:
            if not np.isnan(share_si):
                st.metric(
                    map_indicator,
                    f"{format_indicator_value_map(map_indicator, region_total)}",
                    f"{kpi_text_main}: {kpi_value_main}",
                )
            else:
                if is_percent_like(map_indicator):
                    kpi_text_main = "V primerjavi s Slovenijo"
                    kpi_value_main = format_pct(((region_total - sl_total)*100), 1)
                    if ((region_total - sl_total)*100) >= 0:
                        st.metric(
                            map_indicator, 
                            f"{format_indicator_value_map(map_indicator, region_total)}",
                            f"{kpi_text_main}: +{kpi_value_main}"
                            )
                    else:
                        st.metric(
                            map_indicator, 
                            f"{format_indicator_value_map(map_indicator, region_total)}",
                            f"{kpi_text_main}: {kpi_value_main}"
                            )
                else:
                    kpi_text_main = "V primerjavi s Slovenijo"
                    kpi_value_main = format_si_number((region_total - sl_total), 1)
                    if ((region_total - sl_total)*100) >= 0:
                        st.metric(
                            map_indicator, 
                            f"{format_indicator_value_map(map_indicator, region_total)}",
                            f"{kpi_text_main}: +{kpi_value_main}"
                            )
                    else:
                        st.metric(
                            map_indicator, 
                            f"{format_indicator_value_map(map_indicator, region_total)}",
                            f"{kpi_text_main}: {kpi_value_main}"
                        )
            st.caption("Opomba: »Delež v Sloveniji« je prikazan za kazalnike, kjer se vrednosti seštevajo (ne za stopnje/indekse).")
        with right_kpi:
            green_metric(f" Celotna Slovenija - {map_indicator}", format_indicator_value_map(map_indicator, sl_total))

        if ctx.dashboard_mode and dash_inds:
            kpi_cols = st.columns(min(6, len(dash_inds)))
            for idx, indicator in enumerate(dash_inds[:6]):
                region_value = float(region_agg_by_group.at[selected_region, indicator])
                slovenia_value = df_slo_total_num.get(indicator, np.nan)

                share = np.nan
                if (not is_rate_like(indicator)) and slovenia_value and not np.isnan(slovenia_value) and slovenia_value != 0:
                    share = (region_value / slovenia_value) * 100.0

                with kpi_cols[idx]:
                    if indicator in INDIKATORJI_Z_INDEKSI:
                        kpi_text_dashboard = "Primerjalni indeks s Slovenijo"
                        kpi_value_dashboard = format_si_number(share, 1)
                    else:
                        kpi_text_dashboard = "Delež v Sloveniji"
                        kpi_value_dashboard = format_pct(share, 1)

                    if slovenia_value is not None and not (isinstance(slovenia_value, float) and np.isnan(slovenia_value)):
                        green_metric_small("Slovenija", format_indicator_value_map(indicator, slovenia_value))

                    if not np.isnan(share):
                        st.metric(
                            indicator,
                            format_indicator_value_map(indicator, region_value),
                            f"{kpi_text_dashboard}: {kpi_value_dashboard}",
                        )
                    else:
                        if is_percent_like(map_indicator):
                            kpi_text_main = "V primerjavi s Slovenijo"
                            kpi_value_main = format_pct(((region_total - sl_total)*100), 1)
                            if ((region_total - sl_total)*100) >= 0:
                                st.metric(
                                    map_indicator, 
                                    f"{format_indicator_value_map(map_indicator, region_total)}",
                                    f"{kpi_text_main}: +{kpi_value_main}"
                                    )
                            else:
                                st.metric(
                                    map_indicator, 
                                    f"{format_indicator_value_map(map_indicator, region_total)}",
                                    f"{kpi_text_main}: {kpi_value_main}"
                                    )
                        else:
                            kpi_text_main = "V primerjavi s Slovenijo"
                            kpi_value_main = format_si_number((region_total - sl_total), 1)
                            if ((region_total - sl_total)*100) >= 0:
                                st.metric(
                                    map_indicator, 
                                    f"{format_indicator_value_map(map_indicator, region_total)}",
                                    f"{kpi_text_main}: +{kpi_value_main}"
                                    )
                            else:
                                st.metric(
                                    map_indicator, 
                                    f"{format_indicator_value_map(map_indicator, region_total)}",
                                    f"{kpi_text_main}: {kpi_value_main}"
                                )

        group_sections = build_top_bottom_group_sections(
            reg_df=region_df,
            df_slo_total_num=df_slo_total_num,
            grouped_filtered=grouped_filtered,
            agg_rules=AGG_RULES,
            region_name=selected_region,
            reference_agg_df=compute_region_aggregates(
                numeric_df=numeric_df,
                regions=regions,
                indicator_cols=get_top_bottom_reference_indicators(grouped_filtered, AGG_RULES),
                agg_rules=AGG_RULES,
                group_col=group_col,
            ),
        )

    st.markdown("---")
    

    map_col, table_col = st.columns([2.2, 1.0], gap="large")
    with map_col:
        st.subheader("Zemljevid in razčlenitev")
        st.caption(
        "Skupni pogled: Skupni podatki za posamezna območja. Posamezno območje: "
        "meje občin ter deleži znotraj območja. Dodan je tudi delež Občine glede "
        "na območje (kjer je smiselno)."
        )
        if display_geojson_obj is None or ctx.geojson_name_prop is None:
            st.info("Za zemljevid naloži občinski GeoJSON (npr. `si.json`).")
        else:
            if selected_region == "Vsa območja":
                if regions_geojson is None:
                    st.warning(
                        "Ne uspem sestaviti poligonov regij (dissolve). "
                        "Prikazujem občine obarvane po regijski vrednosti."
                    )
                    muni_region_values = {
                        municipality: region_to_value_map.get(region, np.nan)
                        for municipality, region in municipality_to_region.items()
                    }
                    render_map_municipalities(
                        display_geojson_obj,
                        ctx.geojson_name_prop,
                        set(municipality_to_region.keys()),
                        muni_region_values,
                        indicator_label=map_indicator,
                        height=680,
                        cache_key=cache_key_for_municipalities_map(
                            data_signature=ctx.data_signature,
                            geojson_signature=ctx.geojson_signature,
                            group_col=group_col,
                            selected_region="__all_regions_fallback__",
                            indicator_label=map_indicator,
                        ),
                    )
                else:
                    render_map_regions(
                        regions_geojson,
                        region_to_value_map,
                        indicator_label=map_indicator,
                        group_col=group_col,
                        height=780,
                        cache_key=cache_key_for_regions_map(
                            data_signature=ctx.data_signature,
                            geojson_signature=ctx.geojson_signature,
                            group_col=group_col,
                            indicator_label=map_indicator,
                        ),
                    )
            else:
                municipalities_in_region = set(region_df["__obcina_norm__"].tolist())
                municipality_to_value = {
                    municipality: float(value)
                    for municipality, value in zip(region_df["__obcina_norm__"], region_df[map_indicator])
                }
                render_map_municipalities(
                    display_geojson_obj,
                    ctx.geojson_name_prop,
                    municipalities_in_region,
                    municipality_to_value,
                    indicator_label=map_indicator,
                    height=780,
                    cache_key=cache_key_for_municipalities_map(
                        data_signature=ctx.data_signature,
                        geojson_signature=ctx.geojson_signature,
                        group_col=group_col,
                        selected_region=selected_region,
                        indicator_label=map_indicator,
                    ),
                )
        show_shared_warning_if_needed_map(map_indicator)

    with table_col:
        if selected_region == "Vsa območja":
            st.subheader(f"Tabela območij \n \n **:blue[{map_indicator}]**")
            table = region_agg[[group_col, map_indicator]].copy()
            table = table.sort_values(map_indicator, ascending=False, na_position="last")
            table[map_indicator] = table[map_indicator].apply(lambda value: format_indicator_value_tables(map_indicator, value))
            table = table.rename(columns={map_indicator: "Vrednost"})
            render_ranked_dataframe(
                table,
                source_columns={"Vrednost": map_indicator},
                height=680,
            )
        else:
            st.subheader(f"Tabela občin znotraj območja \n \n **:blue[{map_indicator}]**")
            region_total = aggregate_indicator_with_rules(region_df, map_indicator, AGG_RULES, None)
            table = build_region_indicator_table(region_df, map_indicator, region_total, view_title)
            render_ranked_dataframe(
                table,
                source_columns={"Vrednost": map_indicator},
                height=680,
            )
            if region_total and not np.isnan(region_total) and region_total != 0 and not is_rate_like(map_indicator):
                if view_title == "Turistične regije":
                    st.caption(
                        "**Opomba:** Delež posamezne občine znotraj opazovane turistične regije (%) je prikazan "
                        "za kazalnike, kjer se vrednosti seštevajo. Primerjalni indeks vrednosti kazalnika "
                        "posamezne občine v primerjavi z vrednostjo enakega kazalnika na ravni opazovane "
                        "turistične regije pa je prikazan za kompleksnejše oz. izračunane kazalnike, katerih "
                        "vrednosti se ne seštevajo. "
                    )
                elif view_title == "Vodilne destinacije":
                    st.caption(
                        "**Opomba:** Delež posamezne občine znotraj opazovane vodilne destinacije (%) je prikazan "
                        "za kazalnike, kjer se vrednosti seštevajo. Primerjalni indeks vrednosti kazalnika "
                        "posamezne občine v primerjavi z vrednostjo enakega kazalnika na ravni opazovane vodilne "
                        "destinacije pa je prikazan za kompleksnejše oz. izračunane kazalnike, katerih vrednosti "
                        "se ne seštevajo. "
                    )
                elif view_title == "Makrodestinacije":
                    st.caption(
                        "**Opomba:** Delež posamezne občine znotraj opazovane makro destinacije (%) je prikazan "
                        "za kazalnike, kjer se vrednosti seštevajo. Primerjalni indeks vrednosti kazalnika "
                        "posamezne občine v primerjavi z vrednostjo enakega kazalnika na ravni opazovane makro "
                        "destinacije pa je prikazan za kompleksnejše oz. izračunane kazalnike, katerih vrednosti "
                        "se ne seštevajo. "
                    )
                elif view_title == "Perspektivne destinacije":
                    st.caption(
                        "**Opomba:** Delež posamezne občine znotraj opazovane perspektivne destinacije (%) je "
                        "prikazan za kazalnike, kjer se vrednosti seštevajo. Primerjalni indeks vrednosti "
                        "kazalnika posamezne občine v primerjavi z vrednostjo enakega kazalnika na ravni "
                        "opazovane perspektivne destinacije pa je prikazan za kompleksnejše oz. izračunane "
                        "kazalnike, katerih vrednosti se ne seštevajo. "
                    )

    if selected_region != "Vsa območja":
        st.markdown("---")
        st.subheader("Grafična primerjava občin znotraj območja")

        chart_indicator = map_indicator
        if len(agg_needed) > 1:
            chart_indicator = st.selectbox(
                "Kazalnik za primerjalni graf občin",
                agg_needed,
                index=agg_needed.index(map_indicator),
                key=f"municipality_chart_indicator_{group_col}",
                format_func=lambda indicator: format_indicator_option_label(indicator, indicator_to_group),
            )
        st.subheader(f":blue[{chart_indicator}]")
        region_chart_total = aggregate_indicator_with_rules(region_df, chart_indicator, AGG_RULES, selected_region)
        municipality_chart_df = region_df[[ "Občine", chart_indicator]].copy()
        render_comparison_indicator_chart(
            chart_df=municipality_chart_df,
            label_col="Občine",
            value_col=chart_indicator,
            indicator=chart_indicator,
            title=f"Graf občin znotraj območja: {selected_region}",
            slovenia_value=df_slo_total_num.get(chart_indicator, np.nan),
            area_reference_value=region_chart_total,
            area_reference_label="Območje",
        )

        market_ai_context = build_market_ai_context(
            selected_group=selected_region,
            group_col=group_col,
            df_source=ctx.df,
            numeric_df=numeric_df,
            growth_numeric_df=ctx.market_growth_numeric_df,
        )
        render_region_top_bottom_and_ai(
            selected_region,
            group_col,
            group_sections,
            market_ai_context=market_ai_context,
        )


def render_market_structure(view_title: str, group_col: str, ctx: DashboardContext) -> None:
    st.caption(f"**Pogled:** {view_title}")
    st.subheader("Prenočitve po trgih")

    if not ctx.market_cols:
        st.warning(f"V Excelu ne najdem stolpcev, ki se začnejo z: '{MARKET_PREFIX}'.")
        return

    numeric_df = ctx.numeric_df[ctx.numeric_df[group_col].notna()].copy()

    groups: list[str] = sorted(cast(list[str], numeric_df[group_col].dropna().unique().tolist()))
    if not groups:
        st.warning("Ne najdem nobenih območij za izbran pogled.")
        return

    selected_group_raw = st.selectbox(
        f"Izberi območje ({group_col})",
        groups,
        index=0,
        key=f"trgi_sel_{group_col}",
    )
    if selected_group_raw is None:
        st.info("Izberi območje za prikaz podatkov.")
        return
    selected_group = str(selected_group_raw)
    mode = st.radio(
        "Prikaz",
        ["Celotno območje", "Občine znotraj območja"],
        horizontal=True,
        key=f"trgi_mode_{group_col}",
    )

    structure_tab, growth_tab = st.tabs(
        ["Struktura prenočitev po trgih", "Rast števila prenočitev po trgih"]
    )

    with structure_tab:
        years = [2019, 2024, 2025]
        selected_year = st.selectbox(
            "Leto",
            years,
            index=len(years) - 1,
            key=f"trgi_year_{group_col}",
        )
        render_market_structure_distribution(
            selected_group=selected_group,
            group_col=group_col,
            mode=mode,
            selected_year=selected_year,
            df_source=ctx.df,
            numeric_df=numeric_df,
        )

    with growth_tab:
        render_market_growth_distribution(
            selected_group=selected_group,
            group_col=group_col,
            mode=mode,
            growth_numeric_df=(
                ctx.market_growth_numeric_df[ctx.market_growth_numeric_df[group_col].notna()].copy()
                if ctx.market_growth_numeric_df is not None and group_col in ctx.market_growth_numeric_df.columns
                else None
            ),
        )
