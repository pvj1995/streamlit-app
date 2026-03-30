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
    is_lower_better,
)


def get_agg_rule(
    indicator: str,
    agg_rules: dict[str, tuple[str, str | None]],
) -> tuple[str, str | None]:
    return agg_rules.get(indicator, ("sum", None))


def get_default_population_base(indicator: str) -> str:
    if "2025" in indicator:
        return "Število prebivalcev (H2/2025)"
    return "Število prebivalcev (H2/2024)"


def get_sum_comparison_base(indicator: str) -> tuple[str, str]:
    lower_indicator = indicator.lower()
    population_base = get_default_population_base(indicator)

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
    if any(
        token in lower_indicator
        for token in [
            "prenočitve",
            "prihodi turistov",
            "nastanitvene kapacitete",
            "nastanitvenih obratov",
            "hotelov",
            "kampov",
            "turističnih kmetij",
            "ležišč",
            "sob ",
            "nedeljive enote",
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


def compute_region_aggregates(
    numeric_df: pd.DataFrame,
    regions: list[str],
    indicator_cols: list[str],
    agg_rules: dict[str, tuple[str, str | None]],
    group_col: str,
) -> pd.DataFrame:
    aggregated_df = pd.DataFrame({group_col: regions})
    for indicator in indicator_cols:
        aggregated_df[indicator] = [
            aggregate_indicator_with_rules(
                numeric_df[numeric_df[group_col] == region],
                indicator,
                agg_rules,
                region,
            )
            for region in regions
        ]
    return aggregated_df


def compute_indicator_comparison(
    reg_df: pd.DataFrame,
    indicator: str,
    agg_rules: dict[str, tuple[str, str | None]],
    region_name: str,
    df_slo_total_num: pd.Series,
) -> dict[str, Any] | None:
    region_value = aggregate_indicator_with_rules(reg_df, indicator, agg_rules, region_name)
    slovenia_value = df_slo_total_num.get(indicator, np.nan)

    if pd.isna(region_value) or pd.isna(slovenia_value) or float(slovenia_value) == 0:
        return None

    rule, _ = get_agg_rule(indicator, agg_rules)
    direction = -1.0 if is_lower_better(indicator) else 1.0
    delta_raw = ((float(region_value) - float(slovenia_value)) / abs(float(slovenia_value))) * 100.0
    delta_unit = "%"
    comparison_method = "Neposredno glede na slovensko osnovo"

    if rule == "sum":
        base_indicator, base_label = get_sum_comparison_base(indicator)
        if base_indicator in reg_df.columns:
            base_reg = aggregate_indicator_with_rules(reg_df, base_indicator, agg_rules, region_name)
            base_slo = df_slo_total_num.get(base_indicator, np.nan)
            if not pd.isna(base_reg) and not pd.isna(base_slo) and float(base_slo) != 0:
                indicator_share = float(region_value) / float(slovenia_value)
                benchmark_share = float(base_reg) / float(base_slo)
                delta_raw = (indicator_share - benchmark_share) * 100.0
                delta_unit = "o.t."
                comparison_method = f"Delež kazalnika glede na {base_label}"

    delta_aligned = direction * delta_raw
    return {
        "Kazalnik": indicator,
        "Smer kazalnika": "Nižje je bolje" if direction < 0 else "Višje je bolje",
        "Vrednost območja": format_indicator_value_map(indicator, region_value),
        "Osnova (Slovenija)": format_indicator_value_map(indicator, slovenia_value),
        "Metoda primerjave": comparison_method,
        "Odstopanje_raw": delta_raw,
        "Odstopanje_aligned_raw": delta_aligned,
        "Enota odstopanja": delta_unit,
    }


def build_top_bottom_group_sections(
    reg_df: pd.DataFrame,
    df_slo_total_num: pd.Series,
    grouped_filtered: dict[str, list[str]],
    agg_rules: dict[str, tuple[str, str | None]],
    region_name: str,
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
            )
            if row is not None:
                row["Skupina kazalnikov"] = group_name
                comparison_rows.append(row)

        if not comparison_rows:
            continue

        group_df = pd.DataFrame(comparison_rows)
        limit = min(TOP_BOTTOM_GROUP_LIMITS.get(group_name, 5), len(group_df))
        best_df = group_df.nlargest(limit, "Odstopanje_aligned_raw").copy()

        remaining_df = group_df.drop(best_df.index)
        if len(remaining_df) >= limit:
            worst_df = remaining_df.nsmallest(limit, "Odstopanje_aligned_raw").copy()
        else:
            worst_df = group_df.nsmallest(limit, "Odstopanje_aligned_raw").copy()

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
