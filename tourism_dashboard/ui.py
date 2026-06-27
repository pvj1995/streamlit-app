from __future__ import annotations

import hashlib
import json
import re
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
    compute_market_annual_average_for_subset,
    compute_market_growth_weighted_mean,
    compute_market_monthly_average_from_seasonality,
    compute_market_monthly_structure_for_subset,
    compute_market_monthly_total_from_seasonality,
    compute_market_weighted_mean_from_frames,
    compute_market_seasonality_for_subset,
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
    GROUP_CHART_COLOR_SCALES,
    GROUP_COLOR_EMOJI,
    INDIKATORJI_Z_OPOMBO,
    MARKET_COLOR_MAP,
    MARKET_PREFIX,
    SKUPNO_OPOZORILO_AGREGACIJA,
)
from tourism_dashboard.compass import (
    aggregate_compass_results,
    build_compass_area_maps,
    format_compass_metric_label,
    get_compass_index_path,
    load_compass_workbook,
)
from tourism_dashboard.formatting import (
    ColumnWidth,
    format_indicator_value_map,
    format_indicator_value_tables,
    format_pct,
    format_si_number,
    is_lower_better,
    is_rate_like,
    is_percent_like,
    make_localized_column_config,
)
from tourism_dashboard.helpers import (
    get_secret_value,
    get_indicator_display_name,
    shorten_label,
    col_for_year,
    load_market_arrivals_seasonality_data,
    load_market_overnight_seasonality_data,
    load_market_pdb_data,
    normalize_name,
)
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
from tourism_dashboard.national_kpi import (
    NATIONAL_MAIN_SECTION,
    NATIONAL_NOMINAL_COMPARISON_SECTION,
    NATIONAL_SECTOR_LABELS,
    comparison_section_name,
    get_national_kpi_path,
    get_national_sector_options,
    load_national_business_kpi_data,
    sector_rows,
)


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


def format_national_kpi_value(value: Any, format_type: str, unit: str = "", *, compact: bool = True) -> str:
    if value is None or pd.isna(value):
        return "—"
    number = float(value)
    format_type = str(format_type or "").strip()
    unit = str(unit or "").strip()
    if format_type == "percent_decimal":
        return format_pct(number * 100.0, 1)
    if format_type == "currency":
        if compact and abs(number) >= 1_000_000_000:
            return f"{format_si_number(number / 1_000_000_000, 1)} mrd €"
        if compact and abs(number) >= 1_000_000:
            return f"{format_si_number(number / 1_000_000, 1)} mio €"
        return f"{format_si_number(number, 0)} €"
    if format_type == "index":
        return format_si_number(number, 1)
    if unit == "št.":
        return format_si_number(number, 0)
    return format_si_number(number, 1)


def national_kpi_change(
    start_value: Any,
    end_value: Any,
    format_type: str,
) -> tuple[float | None, str]:
    if start_value is None or end_value is None or pd.isna(start_value) or pd.isna(end_value):
        return None, "—"
    start = float(start_value)
    end = float(end_value)
    if str(format_type) == "percent_decimal":
        change = (end - start) * 100.0
        return change, f"{'+' if change >= 0 else ''}{format_si_number(change, 1)} o.t."
    if start == 0:
        return None, "—"
    change = ((end / start) - 1.0) * 100.0
    return change, f"{'+' if change >= 0 else ''}{format_si_number(change, 1)} %"


def get_indicator_aggregation_method(
    indicator: str,
    agg_rules: dict[str, tuple[str, str | None]] | None,
) -> str:
    if not agg_rules:
        return "sum"
    method, _ = agg_rules.get(indicator, ("sum", None))
    return str(method or "sum").strip().lower()


def build_slovenia_metric_delta(
    indicator: str,
    region_value: float,
    slovenia_value,
    agg_rules: dict[str, tuple[str, str | None]] | None = None,
) -> str:
    if slovenia_value is None or pd.isna(slovenia_value):
        return "V primerjavi s Slovenijo: —"

    lower_is_better = is_lower_better(indicator)
    agg_method = get_indicator_aggregation_method(indicator, agg_rules)

    if float(slovenia_value) != 0:
        share = (float(region_value) / float(slovenia_value)) * 100.0
        favorable = share < 100 if lower_is_better else share > 100
        unfavorable = share > 100 if lower_is_better else share < 100
        prefix = "+ " if favorable else ("- " if unfavorable else "")
        if agg_method != "sum":
            return f"{prefix}Primerjalni indeks s Slovenijo: {format_si_number(share, 1)}"
        return f"Delež v Sloveniji: {format_pct(share, 1)}"

    if is_percent_like(indicator):
        delta = (float(region_value) - float(slovenia_value)) * 100.0
        delta_text = format_pct(delta, 1)
    else:
        delta = float(region_value) - float(slovenia_value)
        delta_text = format_si_number(delta, 1)

    favorable = delta < 0 if lower_is_better else delta > 0
    unfavorable = delta > 0 if lower_is_better else delta < 0
    prefix = "+ " if favorable else ("- " if unfavorable else "")
    return f"{prefix}V primerjavi s Slovenijo: {delta_text}"


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


def build_all_indicator_options(
    indicator_cols: list[str],
    grouped_filtered: dict[str, list[str]],
) -> list[str]:
    ordered_indicators: list[str] = []
    seen: set[str] = set()

    for group_indicators in grouped_filtered.values():
        for indicator in group_indicators:
            if indicator in seen:
                continue
            ordered_indicators.append(indicator)
            seen.add(indicator)

    for indicator in indicator_cols:
        if indicator in seen:
            continue
        ordered_indicators.append(indicator)
        seen.add(indicator)

    return ordered_indicators


def stable_ui_key(value: str) -> str:
    return hashlib.md5(str(value).encode("utf-8")).hexdigest()[:12]


def _metadata_by_indicator(metadata_df: pd.DataFrame | None) -> dict[str, dict[str, Any]]:
    if metadata_df is None or metadata_df.empty or "indicator" not in metadata_df.columns:
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for _, row in metadata_df.iterrows():
        indicator = str(row.get("indicator") or "").strip()
        if indicator:
            rows[indicator] = row.to_dict()
    return rows


def _catalog_year(value: Any) -> int | None:
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _is_period_indicator(indicator: str, display_name: str) -> bool:
    return "{" in str(display_name) or bool(re.search(r"\b(19|20)\d{2}/(19|20)\d{2}\b", str(indicator)))


def _indicator_catalog_label(indicator: str, metadata: dict[str, Any]) -> str:
    display_name = str(metadata.get("display_name") or "").strip()
    if not display_name or _is_period_indicator(indicator, display_name):
        return get_indicator_display_name(indicator)
    return display_name


def build_indicator_catalog(
    indicator_cols: list[str],
    grouped_filtered: dict[str, list[str]],
    metadata_df: pd.DataFrame | None,
) -> dict[str, dict[str, Any]]:
    metadata_by_indicator = _metadata_by_indicator(metadata_df)
    indicator_to_group: dict[str, str] = {}
    for group_name, indicators in grouped_filtered.items():
        for indicator in indicators:
            indicator_to_group.setdefault(indicator, group_name)

    catalog: dict[str, dict[str, Any]] = {}
    for indicator in build_all_indicator_options(indicator_cols, grouped_filtered):
        metadata = metadata_by_indicator.get(indicator, {})
        label = _indicator_catalog_label(indicator, metadata)
        metric_id = str(metadata.get("metric_id") or "").strip()
        year = _catalog_year(metadata.get("year"))

        if _is_period_indicator(indicator, str(metadata.get("display_name") or "")):
            metric_key = f"indicator::{indicator}"
            year = None
        else:
            metric_key = f"metric::{metric_id or label}"

        entry = {
            "indicator": indicator,
            "year": year,
            "label": label,
            "group": indicator_to_group.get(indicator, ""),
        }
        if metric_key not in catalog:
            catalog[metric_key] = {
                "key": metric_key,
                "label": label,
                "group": indicator_to_group.get(indicator, ""),
                "entries": [],
            }
        existing_indicators = {item["indicator"] for item in catalog[metric_key]["entries"]}
        if indicator not in existing_indicators:
            catalog[metric_key]["entries"].append(entry)

    for spec in catalog.values():
        spec["entries"] = sorted(
            spec["entries"],
            key=lambda item: (
                item["year"] is None,
                item["year"] if item["year"] is not None else 9999,
                str(item["indicator"]),
            ),
        )
    return catalog


def metric_options_for_indicators(
    catalog: dict[str, dict[str, Any]],
    indicators: list[str],
) -> list[str]:
    indicator_set = set(indicators)
    return [
        key
        for key, spec in catalog.items()
        if any(entry["indicator"] in indicator_set for entry in spec["entries"])
    ]


def format_metric_option_label(metric_key: str, catalog: dict[str, dict[str, Any]]) -> str:
    spec = catalog[metric_key]
    group_name = str(spec.get("group") or "")
    emoji = GROUP_COLOR_EMOJI[group_name] if group_name in GROUP_COLOR_EMOJI else "•"
    return f"{emoji} {spec['label']}"


def available_year_entries(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        entry
        for entry in spec.get("entries", [])
        if entry.get("year") is not None
    ]


def latest_indicator_entry(spec: dict[str, Any]) -> dict[str, Any]:
    entries = list(spec.get("entries", []))
    year_entries = available_year_entries(spec)
    if year_entries:
        return year_entries[-1]
    return entries[-1]


def indicator_entry_for_year(spec: dict[str, Any], year: int | None) -> dict[str, Any]:
    if year is not None:
        for entry in spec.get("entries", []):
            if entry.get("year") == year:
                return entry
    return latest_indicator_entry(spec)


def resolve_metric_indicator_for_year(
    metric_key: str,
    catalog: dict[str, dict[str, Any]],
    preferred_year: int | None,
) -> str:
    return str(indicator_entry_for_year(catalog[metric_key], preferred_year)["indicator"])


def render_year_comparison(
    *,
    metric_spec: dict[str, Any],
    selected_region: str,
    group_col: str,
    view_title: str,
    numeric_df: pd.DataFrame,
    regions: list[str],
    df_slo_total_num: pd.Series,
    agg_rules: dict[str, tuple[str, str | None]],
) -> None:
    entries = available_year_entries(metric_spec)
    if len(entries) < 2:
        st.info("Za izbrani kazalnik je na voljo samo eno leto.")
        return

    indicators = [str(entry["indicator"]) for entry in entries]
    show_slovenia_in_chart = not any(
        get_indicator_aggregation_method(indicator, agg_rules) == "sum"
        for indicator in indicators
    )
    st.subheader(f"Primerjava po letih - {metric_spec['label']}")

    region_agg = compute_region_aggregates(numeric_df, regions, indicators, agg_rules, group_col=group_col)

    if selected_region == "Vsa območja":
        records: list[dict[str, Any]] = []
        for _, row in region_agg.iterrows():
            area_name = str(row[group_col])
            for entry in entries:
                indicator = str(entry["indicator"])
                value = row.get(indicator, np.nan)
                if pd.isna(value):
                    continue
                records.append(
                    {
                        "Območje": area_name,
                        "Leto": int(entry["year"]),
                        "Vrednost": float(value),
                        "Prikaz": format_indicator_value_map(indicator, value),
                    }
                )
        if show_slovenia_in_chart:
            for entry in entries:
                indicator = str(entry["indicator"])
                value = df_slo_total_num.get(indicator, np.nan)
                if pd.isna(value):
                    continue
                records.append(
                    {
                        "Območje": "Slovenija",
                        "Leto": int(entry["year"]),
                        "Vrednost": float(value),
                        "Prikaz": format_indicator_value_map(indicator, value),
                    }
                )

        latest_indicator = indicators[-1]
        chart_df = pd.DataFrame(records)
        if not chart_df.empty:
            ranked_area_options = (
                region_agg[[group_col, latest_indicator]]
                .dropna(subset=[latest_indicator])
                .sort_values(latest_indicator, ascending=is_lower_better(latest_indicator), na_position="last")[group_col]
                .astype(str)
                .tolist()
            )
            default_chart_areas = ranked_area_options[: min(6, len(ranked_area_options))]
            selected_chart_areas = st.multiselect(
                "Območja za graf",
                ranked_area_options,
                default=default_chart_areas,
                max_selections=8,
                key=f"year_compare_areas_{group_col}_{stable_ui_key('|'.join(indicators))}",
            )
            if not selected_chart_areas:
                selected_chart_areas = default_chart_areas

            chart_areas = [*selected_chart_areas, "Slovenija"] if show_slovenia_in_chart else selected_chart_areas
            chart_plot_df = chart_df[chart_df["Območje"].isin(chart_areas)].copy()
            chart_plot_df["Leto"] = chart_plot_df["Leto"].astype(str)
            fig = px.bar(
                chart_plot_df,
                x="Leto",
                y="Vrednost",
                color="Območje",
                custom_data=["Območje", "Prikaz"],
                labels={"Vrednost": "Vrednost", "Leto": "Leto"},
                title=f"{metric_spec['label']} - primerjava po letih",
                barmode="group",
            )
            fig.update_traces(
                hovertemplate="<b>%{customdata[0]}</b><br>Leto: %{x}<br>Vrednost: %{customdata[1]}<extra></extra>"
            )
            fig.update_xaxes(
                type="category",
                categoryorder="array",
                categoryarray=[str(entry["year"]) for entry in entries],
            )
            fig.update_layout(height=430, legend_title_text=view_title, bargap=0.22, bargroupgap=0.08)
            st.plotly_chart(fig, use_container_width=True)
            if show_slovenia_in_chart:
                st.caption(
                    "Graf prikazuje izbrana območja in Slovenijo. Celotna razvrstitev vseh območij je v tabeli spodaj."
                )
            else:
                st.caption(
                    "Graf prikazuje izbrana območja. Pri seštevnih kazalnikih Slovenija ni dodana v graf, "
                    "ker nacionalni seštevek popači merilo; celotna razvrstitev je v tabeli spodaj."
                )

        table = region_agg[[group_col] + indicators].copy()
        slovenia_table_row = {group_col: "Slovenija"}
        has_slovenia_table_value = False
        for indicator in indicators:
            value = df_slo_total_num.get(indicator, np.nan)
            slovenia_table_row[indicator] = value
            if pd.notna(value):
                has_slovenia_table_value = True
        if has_slovenia_table_value:
            table = pd.concat([table, pd.DataFrame([slovenia_table_row])], ignore_index=True)
        table = table.sort_values(latest_indicator, ascending=is_lower_better(latest_indicator), na_position="last")
        rename_map = {str(entry["indicator"]): str(entry["year"]) for entry in entries}
        source_columns = {str(entry["year"]): str(entry["indicator"]) for entry in entries}
        table = table.rename(columns=rename_map)
        for entry in entries:
            year_label = str(entry["year"])
            indicator = str(entry["indicator"])
            table[year_label] = table[year_label].apply(lambda value, column=indicator: format_indicator_value_tables(column, value))
        table = prefix_rank_to_label_column(table, group_col)
        st.dataframe(
            streamlit_safe_dataframe(table),
            width="stretch",
            hide_index=True,
            column_config=make_localized_column_config(
                table,
                source_columns=source_columns,
                width_overrides={group_col: "large"},
            ),
        )
        return

    selected_row = region_agg[region_agg[group_col] == selected_region]
    if selected_row.empty:
        st.info("Za izbrano območje ni podatkov za primerjavo po letih.")
        return

    selected_row = selected_row.iloc[0]
    kpi_cols = st.columns(min(len(entries), 4))
    for idx, entry in enumerate(entries[:4]):
        indicator = str(entry["indicator"])
        with kpi_cols[idx]:
            st.metric(
                str(entry["year"]),
                format_indicator_value_map(indicator, selected_row.get(indicator, np.nan)),
                build_slovenia_metric_delta(
                    indicator,
                    float(selected_row.get(indicator, np.nan)),
                    df_slo_total_num.get(indicator, np.nan),
                    agg_rules,
                ),
            )

    records = []
    table_rows = []
    for entry in entries:
        indicator = str(entry["indicator"])
        year = int(entry["year"])
        area_value = selected_row.get(indicator, np.nan)
        slovenia_value = df_slo_total_num.get(indicator, np.nan)
        if pd.notna(area_value):
            records.append(
                {
                    "Serija": selected_region,
                    "Leto": year,
                    "Vrednost": float(area_value),
                    "Prikaz": format_indicator_value_map(indicator, area_value),
                }
            )
        if show_slovenia_in_chart and pd.notna(slovenia_value):
            records.append(
                {
                    "Serija": "Slovenija",
                    "Leto": year,
                    "Vrednost": float(slovenia_value),
                    "Prikaz": format_indicator_value_map(indicator, slovenia_value),
                }
            )
        index_value = (
            (float(area_value) / float(slovenia_value)) * 100.0
            if pd.notna(area_value) and pd.notna(slovenia_value) and float(slovenia_value) != 0
            else np.nan
        )
        table_rows.append(
            {
                "Leto": year,
                "Vrednost območja": format_indicator_value_map(indicator, area_value),
                "Slovenija": format_indicator_value_map(indicator, slovenia_value),
                "Indeks Slovenija = 100": format_si_number(index_value, 1) if pd.notna(index_value) else "—",
            }
        )

    chart_df = pd.DataFrame(records)
    if not chart_df.empty:
        chart_df["Leto"] = chart_df["Leto"].astype(str)
        fig = px.bar(
            chart_df,
            x="Leto",
            y="Vrednost",
            color="Serija",
            custom_data=["Serija", "Prikaz"],
            labels={"Vrednost": "Vrednost", "Leto": "Leto"},
            title=f"{metric_spec['label']} - {selected_region}",
            barmode="group",
        )
        fig.update_traces(
            hovertemplate="<b>%{customdata[0]}</b><br>Leto: %{x}<br>Vrednost: %{customdata[1]}<extra></extra>"
        )
        fig.update_xaxes(
            type="category",
            categoryorder="array",
            categoryarray=[str(entry["year"]) for entry in entries],
        )
        fig.update_layout(height=430, bargap=0.22, bargroupgap=0.08)
        st.plotly_chart(fig, use_container_width=True)
        if not show_slovenia_in_chart:
            st.caption(
                "Pri seštevnih kazalnikih Slovenija ni dodana v graf, ker nacionalni seštevek popači merilo. "
                "Primerjava s Slovenijo ostane prikazana v KPI-jih in tabeli."
            )

    st.dataframe(
        streamlit_safe_dataframe(pd.DataFrame(table_rows)),
        width="stretch",
        hide_index=True,
    )


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
    agg_rules: dict[str, tuple[str, str | None]] | None = None,
) -> pd.DataFrame:
    numeric_values = pd.to_numeric(region_df[indicator], errors="coerce")
    table = pd.DataFrame(
        {
            "Občina": region_df["Občine"].astype(str),
            "_sort_value": numeric_values,
            "Vrednost": numeric_values.apply(lambda value: format_indicator_value_tables(indicator, value)),
        }
    )

    if region_total and not np.isnan(region_total) and region_total != 0:
        agg_method = get_indicator_aggregation_method(indicator, agg_rules)
        if agg_method == "sum":
            table[f"Delež {view_title} (%)"] = round(table["_sort_value"] / region_total, 3)
        else:
            table[f"Indeks {view_title}"] = round((table["_sort_value"] / region_total) * 100, 1)

    return (
        table.sort_values("_sort_value", ascending=is_lower_better(indicator), na_position="last")
        .drop(columns="_sort_value")
        .reset_index(drop=True)
    )


