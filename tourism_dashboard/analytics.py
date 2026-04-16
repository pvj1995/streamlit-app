from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from tourism_dashboard.config import (
    AGG_RULES,
    GINI_2025_VALUES,
    GINI_CHANGE_2024_2019,
    GINI_CHANGE_2025_2019,
    MARKET_PREFIX,
    TOP_BOTTOM_EXCLUDED_INDICATORS,
    TOP_BOTTOM_GROUP_LIMITS,
    TOP_BOTTOM_GROUP_ORDER,
)
from tourism_dashboard.formatting import (
    format_comparison_delta,
    format_indicator_value_map,
    format_pct,
    get_indicator_gap_unit,
    is_lower_better,
)
from tourism_dashboard.helpers import col_for_year


def get_agg_rule(
    indicator: str,
    agg_rules: dict[str, tuple[str, str | None]],
) -> tuple[str, str | None]:
    return agg_rules.get(indicator, ("sum", None))


def get_default_population_base(indicator: str) -> str:
    if "2025" in indicator:
        return "Število prebivalcev (H2/2025)"
    return "Število prebivalcev (H2/2024)"


def get_default_bed_capacity_base(indicator: str) -> str:
    if "2025" in indicator:
        return "Nastanitvene kapacitete - stalna ležišča 2025"
    return "Nastanitvene kapacitete - stalna ležišča"


def get_default_unit_capacity_base(indicator: str) -> str:
    if "2025" in indicator:
        return "Nastanitvene kapacitete - Nedeljive enote 2025"
    return "Nastanitvene kapacitete - Nedeljive enote"


def get_total_accommodation_establishment_base(indicator: str) -> str | None:
    if "2025" in indicator:
        return "Število vseh nastanitvenih obratov 2025"
    return None


def get_sum_comparison_base(indicator: str) -> tuple[str, str]:
    lower_indicator = indicator.lower()
    population_base = get_default_population_base(indicator)
    bed_capacity_base = get_default_bed_capacity_base(indicator)
    unit_capacity_base = get_default_unit_capacity_base(indicator)
    establishment_base = get_total_accommodation_establishment_base(indicator)

    if indicator in {"Število prebivalcev (H2/2024)", "Število prebivalcev (H2/2025)"}:
        return "Površina območja (km2)", "delež površine"
    if indicator == "Površina območja (km2)":
        return population_base, "delež prebivalstva"
    if (
        "starih 15 let ali več s srednješolsko" in lower_indicator
        or "starih 15 let ali več z izobrazbo višjo" in lower_indicator
    ):
        return "Število prebivalcev starih 15 let ali več na območju", "delež prebivalcev 15+"
    if "starih 15 let ali več na območju" in lower_indicator:
        return population_base, "delež prebivalstva"
    if "delovno aktivno prebivalstvo v turizmu" in lower_indicator:
        if "2025" in indicator:
            return "Vsi delovno aktivni na območju 2025", "delež vseh delovno aktivnih"
        return "Vsi delovni aktivni na območju", "delež vseh delovno aktivnih"
    if "zaposl" in lower_indicator and "gostinstvu" in lower_indicator:
        return "Vsi delovni aktivni na območju", "delež vseh delovno aktivnih"
    if "zaposleni v nastan.dejav" in lower_indicator:
        return "Vsi delovni aktivni na območju", "delež vseh delovno aktivnih"
    if "število reg. podjetij" in lower_indicator and (
        "gostinstvu" in lower_indicator or "nastanitveni dejav" in lower_indicator
    ):
        return "Število vseh vrst podjetij na območju", "delež vseh podjetij"
    if any(
        token in lower_indicator
        for token in ["prihodki", "dodana vrednost", "stroški dela", "ebitda", "dobiček", "izguba", "sredstva", "kapital"]
    ):
        if "gostinstvu" in lower_indicator:
            return "Zaposleni v Gostinstvu (I) v registr.podjetjih in s.p.", "delež zaposlenih v gostinstvu"
        if "nastanitveni dejav" in lower_indicator:
            return "Zaposleni v nastan.dejav. (I55) v registr.podjetjih in s.p.", "delež zaposlenih v nastanitvi"
    if "poraba el.energije" in lower_indicator and "gostinstvo" in lower_indicator:
        return "Prihodki reg.podjetij in s.p. v Gostinstvu (I)", "delež prihodkov v gostinstvu"
    # Tourism-flow and accommodation-supply totals are more meaningful against sector capacity
    # than against resident population; subtype totals are benchmarked to the matching total stock.
    if any(token in lower_indicator for token in ["prenočitve", "prihodi turistov"]):
        return bed_capacity_base, "delež stalnih ležišč"
    if indicator.startswith("Nastanitvene kapacitete -") or indicator == "Število vseh nastanitvenih obratov 2025":
        return population_base, "delež prebivalstva"
    if any(
        token in lower_indicator
        for token in [
            "sob ",
            "sob v ",
            "enot v ",
            "nedeljive enote",
            "nedeljivih enot",
        ]
    ):
        return unit_capacity_base, "delež sob/enot"
    if any(
        token in lower_indicator
        for token in [
            "stalna ležišča",
            "staln. ležišč",
            "lež",
        ]
    ):
        return bed_capacity_base, "delež stalnih ležišč"
    if establishment_base and any(
        token in lower_indicator
        for token in [
            "nastanitvenih obratov",
            "hotelov",
            "kampov",
            "turističnih kmetij",
            "drugih vrst no",
        ]
    ):
        return establishment_base, "delež nastanitvenih obratov"
    if any(
        token in lower_indicator
        for token in [
            "nastanitvene kapacitete",
        ]
    ):
        return population_base, "delež prebivalstva"
    if any(token in lower_indicator for token in ["stanovanj", "gradbenih dovoljenj", "dijakov", "študentov", "odpadki", "dohodek", "plača"]):
        return population_base, "delež prebivalstva"
    if any(token in lower_indicator for token in ["kmetijskih", "kmetij."]):
        return "Površina območja (km2)", "delež površine"
    return population_base, "delež prebivalstva"