def format_indicator_option_label(indicator: str, indicator_to_group: dict[str, str]) -> str:
    group_name = indicator_to_group[indicator] if indicator in indicator_to_group else ""
    emoji = GROUP_COLOR_EMOJI[group_name] if group_name in GROUP_COLOR_EMOJI else "•"
    return f"{emoji} {get_indicator_display_name(indicator)}"


def rename_indicator_columns_for_display(
    df: pd.DataFrame,
    indicators: list[str],
) -> tuple[pd.DataFrame, dict[str, str]]:
    rename_map = {indicator: get_indicator_display_name(indicator) for indicator in indicators if indicator in df.columns}
    display_df = df.rename(columns=rename_map)
    source_columns = {display_name: raw_name for raw_name, display_name in rename_map.items()}
    return display_df, source_columns


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


def streamlit_safe_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Return a display copy with string column names for Streamlit."""
    if all(isinstance(column, str) for column in df.columns):
        return df
    safe_df = df.copy()
    safe_df.columns = [str(column) for column in safe_df.columns]
    return safe_df


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
    ranked_df = streamlit_safe_dataframe(prepend_rank_column(df))
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


def render_section_heading(title: str, description: str | None = None) -> None:
    st.markdown(f"### {title}")
    if description:
        st.caption(description)


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
        "DOMAČI": "Domači trg",
        "DACH trgi": "DACH trgi (nemško govoreči trgi: D, A in CH)",
        "DACH": "DACH trgi (nemško govoreči trgi: D, A in CH)",
        "ITALIJA": "Italijanski trg",
        "ITA": "Italijanski trg",
        "VZHE": "Vzh.evropski trgi (PL,CZ,HU,SK,LIT,LTV,EST,RU,UKR)",
        "ZAHE": "Drugi zah.in sev. evropski trgi (ES,P, F,Benelux, Skandinavske države)",
        "PMT": "Prekomorski trgi (ZDA, VB, CAN, AU, Azija)",
        "JVE": "Trgi JV Evrope",
        "DRUGI": "Vsi drugi tuji trgi",
        "DRUG": "Vsi drugi tuji trgi",
    }
    return mapping.get(str(label).strip(), str(label).strip())


def shorten_market_axis_label(label: str) -> str:
    return str(label).split("(", 1)[0].strip()


def get_market_chart_label(label: str) -> str:
    return shorten_market_axis_label(normalize_market_display_label(label))


def get_market_chart_color_map() -> dict[str, str]:
    return {
        get_market_chart_label(label): color
        for label, color in MARKET_COLOR_MAP.items()
    }


def format_growth_label(value: float) -> str:
    if pd.isna(value):
        return "—"
    return format_pct(float(value) * 100.0, 1)


MARKET_AVERAGE_DISPLAY_LABEL = "Povprečje vseh trgov na območju"
MARKET_TOTAL_DISPLAY_LABEL = "Vsi trgi na območju skupaj"
MARKET_AVERAGE_COLOR = "#0f766e"
MARKET_TOTAL_FILL_COLOR = "rgba(134, 239, 172, 0.28)"
MARKET_TOTAL_LINE_COLOR = "rgba(134, 239, 172, 0.0)"
AREA_REFERENCE_COLOR = "#f59e0b"
SECONDARY_REFERENCE_COLOR = "#dc2626"


def round_market_structure_display_counts(values: pd.Series) -> pd.Series:
    numeric_values = pd.to_numeric(values, errors="coerce")
    rounded_values = pd.Series(pd.array([pd.NA] * len(numeric_values), dtype="Int64"), index=numeric_values.index)
    valid_values = numeric_values[numeric_values.notna()].astype(float)
    if valid_values.empty:
        return rounded_values

    floored_values = pd.Series(np.floor(valid_values.to_numpy()), index=valid_values.index, dtype=int)
    target_total = int(round(float(valid_values.sum())))
    remainder = max(0, target_total - int(floored_values.sum()))
    if remainder > 0:
        fractional_parts = (valid_values - floored_values).sort_values(ascending=False)
        floored_values.loc[fractional_parts.index[:remainder]] += 1

    rounded_values.loc[valid_values.index] = floored_values.astype("Int64")
    return rounded_values


def render_market_growth_chart(
    growth_df: pd.DataFrame,
    title: str,
    *,
    reference_lines: list[tuple[str, float | None, str]] | None = None,
) -> None:
    if growth_df.empty:
        st.info("Za izbran prikaz ni dovolj podatkov o rasti po trgih.")
        return

    chart_df = growth_df.copy().dropna(subset=["Rast_raw"])
    if chart_df.empty:
        st.info("Za izbran prikaz ni dovolj podatkov o rasti po trgih.")
        return

    chart_df["Trg_full"] = chart_df["Trg"].apply(normalize_market_display_label)
    chart_df = chart_df.sort_values("Rast_raw", ascending=False).reset_index(drop=True)
    chart_df["Trg"] = chart_df["Trg_full"].apply(shorten_market_axis_label)
    chart_df["Trg_chart"] = chart_df["Trg"].apply(wrap_market_chart_label)
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
        color_discrete_map=get_market_chart_color_map(),
        text="Rast_label",
        custom_data=["Trg_full", "Rast_label"],
    )
    fig.update_traces(
        cliponaxis=False,
        textposition="outside",
        hovertemplate="<b>%{customdata[0]}</b><br>Rast: %{customdata[1]}<extra></extra>",
        showlegend=False,
    )
    has_reference_lines = False
    for label, value, color in reference_lines or []:
        if value is None or not np.isfinite(value):
            continue
        has_reference_lines = True
        fig.add_hline(
            y=float(value),
            line_color=color,
            line_dash="dash",
            line_width=3,
        )
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                line=dict(color=color, width=3, dash="dash"),
                name=f"{label}: {format_growth_label(float(value))}",
                showlegend=True,
                hoverinfo="skip",
            )
        )
    fig.update_layout(
        margin=dict(t=20, b=20, l=10, r=10),
        showlegend=has_reference_lines,
        xaxis_title="Trgi",
        yaxis_title="Rast prenočitev",
        legend_title_text="Reference",
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


def render_market_seasonality_chart(
    seasonality_df: pd.DataFrame,
    title: str,
    *,
    value_title: str = "Število prenočitev",
    empty_message: str = "Za izbran prikaz ni dovolj podatkov o sezonskosti prenočitev po trgih.",
    hover_indicator: str = "Prenočitve turistov SKUPAJ - 2025",
    add_market_average_line: bool = False,
    add_total_area_secondary: bool = False,
    add_average_area_secondary: bool = False,
) -> None:
    if seasonality_df.empty:
        st.info(empty_message)
        return

    chart_df = seasonality_df.copy().dropna(subset=["Vrednost"])
    if chart_df.empty:
        st.info(empty_message)
        return

    month_order = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "avg", "sep", "okt", "nov", "dec"]
    total_df = compute_market_monthly_total_from_seasonality(chart_df) if add_total_area_secondary else pd.DataFrame()
    average_df = compute_market_monthly_average_from_seasonality(chart_df) if (add_market_average_line or add_average_area_secondary) else pd.DataFrame()
    chart_df["Trg_full"] = chart_df["Trg"].apply(normalize_market_display_label)
    chart_df["Trg"] = chart_df["Trg_full"].apply(shorten_market_axis_label)
    chart_df["Mesec"] = pd.Categorical(chart_df["Mesec"], categories=month_order, ordered=True)
    chart_df = chart_df.sort_values(["Trg", "Mesec"]).reset_index(drop=True)
    chart_df["Vrednost_prikaz"] = chart_df["Vrednost"].apply(
        lambda value: format_indicator_value_map(hover_indicator, value)
    )

    st.markdown(f"**{title}**")
    fig = go.Figure()

    area_df = total_df if add_total_area_secondary else average_df if add_average_area_secondary else pd.DataFrame()
    area_label = MARKET_TOTAL_DISPLAY_LABEL if add_total_area_secondary else MARKET_AVERAGE_DISPLAY_LABEL
    area_on_secondary_axis = add_total_area_secondary
    if not area_df.empty:
        area_df = area_df.copy()
        area_df["Mesec"] = pd.Categorical(area_df["Mesec"], categories=month_order, ordered=True)
        area_df = area_df.sort_values("Mesec").reset_index(drop=True)
        area_df["Vrednost_prikaz"] = area_df["Vrednost"].apply(
            lambda value: format_indicator_value_map(hover_indicator, value)
        )
        fig.add_trace(
            go.Scatter(
                x=area_df["Mesec"],
                y=area_df["Vrednost"],
                mode="lines",
                name=area_label,
                line=dict(color=MARKET_TOTAL_LINE_COLOR, width=0),
                fill="tozeroy",
                fillcolor=MARKET_TOTAL_FILL_COLOR,
                hovertemplate="<b>" + area_label + "</b><br>%{x}: %{customdata}<extra></extra>",
                customdata=area_df["Vrednost_prikaz"],
                yaxis="y2" if area_on_secondary_axis else None,
            )
        )

    market_color_map = get_market_chart_color_map()
    for short_label in chart_df["Trg"].drop_duplicates().tolist():
        group_df = chart_df[chart_df["Trg"] == short_label].copy()
        full_label = str(group_df["Trg_full"].iloc[0])
        fig.add_trace(
            go.Scatter(
                x=group_df["Mesec"],
                y=group_df["Vrednost"],
                mode="lines+markers",
                name=short_label,
                line=dict(color=market_color_map.get(short_label, "#2563eb"), width=3),
                marker=dict(size=7),
                customdata=np.column_stack([group_df["Vrednost_prikaz"], group_df["Trg_full"]]),
                hovertemplate="<b>%{customdata[1]}</b><br>%{x}: %{customdata[0]}<extra></extra>",
            )
        )

    if not average_df.empty and not add_average_area_secondary:
        average_df = average_df.copy()
        average_df["Mesec"] = pd.Categorical(average_df["Mesec"], categories=month_order, ordered=True)
        average_df = average_df.sort_values("Mesec").reset_index(drop=True)
        average_df["Vrednost_prikaz"] = average_df["Vrednost"].apply(
            lambda value: format_indicator_value_map(hover_indicator, value)
        )
        fig.add_trace(
            go.Scatter(
                x=average_df["Mesec"],
                y=average_df["Vrednost"],
                mode="lines+markers",
                name=MARKET_AVERAGE_DISPLAY_LABEL,
                line=dict(color=MARKET_AVERAGE_COLOR, width=3, dash="dash"),
                marker=dict(size=6),
                customdata=average_df["Vrednost_prikaz"],
                hovertemplate="<b>" + MARKET_AVERAGE_DISPLAY_LABEL + "</b><br>%{x}: %{customdata}<extra></extra>",
            )
        )

    yaxis_config: dict[str, Any] = {"title": value_title}
    layout_kwargs: dict[str, Any] = {}
    right_margin = 10
    if add_total_area_secondary and not area_df.empty:
        left_max = float(pd.to_numeric(chart_df["Vrednost"], errors="coerce").max())
        right_max = float(pd.to_numeric(area_df["Vrednost"], errors="coerce").max())
        left_limit = left_max * 1.08 if np.isfinite(left_max) and left_max > 0 else 1.0
        right_limit = right_max * 1.08 if np.isfinite(right_max) and right_max > 0 else 1.0
        yaxis_config["range"] = [0, left_limit]
        right_margin = 150
        layout_kwargs["yaxis2"] = {
            "title": f"{value_title} – {'povprečje trgov' if add_average_area_secondary else 'vsi trgi'}",
            "overlaying": "y",
            "side": "right",
            "range": [0, right_limit],
            "showgrid": False,
            "rangemode": "tozero",
            "title_standoff": 18,
            "automargin": True,
        }
        layout_kwargs["legend"] = {
            "x": 1.10,
            "y": 1.0,
            "xanchor": "left",
            "yanchor": "top",
        }
    elif add_average_area_secondary and not area_df.empty:
        left_max = float(pd.to_numeric(chart_df["Vrednost"], errors="coerce").max())
        area_max = float(pd.to_numeric(area_df["Vrednost"], errors="coerce").max())
        upper_bound = max(left_max, area_max)
        upper_limit = upper_bound * 1.08 if np.isfinite(upper_bound) and upper_bound > 1 else 1.1
        yaxis_config["range"] = [1, upper_limit]

    fig.update_layout(
        margin=dict(t=20, b=10, l=10, r=right_margin),
        xaxis_title="Meseci",
        yaxis=yaxis_config,
        legend_title_text="Skupine trgov",
        hovermode="x unified",
        height=520,
        **layout_kwargs,
    )
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=month_order)
    st.plotly_chart(fig, width="stretch")


def render_market_pdb_annual_chart(
    annual_df: pd.DataFrame,
    title: str,
    *,
    reference_lines: list[tuple[str, float | None, str]] | None = None,
) -> None:
    if annual_df.empty:
        st.info("Za izbran prikaz ni dovolj podatkov o letnem povprečju PDB po trgih.")
        return

    chart_df = annual_df.copy().dropna(subset=["Vrednost"])
    if chart_df.empty:
        st.info("Za izbran prikaz ni dovolj podatkov o letnem povprečju PDB po trgih.")
        return

    chart_df["Trg_full"] = chart_df["Trg"].apply(normalize_market_display_label)
    chart_df["Trg"] = chart_df["Trg_full"].apply(shorten_market_axis_label)
    chart_df = chart_df.sort_values("Vrednost", ascending=True).reset_index(drop=True)
    chart_df["Trg_chart"] = chart_df["Trg"].apply(wrap_market_chart_label)
    chart_df["Vrednost_label"] = chart_df["Vrednost"].apply(lambda value: format_si_number(value, 1))

    st.markdown(f"**{title}**")
    fig = px.bar(
        chart_df,
        x="Vrednost",
        y="Trg_chart",
        orientation="h",
        color="Trg",
        color_discrete_map=get_market_chart_color_map(),
        text="Vrednost_label",
        custom_data=["Trg_full", "Vrednost_label"],
    )
    fig.update_traces(
        textposition="outside",
        cliponaxis=False,
        hovertemplate="<b>%{customdata[0]}</b><br>PDB: %{customdata[1]}<extra></extra>",
        showlegend=False,
    )
    has_reference_lines = False
    for label, value, color in reference_lines or []:
        if value is None or not np.isfinite(value):
            continue
        has_reference_lines = True
        fig.add_vline(
            x=float(value),
            line_color=color,
            line_dash="dash",
            line_width=3,
        )
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                line=dict(color=color, width=3, dash="dash"),
                name=f"{label}: {format_si_number(float(value), 1)}",
                showlegend=True,
                hoverinfo="skip",
            )
        )
    fig.update_xaxes(automargin=True)
    fig.update_layout(
        margin=dict(t=20, b=10, l=10, r=30),
        showlegend=has_reference_lines,
        xaxis_title="PDB",
        yaxis_title="Trgi",
        legend_title_text="Reference",
        uniformtext_minsize=10,
        uniformtext_mode="hide",
        height=520,
    )
    st.plotly_chart(fig, width="stretch")


def render_market_structure_pie_table(
    structure_df: pd.DataFrame,
    *,
    pie_title: str,
    value_column_label: str,
    value_indicator_label: str,
    category_column_label: str = "Trg",
    total_row_label: str = MARKET_TOTAL_DISPLAY_LABEL,
    legend_title: str = "Trgi",
    color_discrete_map: dict[str, str] | None = None,
    note_text: str | None = None,
) -> None:
    if structure_df.empty:
        st.info("Za izbran prikaz ni dovolj podatkov o strukturi po trgih.")
        return

    display_df = structure_df.copy().dropna(subset=["Delež_norm", "Vrednost"])
    if display_df.empty:
        st.info("Za izbran prikaz ni dovolj podatkov o strukturi po trgih.")
        return

    display_df["Trg_full"] = display_df["Trg"].apply(normalize_market_display_label)
    display_df["Trg_short"] = display_df["Trg_full"].apply(shorten_market_axis_label)
    display_df = display_df.sort_values("Delež_norm", ascending=False).reset_index(drop=True)
    display_df["Trg_short_wrapped"] = display_df["Trg_short"].apply(lambda value: shorten_label(value, 24))
    display_df["Vrednost_display"] = round_market_structure_display_counts(display_df["Vrednost"])
    display_df["Share_label"] = display_df["Delež_norm"].apply(lambda value: format_pct(float(value) * 100.0, 1))
    display_df["Value_label"] = display_df["Vrednost_display"].apply(
        lambda value: format_indicator_value_map(value_indicator_label, value)
    )
    display_df["Hover_label"] = display_df.apply(
        lambda row: (
            f"<b>{row['Trg_full']}</b><br>"
            f"Delež: {row['Share_label']}<br>"
            f"{value_column_label}: {row['Value_label']}"
        ),
        axis=1,
    )

    chart_col, table_col = st.columns([1.2, 1])
    with chart_col:
        st.markdown(f"**{pie_title}**")
        fig = px.pie(
            display_df,
            names="Trg_short_wrapped",
            values="Delež_norm",
            color="Trg_short",
            color_discrete_map=color_discrete_map or get_market_chart_color_map(),
            hole=0.4,
        )
        fig.update_traces(
            textposition="inside",
            textinfo="percent+label",
            hovertext=display_df["Hover_label"],
            hovertemplate="%{hovertext}<extra></extra>",
        )
        fig.update_layout(
            margin=dict(t=10, b=10, l=10, r=10),
            showlegend=True,
            legend_title_text=legend_title,
        )
        st.plotly_chart(fig, width="stretch")

    with table_col:
        st.markdown("**Tabela**")
        table = display_df[["Trg_full", "Delež_norm", "Vrednost_display"]].rename(
            columns={
                "Trg_full": category_column_label,
                "Delež_norm": "Delež (%)",
                "Vrednost_display": value_column_label,
            }
        )
        total_row = pd.DataFrame(
            [
                {
                    category_column_label: total_row_label,
                    "Delež (%)": 1.0,
                    value_column_label: int(display_df["Vrednost_display"].sum(skipna=True)),
                }
            ]
        )
        table = pd.concat([table, total_row], ignore_index=True)
        table = streamlit_safe_dataframe(table)
        st.dataframe(
            table,
            width="stretch",
            hide_index=True,
            column_config={
                **make_localized_column_config(
                    table,
                    source_columns={value_column_label: value_indicator_label},
                    width_overrides={
                        category_column_label: "medium",
                        value_column_label: "small",
                    },
                ),
                "Delež (%)": st.column_config.NumberColumn(format="percent", width="small"),
            },
        )

    if note_text:
        st.caption(note_text)


ACCOMMODATION_CAPACITY_YEARS = [2019, 2024, 2025]
ACCOMMODATION_CAPACITY_GROWTH_PERIODS = {
    "2024/2019": (2019, 2024),
    "2025/2019": (2019, 2025),
    "2025/2024": (2024, 2025),
}
ACCOMMODATION_TYPE_HOTELS = "Hoteli in podobni nastanitveni obrati"
ACCOMMODATION_TYPE_CAMPS = "Kampi"
ACCOMMODATION_TYPE_OTHER = "Druge vrste nastanitvenih obratov"
ACCOMMODATION_CAPACITY_CATEGORY_LABELS = [
    ACCOMMODATION_TYPE_HOTELS,
    ACCOMMODATION_TYPE_CAMPS,
    ACCOMMODATION_TYPE_OTHER,
]
ACCOMMODATION_CAPACITY_COLOR_MAP = {
    ACCOMMODATION_TYPE_HOTELS: "#2563eb",
    ACCOMMODATION_TYPE_CAMPS: "#16a34a",
    ACCOMMODATION_TYPE_OTHER: "#f59e0b",
    "Skupaj vse vrste obratov": "#0f766e",
    "Skupaj vse vrste kapacitet": "#0f766e",
}

ACCOMMODATION_CAPACITY_SPECS: dict[str, dict[str, Any]] = {
    "establishments": {
        "value_column_label": "Število obratov",
        "total_label": "Skupaj vse vrste obratov",
        "years": {
            2019: {
                ACCOMMODATION_TYPE_HOTELS: [["Število hotelov ipd. NO 2019"]],
                ACCOMMODATION_TYPE_CAMPS: [["Število kampov 2019"]],
                ACCOMMODATION_TYPE_OTHER: [
                    [
                        "Število turističnih kmetij z nastanitvijo 2019",
                        "Število vseh drugih vrst NO 2019",
                    ],
                    ["Število vseh drugih vrst NO 2019"],
                ],
            },
            2024: {
                ACCOMMODATION_TYPE_HOTELS: [["Število hotelov ipd. NO 2024"]],
                ACCOMMODATION_TYPE_CAMPS: [["Število kampov 2024"]],
                ACCOMMODATION_TYPE_OTHER: [
                    [
                        "Število turističnih kmetij z nastanitvijo 2024",
                        "Število vseh drugih vrst NO 2024",
                    ],
                    ["Število vseh drugih vrst NO 2024"],
                ],
            },
            2025: {
                ACCOMMODATION_TYPE_HOTELS: [["Število hotelov ipd. NO 2025"]],
                ACCOMMODATION_TYPE_CAMPS: [["Število kampov 2025"]],
                ACCOMMODATION_TYPE_OTHER: [
                    [
                        "Število turističnih kmetij z nastanitvijo 2025",
                        "Število vseh drugih vrst NO 2025",
                    ],
                    ["Število vseh drugih vrst NO 2025"],
                ],
            },
        },
    },
    "rooms": {
        "value_column_label": "Sobe (nedeljive enote)",
        "total_label": "Skupaj vse vrste kapacitet",
        "years": {
            2019: {
                ACCOMMODATION_TYPE_HOTELS: [
                    ["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Hoteli in podobni obrati 2019"],
                    ["Število sob v hotelih ipd. NO 2019"],
                ],
                ACCOMMODATION_TYPE_CAMPS: [
                    ["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Kampi 2019"],
                    ["Število enot v kampih 2019"],
                ],
                ACCOMMODATION_TYPE_OTHER: [
                    ["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet 2019"],
                    [
                        "Število sob v turističnih kmetijah z nastanitvijo 2019",
                        "Število sob v vseh drugih vrstah NO 2019",
                    ],
                    ["Število sob v vseh drugih vrstah NO 2019"],
                ],
            },
            2024: {
                ACCOMMODATION_TYPE_HOTELS: [
                    ["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Hoteli in podobni obrati"],
                    ["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Hoteli in podobni obrati 2024"],
                    ["Število sob v hotelih ipd. NO 2024"],
                ],
                ACCOMMODATION_TYPE_CAMPS: [
                    ["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Kampi"],
                    ["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Kampi 2024"],
                    ["Število enot v kampih 2024"],
                ],
                ACCOMMODATION_TYPE_OTHER: [
                    ["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet"],
                    ["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet 2024"],
                    [
                        "Število sob v turističnih kmetijah z nastanitvijo 2024",
                        "Število sob v vseh drugih vrstah NO 2024",
                    ],
                    ["Število sob v vseh drugih vrstah NO 2024"],
                ],
            },
            2025: {
                ACCOMMODATION_TYPE_HOTELS: [["Število sob v hotelih ipd. NO 2025"]],
                ACCOMMODATION_TYPE_CAMPS: [["Število enot v kampih 2025"]],
                ACCOMMODATION_TYPE_OTHER: [
                    [
                        "Število sob v turističnih kmetijah z nastanitvijo 2025",
                        "Število sob v vseh drugih vrstah NO 2025",
                    ],
                    ["Število sob v vseh drugih vrstah NO 2025"],
                ],
            },
        },
    },
    "beds": {
        "value_column_label": "Stalna ležišča",
        "total_label": "Skupaj vse vrste kapacitet",
        "years": {
            2019: {
                ACCOMMODATION_TYPE_HOTELS: [
                    ["Struktura nastanitvenih kapacitet - Stalna ležišča - Hoteli in podobni obrati 2019"],
                    ["Število stalnih ležišč v hotelih ipd. NO 2019"],
                ],
                ACCOMMODATION_TYPE_CAMPS: [
                    ["Struktura nastanitvenih kapacitet - Stalna ležišča - Kampi 2019"],
                    ["Število ležišč v kampih 2019"],
                ],
                ACCOMMODATION_TYPE_OTHER: [
                    ["Struktura nastanitvenih kapacitet - Stalna ležišča - Druge vrste kapacitet 2019"],
                    [
                        "Število ležišč v turističnih kmetijah z nastanitvijo 2019",
                        "Število ležišč v vseh drugih vrstah NO 2019",
                    ],
                    ["Število ležišč v vseh drugih vrstah NO 2019"],
                ],
            },
            2024: {
                ACCOMMODATION_TYPE_HOTELS: [
                    ["Struktura nastanitvenih kapacitet - Stalna ležišča - Hoteli in podobni obrati"],
                    ["Struktura nastanitvenih kapacitet - Stalna ležišča - Hoteli in podobni obrati 2024"],
                    ["Število stalnih ležišč v hotelih ipd. NO 2024"],
                ],
                ACCOMMODATION_TYPE_CAMPS: [
                    ["Struktura nastanitvenih kapacitet - Stalna ležišča - Kampi"],
                    ["Struktura nastanitvenih kapacitet - Stalna ležišča - Kampi 2024"],
                    ["Število ležišč v kampih 2024"],
                ],
                ACCOMMODATION_TYPE_OTHER: [
                    ["Struktura nastanitvenih kapacitet - Stalna ležišča - Druge vrste kapacitet"],
                    ["Struktura nastanitvenih kapacitet - Stalna ležišča - Druge vrste kapacitet 2024"],
                    [
                        "Število ležišč v turističnih kmetijah z nastanitvijo 2024",
                        "Število ležišč v vseh drugih vrstah NO 2024",
                    ],
                    ["Število ležišč v vseh drugih vrstah NO 2024"],
                ],
            },
            2025: {
                ACCOMMODATION_TYPE_HOTELS: [["Število stalnih ležišč v hotelih ipd. NO 2025"]],
                ACCOMMODATION_TYPE_CAMPS: [["Število ležišč v kampih 2025"]],
                ACCOMMODATION_TYPE_OTHER: [
                    [
                        "Število ležišč v turističnih kmetijah z nastanitvijo 2025",
                        "Število ležišč v vseh drugih vrstah NO 2025",
                    ],
                    ["Število ležišč v vseh drugih vrstah NO 2025"],
                ],
            },
        },
    },
}


def sum_first_available_accommodation_columns(
    source_df: pd.DataFrame,
    candidate_groups: list[list[str]],
) -> float | None:
    for candidate_group in candidate_groups:
        existing_columns = [column for column in candidate_group if column in source_df.columns]
        if not existing_columns:
            continue
        total = 0.0
        for column in existing_columns:
            total += float(pd.to_numeric(source_df[column], errors="coerce").sum(skipna=True))
        return total
    return None


def build_accommodation_capacity_structure_df(
    source_df: pd.DataFrame,
    spec_key: str,
    year: int,
) -> tuple[pd.DataFrame, list[str]]:
    spec = ACCOMMODATION_CAPACITY_SPECS[spec_key]
    year_specs = cast(dict[int, dict[str, list[list[str]]]], spec["years"])
    category_specs = year_specs.get(year, {})
    missing_categories: list[str] = []
    rows: list[dict[str, Any]] = []

    for category_label in ACCOMMODATION_CAPACITY_CATEGORY_LABELS:
        value = sum_first_available_accommodation_columns(
            source_df,
            category_specs.get(category_label, []),
        )
        if value is None:
            missing_categories.append(category_label)
            continue
        rows.append({"Trg": category_label, "Vrednost": value})

    structure_df = pd.DataFrame(rows)
    if structure_df.empty:
        return pd.DataFrame(columns=["Trg", "Vrednost", "Delež_norm"]), missing_categories

    total_value = float(structure_df["Vrednost"].sum(skipna=True))
    if not np.isfinite(total_value) or total_value <= 0:
        return pd.DataFrame(columns=["Trg", "Vrednost", "Delež_norm"]), missing_categories

    structure_df["Delež_norm"] = structure_df["Vrednost"] / total_value
    return structure_df, missing_categories


def render_accommodation_capacity_missing_message(
    *,
    title: str,
    year_or_period: str,
    missing_categories: list[str],
) -> None:
    missing_text = ", ".join(missing_categories) if missing_categories else "zahtevane vrste kapacitet"
    st.info(
        f"Za prikaz »{title}« za {year_or_period} trenutno ni dovolj podatkov. "
        f"Manjkajo stolpci za: {missing_text}."
    )


def render_accommodation_capacity_structure_tab(
    *,
    source_df: pd.DataFrame,
    spec_key: str,
    title: str,
    area_label: str,
    key_prefix: str,
) -> None:
    selected_year = st.selectbox(
        "Leto",
        ACCOMMODATION_CAPACITY_YEARS,
        index=len(ACCOMMODATION_CAPACITY_YEARS) - 1,
        key=f"{key_prefix}_year",
    )
    spec = ACCOMMODATION_CAPACITY_SPECS[spec_key]
    value_column_label = cast(str, spec["value_column_label"])
    total_label = cast(str, spec["total_label"])

    with st.container(border=True):
        render_section_heading(
            f"{title}: {area_label}",
            f"Struktura po vrstah kapacitet za leto {selected_year}.",
        )
        structure_df, missing_categories = build_accommodation_capacity_structure_df(
            source_df,
            spec_key,
            selected_year,
        )
        if structure_df.empty:
            render_accommodation_capacity_missing_message(
                title=title,
                year_or_period=f"leto {selected_year}",
                missing_categories=missing_categories,
            )
            return

        if missing_categories:
            st.caption(f"Manjkajo podatki za: {', '.join(missing_categories)}.")

        render_market_structure_pie_table(
            structure_df,
            pie_title=f"{title} ({selected_year})",
            value_column_label=value_column_label,
            value_indicator_label=f"{value_column_label} {selected_year}",
            category_column_label="Vrsta",
            total_row_label=total_label,
            legend_title="Vrste",
            color_discrete_map=ACCOMMODATION_CAPACITY_COLOR_MAP,
        )


def build_accommodation_capacity_growth_df(
    source_df: pd.DataFrame,
    spec_key: str,
    start_year: int,
    end_year: int,
) -> tuple[pd.DataFrame, list[str]]:
    spec = ACCOMMODATION_CAPACITY_SPECS[spec_key]
    total_label = cast(str, spec["total_label"])
    start_df, missing_start = build_accommodation_capacity_structure_df(source_df, spec_key, start_year)
    end_df, missing_end = build_accommodation_capacity_structure_df(source_df, spec_key, end_year)
    missing_context = [
        *(f"{start_year}: {category}" for category in missing_start),
        *(f"{end_year}: {category}" for category in missing_end),
    ]
    if start_df.empty or end_df.empty:
        return pd.DataFrame(columns=["Vrsta", "Rast", "Začetna vrednost", "Končna vrednost"]), missing_context

    start_values = dict(zip(start_df["Trg"], start_df["Vrednost"]))
    end_values = dict(zip(end_df["Trg"], end_df["Vrednost"]))
    start_values[total_label] = float(start_df["Vrednost"].sum(skipna=True))
    end_values[total_label] = float(end_df["Vrednost"].sum(skipna=True))

    rows: list[dict[str, Any]] = []
    for label in [*ACCOMMODATION_CAPACITY_CATEGORY_LABELS, total_label]:
        start_value = float(start_values.get(label, np.nan))
        end_value = float(end_values.get(label, np.nan))
        if not np.isfinite(start_value) or start_value <= 0 or not np.isfinite(end_value):
            continue
        rows.append(
            {
                "Vrsta": label,
                "Rast": (end_value / start_value) - 1.0,
                "Začetna vrednost": start_value,
                "Končna vrednost": end_value,
            }
        )

    return pd.DataFrame(rows), missing_context


def render_accommodation_capacity_growth_chart(
    growth_df: pd.DataFrame,
    *,
    title: str,
    value_column_label: str,
) -> None:
    chart_df = growth_df.copy().dropna(subset=["Rast"])
    if chart_df.empty:
        st.info("Za izbran prikaz ni dovolj podatkov o rasti kapacitet.")
        return

    chart_df["Vrsta_chart"] = chart_df["Vrsta"].apply(lambda value: wrap_market_chart_label(value, 18))
    chart_df["Rast_label"] = chart_df["Rast"].apply(format_growth_label)
    chart_df["Začetna_label"] = chart_df["Začetna vrednost"].apply(lambda value: format_si_number(round(value)))
    chart_df["Končna_label"] = chart_df["Končna vrednost"].apply(lambda value: format_si_number(round(value)))

    st.markdown(f"**{title}**")
    fig = px.bar(
        chart_df,
        x="Vrsta_chart",
        y="Rast",
        color="Vrsta",
        color_discrete_map=ACCOMMODATION_CAPACITY_COLOR_MAP,
        text="Rast_label",
        custom_data=["Vrsta", "Rast_label", "Začetna_label", "Končna_label"],
    )
    fig.update_traces(
        cliponaxis=False,
        textposition="outside",
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Rast: %{customdata[1]}<br>"
            f"Začetna vrednost ({value_column_label}): %{{customdata[2]}}<br>"
            f"Končna vrednost ({value_column_label}): %{{customdata[3]}}"
            "<extra></extra>"
        ),
    )
    fig.add_hline(y=0, line_color="#64748b", line_width=1)
    fig.update_layout(
        margin=dict(t=20, b=20, l=10, r=10),
        showlegend=False,
        xaxis_title="Vrste kapacitet",
        yaxis_title="Rast",
        uniformtext_minsize=10,
        uniformtext_mode="hide",
    )
    fig.update_xaxes(automargin=True)
    fig.update_yaxes(tickformat=".0%", zeroline=True, zerolinewidth=1)
    st.plotly_chart(fig, width="stretch")


def render_accommodation_capacity_growth_tab(
    *,
    source_df: pd.DataFrame,
    spec_key: str,
    title: str,
    area_label: str,
    key_prefix: str,
) -> None:
    period_labels = list(ACCOMMODATION_CAPACITY_GROWTH_PERIODS.keys())
    selected_period = st.selectbox(
        "Obdobje rasti",
        period_labels,
        index=len(period_labels) - 1,
        key=f"{key_prefix}_growth_period",
    )
    start_year, end_year = ACCOMMODATION_CAPACITY_GROWTH_PERIODS[selected_period]
    spec = ACCOMMODATION_CAPACITY_SPECS[spec_key]
    value_column_label = cast(str, spec["value_column_label"])

    with st.container(border=True):
        render_section_heading(
            f"{title}: {area_label}",
            f"Rast med letoma {start_year} in {end_year}.",
        )
        growth_df, missing_context = build_accommodation_capacity_growth_df(
            source_df,
            spec_key,
            start_year,
            end_year,
        )
        if growth_df.empty:
            render_accommodation_capacity_missing_message(
                title=title,
                year_or_period=f"obdobje {selected_period}",
                missing_categories=missing_context,
            )
            return

        if missing_context:
            st.caption(f"Manjkajo podatki za: {', '.join(missing_context)}.")

        render_accommodation_capacity_growth_chart(
            growth_df,
            title=f"{title} ({selected_period})",
            value_column_label=value_column_label,
        )


def get_seasonality_sheet_key(view_title: str, group_col: str) -> str | None:
    if group_col == "SLOVENIJA":
        return "Občine"

    mapping = {
        "Turistične regije": "Turistične regije",
        "Vodilne destinacije": "Vodilne destinacije",
        "Perspektivne destinacije": "Perspektivne destinacije",
        "Makrodestinacije": "Makrodestinacije",
    }
    return mapping.get(view_title)


def get_market_monthly_area_subset(
    *,
    monthly_sheet: pd.DataFrame,
    aggregate_sheet: pd.DataFrame | None,
    selected_group: str,
    group_col: str,
) -> pd.DataFrame:
    if group_col == "SLOVENIJA":
        return monthly_sheet[
            monthly_sheet["__label__"].apply(normalize_name) == normalize_name("SLOVENIJA")
        ].copy()

    if aggregate_sheet is None or aggregate_sheet.empty:
        return pd.DataFrame()

    return aggregate_sheet[
        aggregate_sheet["__label__"].apply(normalize_name) == normalize_name(selected_group)
    ].copy()


def get_market_monthly_municipality_names(
    *,
    df_source: pd.DataFrame,
    municipality_sheet: pd.DataFrame,
    selected_group: str,
    group_col: str,
) -> list[str]:
    municipality_name_set = set(municipality_sheet["__label__"].apply(normalize_name))
    municipality_names = (
        df_source[df_source[group_col] == selected_group]["Občine"]
        .dropna()
        .astype(str)
        .tolist()
    )
    return [name for name in municipality_names if normalize_name(name) in municipality_name_set]


def render_market_overnight_seasonality_distribution(
    *,
    selected_group: str,
    view_title: str,
    group_col: str,
    mode: str,
    df_source: pd.DataFrame,
) -> None:
    seasonality_by_year = load_market_overnight_seasonality_data()
    if not seasonality_by_year:
        st.warning("Ne najdem datotek za sezonskost prenočitev po trgih.")
        return

    available_years = sorted(seasonality_by_year.keys())
    selected_year = st.selectbox(
        "Leto",
        available_years,
        index=len(available_years) - 1,
        key=f"trgi_seasonality_year_{group_col}",
    )
    seasonality_book = seasonality_by_year[selected_year]
    municipality_sheet = seasonality_book.get("Občine")
    if municipality_sheet is None or municipality_sheet.empty:
        st.warning("V sezonski datoteki manjka list »Občine«.")
        return

    if mode == "Celotno območje":
        if group_col == "SLOVENIJA":
            area_subset = municipality_sheet[
                municipality_sheet["__label__"].apply(normalize_name) == normalize_name("SLOVENIJA")
            ].copy()
        else:
            sheet_key = get_seasonality_sheet_key(view_title, group_col)
            sheet_df = seasonality_book.get(sheet_key or "")
            if sheet_df is None or sheet_df.empty:
                st.warning("V sezonski datoteki ne najdem ustreznega lista za izbran pogled.")
                return
            area_subset = sheet_df[
                sheet_df["__label__"].apply(normalize_name) == normalize_name(selected_group)
            ].copy()

        if area_subset.empty:
            st.info("Za izbrano območje ni sezonskih podatkov o prenočitvah po trgih.")
            return

        with st.container(border=True):
            render_section_heading(
                f"Sezonskost prenočitev po trgih: {selected_group}",
                f"Linijski prikaz mesečnega gibanja prenočitev po skupinah trgov za leto {selected_year}.",
            )
            chart_df = compute_market_seasonality_for_subset(area_subset)
            render_market_seasonality_chart(
                chart_df,
                f"Sezonskost prenočitev po trgih ({selected_year})",
                add_total_area_secondary=True,
            )
        return

    filtered_source = df_source[df_source[group_col].notna()].copy()
    municipality_names = (
        filtered_source[filtered_source[group_col] == selected_group]["Občine"]
        .dropna()
        .astype(str)
        .tolist()
    )
    municipality_names = [name for name in municipality_names if normalize_name(name) in set(municipality_sheet["__label__"].apply(normalize_name))]
    if not municipality_names:
        st.info("Za izbrano območje ni občinskih sezonskih podatkov o prenočitvah po trgih.")
        return

    with st.container(border=True):
        render_section_heading(
            f"Občine znotraj območja: {selected_group}",
            f"Izberi občino za prikaz mesečnega gibanja prenočitev po trgih v letu {selected_year}.",
        )
        chosen_muni_raw = st.selectbox(
            "Izberi občino",
            municipality_names,
            index=0,
            key=f"trgi_seasonality_muni_{group_col}_{selected_year}",
        )
        if chosen_muni_raw is None:
            return
        chosen_muni = str(chosen_muni_raw)
        muni_subset = municipality_sheet[
            municipality_sheet["__label__"].apply(normalize_name) == normalize_name(chosen_muni)
        ].copy()
        chart_df = compute_market_seasonality_for_subset(muni_subset)
        render_market_seasonality_chart(
            chart_df,
            f"{chosen_muni} – sezonskost prenočitev po trgih ({selected_year})",
            add_total_area_secondary=True,
        )


def render_market_arrivals_structure_distribution(
    *,
    selected_group: str,
    view_title: str,
    group_col: str,
    mode: str,
    df_source: pd.DataFrame,
) -> None:
    seasonality_by_year = load_market_arrivals_seasonality_data()
    if not seasonality_by_year:
        st.warning("Ne najdem datotek za sezonskost prihodov po trgih.")
        return

    available_years = sorted(seasonality_by_year.keys())
    selected_year = st.selectbox(
        "Leto",
        available_years,
        index=len(available_years) - 1,
        key=f"prihodi_structure_year_{group_col}",
    )
    seasonality_book = seasonality_by_year[selected_year]
    municipality_sheet = seasonality_book.get("Občine")
    if municipality_sheet is None or municipality_sheet.empty:
        st.warning("V datoteki prihodov manjka list »Občine«.")
        return

    if mode == "Celotno območje":
        if group_col == "SLOVENIJA":
            area_subset = municipality_sheet[
                municipality_sheet["__label__"].apply(normalize_name) == normalize_name("SLOVENIJA")
            ].copy()
        else:
            sheet_key = get_seasonality_sheet_key(view_title, group_col)
            sheet_df = seasonality_book.get(sheet_key or "")
            if sheet_df is None or sheet_df.empty:
                st.warning("V datoteki prihodov ne najdem ustreznega lista za izbran pogled.")
                return
            area_subset = sheet_df[
                sheet_df["__label__"].apply(normalize_name) == normalize_name(selected_group)
            ].copy()

        if area_subset.empty:
            st.info("Za izbrano območje ni podatkov o strukturi prihodov po trgih.")
            return

        with st.container(border=True):
            render_section_heading(
                f"Struktura prihodov po trgih: {selected_group}",
                f"Tortni prikaz strukture prihodov po skupinah trgov za leto {selected_year}.",
            )
            structure_df = compute_market_monthly_structure_for_subset(area_subset)
            render_market_structure_pie_table(
                structure_df,
                pie_title=f"Struktura prihodov po trgih ({selected_year})",
                value_column_label="Prihodi",
                value_indicator_label=f"Prihodi turistov SKUPAJ - {selected_year}",
                note_text=(
                    "Deleži so izračunani iz vsote vseh mesečnih prihodov po posamezni skupini trgov "
                    f"v letu {selected_year} in nato normalizirani na 100%."
                ),
            )
        return

    filtered_source = df_source[df_source[group_col].notna()].copy()
    municipality_name_set = set(municipality_sheet["__label__"].apply(normalize_name))
    municipality_names = (
        filtered_source[filtered_source[group_col] == selected_group]["Občine"]
        .dropna()
        .astype(str)
        .tolist()
    )
    municipality_names = [name for name in municipality_names if normalize_name(name) in municipality_name_set]
    if not municipality_names:
        st.info("Za izbrano območje ni občinskih podatkov o strukturi prihodov po trgih.")
        return

    with st.container(border=True):
        render_section_heading(
            f"Občine znotraj območja: {selected_group}",
            f"Izberi občino za prikaz strukture prihodov po trgih v letu {selected_year}.",
        )
        chosen_muni_raw = st.selectbox(
            "Izberi občino",
            municipality_names,
            index=0,
            key=f"prihodi_structure_muni_{group_col}_{selected_year}",
        )
        if chosen_muni_raw is None:
            return
        chosen_muni = str(chosen_muni_raw)
        muni_subset = municipality_sheet[
            municipality_sheet["__label__"].apply(normalize_name) == normalize_name(chosen_muni)
        ].copy()
        structure_df = compute_market_monthly_structure_for_subset(muni_subset)
        render_market_structure_pie_table(
            structure_df,
            pie_title=f"{chosen_muni} – struktura prihodov po trgih ({selected_year})",
            value_column_label="Prihodi",
            value_indicator_label=f"Prihodi turistov SKUPAJ - {selected_year}",
            note_text=(
                "Deleži so izračunani iz vsote vseh mesečnih prihodov po posamezni skupini trgov "
                f"v letu {selected_year}."
            ),
        )


def render_market_arrivals_seasonality_distribution(
    *,
    selected_group: str,
    view_title: str,
    group_col: str,
    mode: str,
    df_source: pd.DataFrame,
) -> None:
    seasonality_by_year = load_market_arrivals_seasonality_data()
    if not seasonality_by_year:
        st.warning("Ne najdem datotek za sezonskost prihodov po trgih.")
        return

    available_years = sorted(seasonality_by_year.keys())
    selected_year = st.selectbox(
        "Leto",
        available_years,
        index=len(available_years) - 1,
        key=f"prihodi_seasonality_year_{group_col}",
    )
    seasonality_book = seasonality_by_year[selected_year]
    municipality_sheet = seasonality_book.get("Občine")
    if municipality_sheet is None or municipality_sheet.empty:
        st.warning("V sezonski datoteki prihodov manjka list »Občine«.")
        return

    if mode == "Celotno območje":
        if group_col == "SLOVENIJA":
            area_subset = municipality_sheet[
                municipality_sheet["__label__"].apply(normalize_name) == normalize_name("SLOVENIJA")
            ].copy()
        else:
            sheet_key = get_seasonality_sheet_key(view_title, group_col)
            sheet_df = seasonality_book.get(sheet_key or "")
            if sheet_df is None or sheet_df.empty:
                st.warning("V datoteki prihodov ne najdem ustreznega lista za izbran pogled.")
                return
            area_subset = sheet_df[
                sheet_df["__label__"].apply(normalize_name) == normalize_name(selected_group)
            ].copy()

        if area_subset.empty:
            st.info("Za izbrano območje ni sezonskih podatkov o prihodih po trgih.")
            return

        with st.container(border=True):
            render_section_heading(
                f"Sezonskost prihodov po trgih: {selected_group}",
                f"Linijski prikaz mesečnega gibanja prihodov po skupinah trgov za leto {selected_year}.",
            )
            chart_df = compute_market_seasonality_for_subset(area_subset)
            render_market_seasonality_chart(
                chart_df,
                f"Sezonskost prihodov po trgih ({selected_year})",
                value_title="Število prihodov",
                empty_message="Za izbran prikaz ni dovolj podatkov o sezonskosti prihodov po trgih.",
                hover_indicator="Prihodi turistov SKUPAJ - 2025",
                add_total_area_secondary=True,
            )
        return

    filtered_source = df_source[df_source[group_col].notna()].copy()
    municipality_name_set = set(municipality_sheet["__label__"].apply(normalize_name))
    municipality_names = (
        filtered_source[filtered_source[group_col] == selected_group]["Občine"]
        .dropna()
        .astype(str)
        .tolist()
    )
    municipality_names = [name for name in municipality_names if normalize_name(name) in municipality_name_set]
    if not municipality_names:
        st.info("Za izbrano območje ni občinskih sezonskih podatkov o prihodih po trgih.")
        return

    with st.container(border=True):
        render_section_heading(
            f"Občine znotraj območja: {selected_group}",
            f"Izberi občino za prikaz mesečnega gibanja prihodov po trgih v letu {selected_year}.",
        )
        chosen_muni_raw = st.selectbox(
            "Izberi občino",
            municipality_names,
            index=0,
            key=f"prihodi_seasonality_muni_{group_col}_{selected_year}",
        )
        if chosen_muni_raw is None:
            return
        chosen_muni = str(chosen_muni_raw)
        muni_subset = municipality_sheet[
            municipality_sheet["__label__"].apply(normalize_name) == normalize_name(chosen_muni)
        ].copy()
        chart_df = compute_market_seasonality_for_subset(muni_subset)
        render_market_seasonality_chart(
            chart_df,
            f"{chosen_muni} – sezonskost prihodov po trgih ({selected_year})",
            value_title="Število prihodov",
            empty_message="Za izbran prikaz ni dovolj podatkov o sezonskosti prihodov po trgih.",
            hover_indicator="Prihodi turistov SKUPAJ - 2025",
            add_total_area_secondary=True,
        )


def render_market_pdb_annual_distribution(
    *,
    selected_group: str,
    view_title: str,
    group_col: str,
    mode: str,
    df_source: pd.DataFrame,
) -> None:
    pdb_by_year = load_market_pdb_data()
    arrivals_by_year = load_market_arrivals_seasonality_data()
    if not pdb_by_year:
        st.warning("Ne najdem datotek za PDB po trgih.")
        return

    available_years = sorted(pdb_by_year.keys())
    selected_year = st.selectbox(
        "Leto",
        available_years,
        index=len(available_years) - 1,
        key=f"pdb_annual_year_{group_col}",
    )
    pdb_book = pdb_by_year[selected_year]
    municipality_entry = pdb_book.get("Občine")
    municipality_annual_df = municipality_entry.get("annual_avg") if municipality_entry else None
    if municipality_annual_df is None or municipality_annual_df.empty:
        st.warning("V PDB datoteki manjka del z letnim povprečjem za list »Občine«.")
        return
    arrivals_book = arrivals_by_year.get(selected_year, {})
    municipality_arrivals_df = arrivals_book.get("Občine")

    if mode == "Celotno območje":
        sheet_key = get_seasonality_sheet_key(view_title, group_col)
        aggregate_entry = pdb_book.get(sheet_key or "")
        aggregate_annual_df = aggregate_entry.get("annual_avg") if aggregate_entry else None
        area_subset = get_market_monthly_area_subset(
            monthly_sheet=municipality_annual_df,
            aggregate_sheet=aggregate_annual_df,
            selected_group=selected_group,
            group_col=group_col,
        )
        if area_subset.empty:
            st.info("Za izbrano območje ni podatkov o letnem povprečju PDB po trgih.")
            return

        area_arrivals_aggregate_df = arrivals_book.get(sheet_key or "")
        area_arrivals_subset = get_market_monthly_area_subset(
            monthly_sheet=municipality_arrivals_df if municipality_arrivals_df is not None else pd.DataFrame(),
            aggregate_sheet=area_arrivals_aggregate_df,
            selected_group=selected_group,
            group_col=group_col,
        )

        with st.container(border=True):
            render_section_heading(
                f"PDB po trgih – letno povprečje: {selected_group}",
                f"Vodoravni stolpčni graf letnega povprečja PDB po skupinah trgov za leto {selected_year}.",
            )
            annual_df = compute_market_annual_average_for_subset(area_subset)
            slovenia_subset = municipality_annual_df[
                municipality_annual_df["__label__"].apply(normalize_name) == normalize_name("SLOVENIJA")
            ].copy()
            slovenia_annual_df = compute_market_annual_average_for_subset(slovenia_subset)
            slovenia_arrivals_subset = (
                municipality_arrivals_df[
                    municipality_arrivals_df["__label__"].apply(normalize_name) == normalize_name("SLOVENIJA")
                ].copy()
                if municipality_arrivals_df is not None and not municipality_arrivals_df.empty
                else pd.DataFrame()
            )
            area_arrivals_weights = compute_market_monthly_structure_for_subset(area_arrivals_subset)
            slovenia_arrivals_weights = compute_market_monthly_structure_for_subset(slovenia_arrivals_subset)
            render_market_pdb_annual_chart(
                annual_df,
                f"PDB po trgih – letno povprečje ({selected_year})",
                reference_lines=[
                    (MARKET_AVERAGE_DISPLAY_LABEL, compute_market_weighted_mean_from_frames(annual_df, area_arrivals_weights), AREA_REFERENCE_COLOR),
                    ("Povprečje vseh trgov v Sloveniji", compute_market_weighted_mean_from_frames(slovenia_annual_df, slovenia_arrivals_weights), SECONDARY_REFERENCE_COLOR),
                ],
            )
        return

    municipality_names = get_market_monthly_municipality_names(
        df_source=df_source,
        municipality_sheet=municipality_annual_df,
        selected_group=selected_group,
        group_col=group_col,
    )
    if not municipality_names:
        st.info("Za izbrano območje ni občinskih podatkov o letnem povprečju PDB po trgih.")
        return

    with st.container(border=True):
        render_section_heading(
            f"Občine znotraj območja: {selected_group}",
            f"Izberi občino za prikaz letnega povprečja PDB po trgih v letu {selected_year}.",
        )
        chosen_muni_raw = st.selectbox(
            "Izberi občino",
            municipality_names,
            index=0,
            key=f"pdb_annual_muni_{group_col}_{selected_year}",
        )
        if chosen_muni_raw is None:
            return
        chosen_muni = str(chosen_muni_raw)
        muni_subset = municipality_annual_df[
            municipality_annual_df["__label__"].apply(normalize_name) == normalize_name(chosen_muni)
        ].copy()
        annual_df = compute_market_annual_average_for_subset(muni_subset)
        area_sheet_key = get_seasonality_sheet_key(view_title, group_col)
        area_entry = pdb_book.get(area_sheet_key or "")
        area_annual_df_raw = area_entry.get("annual_avg") if area_entry else None
        area_subset = get_market_monthly_area_subset(
            monthly_sheet=municipality_annual_df,
            aggregate_sheet=area_annual_df_raw,
            selected_group=selected_group,
            group_col=group_col,
        )
        area_annual_df = compute_market_annual_average_for_subset(area_subset)
        muni_arrivals_subset = (
            municipality_arrivals_df[
                municipality_arrivals_df["__label__"].apply(normalize_name) == normalize_name(chosen_muni)
            ].copy()
            if municipality_arrivals_df is not None and not municipality_arrivals_df.empty
            else pd.DataFrame()
        )
        area_arrivals_entry = arrivals_book.get(area_sheet_key or "")
        area_arrivals_subset = get_market_monthly_area_subset(
            monthly_sheet=municipality_arrivals_df if municipality_arrivals_df is not None else pd.DataFrame(),
            aggregate_sheet=area_arrivals_entry,
            selected_group=selected_group,
            group_col=group_col,
        )
        area_arrivals_weights = compute_market_monthly_structure_for_subset(area_arrivals_subset)
        muni_arrivals_weights = compute_market_monthly_structure_for_subset(muni_arrivals_subset)
        render_market_pdb_annual_chart(
            annual_df,
            f"{chosen_muni} – PDB po trgih, letno povprečje ({selected_year})",
            reference_lines=[
                (MARKET_AVERAGE_DISPLAY_LABEL, compute_market_weighted_mean_from_frames(area_annual_df, area_arrivals_weights), AREA_REFERENCE_COLOR),
                ("Povprečje vseh trgov v občini", compute_market_weighted_mean_from_frames(annual_df, muni_arrivals_weights), SECONDARY_REFERENCE_COLOR),
            ],
        )


def render_market_pdb_seasonality_distribution(
    *,
    selected_group: str,
    view_title: str,
    group_col: str,
    mode: str,
    df_source: pd.DataFrame,
) -> None:
    pdb_by_year = load_market_pdb_data()
    if not pdb_by_year:
        st.warning("Ne najdem datotek za PDB po trgih.")
        return

    available_years = sorted(pdb_by_year.keys())
    selected_year = st.selectbox(
        "Leto",
        available_years,
        index=len(available_years) - 1,
        key=f"pdb_seasonality_year_{group_col}",
    )
    pdb_book = pdb_by_year[selected_year]
    municipality_entry = pdb_book.get("Občine")
    municipality_seasonality_df = municipality_entry.get("seasonality") if municipality_entry else None
    if municipality_seasonality_df is None or municipality_seasonality_df.empty:
        st.warning("V PDB datoteki manjka del s sezonskostjo za list »Občine«.")
        return

    if mode == "Celotno območje":
        sheet_key = get_seasonality_sheet_key(view_title, group_col)
        aggregate_entry = pdb_book.get(sheet_key or "")
        aggregate_seasonality_df = aggregate_entry.get("seasonality") if aggregate_entry else None
        area_subset = get_market_monthly_area_subset(
            monthly_sheet=municipality_seasonality_df,
            aggregate_sheet=aggregate_seasonality_df,
            selected_group=selected_group,
            group_col=group_col,
        )
        if area_subset.empty:
            st.info("Za izbrano območje ni sezonskih podatkov o PDB po trgih.")
            return

        with st.container(border=True):
            render_section_heading(
                f"Sezonskost PDB po trgih: {selected_group}",
                f"Linijski prikaz mesečnega gibanja PDB po skupinah trgov za leto {selected_year}.",
            )
            chart_df = compute_market_seasonality_for_subset(area_subset)
            render_market_seasonality_chart(
                chart_df,
                f"Sezonskost PDB po trgih ({selected_year})",
                value_title="PDB",
                empty_message="Za izbran prikaz ni dovolj podatkov o sezonskosti PDB po trgih.",
                hover_indicator="PDB turistov SKUPAJ - 2025",
                add_average_area_secondary=True,
            )
        return

    municipality_names = get_market_monthly_municipality_names(
        df_source=df_source,
        municipality_sheet=municipality_seasonality_df,
        selected_group=selected_group,
        group_col=group_col,
    )
    if not municipality_names:
        st.info("Za izbrano območje ni občinskih sezonskih podatkov o PDB po trgih.")
        return

    with st.container(border=True):
        render_section_heading(
            f"Občine znotraj območja: {selected_group}",
            f"Izberi občino za prikaz mesečnega gibanja PDB po trgih v letu {selected_year}.",
        )
        chosen_muni_raw = st.selectbox(
            "Izberi občino",
            municipality_names,
            index=0,
            key=f"pdb_seasonality_muni_{group_col}_{selected_year}",
        )
        if chosen_muni_raw is None:
            return
        chosen_muni = str(chosen_muni_raw)
        muni_subset = municipality_seasonality_df[
            municipality_seasonality_df["__label__"].apply(normalize_name) == normalize_name(chosen_muni)
        ].copy()
        chart_df = compute_market_seasonality_for_subset(muni_subset)
        render_market_seasonality_chart(
            chart_df,
            f"{chosen_muni} – sezonskost PDB po trgih ({selected_year})",
            value_title="PDB",
            empty_message="Za izbran prikaz ni dovolj podatkov o sezonskosti PDB po trgih.",
            hover_indicator="PDB turistov SKUPAJ - 2025",
            add_average_area_secondary=True,
        )


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


def should_use_share_pie_chart(
    indicator: str,
    values: pd.Series,
    agg_rules: dict[str, tuple[str, str | None]],
) -> bool:
    agg_method, _ = agg_rules.get(indicator, ("sum", None))
    if agg_method != "sum":
        return False
    if is_percent_like(indicator) or is_rate_like(indicator):
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
    agg_rules: dict[str, tuple[str, str | None]] | None = None,
) -> None:
    display_indicator = get_indicator_display_name(indicator)
    plot_df = chart_df[[label_col, value_col]].copy()
    plot_df[value_col] = pd.to_numeric(plot_df[value_col], errors="coerce")
    plot_df = plot_df.dropna(subset=[value_col])
    if plot_df.empty:
        st.info("Za izbrani kazalnik ni dovolj podatkov za grafični prikaz.")
        return

    if should_use_share_pie_chart(indicator, plot_df[value_col], agg_rules or {}):
        st.markdown(f"**{title}** ***(delež)***")
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
            texttemplate="%{customdata[0]}<br>%{customdata[1]}",
            customdata=plot_df[["Value_label", "Share_label"]].to_numpy(),
            hovertext=plot_df["Hover_label"],
            hovertemplate="%{hovertext}<extra></extra>",
        )
        fig.update_layout(
            margin=dict(t=20, b=10, l=10, r=10),
            legend_title_text=label_col,
            showlegend=True,
            uniformtext_minsize=10,
            uniformtext_mode="hide",
        )
        st.plotly_chart(fig, width="stretch")
        return

    lower_better = is_lower_better(indicator)
    plot_df = plot_df.sort_values(value_col, ascending=lower_better).reset_index(drop=True)
    plot_df["Value_label"] = plot_df[value_col].apply(lambda value: format_indicator_value_map(indicator, value))
    orientation = "h" if should_use_horizontal_chart(plot_df[label_col]) else "v"
    st.markdown(f"**{title}** ***(vrednost)***")

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
            xaxis_title=display_indicator,
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
            yaxis_title=display_indicator,
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
        render_market_structure_pie_table(
            structure_df,
            pie_title="Tortni prikaz (normalizirano na 100%)",
            value_column_label="Prenočitve",
            value_indicator_label=f"Prenočitve turistov SKUPAJ - {selected_year}",
        )
        st.caption(
            "Opomba: deleži so izračunani uteženo glede na celotno število prenočitev "
            "in nato normalizirani na 100% (zaradi zaokroževanja/manjkajočih trgov)."
        )
        return

    st.markdown(f"### Občine znotraj območja: {selected_group}")
    municipality_df = subset[["Občine", base_weight_col] + market_cols_year].copy().rename(columns={"Občine": "Občina"})
    chosen_muni_raw = st.selectbox(
        "Izberi občino",
        municipality_df["Občina"].dropna().astype(str).tolist(),
        index=0,
        key=f"trgi_muni_{group_col}_{selected_year}",
    )
    if chosen_muni_raw is None:
        return
    chosen_muni = str(chosen_muni_raw)

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
    municipality_total_overnights = float(municipality_row[base_weight_col]) if pd.notna(municipality_row[base_weight_col]) else np.nan
    municipality_structure["Vrednost"] = (
        municipality_structure["Delež_norm"] * municipality_total_overnights
        if pd.notna(municipality_total_overnights) and municipality_total > 0
        else np.nan
    )

    render_market_structure_pie_table(
        municipality_structure,
        pie_title=f"{chosen_muni} – tortni prikaz (normalizirano na 100%)",
        value_column_label="Prenočitve",
        value_indicator_label=f"Prenočitve turistov SKUPAJ - {selected_year}",
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
                reference_lines=[
                    (MARKET_AVERAGE_DISPLAY_LABEL, compute_market_growth_weighted_mean(subset, base_year=base_year, target_year=target_year), AREA_REFERENCE_COLOR),
                    ("Povprečje vseh trgov v Sloveniji", compute_market_growth_weighted_mean(growth_numeric_df, base_year=base_year, target_year=target_year), SECONDARY_REFERENCE_COLOR),
                ],
            )
        with table_col:
            st.markdown("**Tabela**")
            render_market_growth_table(growth_df)
        return

    st.markdown(f"### Občine znotraj območja: {selected_group}")
    municipality_names = subset["Občine"].dropna().astype(str).tolist()
    chosen_muni_raw = st.selectbox(
        "Izberi občino",
        municipality_names,
        index=0,
        key=f"trgi_growth_muni_{group_col}_{selected_period}",
    )
    if chosen_muni_raw is None:
        return
    chosen_muni = str(chosen_muni_raw)
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
            reference_lines=[
                (MARKET_AVERAGE_DISPLAY_LABEL, compute_market_growth_weighted_mean(subset, base_year=base_year, target_year=target_year), AREA_REFERENCE_COLOR),
                ("Povprečje vseh trgov v občini", compute_market_growth_weighted_mean(municipality_subset, base_year=base_year, target_year=target_year), SECONDARY_REFERENCE_COLOR),
            ],
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
                best_table_df = section["best_df"][table_cols].copy()
                best_table_df["Kazalnik"] = best_table_df["Kazalnik"].apply(get_indicator_display_name)
                render_ranked_dataframe(best_table_df)
            with worst_col:
                st.markdown(f"**Najslabši {section['group']}**")
                worst_table_df = section["worst_df"][table_cols].copy()
                worst_table_df["Kazalnik"] = worst_table_df["Kazalnik"].apply(get_indicator_display_name)
                render_ranked_dataframe(worst_table_df)
            show_shared_warning_if_needed_map(section['group'])

    st.markdown("---")
    render_ai_section_header()
    ai_status_container = st.empty()
    ai_output_container = st.empty()
    ai_output_container.empty()

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
        cached_text = str(cached_payload.get("text") or "").strip() if cached_payload else ""
        if cached_payload and cached_text:
            st.session_state[ai_state_key] = {
                "text": cached_text,
                "source": "db_cache",
                "error": None,
                "region": selected_region,
                "signature": ai_signature,
            }
        else:
            with ai_status_container:
                with st.spinner("Generiram komentar in priporočila..."):
                    ai_text, ai_source, ai_error = generate_region_ai_commentary(
                        selected_region,
                        group_sections,
                        market_analysis=market_ai_context,
                    )
            cache_store_failed = False
            if ai_source == "ai" and str(ai_text or "").strip():
                cache_store_failed = not store_cached_ai_commentary(
                    ai_cache_key,
                    payload_hash=ai_payload_hash,
                    region_name=selected_region,
                    group_name=group_col,
                    text=ai_text,
                    model=str(get_secret_value("OPENAI_MODEL", "gpt-5.4") or "gpt-5.4"),
                )
            st.session_state[ai_state_key] = {
                "text": str(ai_text or "").strip(),
                "source": ai_source,
                "error": ai_error,
                "region": selected_region,
                "signature": ai_signature,
                "cache_store_failed": cache_store_failed,
            }

    ai_status_container.empty()
    ai_payload = st.session_state.get(ai_state_key, {})
    ai_text = str(ai_payload.get("text") or "").strip()
    with ai_output_container.container():
        if ai_payload.get("region") and ai_payload.get("region") != selected_region:
            st.info("AI komentar za izbrano območje se pripravlja.")
            return

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
        elif ai_payload.get("cache_store_failed"):
            st.caption("AI komentar je bil ustvarjen, vendar ga ni bilo mogoče shraniti v trajni podatkovni cache.")

        if ai_payload.get("error"):
            st.caption(f"Podrobnosti: {ai_payload['error']}")
        if ai_text:
            st.markdown(ai_text)
        else:
            st.info("AI komentar za izbrano območje še ni na voljo.")


def render_view(view_title: str, group_col: str, ctx: DashboardContext) -> None:
    st.caption(f"**Pogled:** {view_title}")

    indicator_cols = ctx.indicator_cols
    grouped_filtered, indicator_to_group = build_filtered_indicator_groups(indicator_cols, ctx.grouped_indicators)
    all_indicator_options = build_all_indicator_options(indicator_cols, grouped_filtered)
    indicator_catalog = build_indicator_catalog(indicator_cols, grouped_filtered, ctx.indicator_metadata_df)

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

    group_indicator_cols = (
        all_indicator_options if selected_group_key == "__all__" else grouped_filtered.get(selected_group_key, [])
    )
    if not group_indicator_cols:
        group_indicator_cols = all_indicator_options
    metric_options = metric_options_for_indicators(indicator_catalog, group_indicator_cols)
    if not metric_options:
        st.info("Za izbrano skupino ni kazalnikov.")
        return

    with map_indicator_col:
        st.markdown("<div style='min-height: 10rem;'></div>", unsafe_allow_html=True)
        metric_selector_key = f"sel_metric_{group_col}"
        if st.session_state.get(metric_selector_key) not in metric_options:
            st.session_state[metric_selector_key] = metric_options[0]
        selected_metric_key = st.selectbox(
            "Glavni kazalnik",
            metric_options,
            index=0,
            key=metric_selector_key,
            format_func=lambda metric_key: format_metric_option_label(metric_key, indicator_catalog),
        )
        selected_metric_spec = indicator_catalog[selected_metric_key]
        selected_year_entries = available_year_entries(selected_metric_spec)
        selected_year: int | None = None
        comparison_mode = "Posamično leto"
        if len(selected_year_entries) > 1:
            comparison_mode = st.radio(
                "Prikaz",
                ["Primerjava po letih", "Posamično leto"],
                horizontal=True,
                key=f"metric_mode_{group_col}_{stable_ui_key(selected_metric_key)}",
            )
        if comparison_mode == "Posamično leto" and selected_year_entries:
            selected_year = st.selectbox(
                "Leto",
                [int(entry["year"]) for entry in selected_year_entries],
                index=len(selected_year_entries) - 1,
                key=f"metric_year_{group_col}_{stable_ui_key(selected_metric_key)}",
            )

        map_indicator = resolve_metric_indicator_for_year(selected_metric_key, indicator_catalog, selected_year)
        show_shared_warning_if_needed_indicator(map_indicator)

    if comparison_mode == "Primerjava po letih":
        render_year_comparison(
            metric_spec=selected_metric_spec,
            selected_region=selected_region,
            group_col=group_col,
            view_title=view_title,
            numeric_df=numeric_df,
            regions=regions,
            df_slo_total_num=df_slo_total_num,
            agg_rules=ctx.agg_rules,
        )
        return

    map_reverse_color_scale = False
    map_color_direction = "higher_value"

    dash_inds = []
    if ctx.dashboard_mode:
        dashboard_metric_options = [metric_key for metric_key in metric_options if metric_key != selected_metric_key]
        dash_selector_key = f"dash_{group_col}"
        previous_dash_keys = st.session_state.get(dash_selector_key, [])
        if previous_dash_keys:
            st.session_state[dash_selector_key] = [
                metric_key for metric_key in previous_dash_keys if metric_key in dashboard_metric_options
            ]
        dash_metric_keys = st.multiselect(
            "Dodatni kazalniki za dashboard in grafe (do 6)",
            dashboard_metric_options,
            max_selections=6,
            placeholder="Izberi kazalnik",
            key=dash_selector_key,
            format_func=lambda metric_key: format_metric_option_label(metric_key, indicator_catalog),
        )
        dash_inds = [
            resolve_metric_indicator_for_year(metric_key, indicator_catalog, selected_year)
            for metric_key in dash_metric_keys
        ]

    agg_needed = [map_indicator] + [indicator for indicator in dash_inds if indicator != map_indicator]
    region_agg = compute_region_aggregates(numeric_df, regions, agg_needed, ctx.agg_rules, group_col=group_col)
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
                index=1 if is_lower_better(sort_indicator) else 0,
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
        show_df, display_source_columns = rename_indicator_columns_for_display(show_df, agg_needed)
        comparison_widths: dict[str, ColumnWidth] = {group_col: "large"}
        for column in agg_needed:
            comparison_widths[get_indicator_display_name(column)] = "medium"

        show_df = streamlit_safe_dataframe(show_df)
        st.dataframe(
            show_df,
            width='stretch',
            height=260,
            hide_index=True,
            column_config=make_localized_column_config(
                show_df,
                source_columns=display_source_columns,
                width_overrides=comparison_widths,
            ),
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
            title=f"Grafična primerjava območij - {chart_indicator}",
            slovenia_value=df_slo_total_num.get(chart_indicator, np.nan),
            agg_rules=ctx.agg_rules,
        )

        _, _, kpi_col = st.columns([1, 2, 1])
        with kpi_col:
            green_metric(
                f" Celotna Slovenija - {get_indicator_display_name(map_indicator)}",
                format_indicator_value_map(map_indicator, df_slo_total_num.get(map_indicator, np.nan)),
            )
    else:
        st.subheader("Povzetek izbranega območja")
        region_df = numeric_df[numeric_df[group_col] == selected_region].copy()
        region_total = region_agg_by_group.at[selected_region, map_indicator]
        sl_total = df_slo_total_num.get(map_indicator, np.nan)

        main_delta_text = build_slovenia_metric_delta(map_indicator, float(region_total), sl_total, ctx.agg_rules)

        left_kpi, right_kpi = st.columns([1.2, 1])
        with left_kpi:
            st.metric(
                get_indicator_display_name(map_indicator),
                f"{format_indicator_value_map(map_indicator, region_total)}",
                main_delta_text,
            )
            if get_indicator_aggregation_method(map_indicator, ctx.agg_rules) == "sum":
                st.caption(
                    "Opomba: »Delež v Sloveniji« je prikazan za kazalnike, kjer se vrednosti seštevajo."
                )
            else:
                st.caption(
                    "Opomba: »Primerjalni indeks s Slovenijo« primerja vrednost območja z vrednostjo Slovenije "
                    "(Slovenija = 100)."
                )
        with right_kpi:
            green_metric(
                f" Celotna Slovenija - {get_indicator_display_name(map_indicator)}",
                format_indicator_value_map(map_indicator, sl_total),
            )

        if ctx.dashboard_mode and dash_inds:
            kpi_cols = st.columns(min(6, len(dash_inds)))
            for idx, indicator in enumerate(dash_inds[:6]):
                region_value = float(region_agg_by_group.at[selected_region, indicator])
                slovenia_value = df_slo_total_num.get(indicator, np.nan)

                with kpi_cols[idx]:
                    if slovenia_value is not None and not (isinstance(slovenia_value, float) and np.isnan(slovenia_value)):
                        green_metric_small("Slovenija", format_indicator_value_map(indicator, slovenia_value))

                    st.metric(
                        get_indicator_display_name(indicator),
                        format_indicator_value_map(indicator, region_value),
                        build_slovenia_metric_delta(indicator, region_value, slovenia_value, ctx.agg_rules),
                    )

        group_sections = build_top_bottom_group_sections(
            reg_df=region_df,
            df_slo_total_num=df_slo_total_num,
            grouped_filtered=grouped_filtered,
            agg_rules=ctx.agg_rules,
            region_name=selected_region,
            reference_agg_df=compute_region_aggregates(
                numeric_df=numeric_df,
                regions=regions,
                indicator_cols=get_top_bottom_reference_indicators(grouped_filtered, ctx.agg_rules),
                agg_rules=ctx.agg_rules,
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
                            color_direction=map_color_direction,
                        ),
                        reverse_color_scale=map_reverse_color_scale,
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
                            color_direction=map_color_direction,
                        ),
                        reverse_color_scale=map_reverse_color_scale,
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
                        color_direction=map_color_direction,
                    ),
                    reverse_color_scale=map_reverse_color_scale,
                )
        show_shared_warning_if_needed_map(map_indicator)

    with table_col:
        if selected_region == "Vsa območja":
            st.subheader(f"Tabela območij \n \n **:blue[{get_indicator_display_name(map_indicator)}]**")
            table = region_agg[[group_col, map_indicator]].copy()
            agg_rule, _ = ctx.agg_rules.get(map_indicator, ("sum", None))
            slovenia_total = df_slo_total_num.get(map_indicator, np.nan)
            show_share_column = (
                agg_rule == "sum"
                and slovenia_total is not None
                and not np.isnan(slovenia_total)
                and float(slovenia_total) != 0.0
            )
            if show_share_column:
                table["Delež Slovenije (%)"] = table[map_indicator].astype(float) / float(slovenia_total)
            table = table.sort_values(map_indicator, ascending=is_lower_better(map_indicator), na_position="last")
            table[map_indicator] = table[map_indicator].apply(lambda value: format_indicator_value_tables(map_indicator, value))
            table = table.rename(columns={map_indicator: "Vrednost"})
            source_columns = {"Vrednost": map_indicator}
            if show_share_column:
                source_columns["Delež Slovenije (%)"] = "Delež Slovenije (%)"
            render_ranked_dataframe(
                table,
                source_columns=source_columns,
                height=680,
            )
        else:
            st.subheader(f"Tabela občin znotraj območja \n \n **:blue[{get_indicator_display_name(map_indicator)}]**")
            region_total = aggregate_indicator_with_rules(region_df, map_indicator, ctx.agg_rules, None)
            table = build_region_indicator_table(region_df, map_indicator, region_total, view_title, ctx.agg_rules)
            render_ranked_dataframe(
                table,
                source_columns={"Vrednost": map_indicator},
                height=680,
            )
            if region_total and not np.isnan(region_total) and region_total != 0:
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
        st.subheader(f":blue[{get_indicator_display_name(chart_indicator)}]")
        region_chart_total = aggregate_indicator_with_rules(region_df, chart_indicator, ctx.agg_rules, selected_region)
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
            agg_rules=ctx.agg_rules,
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

NATIONAL_KPI_PRIORITY_METRICS = [
    "Čisti prihodki od prodaje",
    "Denarni tok iz poslovanja (EBITDA)",
    "EBITDA marža",
    "Čisti dobiček ali čista izguba",
    "Čisti dobiček/izguba",
    "Dodana vrednost ali izguba na substanci na zaposlenega",
    "Dodana vrednost/zaposlenega",
    "Število zaposlenih",
    "Število vseh prenočitev",
    "Povprečna zasedenost stalnih ležišč",
]

NATIONAL_TREND_GROUPS = {
    "Vodstveni povzetek": [
        "Čisti prihodki od prodaje",
        "Denarni tok iz poslovanja (EBITDA)",
        "Čisti dobiček ali čista izguba",
        "Čisti dobiček/izguba",
        "Dodana vrednost ali izguba na substanci na zaposlenega",
        "Število zaposlenih",
    ],
    "Obseg in kapacitete": [
        "Število subjektov",
        "Število poslovnih subjektov",
        "Število zaposlenih",
        "Število stalnih ležišč",
        "Število vseh prenočitev",
    ],
    "Prihodki in rezultat": [
        "Čisti prihodki od prodaje",
        "Prihodki",
        "Dobiček ali izguba iz poslovanja (EBIT)",
        "Denarni tok iz poslovanja (EBITDA)",
        "Čisti dobiček ali čista izguba",
        "Čisti dobiček/izguba",
    ],
    "Produktivnost": [
        "Dodana vrednost ali izguba na substanci na zaposlenega",
        "Dodana vrednost/zaposlenega",
        "Produktivnost (DV v EUR na delovno uro)",
        "Povprečno realiziran Prihodek na zaposlenega",
        "Povprečno realiziran EBITDA na zaposlenega",
    ],
    "Marže in stroški": [
        "EBITDA marža",
        "Profitna marža",
        "Delež stroškov dela v čistih prihodkih od prodaje",
        "Delež stroškov dela v dodani vrednosti",
        "Delež stroškov dela, blaga, materiala in storitev v prihodkih",
    ],
}


def normalize_metric_label(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def first_matching_metric(available_metrics: list[str], candidates: list[str]) -> str | None:
    normalized_available = {normalize_metric_label(metric): metric for metric in available_metrics}
    for candidate in candidates:
        exact = normalized_available.get(normalize_metric_label(candidate))
        if exact:
            return exact
    for candidate in candidates:
        candidate_norm = normalize_metric_label(candidate)
        for metric in available_metrics:
            if candidate_norm in normalize_metric_label(metric):
                return metric
    return None


def deduplicate_national_metric_years(rows: pd.DataFrame) -> pd.DataFrame:
    return (
        rows.sort_values("source_order")
        .drop_duplicates(subset=["metric", "year"], keep="first")
        .reset_index(drop=True)
    )


def build_national_metric_wide(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    deduped = deduplicate_national_metric_years(rows)
    values = deduped.pivot(index="metric", columns="year", values="value")
    meta = deduped.sort_values("source_order").drop_duplicates("metric", keep="first")
    meta = meta.set_index("metric")[["unit", "format_type", "higher_is_better", "source_order"]]
    wide = meta.join(values, how="left").sort_values("source_order").reset_index()
    return wide


def build_national_comparison_rows(
    df: pd.DataFrame,
    sector_id: str,
    *,
    real: bool,
) -> tuple[pd.DataFrame, str | None, str | None]:
    end_section = comparison_section_name(df, sector_id, real=real)
    real_from_duplicate_nominal_rows = False
    if real and end_section is None:
        nominal_2024_rows = sector_rows(df, sector_id, NATIONAL_NOMINAL_COMPARISON_SECTION)
        nominal_2024_rows = nominal_2024_rows[nominal_2024_rows["year"] == 2024]
        real_from_duplicate_nominal_rows = nominal_2024_rows.duplicated(["metric", "year"], keep=False).any()
        if real_from_duplicate_nominal_rows:
            end_section = NATIONAL_NOMINAL_COMPARISON_SECTION
    if end_section is None:
        return pd.DataFrame(), None, None

    start_section = NATIONAL_NOMINAL_COMPARISON_SECTION if real else end_section
    if start_section not in df[df["sector_id_norm"] == sector_id]["section"].unique():
        start_section = NATIONAL_MAIN_SECTION

    start_rows = sector_rows(df, sector_id, start_section)
    end_rows = sector_rows(df, sector_id, end_section)
    start_rows = deduplicate_national_metric_years(start_rows[start_rows["year"] == 2019])
    end_rows = end_rows[end_rows["year"] == 2024].sort_values("source_order")
    if real_from_duplicate_nominal_rows:
        end_rows = (
            end_rows[end_rows.duplicated(["metric", "year"], keep=False)]
            .drop_duplicates(subset=["metric", "year"], keep="last")
            .reset_index(drop=True)
        )
    else:
        end_rows = deduplicate_national_metric_years(end_rows)
    if start_rows.empty or end_rows.empty:
        return pd.DataFrame(), start_section, end_section

    comparison = start_rows[
        ["metric", "value", "unit", "format_type", "higher_is_better", "source_order"]
    ].merge(
        end_rows[["metric", "value", "unit", "format_type", "higher_is_better", "source_order"]],
        on="metric",
        suffixes=("_2019", "_2024"),
    )
    if comparison.empty:
        return comparison, start_section, end_section

    comparison["format_type"] = comparison["format_type_2024"].fillna(comparison["format_type_2019"])
    comparison["unit"] = comparison["unit_2024"].fillna(comparison["unit_2019"])
    comparison["higher_is_better"] = comparison["higher_is_better_2024"].fillna(comparison["higher_is_better_2019"])
    comparison["sort_order"] = comparison[["source_order_2024", "source_order_2019"]].min(axis=1)
    changes = comparison.apply(
        lambda row: national_kpi_change(row["value_2019"], row["value_2024"], row["format_type"]),
        axis=1,
    )
    comparison["change_value"] = [item[0] for item in changes]
    comparison["change_label"] = [item[1] for item in changes]
    comparison["value_2019_label"] = comparison.apply(
        lambda row: format_national_kpi_value(row["value_2019"], row["format_type"], row["unit"]),
        axis=1,
    )
    comparison["value_2024_label"] = comparison.apply(
        lambda row: format_national_kpi_value(row["value_2024"], row["format_type"], row["unit"]),
        axis=1,
    )
    comparison["outcome"] = comparison.apply(
        lambda row: (
            "Ugodno"
            if pd.notna(row["change_value"]) and bool(row["higher_is_better"]) == (float(row["change_value"]) >= 0)
            else "Neugodno"
            if pd.notna(row["change_value"])
            else "Ni podatka"
        ),
        axis=1,
    )
    return comparison.sort_values("sort_order").reset_index(drop=True), start_section, end_section


def render_national_kpi_card(metric: str, row: pd.Series) -> None:
    if 2024 not in row.index or pd.isna(row.get(2024)):
        return
    value_label = format_national_kpi_value(row[2024], row["format_type"], row["unit"])
    _, delta_label = national_kpi_change(row.get(2019), row.get(2024), row["format_type"])
    st.metric(
        get_indicator_display_name(metric),
        value_label,
        delta_label if delta_label != "—" else None,
        delta_color="normal" if bool(row.get("higher_is_better", True)) else "inverse",
    )


def render_national_kpi_overview(sector_df: pd.DataFrame, sector_id: str, sector_label: str) -> None:
    main_rows = sector_rows(sector_df, sector_id, NATIONAL_MAIN_SECTION)
    wide = build_national_metric_wide(main_rows)
    if wide.empty:
        st.info("Za izbrano raven ni podatkov za vodstveni pregled.")
        return

    st.markdown(f"### {sector_label}")
    st.caption("Ključne vrednosti za leto 2024 s primerjavo glede na leto 2019.")
    available_metrics = wide["metric"].astype(str).tolist()
    selected_metrics: list[str] = []
    for candidate in NATIONAL_KPI_PRIORITY_METRICS:
        match = first_matching_metric(available_metrics, [candidate])
        if match and match not in selected_metrics:
            selected_metrics.append(match)
        if len(selected_metrics) >= 8:
            break
    if not selected_metrics:
        selected_metrics = available_metrics[:8]

    for start in range(0, len(selected_metrics), 4):
        cols = st.columns(4)
        for col, metric in zip(cols, selected_metrics[start : start + 4]):
            row = wide[wide["metric"] == metric].iloc[0]
            with col:
                render_national_kpi_card(metric, row)


def render_national_trend_chart(sector_df: pd.DataFrame, sector_id: str) -> None:
    main_rows = sector_rows(sector_df, sector_id, NATIONAL_MAIN_SECTION)
    wide = build_national_metric_wide(main_rows)
    if wide.empty:
        st.info("Za izbrano raven ni časovnih vrst.")
        return

    group_name = st.selectbox(
        "Skupina kazalnikov",
        list(NATIONAL_TREND_GROUPS.keys()),
        index=0,
        key=f"national_trend_group_{sector_id}",
    )
    available_metrics = wide["metric"].astype(str).tolist()
    selected_metrics = [
        metric
        for metric in (
            first_matching_metric(available_metrics, [candidate])
            for candidate in NATIONAL_TREND_GROUPS[group_name]
        )
        if metric
    ]
    selected_metrics = list(dict.fromkeys(selected_metrics))
    if not selected_metrics:
        selected_metrics = available_metrics[:8]

    chart_rows: list[dict[str, Any]] = []
    for _, row in wide[wide["metric"].isin(selected_metrics)].iterrows():
        base_value = row.get(2019)
        if base_value is None or pd.isna(base_value) or float(base_value) == 0:
            continue
        for year in [2019, 2023, 2024]:
            value = row.get(year)
            if value is None or pd.isna(value):
                continue
            chart_rows.append(
                {
                    "Kazalnik": get_indicator_display_name(str(row["metric"])),
                    "Leto": int(year),
                    "Indeks 2019 = 100": (float(value) / float(base_value)) * 100.0,
                    "Vrednost": format_national_kpi_value(value, row["format_type"], row["unit"]),
                }
            )

    chart_df = pd.DataFrame(chart_rows)
    if chart_df.empty:
        st.info("Za izbrano skupino ni dovolj podatkov za trendni graf.")
        return

    fig = px.line(
        chart_df,
        x="Leto",
        y="Indeks 2019 = 100",
        color="Kazalnik",
        markers=True,
        custom_data=["Kazalnik", "Vrednost"],
    )
    fig.update_traces(
        hovertemplate="<b>%{customdata[0]}</b><br>Leto: %{x}<br>Indeks: %{y:.1f}<br>Vrednost: %{customdata[1]}<extra></extra>"
    )
    fig.add_hline(y=100, line_color="#64748b", line_dash="dash", line_width=1)
    fig.update_layout(
        margin=dict(t=20, b=20, l=10, r=10),
        legend_title_text="Kazalnik",
        yaxis_title="Indeks 2019 = 100",
        xaxis_title="Leto",
    )
    st.plotly_chart(fig, width="stretch")
    table = chart_df.pivot(index="Kazalnik", columns="Leto", values="Vrednost").reset_index()
    table = streamlit_safe_dataframe(table)
    st.dataframe(table, width="stretch", hide_index=True)


def render_national_comparison(sector_df: pd.DataFrame, sector_id: str, *, real: bool) -> None:
    comparison_df, _, end_section = build_national_comparison_rows(sector_df, sector_id, real=real)
    if comparison_df.empty:
        st.info("Za ta prikaz trenutno ni dovolj podatkov za primerjavo 2024/2019.")
        return

    if real:
        st.caption("Realna primerjava uporablja nominalne vrednosti za 2019 in deflacionirane vrednosti za 2024.")
    elif end_section != NATIONAL_MAIN_SECTION:
        st.caption("Nominalna primerjava uporablja pripravljeni sklop »Primerjava kazalnikov - 2024/2019 - nominalno«.")

    metric_options = comparison_df["metric"].astype(str).tolist()
    default_metrics = [
        metric
        for metric in (
            first_matching_metric(metric_options, [candidate])
            for candidate in NATIONAL_KPI_PRIORITY_METRICS
        )
        if metric
    ]
    default_metrics = list(dict.fromkeys(default_metrics))[:10]
    selected_metrics = st.multiselect(
        "Kazalniki za graf",
        metric_options,
        default=default_metrics or metric_options[:10],
        key=f"national_compare_metrics_{sector_id}_{'real' if real else 'nominal'}",
        format_func=get_indicator_display_name,
    )
    chart_df = comparison_df[comparison_df["metric"].isin(selected_metrics)].dropna(subset=["change_value"]).copy()
    if not chart_df.empty:
        chart_df["Kazalnik"] = chart_df["metric"].apply(get_indicator_display_name)
        chart_df["Kazalnik_chart"] = chart_df["Kazalnik"].apply(lambda value: wrap_market_chart_label(value, 26))
        fig = px.bar(
            chart_df.sort_values("change_value", ascending=True),
            x="change_value",
            y="Kazalnik_chart",
            orientation="h",
            color="outcome",
            color_discrete_map={"Ugodno": "#16a34a", "Neugodno": "#dc2626", "Ni podatka": "#64748b"},
            custom_data=["Kazalnik", "value_2019_label", "value_2024_label", "change_label"],
            text="change_label",
        )
        fig.update_traces(
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "2019: %{customdata[1]}<br>"
                "2024: %{customdata[2]}<br>"
                "Sprememba: %{customdata[3]}<extra></extra>"
            ),
        )
        fig.add_vline(x=0, line_color="#64748b", line_width=1)
        fig.update_layout(
            margin=dict(t=20, b=20, l=10, r=10),
            xaxis_title="Sprememba 2024/2019 (% ali o.t.)",
            yaxis_title=None,
            legend_title_text="Interpretacija",
            height=max(420, 44 * len(chart_df) + 100),
        )
        st.plotly_chart(fig, width="stretch")

    table = comparison_df[
        ["metric", "value_2019_label", "value_2024_label", "change_label", "outcome"]
    ].rename(
        columns={
            "metric": "Kazalnik",
            "value_2019_label": "2019",
            "value_2024_label": "2024",
            "change_label": "Sprememba 2024/2019",
            "outcome": "Interpretacija",
        }
    )
    table["Kazalnik"] = table["Kazalnik"].apply(get_indicator_display_name)
    table = streamlit_safe_dataframe(table)
    st.dataframe(table, width="stretch", hide_index=True)


def render_national_all_indicators_table(sector_df: pd.DataFrame, sector_id: str) -> None:
    sections = sector_df["section"].dropna().drop_duplicates().tolist()
    selected_section = st.selectbox(
        "Sklop podatkov",
        sections,
        index=0,
        key=f"national_table_section_{sector_id}",
    )
    rows = sector_rows(sector_df, sector_id, selected_section)
    if str(selected_section).startswith("Primerjava kazalnikov - 2024/2019 - realno"):
        nominal_rows = sector_rows(sector_df, sector_id, NATIONAL_NOMINAL_COMPARISON_SECTION)
        nominal_2019_rows = nominal_rows[nominal_rows["year"] == 2019].copy()
        real_metrics = set(rows["metric"].dropna().astype(str))
        nominal_2019_rows = nominal_2019_rows[nominal_2019_rows["metric"].astype(str).isin(real_metrics)]
        rows = pd.concat([nominal_2019_rows, rows], ignore_index=True)
    wide = build_national_metric_wide(rows)
    if wide.empty:
        st.info("Za izbrani sklop ni podatkov.")
        return

    table_rows: list[dict[str, Any]] = []
    for _, row in wide.iterrows():
        _, change_label = national_kpi_change(row.get(2019), row.get(2024), row["format_type"])
        table_rows.append(
            {
                "Kazalnik": get_indicator_display_name(str(row["metric"])),
                "2019": format_national_kpi_value(row.get(2019), row["format_type"], row["unit"]),
                "2023": format_national_kpi_value(row.get(2023), row["format_type"], row["unit"]),
                "2024": format_national_kpi_value(row.get(2024), row["format_type"], row["unit"]),
                "Primerjava 2024/2019": change_label,
                "Enota": row["unit"],
            }
        )
    table = streamlit_safe_dataframe(pd.DataFrame(table_rows))
    st.dataframe(table, width="stretch", hide_index=True, height=680)


def render_national_business_indicators() -> None:
    st.subheader("Ključni razvojni in poslovni kazalniki - nacionalna raven")
    st.caption("Nacionalni prikaz brez regionalnih, destinacijskih ali občinskih členitev.")

    try:
        kpi_df = load_national_business_kpi_data()
    except Exception as exc:
        st.error(f"Nacionalnih KPI podatkov ni bilo mogoče prebrati: {exc}")
        return

    if kpi_df.empty:
        st.warning(f"Ne najdem podatkov v datoteki: {get_national_kpi_path().name}")
        return

    sector_options = get_national_sector_options(kpi_df)
    if not sector_options:
        st.warning("V nacionalni KPI datoteki ne najdem pričakovanih ravni dejavnosti.")
        return

    selected_sector = st.radio(
        "Raven dejavnosti",
        sector_options,
        horizontal=True,
        key="national_business_sector",
        format_func=lambda sector_id: NATIONAL_SECTOR_LABELS.get(sector_id, sector_id),
    )
    sector_label = NATIONAL_SECTOR_LABELS.get(selected_sector, selected_sector)
    sector_df = kpi_df[kpi_df["sector_id_norm"] == selected_sector].copy()

    overview_tab, trend_tab, comparison_tab, detail_tab = st.tabs(
        ["Vodstveni pregled", "Trendi kazalnikov", "Primerjava 2024/2019", "Vsi kazalniki"]
    )
    with overview_tab:
        render_national_kpi_overview(sector_df, selected_sector, sector_label)
    with trend_tab:
        render_section_heading(
            "Trendi kazalnikov",
            "Kazalniki so prikazani kot indeks, kjer je leto 2019 enako 100. To omogoča primerjavo kazalnikov z različnimi enotami.",
        )
        render_national_trend_chart(sector_df, selected_sector)
    with comparison_tab:
        nominal_tab, real_tab = st.tabs(["Nominalno", "Realno"])
        with nominal_tab:
            render_section_heading("Nominalna primerjava 2024/2019")
            render_national_comparison(sector_df, selected_sector, real=False)
        with real_tab:
            render_section_heading("Realna primerjava 2024/2019")
            render_national_comparison(sector_df, selected_sector, real=True)
    with detail_tab:
        render_section_heading("Podrobna tabela kazalnikov")
        render_national_all_indicators_table(sector_df, selected_sector)


def render_news_article_placeholder_cards(category: str) -> None:
    st.markdown(
        """
        <div class="news-placeholder-grid">
            <div class="news-placeholder-card">
                <div class="news-placeholder-date">V izdelavi</div>
                <div class="news-placeholder-title">Naslov objave</div>
                <div class="news-placeholder-text">Tukaj bodo prikazane najnovejše objave za izbrani sklop.</div>
            </div>
            <div class="news-placeholder-card">
                <div class="news-placeholder-date">V izdelavi</div>
                <div class="news-placeholder-title">Naslov objave</div>
                <div class="news-placeholder-text">Objave bodo urejene po datumu, najnovejše na vrhu.</div>
            </div>
            <div class="news-placeholder-card">
                <div class="news-placeholder-date">V izdelavi</div>
                <div class="news-placeholder-title">Naslov objave</div>
                <div class="news-placeholder-text">Klik na naslov bo odprl povezavo do spletne objave.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.info(f"{category}: V izdelavi")


def render_news_and_articles() -> None:
    st.markdown('<div id="novice-in-strokovni-clanki"></div>', unsafe_allow_html=True)
    st.subheader("Novice in strokovni članki")
    st.markdown(
        """
        <style>
        .news-placeholder-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 14px;
            margin: 12px 0 18px;
        }
        .news-placeholder-card {
            min-height: 150px;
            border-radius: 8px;
            padding: 16px;
            color: #ffffff;
            background:
                linear-gradient(135deg, rgba(15, 23, 42, 0.84), rgba(30, 64, 175, 0.72)),
                linear-gradient(90deg, #2563eb, #16a34a);
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.12);
        }
        .news-placeholder-date {
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
            opacity: 0.82;
            margin-bottom: 24px;
        }
        .news-placeholder-title {
            font-size: 1.05rem;
            font-weight: 800;
            line-height: 1.25;
            margin-bottom: 8px;
        }
        .news-placeholder-text {
            font-size: 0.9rem;
            line-height: 1.35;
            opacity: 0.9;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    (
        slovenia_news_tab,
        slovenia_articles_tab,
        international_news_tab,
        international_articles_tab,
        analyses_tab,
        strategy_docs_tab,
    ) = st.tabs(
        [
            "Novice Slovenija",
            "Strokovni članki Slovenija",
            "Mednarodne novice",
            "Mednarodni strokovni članki",
            "Posebne analize in študije",
            "Strateški razvojni dokumenti turističnih destinacij",
        ]
    )

    with slovenia_news_tab:
        render_news_article_placeholder_cards("Novice Slovenija")

    with slovenia_articles_tab:
        render_news_article_placeholder_cards("Strokovni članki Slovenija")

    with international_news_tab:
        render_news_article_placeholder_cards("Mednarodne novice")

    with international_articles_tab:
        render_news_article_placeholder_cards("Mednarodni strokovni članki")

    with analyses_tab:
        st.markdown("#### Posebne analize in študije")
        st.info("V izdelavi")

    with strategy_docs_tab:
        st.markdown("#### Strateški razvojni dokumenti turističnih destinacij")
        (
            national_tab,
            leading_tab,
            prospective_tab,
            municipalities_tab,
        ) = st.tabs(["Slovenija – nacionalna raven", "Vodilne destinacije", "Perspektivne destinacije", "Občine"])
        with national_tab:
            st.info("V izdelavi")
        with leading_tab:
            st.selectbox("Entiteta", ["V izdelavi"], key="strategy_docs_leading_entity", disabled=True)
            st.info("V izdelavi")
        with prospective_tab:
            st.selectbox("Entiteta", ["V izdelavi"], key="strategy_docs_prospective_entity", disabled=True)
            st.info("V izdelavi")
        with municipalities_tab:
            st.selectbox("Entiteta", ["V izdelavi"], key="strategy_docs_municipality_entity", disabled=True)
            st.info("V izdelavi")


def render_compass_destination_index(ctx: DashboardContext, logo_path: Any | None = None) -> None:
    frames = load_compass_workbook()
    if not frames:
        st.info(
            "Podatkov za razvojni indeks turističnih destinacij nisem našel. "
            f"Pričakovana datoteka: `{get_compass_index_path()}`."
        )
        return

    required_sheets = {
        "compass_area_levels",
        "compass_index_groups",
        "compass_metrics",
        "compass_area_mapping",
        "compass_values_long",
        "compass_aggregation_rules",
        "compass_weight_rules",
        "compass_metric_components",
    }
    missing_sheets = sorted(sheet for sheet in required_sheets if sheet not in frames or frames[sheet].empty)
    if missing_sheets:
        st.warning("COMPASS Excel nima vseh potrebnih listov: " + ", ".join(missing_sheets))
        return

    metrics = frames["compass_metrics"].copy()
    values = frames["compass_values_long"].copy()
    area_levels = frames["compass_area_levels"].sort_values("display_order").copy()
    index_groups = frames["compass_index_groups"].sort_values("display_order").copy()

    if logo_path is not None and getattr(logo_path, "exists", lambda: False)():
        st.image(str(logo_path), width=360)

    st.subheader("Razvojni indeks turističnih destinacij - Tourism Destination COMPASS INDEX")

    content_tab, explanation_tab = st.tabs(
        [
            "Prikaz indeksa",
            "Obrazložitev izračuna indeksa in uvrščanja destinacij",
        ]
    )

    with content_tab:

        available_years = sorted(int(year) for year in values["index_year"].dropna().unique().tolist())
        year_col, area_col, group_col = st.columns([0.8, 1.4, 2.2], gap="large")
        with year_col:
            selected_year = st.selectbox(
                "Leto indeksa",
                available_years,
                index=len(available_years) - 1 if available_years else 0,
                key="compass_index_year",
            )
        with area_col:
            area_options = area_levels["area_level"].dropna().astype(str).tolist()
            selected_area_level = st.selectbox(
                "Raven območja",
                area_options,
                index=0,
                key="compass_area_level",
            )
        with group_col:
            group_options = index_groups["ui_filter_label"].dropna().astype(str).tolist()
            selected_group_label = st.selectbox(
                "Področje razvojnega indeksa - Tourism Destination COMPASS INDEX",
                group_options,
                index=0,
                key="compass_index_group",
            )

        selected_group = index_groups[index_groups["ui_filter_label"] == selected_group_label].iloc[0]
        selected_metric_id = str(selected_group["total_metric_id"])
        selected_index_group_name = str(selected_group["index_group_name"])
        chart_color_scale = GROUP_CHART_COLOR_SCALES.get(
            selected_index_group_name,
            GROUP_CHART_COLOR_SCALES["Krovni Index"],
        )
        metric_row_df = metrics[metrics["metric_id"] == selected_metric_id]
        if metric_row_df.empty:
            st.warning(f"V `compass_metrics` ni metrike `{selected_metric_id}`.")
            return
        metric_row = metric_row_df.iloc[0]

        metric_values = values[
            (values["metric_id"] == selected_metric_id)
            & (values["index_year"] == selected_year)
        ]
        if metric_values.empty:
            source_year = int(selected_year)
            reference_year = int(selected_year)
        else:
            source_year = int(metric_values.iloc[0]["source_year"])
            reference_year = int(metric_values.iloc[0]["reference_year"])
        metric_label = format_compass_metric_label(
            metric_row,
            source_year=source_year,
            reference_year=reference_year,
        )

        result_df = aggregate_compass_results(
            frames=frames,
            main_df=ctx.numeric_df,
            area_level=selected_area_level,
            metric_id=selected_metric_id,
            index_year=int(selected_year),
        )
        if result_df.empty:
            st.info("Za izbrano raven in indeks ni podatkov.")
            return
        slovenia_result_df = aggregate_compass_results(
            frames=frames,
            main_df=ctx.numeric_df,
            area_level="Slovenija",
            metric_id=selected_metric_id,
            index_year=int(selected_year),
        )
        slovenia_index_value = (
            float(slovenia_result_df.iloc[0]["value"])
            if not slovenia_result_df.empty and pd.notna(slovenia_result_df.iloc[0]["value"])
            else np.nan
        )

        kpi_cols = st.columns(3)
        with kpi_cols[0]:
            st.metric("Število območij", format_si_number(len(result_df), 0))
        with kpi_cols[1]:
            st.metric("Najvišja vrednost", format_si_number(float(result_df["value"].max()), 1))
        with kpi_cols[2]:
            st.metric("Povprečje", format_si_number(float(result_df["value"].mean()), 1))

        map_col, table_col = st.columns([1.55, 1.0], gap="large")
        with map_col:
            st.subheader("Geografski prikaz")
            display_geojson_obj = _get_display_geojson(ctx)
            if display_geojson_obj is None or ctx.geojson_name_prop is None:
                st.info("Za zemljevid naloži občinski GeoJSON oziroma uporabi privzeti `si_display.json`.")
            else:
                municipalities, municipality_to_value, municipality_to_area, area_to_value = build_compass_area_maps(
                    frames,
                    selected_area_level,
                    result_df,
                )
                if selected_area_level in {"Občine", "Slovenija"}:
                    st.caption(
                        "Prikazane so občine. Pri Sloveniji imajo vse občine enako nacionalno vrednost indeksa."
                    )
                    render_map_municipalities(
                        display_geojson_obj,
                        ctx.geojson_name_prop,
                        municipalities,
                        municipality_to_value,
                        indicator_label=selected_group_label,
                        height=700,
                        color_scale=chart_color_scale,
                        raw_indicator_label=True,
                        cache_key=cache_key_for_municipalities_map(
                            data_signature=ctx.data_signature,
                            geojson_signature=ctx.geojson_signature,
                            group_col=f"compass:{selected_area_level}",
                            selected_region="__all__",
                            indicator_label=f"{selected_metric_id}:{selected_year}:raw_tooltip",
                        ),
                    )
                else:
                    st.caption(
                        "Prikazana so združena območja iz občinskih geometrij; meje sledijo izbrani ravni območja."
                    )
                    regions_geojson = _get_regions_geojson(
                        ctx=ctx,
                        municipality_to_region=municipality_to_area,
                        group_col=selected_area_level,
                    )
                    if regions_geojson is None:
                        st.warning(
                            "Ne uspem sestaviti združenih poligonov za izbrano raven. "
                            "Prikazujem občine obarvane po vrednosti območja."
                        )
                        render_map_municipalities(
                            display_geojson_obj,
                            ctx.geojson_name_prop,
                            municipalities,
                            municipality_to_value,
                            indicator_label=selected_group_label,
                            height=700,
                            color_scale=chart_color_scale,
                            raw_indicator_label=True,
                            cache_key=cache_key_for_municipalities_map(
                                data_signature=ctx.data_signature,
                                geojson_signature=ctx.geojson_signature,
                                group_col=f"compass:{selected_area_level}",
                                selected_region="__fallback__",
                                indicator_label=f"{selected_metric_id}:{selected_year}:raw_tooltip",
                            ),
                        )
                    else:
                        render_map_regions(
                            regions_geojson,
                            area_to_value,
                            indicator_label=selected_group_label,
                            group_col=selected_area_level,
                            height=700,
                            color_scale=chart_color_scale,
                            raw_indicator_label=True,
                            cache_key=cache_key_for_regions_map(
                                data_signature=ctx.data_signature,
                                geojson_signature=ctx.geojson_signature,
                                group_col=f"compass:{selected_area_level}",
                                indicator_label=f"{selected_metric_id}:{selected_year}:raw_tooltip",
                            ),
                        )

        with table_col:
            st.subheader("Tabela z uvrstitvijo")
            table_df = result_df[["rank", "area_name", "value", "municipality_count"]].copy()
            table_df = table_df.rename(
                columns={
                    "rank": "Rang",
                    "area_name": "Območje",
                    "value": "Vrednost indeksa",
                    "municipality_count": "Št. občin",
                }
            )
            table_df["Vrednost indeksa"] = table_df["Vrednost indeksa"].apply(lambda value: format_si_number(value, 1))
            table_df = streamlit_safe_dataframe(table_df)
            st.dataframe(
                table_df,
                width="stretch",
                height=700,
                hide_index=True,
                column_config=make_localized_column_config(
                    table_df,
                    width_overrides={"Območje": "large", "Vrednost indeksa": "medium"},
                ),
            )

        st.subheader("Graf uvrstitve")
        chart_limit = len(result_df)
        if len(result_df) > 40:
            chart_limit = st.slider(
                "Število prikazanih območij v grafu",
                min_value=10,
                max_value=min(80, len(result_df)),
                value=min(40, len(result_df)),
                step=5,
                key=f"compass_chart_limit_{selected_area_level}_{selected_metric_id}_{selected_year}",
            )
        chart_df = result_df.head(chart_limit).copy()
        chart_df["label"] = chart_df["rank"].astype(str) + ". " + chart_df["area_name"].astype(str)
        chart_df["value_label"] = chart_df["value"].apply(lambda value: format_si_number(value, 1))
        chart_df["hover_label"] = chart_df.apply(
            lambda row: (
                f"<b>Rang in območje:</b> {row['label']}<br>"
                f"<b>Vrednost indeksa:</b> {row['value_label']}"
            ),
            axis=1,
        )
        chart_df = chart_df.sort_values("rank", ascending=False)
        fig = px.bar(
            chart_df,
            x="value",
            y="label",
            orientation="h",
            text="value_label",
            labels={"value": "Vrednost indeksa", "label": "Rang in območje"},
            color="value",
            color_continuous_scale=chart_color_scale,
            custom_data=["hover_label"],
        )
        fig.update_traces(
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{customdata[0]}<extra></extra>",
        )
        if pd.notna(slovenia_index_value):
            slovenia_label = f"Slovenija: {format_si_number(slovenia_index_value, 1)}"
            fig.add_vline(
                x=slovenia_index_value,
                line_color="#111827",
                line_width=2,
                line_dash="dash",
            )
            fig.add_annotation(
                x=slovenia_index_value,
                y=1.04,
                xref="x",
                yref="paper",
                text=slovenia_label,
                showarrow=False,
                xanchor="center",
                yanchor="bottom",
                font=dict(color="#111827", size=13),
                bgcolor="rgba(255,255,255,0.94)",
                bordercolor="#111827",
                borderwidth=1,
                borderpad=4,
            )
        fig.update_layout(
            title=f"{selected_group_label} - {selected_area_level}",
            height=max(420, min(1100, 32 * len(chart_df) + 140)),
            margin=dict(l=20, r=70, t=95, b=30),
            coloraxis_showscale=False,
            yaxis_title=None,
        )
        st.plotly_chart(fig, width="stretch")

    with explanation_tab:
        explanation_df = frames.get("compass_explanation", pd.DataFrame())
        if explanation_df.empty:
            st.info("Besedilo obrazložitve je še v izdelavi.")
        else:
            for row in explanation_df.sort_values("display_order").itertuples(index=False):
                st.markdown(f"### {getattr(row, 'title')}")
                body = str(getattr(row, "body") or "").strip()
                st.write(body if body else "Besedilo je še v izdelavi.")


def render_accommodation_capacity_structure(view_title: str, group_col: str, ctx: DashboardContext) -> None:
    st.caption(f"**Pogled:** {view_title}")
    st.subheader("Nastanitvene kapacitete, struktura kapacitet in rast obsega po vrstah kapacitet")

    numeric_df = ctx.numeric_df[ctx.numeric_df[group_col].notna()].copy()
    groups: list[str] = sorted(cast(list[str], numeric_df[group_col].dropna().unique().tolist()))
    if not groups:
        st.warning("Ne najdem nobenih območij za izbran pogled.")
        return

    selected_group_raw = st.selectbox(
        f"Izberi območje ({group_col})",
        groups,
        index=0,
        key=f"capacity_sel_{group_col}",
    )
    if selected_group_raw is None:
        st.info("Izberi območje za prikaz podatkov.")
        return
    selected_group = str(selected_group_raw)

    mode = st.radio(
        "Prikaz",
        ["Celotno območje", "Občine znotraj območja"],
        horizontal=True,
        key=f"capacity_mode_{group_col}",
    )

    area_df = numeric_df[numeric_df[group_col] == selected_group].copy()
    if area_df.empty:
        st.info("Za izbrano območje ni podatkov.")
        return

    source_df = area_df
    area_label = selected_group
    if mode == "Občine znotraj območja":
        municipality_names = area_df["Občine"].dropna().astype(str).tolist()
        if not municipality_names:
            st.info("Za izbrano območje ni občinskih podatkov.")
            return
        chosen_muni_raw = st.selectbox(
            "Izberi občino",
            municipality_names,
            index=0,
            key=f"capacity_muni_{group_col}",
        )
        if chosen_muni_raw is None:
            return
        area_label = str(chosen_muni_raw)
        source_df = area_df[area_df["Občine"].astype(str) == area_label].copy()

    (
        establishments_structure_tab,
        establishments_growth_tab,
        rooms_structure_tab,
        rooms_growth_tab,
        beds_structure_tab,
        beds_growth_tab,
    ) = st.tabs(
        [
            "Struktura nastanitvenih obratov po vrstah obratov",
            "Rast števila nastanitvenih obratov po vrstah obratov in skupaj",
            "Struktura po vrstah nastanitvenih kapacitet – sobe (nedeljive enote)",
            "Rast obsega sob (nedeljivih enot) po vrstah nastanitvenih kapacitet in skupaj",
            "Struktura po vrstah nastanitvenih kapacitet – stalna ležišča",
            "Rast obsega stalnih ležišč po vrstah nastanitvenih kapacitet in skupaj",
        ]
    )

    with establishments_structure_tab:
        render_accommodation_capacity_structure_tab(
            source_df=source_df,
            spec_key="establishments",
            title="Struktura nastanitvenih obratov po vrstah obratov",
            area_label=area_label,
            key_prefix=f"capacity_establishments_structure_{group_col}",
        )

    with establishments_growth_tab:
        render_accommodation_capacity_growth_tab(
            source_df=source_df,
            spec_key="establishments",
            title="Rast števila nastanitvenih obratov po vrstah obratov in skupaj",
            area_label=area_label,
            key_prefix=f"capacity_establishments_growth_{group_col}",
        )

    with rooms_structure_tab:
        render_accommodation_capacity_structure_tab(
            source_df=source_df,
            spec_key="rooms",
            title="Struktura po vrstah nastanitvenih kapacitet – sobe (nedeljive enote)",
            area_label=area_label,
            key_prefix=f"capacity_rooms_structure_{group_col}",
        )

    with rooms_growth_tab:
        render_accommodation_capacity_growth_tab(
            source_df=source_df,
            spec_key="rooms",
            title="Rast obsega sob (nedeljivih enot) po vrstah nastanitvenih kapacitet in skupaj",
            area_label=area_label,
            key_prefix=f"capacity_rooms_growth_{group_col}",
        )

    with beds_structure_tab:
        render_accommodation_capacity_structure_tab(
            source_df=source_df,
            spec_key="beds",
            title="Struktura po vrstah nastanitvenih kapacitet – stalna ležišča",
            area_label=area_label,
            key_prefix=f"capacity_beds_structure_{group_col}",
        )

    with beds_growth_tab:
        render_accommodation_capacity_growth_tab(
            source_df=source_df,
            spec_key="beds",
            title="Rast obsega stalnih ležišč po vrstah nastanitvenih kapacitet in skupaj",
            area_label=area_label,
            key_prefix=f"capacity_beds_growth_{group_col}",
        )


def render_market_structure(view_title: str, group_col: str, ctx: DashboardContext) -> None:
    st.caption(f"**Pogled:** {view_title}")
    st.subheader("Prenočitve, prihodi, PDB in sezonskost po trgih")

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

    (
        structure_tab,
        growth_tab,
        seasonality_tab,
        arrivals_structure_tab,
        arrivals_seasonality_tab,
        pdb_annual_tab,
        pdb_seasonality_tab,
    ) = st.tabs(
        [
            "Struktura prenočitev po trgih",
            "Rast števila prenočitev po trgih",
            "Sezonskost prenočitev po trgih",
            "Struktura prihodov po trgih",
            "Sezonskost prihodov po trgih",
            "PDB po trgih – letno povprečje",
            "Sezonskost PDB po trgih",
        ]
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
                ctx.market_growth_numeric_df.copy()
                if ctx.market_growth_numeric_df is not None and group_col in ctx.market_growth_numeric_df.columns
                else None
            ),
        )

    with seasonality_tab:
        render_market_overnight_seasonality_distribution(
            selected_group=selected_group,
            view_title=view_title,
            group_col=group_col,
            mode=mode,
            df_source=ctx.df,
        )

    with arrivals_structure_tab:
        render_market_arrivals_structure_distribution(
            selected_group=selected_group,
            view_title=view_title,
            group_col=group_col,
            mode=mode,
            df_source=ctx.df,
        )

    with arrivals_seasonality_tab:
        render_market_arrivals_seasonality_distribution(
            selected_group=selected_group,
            view_title=view_title,
            group_col=group_col,
            mode=mode,
            df_source=ctx.df,
        )

    with pdb_annual_tab:
        render_market_pdb_annual_distribution(
            selected_group=selected_group,
            view_title=view_title,
            group_col=group_col,
            mode=mode,
            df_source=ctx.df,
        )

    with pdb_seasonality_tab:
        render_market_pdb_seasonality_distribution(
            selected_group=selected_group,
            view_title=view_title,
            group_col=group_col,
            mode=mode,
            df_source=ctx.df,
        )