def get_precomputed_indicator_value(
    indicator: str,
    region_name: str | None,
    df: pd.DataFrame,
) -> float | None:
    if region_name is None:
        return None

    if "Gibanje GINI Indeksa prenoč. 2024/2019" in indicator:
        return GINI_CHANGE_2024_2019.get(region_name)
    if "GINI Indeks - sezonskost prenočitev - 2025" in indicator:
        return GINI_2025_VALUES.get(region_name)
    if "Gibanje GINI Indeksa prenoč. 2025/2019" in indicator:
        return GINI_CHANGE_2025_2019.get(region_name)

    if "Celotni prihodki v nastan. dejav. na prenočitev" in indicator:
        numerator = df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"].astype(float).sum()
        denominator = df["Prenočitve turistov SKUPAJ - 2024"].sum()
        return numerator / denominator if denominator else np.nan

    if "Ocenjeni prihodki iz nast. dejav. na prenočitev" in indicator:
        numerator = df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"].astype(float).sum() * 0.8
        denominator = df["Prenočitve turistov SKUPAJ - 2024"].sum()
        return numerator / denominator if denominator else np.nan

    if "Ocenjeni prihodki iz nast.dej. na prodano sobo (ned.enoto)" in indicator:
        numerator = (df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"] * 0.8).sum()
        hoteli = df["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Hoteli in podobni obrati"].sum()
        druge_enote = df["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet"].sum()
        kampi = df["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Kampi"].sum()
        vse_enote = hoteli + druge_enote + kampi
        if not vse_enote:
            return np.nan
        hoteli_zasedenost = 1.6 * (hoteli / vse_enote)
        kampi_zasedenost = 2.5 * (kampi / vse_enote)
        druge_zasedenost = 2 * (druge_enote / vse_enote)
        denominator = df["Prenočitve turistov SKUPAJ - 2024"].sum() / (
            hoteli_zasedenost + kampi_zasedenost + druge_zasedenost
        )
        return numerator / denominator if denominator else np.nan

    if "Ocenjeni prihodki iz nastan. dej. na razpoložljivo sobo (enoto)" in indicator:
        numerator = (df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"] * 0.8).sum()
        hoteli = df["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Hoteli in podobni obrati"].sum()
        druge_enote = df["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet"].sum()
        kampi = df["Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Kampi"].sum()
        denominator = (hoteli + druge_enote) * 365 + kampi * 153
        return numerator / denominator if denominator else np.nan

    return None


def aggregate_indicator_with_rules(
    df: pd.DataFrame,
    indicator: str,
    agg_rules: dict[str, tuple[str, str | None]] = AGG_RULES,
    region_name: str | None = None,
) -> float:
    precomputed_value = get_precomputed_indicator_value(indicator, region_name, df)
    if precomputed_value is not None:
        return precomputed_value

    if indicator not in agg_rules:
        return df[indicator].sum(skipna=True)

    rule, weight_col = agg_rules[indicator]
    values = df[indicator].astype(float)

    if rule == "sum":
        return float(values.sum(skipna=True))
    if rule == "mean":
        return float(values.mean(skipna=True))
    if rule == "wmean":
        if weight_col is None or weight_col not in df.columns:
            return float(values.mean(skipna=True))
        weights = df[weight_col].astype(float)
        mask = (~values.isna()) & (~weights.isna()) & (weights > 0)
        if not mask.any():
            return np.nan
        return float(np.average(values[mask], weights=weights[mask]))
    return float(values.sum(skipna=True))


def compute_non_sum_display_delta(
    indicator: str,
    region_value: float,
    slovenia_value: float,
) -> tuple[float, str, str]:
    delta_raw = float(region_value) - float(slovenia_value)
    delta_unit = get_indicator_gap_unit(indicator)
    if delta_unit == "o.t.":
        delta_raw *= 100.0
    return delta_raw, delta_unit, "Neposredni odmik glede na slovensko osnovo"


def compute_sum_display_delta(
    reg_df: pd.DataFrame,
    indicator: str,
    agg_rules: dict[str, tuple[str, str | None]],
    region_name: str,
    region_value: float,
    slovenia_value: float,
    df_slo_total_num: pd.Series,
) -> tuple[float, str, str]:
    base_indicator, base_label = get_sum_comparison_base(indicator)
    if base_indicator not in reg_df.columns:
        return np.nan, "o.t.", f"Delež kazalnika glede na {base_label}"

    base_reg = aggregate_indicator_with_rules(reg_df, base_indicator, agg_rules, region_name)
    base_slo = df_slo_total_num.get(base_indicator, np.nan)
    if pd.isna(base_reg) or pd.isna(base_slo) or float(base_slo) == 0:
        return np.nan, "o.t.", f"Delež kazalnika glede na {base_label}"

    indicator_share = float(region_value) / float(slovenia_value)
    benchmark_share = float(base_reg) / float(base_slo)
    delta_raw = (indicator_share - benchmark_share) * 100.0
    return delta_raw, "o.t.", f"Delež kazalnika glede na {base_label}"


def compute_indicator_metric_series(
    reference_agg_df: pd.DataFrame,
    indicator: str,
    agg_rules: dict[str, tuple[str, str | None]],
    df_slo_total_num: pd.Series,
) -> pd.Series:
    if indicator not in reference_agg_df.columns:
        return pd.Series(dtype=float)

    rule, _ = get_agg_rule(indicator, agg_rules)
    slovenia_value = df_slo_total_num.get(indicator, np.nan)
    if pd.isna(slovenia_value) or float(slovenia_value) == 0:
        return pd.Series(dtype=float)

    values = reference_agg_df[indicator].astype(float)
    if rule == "sum":
        base_indicator, _ = get_sum_comparison_base(indicator)
        if base_indicator not in reference_agg_df.columns:
            return pd.Series(dtype=float)
        base_slo = df_slo_total_num.get(base_indicator, np.nan)
        if pd.isna(base_slo) or float(base_slo) == 0:
            return pd.Series(dtype=float)
        base_values = reference_agg_df[base_indicator].astype(float)
        metric_series = ((values / float(slovenia_value)) - (base_values / float(base_slo))) * 100.0
        return metric_series.replace([np.inf, -np.inf], np.nan).dropna()

    delta_series = values - float(slovenia_value)
    if get_indicator_gap_unit(indicator) == "o.t.":
        delta_series = delta_series * 100.0
    return delta_series.replace([np.inf, -np.inf], np.nan).dropna()


def compute_indicator_ranking_scale(metric_series: pd.Series) -> float:
    prepared = pd.to_numeric(metric_series, errors="coerce").dropna().astype(float)
    if prepared.empty:
        return np.nan

    median_value = float(prepared.median())
    median_abs = float(np.nanmedian(np.abs(prepared.values)))
    mad = float((prepared - median_value).abs().median())

    candidates = []
    if mad > 1e-9:
        candidates.append(mad * 1.4826)

    if len(prepared) >= 4:
        iqr = float(prepared.quantile(0.75) - prepared.quantile(0.25))
        if iqr > 1e-9:
            candidates.append(iqr / 1.349)

    if len(prepared) >= 2:
        std = float(prepared.std(ddof=0))
        if std > 1e-9:
            candidates.append(std)

    if median_abs > 1e-9:
        candidates.append(median_abs)

    if candidates:
        return max(candidates)
    return 1.0


def compute_region_aggregates(
    numeric_df: pd.DataFrame,
    regions: list[str],
    indicator_cols: list[str],
    agg_rules: dict[str, tuple[str, str | None]],
    group_col: str,
) -> pd.DataFrame:
    grouped_frames: dict[str, pd.DataFrame] = {
        str(region): group for region, group in numeric_df.groupby(group_col, sort=False)
    }
    empty_frame = numeric_df.iloc[0:0]
    aggregated_data: dict[str, list[Any]] = {group_col: regions}
    for indicator in indicator_cols:
        aggregated_data[indicator] = [
            aggregate_indicator_with_rules(
                grouped_frames[str(region)] if str(region) in grouped_frames else empty_frame,
                indicator,
                agg_rules,
                region,
            )
            for region in regions
        ]
    return pd.DataFrame(aggregated_data)


def get_top_bottom_reference_indicators(
    grouped_filtered: dict[str, list[str]],
    agg_rules: dict[str, tuple[str, str | None]],
) -> list[str]:
    reference_indicators: set[str] = set()
    for indicators in grouped_filtered.values():
        for indicator in indicators:
            reference_indicators.add(indicator)
            rule, _ = get_agg_rule(indicator, agg_rules)
            if rule == "sum":
                base_indicator, _ = get_sum_comparison_base(indicator)
                reference_indicators.add(base_indicator)
    return sorted(reference_indicators)


def compute_indicator_comparison(
    reg_df: pd.DataFrame,
    indicator: str,
    agg_rules: dict[str, tuple[str, str | None]],
    region_name: str,
    df_slo_total_num: pd.Series,
    reference_agg_df: pd.DataFrame | None = None,
) -> dict[str, Any] | None:
    region_value = aggregate_indicator_with_rules(reg_df, indicator, agg_rules, region_name)
    slovenia_value = df_slo_total_num.get(indicator, np.nan)

    if pd.isna(region_value) or pd.isna(slovenia_value) or float(slovenia_value) == 0:
        return None

    rule, _ = get_agg_rule(indicator, agg_rules)
    direction = -1.0 if is_lower_better(indicator) else 1.0
    if rule == "sum":
        delta_raw, delta_unit, comparison_method = compute_sum_display_delta(
            reg_df=reg_df,
            indicator=indicator,
            agg_rules=agg_rules,
            region_name=region_name,
            region_value=float(region_value),
            slovenia_value=float(slovenia_value),
            df_slo_total_num=df_slo_total_num,
        )
    else:
        delta_raw, delta_unit, comparison_method = compute_non_sum_display_delta(
            indicator=indicator,
            region_value=float(region_value),
            slovenia_value=float(slovenia_value),
        )

    if pd.isna(delta_raw):
        return None

    delta_aligned = direction * delta_raw
    ranking_score = delta_aligned
    if reference_agg_df is not None:
        metric_series = compute_indicator_metric_series(
            reference_agg_df=reference_agg_df,
            indicator=indicator,
            agg_rules=agg_rules,
            df_slo_total_num=df_slo_total_num,
        )
        scale = compute_indicator_ranking_scale(metric_series)
        if not pd.isna(scale) and scale > 0:
            ranking_score = delta_aligned / scale

    return {
        "Kazalnik": indicator,
        "Smer kazalnika": "Nižje je bolje" if direction < 0 else "Višje je bolje",
        "Vrednost območja": format_indicator_value_map(indicator, region_value),
        "Osnova (Slovenija)": format_indicator_value_map(indicator, slovenia_value),
        "Metoda primerjave": comparison_method,
        "Odstopanje_raw": delta_raw,
        "Odstopanje_aligned_raw": delta_aligned,
        "Rangirni_odmik_raw": ranking_score,
        "Enota odstopanja": delta_unit,
    }


def build_top_bottom_group_sections(
    reg_df: pd.DataFrame,
    df_slo_total_num: pd.Series,
    grouped_filtered: dict[str, list[str]],
    agg_rules: dict[str, tuple[str, str | None]],
    region_name: str,
    reference_agg_df: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for group_name in TOP_BOTTOM_GROUP_ORDER:
        group_indicators = [
            indicator
            for indicator in grouped_filtered.get(group_name, [])
            if indicator not in TOP_BOTTOM_EXCLUDED_INDICATORS
        ]
        comparison_rows = []
        for indicator in group_indicators:
            row = compute_indicator_comparison(
                reg_df=reg_df,
                indicator=indicator,
                agg_rules=agg_rules,
                region_name=region_name,
                df_slo_total_num=df_slo_total_num,
                reference_agg_df=reference_agg_df,
            )
            if row is not None:
                row["Skupina kazalnikov"] = group_name
                comparison_rows.append(row)

        if not comparison_rows:
            continue

        group_df = pd.DataFrame(comparison_rows)
        limit = min(TOP_BOTTOM_GROUP_LIMITS.get(group_name, 5), len(group_df))
        best_df = group_df.nlargest(limit, "Rangirni_odmik_raw").copy()

        remaining_df = group_df.drop(best_df.index)
        if len(remaining_df) >= limit:
            worst_df = remaining_df.nsmallest(limit, "Rangirni_odmik_raw").copy()
        else:
            worst_df = group_df.nsmallest(limit, "Rangirni_odmik_raw").copy()

        for table in (best_df, worst_df):
            table["Odstopanje glede na smer"] = table.apply(
                lambda row: format_comparison_delta(row["Odstopanje_aligned_raw"], row["Enota odstopanja"]),
                axis=1,
            )
            table["Primerjalni odmik"] = table.apply(
                lambda row: format_comparison_delta(row["Odstopanje_raw"], row["Enota odstopanja"]),
                axis=1,
            )

        ai_columns = [
            "Kazalnik",
            "Smer kazalnika",
            "Vrednost območja",
            "Osnova (Slovenija)",
            "Metoda primerjave",
            "Odstopanje glede na smer",
            "Primerjalni odmik",
        ]
        sections.append(
            {
                "group": group_name,
                "limit": limit,
                "best_df": best_df,
                "worst_df": worst_df,
                "top_rows": best_df[ai_columns].to_dict("records"),
                "bottom_rows": worst_df[ai_columns].to_dict("records"),
            }
        )

    return sections


def get_market_cols_for_year(df: pd.DataFrame, year: int) -> tuple[list[str], list[str]]:
    pattern = re.compile(rf"^{re.escape(MARKET_PREFIX)}(.+?)\s*-\s*{year}\s*$")
    cols = []
    labels = []
    for column in df.columns:
        match = pattern.match(str(column))
        if match:
            cols.append(column)
            labels.append(match.group(1).strip())
    return cols, labels


def get_available_market_years(df: pd.DataFrame) -> list[int]:
    pattern = re.compile(rf"^{re.escape(MARKET_PREFIX)}.+?\s*-\s*((?:19|20)\d{{2}})\s*$")
    years: set[int] = set()
    for column in df.columns:
        match = pattern.match(str(column))
        if match:
            years.add(int(match.group(1)))
    return sorted(years)


def get_market_overnight_cols_for_year(df: pd.DataFrame, year: int) -> tuple[list[str], list[str]]:
    pattern = re.compile(rf"^Število nočitev\s+{year}\s*-\s*(.+?)\s*$")
    cols = []
    labels = []
    for column in df.columns:
        match = pattern.match(str(column))
        if match:
            cols.append(column)
            labels.append(match.group(1).strip())
    return cols, labels


def get_available_market_overnight_years(df: pd.DataFrame) -> list[int]:
    pattern = re.compile(r"^Število nočitev\s+((?:19|20)\d{2})\s*-\s*(.+?)\s*$")
    years: set[int] = set()
    for column in df.columns:
        match = pattern.match(str(column))
        if match:
            years.add(int(match.group(1)))
    return sorted(years)


def compute_market_structure_for_subset(
    subset: pd.DataFrame,
    *,
    df_source: pd.DataFrame,
    selected_year: int,
) -> pd.DataFrame:
    if subset.empty:
        return pd.DataFrame(columns=["Trg", "Delež", "Delež_norm"])

    base_weight_col = col_for_year("Prenočitve turistov SKUPAJ - 2024", selected_year)
    market_cols_year, market_labels_year = get_market_cols_for_year(df_source, selected_year)
    required_cols = [base_weight_col] + market_cols_year
    if any(column not in subset.columns for column in required_cols):
        return pd.DataFrame(columns=["Trg", "Delež", "Delež_norm"])

    total_weights = subset[base_weight_col].astype(float)
    total_weights_array = total_weights.to_numpy(dtype=float, copy=False)
    denominator = float(np.nansum(total_weights_array))
    if not np.isfinite(denominator) or denominator <= 0:
        return pd.DataFrame(columns=["Trg", "Delež", "Delež_norm"])

    rows: list[dict[str, Any]] = []
    for column, label in zip(market_cols_year, market_labels_year):
        series = subset[column].astype(float)
        mask = (~series.isna()) & (~total_weights.isna()) & (total_weights > 0)
        if not mask.any():
            continue
        weighted_values_array = (series[mask] * total_weights[mask]).to_numpy(dtype=float, copy=False)
        masked_weights_array = total_weights[mask].to_numpy(dtype=float, copy=False)
        rows.append(
            {
                "Trg": label,
                "Delež": float(
                    np.nansum(weighted_values_array)
                    / np.nansum(masked_weights_array)
                ),
            }
        )

    structure_df = pd.DataFrame(rows).dropna()
    if structure_df.empty:
        return pd.DataFrame(columns=["Trg", "Delež", "Delež_norm"])

    total_share = float(structure_df["Delež"].sum())
    structure_df["Delež_norm"] = structure_df["Delež"] / total_share if total_share > 0 else np.nan
    return structure_df


def build_market_ai_context(
    *,
    selected_group: str,
    group_col: str,
    df_source: pd.DataFrame,
    numeric_df: pd.DataFrame,
    growth_numeric_df: pd.DataFrame | None,
) -> dict[str, Any] | None:
    subset = numeric_df[numeric_df[group_col] == selected_group].copy()
    if subset.empty:
        return None

    market_years = get_available_market_years(df_source)
    if not market_years:
        return None

    latest_year = max(market_years)
    structure_df = compute_market_structure_for_subset(
        subset,
        df_source=df_source,
        selected_year=latest_year,
    )
    structure_rows = []
    if not structure_df.empty:
        structure_df = structure_df.sort_values("Delež_norm", ascending=False).reset_index(drop=True)
        structure_rows = [
            {
                "Trg": str(row["Trg"]),
                "Delež_norm_raw": float(row["Delež_norm"]),
                "Delež_norm": format_pct(float(row["Delež_norm"]) * 100.0, 1),
            }
            for _, row in structure_df.iterrows()
            if pd.notna(row["Delež_norm"])
        ]

    growth_payloads: dict[str, dict[str, Any]] = {}
    if growth_numeric_df is not None and group_col in growth_numeric_df.columns:
        growth_subset = growth_numeric_df[growth_numeric_df[group_col] == selected_group].copy()
        growth_years = get_available_market_overnight_years(growth_subset)
        if not growth_subset.empty and latest_year in growth_years:
            candidate_base_years = [year for year in growth_years if year < latest_year]
            if candidate_base_years:
                previous_year = max(candidate_base_years)
                growth_previous_df = compute_market_growth_for_subset(
                    growth_subset,
                    base_year=previous_year,
                    target_year=latest_year,
                )
                if not growth_previous_df.empty:
                    growth_previous_df = growth_previous_df.sort_values("Rast_raw", ascending=False).reset_index(drop=True)
                    growth_payloads[f"{latest_year}/{previous_year}"] = {
                        "period": f"{latest_year}/{previous_year}",
                        "rows": [
                            {
                                "Trg": str(row["Trg"]),
                                "Rast_raw": float(row["Rast_raw"]),
                                "Rast": format_pct(float(row["Rast_raw"]) * 100.0, 1),
                            }
                            for _, row in growth_previous_df.iterrows()
                            if pd.notna(row["Rast_raw"])
                        ],
                    }

                if 2019 in candidate_base_years and previous_year != 2019:
                    growth_2019_df = compute_market_growth_for_subset(
                        growth_subset,
                        base_year=2019,
                        target_year=latest_year,
                    )
                    if not growth_2019_df.empty:
                        growth_2019_df = growth_2019_df.sort_values("Rast_raw", ascending=False).reset_index(drop=True)
                        growth_payloads[f"{latest_year}/2019"] = {
                            "period": f"{latest_year}/2019",
                            "rows": [
                                {
                                    "Trg": str(row["Trg"]),
                                    "Rast_raw": float(row["Rast_raw"]),
                                    "Rast": format_pct(float(row["Rast_raw"]) * 100.0, 1),
                                }
                                for _, row in growth_2019_df.iterrows()
                                if pd.notna(row["Rast_raw"])
                            ],
                        }
                elif 2019 in candidate_base_years and previous_year == 2019:
                    growth_payloads.setdefault(f"{latest_year}/2019", growth_payloads[f"{latest_year}/{previous_year}"])

    return {
        "latest_year": latest_year,
        "structure_rows": structure_rows,
        "growth_periods": growth_payloads,
    }


def compute_market_growth_for_subset(
    subset: pd.DataFrame,
    *,
    base_year: int,
    target_year: int,
) -> pd.DataFrame:
    if subset.empty:
        return pd.DataFrame(columns=["Trg", "Rast_raw"])

    base_cols, base_labels = get_market_overnight_cols_for_year(subset, base_year)
    target_cols, target_labels = get_market_overnight_cols_for_year(subset, target_year)
    base_market_cols = {label: column for column, label in zip(base_cols, base_labels)}
    target_market_cols = {label: column for column, label in zip(target_cols, target_labels)}
    labels = [label for label in target_market_cols if label in base_market_cols]
    if not labels:
        return pd.DataFrame(columns=["Trg", "Rast_raw"])

    rows: list[dict[str, Any]] = []
    for label in labels:
        base_share_col = base_market_cols[label]
        target_share_col = target_market_cols[label]
        base_values = subset[base_share_col].astype(float)
        target_values = subset[target_share_col].astype(float)
        mask = (~base_values.isna()) & (~target_values.isna()) & (base_values >= 0) & (target_values >= 0)
        if not mask.any():
            rows.append({"Trg": label, "Rast_raw": np.nan})
            continue

        base_sum = float(base_values[mask].sum(skipna=True))
        target_sum = float(target_values[mask].sum(skipna=True))
        if base_sum <= 0:
            growth = np.nan
        else:
            growth = (target_sum / base_sum) - 1.0

        rows.append({"Trg": label, "Rast_raw": growth})

    return pd.DataFrame(rows)


MARKET_MONTH_ORDER = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "avg", "sep", "okt", "nov", "dec"]


def compute_market_seasonality_for_subset(
    subset: pd.DataFrame,
    *,
    include_total_market: bool = False,
) -> pd.DataFrame:
    if subset.empty:
        return pd.DataFrame(columns=["Trg", "Mesec", "Vrednost"])

    pattern = re.compile(r"^(.+?)__(jan|feb|mar|apr|maj|jun|jul|avg|sep|okt|nov|dec)$", re.IGNORECASE)
    month_order = {month: index for index, month in enumerate(MARKET_MONTH_ORDER)}
    market_order: dict[str, int] = {}
    next_market_order = 0
    rows: list[dict[str, Any]] = []

    for column in subset.columns:
        match = pattern.match(str(column))
        if not match:
            continue

        market_label = match.group(1).strip()
        month_label = match.group(2).lower()
        if market_label == "SKUPAJ VSI TRGI" and not include_total_market:
            continue

        if market_label not in market_order:
            market_order[market_label] = next_market_order
            next_market_order += 1

        values = subset[column].astype(float)
        rows.append(
            {
                "Trg": market_label,
                "Mesec": month_label,
                "Vrednost": float(values.sum(skipna=True)),
                "_market_order": market_order[market_label],
                "_month_order": month_order.get(month_label, 999),
            }
        )

    seasonality_df = pd.DataFrame(rows)
    if seasonality_df.empty:
        return pd.DataFrame(columns=["Trg", "Mesec", "Vrednost"])

    seasonality_df = seasonality_df.sort_values(
        ["_market_order", "_month_order"],
        ascending=[True, True],
        na_position="last",
    ).reset_index(drop=True)
    return seasonality_df.drop(columns=["_market_order", "_month_order"])
