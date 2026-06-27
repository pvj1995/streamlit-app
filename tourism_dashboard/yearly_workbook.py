from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from tourism_dashboard.config import AGG_RULES


REQUIRED_YEARLY_SHEETS = {
    "areas",
    "metrics",
    "metric_year_rules",
}
AREA_OUTPUT_COLUMNS = [
    "Občine",
    "SLOVENIJA",
    "Makro destinacije",
    "Perspektivne destinacije",
    "Vodilne destinacije",
    "Turistična regija",
    "Tip območja",
]
GROUP_OUTPUT_ORDER = [
    "Družbeni kazalniki",
    "Okoljski kazalniki",
    "Ekonomski nastanitveni in tržni turistični kazalniki",
    "Ekonomsko poslovni kazalniki turistične dejavnosti",
]


@dataclass(frozen=True)
class YearlyDashboardFrames:
    main_df: pd.DataFrame
    market_growth_df: pd.DataFrame | None
    mapping_df: pd.DataFrame
    indicator_metadata_df: pd.DataFrame
    agg_rules_df: pd.DataFrame
    agg_rules: dict[str, tuple[str, str | None]]


def _source_to_excel_file(source: Path | bytes | BytesIO | str) -> pd.ExcelFile:
    if isinstance(source, bytes):
        return pd.ExcelFile(BytesIO(source))
    return pd.ExcelFile(source)


def is_yearly_indicator_workbook(source: Path | bytes | BytesIO | str) -> bool:
    try:
        workbook = _source_to_excel_file(source)
    except Exception:
        return False
    sheet_names = {str(sheet_name) for sheet_name in workbook.sheet_names}
    return REQUIRED_YEARLY_SHEETS.issubset(sheet_names) and any(
        sheet_name.startswith("Y") and sheet_name[1:].isdigit()
        for sheet_name in sheet_names
    )


def _read_sheet(workbook: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    if sheet_name not in workbook.sheet_names:
        return pd.DataFrame()
    return pd.read_excel(workbook, sheet_name=sheet_name)


def _clean_optional_text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _clean_year(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "yes", "1", "da"}:
        return True
    if normalized in {"false", "no", "0", "ne"}:
        return False
    return default


def _normalize_metrics_dataframe(metrics_df: pd.DataFrame) -> pd.DataFrame:
    if metrics_df.empty:
        return metrics_df
    if "metric_id" not in metrics_df.columns and len(metrics_df.columns) > 0:
        metrics_df = metrics_df.rename(columns={metrics_df.columns[0]: "metric_id"})
    return metrics_df


def _metrics_by_id(metrics_df: pd.DataFrame) -> dict[str, pd.Series]:
    if metrics_df.empty or "metric_id" not in metrics_df.columns:
        return {}
    return {
        _clean_optional_text(row.get("metric_id")): row
        for _, row in metrics_df.iterrows()
        if _clean_optional_text(row.get("metric_id"))
    }


def _metric_output_label(row: pd.Series, metrics_by_metric_id: dict[str, pd.Series]) -> str:
    source_column = _clean_optional_text(row.get("source_column"))
    if source_column:
        return source_column

    metric_id = _clean_optional_text(row.get("metric_id"))
    year = _clean_year(row.get("year"))
    metric = metrics_by_metric_id.get(metric_id)
    display_name = _clean_optional_text(metric.get("display_name")) if metric is not None else ""
    label = display_name or metric_id
    if not label:
        return ""

    if year is None or str(year) in label:
        return label
    return f"{label} {year}"


def _metric_group(row: pd.Series, metrics_by_metric_id: dict[str, pd.Series]) -> str:
    group = _clean_optional_text(row.get("group"))
    if group:
        return group
    metric_id = _clean_optional_text(row.get("metric_id"))
    metric = metrics_by_metric_id.get(metric_id)
    return _clean_optional_text(metric.get("group")) if metric is not None else ""


def _metric_selectable(row: pd.Series, metrics_by_metric_id: dict[str, pd.Series]) -> bool:
    if "selectable" in row.index and not pd.isna(row.get("selectable")):
        return _clean_bool(row.get("selectable"), True)
    metric_id = _clean_optional_text(row.get("metric_id"))
    metric = metrics_by_metric_id.get(metric_id)
    if metric is not None and "selectable" in metric.index:
        return _clean_bool(metric.get("selectable"), True)
    return True


def _metric_metadata_value(
    row: pd.Series,
    metric: pd.Series | None,
    column: str,
    default: Any = "",
) -> Any:
    value = row.get(column) if column in row.index else None
    if _clean_optional_text(value):
        return value
    if metric is not None and column in metric.index:
        return metric.get(column)
    return default


def _derived_output_label(row: pd.Series) -> str:
    source_column = _clean_optional_text(row.get("source_column"))
    if source_column:
        return source_column

    template = _clean_optional_text(row.get("display_name_template"))
    current_year = _clean_year(row.get("current_year"))
    base_year = _clean_year(row.get("base_year"))
    if template and current_year is not None and base_year is not None:
        return template.format(current_year=current_year, base_year=base_year)
    return template


def _infer_derived_metric_id(label: str) -> str:
    normalized = label.lower()
    if "gini" in normalized:
        return "gini_indeks_sezonskost_prenocitev"
    if "prenoč" in normalized or "prenoc" in normalized:
        if "doma" in normalized:
            return "prenocitve_turistov_domaci"
        if "tuji" in normalized:
            return "prenocitve_turistov_tuji"
        return "prenocitve_turistov_skupaj"
    return ""


def _infer_derived_formula_type(label: str, formula_type: str) -> str:
    if formula_type and formula_type != "growth_or_change":
        return formula_type
    normalized = label.lower()
    if "gini" in normalized or "gibanje" in normalized:
        return "index_ratio_100"
    return "growth_rate"


def _calculate_derived_series(
    current_values: pd.Series,
    base_values: pd.Series,
    formula_type: str,
) -> pd.Series:
    current_numeric = pd.to_numeric(current_values, errors="coerce")
    base_numeric = pd.to_numeric(base_values, errors="coerce")
    valid_base = base_numeric.where(base_numeric != 0)

    if formula_type in {"index_ratio_100", "ratio_index_100"}:
        return (current_numeric / valid_base) * 100.0
    if formula_type in {"difference", "absolute_change"}:
        return current_numeric - base_numeric
    return (current_numeric / valid_base) - 1.0


def build_indicator_groups_from_mapping_dataframe(mapping_df: pd.DataFrame) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    if mapping_df.empty:
        return groups
    for column in mapping_df.columns:
        series = mapping_df[column].dropna().astype(str).str.strip()
        values = [value for value in series.tolist() if value]
        if values:
            groups[str(column)] = values
    return groups


def _pad_group_values(groups: dict[str, list[str]]) -> pd.DataFrame:
    if not groups:
        return pd.DataFrame()
    ordered_groups = {
        group: groups[group]
        for group in GROUP_OUTPUT_ORDER
        if group in groups
    }
    for group, values in groups.items():
        if group not in ordered_groups:
            ordered_groups[group] = values
    max_len = max(len(values) for values in groups.values())
    return pd.DataFrame(
        {
            group: values + [""] * (max_len - len(values))
            for group, values in ordered_groups.items()
        }
    )


def _build_mapping_from_metadata(
    metric_year_rules: pd.DataFrame,
    derived_metrics: pd.DataFrame,
    metrics_by_metric_id: dict[str, pd.Series],
) -> pd.DataFrame:
    groups: dict[str, list[str]] = {}
    if not metric_year_rules.empty:
        ordered_rule_rows: list[pd.Series] = []
        seen_rule_indexes: set[int] = set()
        indexed_rule_rows = list(enumerate(metric_year_rules.iterrows()))
        for metric_id in metrics_by_metric_id:
            for row_index, (_, row) in indexed_rule_rows:
                if str(row.get("metric_id") or "").strip() != metric_id:
                    continue
                ordered_rule_rows.append(row)
                seen_rule_indexes.add(row_index)
        for row_index, (_, row) in indexed_rule_rows:
            if row_index not in seen_rule_indexes:
                ordered_rule_rows.append(row)

        for row in ordered_rule_rows:
            group = _metric_group(row, metrics_by_metric_id)
            source_column = _metric_output_label(row, metrics_by_metric_id)
            selectable = _metric_selectable(row, metrics_by_metric_id)
            if group and source_column and selectable:
                groups.setdefault(group, []).append(source_column)
    if not derived_metrics.empty:
        for _, row in derived_metrics.iterrows():
            group = _clean_optional_text(row.get("group"))
            source_column = _derived_output_label(row)
            selectable = _clean_bool(row.get("selectable"), True)
            if group and source_column and selectable:
                groups.setdefault(group, []).append(source_column)
    return _pad_group_values(groups)


def aggregation_rules_from_dataframe(
    agg_rules_df: pd.DataFrame,
    *,
    include_defaults: bool = True,
) -> dict[str, tuple[str, str | None]]:
    rules = dict(AGG_RULES) if include_defaults else {}
    if agg_rules_df.empty:
        return rules
    required = {"indicator", "aggregation_method"}
    if not required.issubset(set(agg_rules_df.columns)):
        return rules
    for row in agg_rules_df.itertuples(index=False):
        indicator = _clean_optional_text(getattr(row, "indicator", ""))
        method = _clean_optional_text(getattr(row, "aggregation_method", ""))
        weight = _clean_optional_text(getattr(row, "weight_indicator", ""))
        if indicator and method:
            rules[indicator] = (method, weight or None)
    return rules


def aggregation_rules_to_dataframe(agg_rules: dict[str, tuple[str, str | None]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "indicator": indicator,
                "aggregation_method": method,
                "weight_indicator": weight or "",
            }
            for indicator, (method, weight) in agg_rules.items()
        ]
    )


def _build_agg_rules_dataframe(
    metric_year_rules: pd.DataFrame,
    derived_metrics: pd.DataFrame,
    metrics_by_metric_id: dict[str, pd.Series],
    metric_year_labels: dict[tuple[str, int], str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not metric_year_rules.empty:
        for _, row in metric_year_rules.iterrows():
            source_column = _metric_output_label(row, metrics_by_metric_id)
            method = _clean_optional_text(row.get("aggregation_method"))
            weight_metric_id = _clean_optional_text(row.get("weight_metric_id"))
            weight_year = _clean_year(row.get("weight_year"))
            weight = ""
            if weight_metric_id and weight_year is not None:
                weight = metric_year_labels.get((weight_metric_id, weight_year), "")
            if not weight:
                weight = _clean_optional_text(row.get("weight_source_column"))
            if source_column and method:
                rows.append(
                    {
                        "indicator": source_column,
                        "aggregation_method": method,
                        "weight_indicator": weight,
                    }
                )

    if not derived_metrics.empty:
        existing = {item["indicator"] for item in rows}
        for _, row in derived_metrics.iterrows():
            source_column = _derived_output_label(row)
            if not source_column or source_column in {item["indicator"] for item in rows}:
                continue
            method = _clean_optional_text(row.get("aggregation_method"))
            weight_metric_id = _clean_optional_text(row.get("weight_metric_id"))
            weight_year = _clean_year(row.get("weight_year"))
            weight = ""
            if weight_metric_id and weight_year is not None:
                weight = metric_year_labels.get((weight_metric_id, weight_year), "")
            if not method:
                method, configured_weight = AGG_RULES.get(source_column, ("sum", None))
                weight = weight or configured_weight or ""
            if not weight:
                weight = _clean_optional_text(row.get("weight_source_column"))
            rows.append(
                {
                    "indicator": source_column,
                    "aggregation_method": method,
                    "weight_indicator": weight or "",
                }
            )
    return pd.DataFrame(rows)


def _build_indicator_metadata_dataframe(
    metric_year_rules: pd.DataFrame,
    derived_metrics: pd.DataFrame,
    metrics_by_metric_id: dict[str, pd.Series],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    if not metric_year_rules.empty:
        for _, row in metric_year_rules.iterrows():
            indicator = _metric_output_label(row, metrics_by_metric_id)
            metric_id = _clean_optional_text(row.get("metric_id"))
            year = _clean_year(row.get("year"))
            metric = metrics_by_metric_id.get(metric_id)
            if not indicator or indicator in seen:
                continue
            rows.append(
                {
                    "indicator": indicator,
                    "metric_id": metric_id,
                    "year": year,
                    "display_name": _clean_optional_text(metric.get("display_name")) if metric is not None else "",
                    "unit": _clean_optional_text(_metric_metadata_value(row, metric, "unit")),
                    "format_type": _clean_optional_text(_metric_metadata_value(row, metric, "format_type")),
                    "decimal_places": _metric_metadata_value(row, metric, "decimal_places", ""),
                    "lower_is_better": _metric_metadata_value(row, metric, "lower_is_better", ""),
                }
            )
            seen.add(indicator)

    if not derived_metrics.empty:
        for _, row in derived_metrics.iterrows():
            indicator = _derived_output_label(row)
            if not indicator or indicator in seen:
                continue
            formula_type = _infer_derived_formula_type(indicator, _clean_optional_text(row.get("formula_type")))
            rows.append(
                {
                    "indicator": indicator,
                    "metric_id": _clean_optional_text(row.get("derived_metric_id")),
                    "year": _clean_year(row.get("current_year")),
                    "display_name": _clean_optional_text(row.get("display_name_template")),
                    "unit": "%" if formula_type == "growth_rate" else "",
                    "format_type": "percent_or_rate" if formula_type == "growth_rate" else "index",
                    "decimal_places": 1,
                    "lower_is_better": row.get("lower_is_better", ""),
                }
            )
            seen.add(indicator)

    return pd.DataFrame(rows)


def _validate_yearly_workbook(workbook: pd.ExcelFile) -> None:
    sheet_names = {str(sheet_name) for sheet_name in workbook.sheet_names}
    missing = sorted(REQUIRED_YEARLY_SHEETS - sheet_names)
    if missing:
        raise ValueError(f"Missing required yearly workbook sheets: {', '.join(missing)}")
    if not any(sheet_name.startswith("Y") and sheet_name[1:].isdigit() for sheet_name in sheet_names):
        raise ValueError("Yearly workbook must contain at least one Y#### sheet.")


def load_yearly_dashboard_frames(source: Path | bytes | BytesIO | str) -> YearlyDashboardFrames:
    workbook = _source_to_excel_file(source)
    _validate_yearly_workbook(workbook)

    areas_df = _read_sheet(workbook, "areas")
    metrics_df = _normalize_metrics_dataframe(_read_sheet(workbook, "metrics"))
    metric_year_rules = _read_sheet(workbook, "metric_year_rules")
    derived_metrics = _read_sheet(workbook, "derived_metrics")
    market_overnights = _read_sheet(workbook, "market_overnights_by_market")
    metrics_by_metric_id = _metrics_by_id(metrics_df)

    required_area_columns = {"area_id", "Občine"}
    if not required_area_columns.issubset(set(areas_df.columns)):
        raise ValueError("Sheet 'areas' must contain area_id and Občine columns.")
    required_rule_columns = {"metric_id", "year"}
    if not required_rule_columns.issubset(set(metric_year_rules.columns)):
        raise ValueError("Sheet 'metric_year_rules' must contain metric_id and year columns.")

    output_area_columns = [column for column in AREA_OUTPUT_COLUMNS if column in areas_df.columns]
    main_base_df = areas_df[output_area_columns].reset_index(drop=True).copy()
    area_ids = areas_df["area_id"].astype(str)

    yearly_sheet_cache: dict[int, pd.DataFrame] = {}
    metric_series_cache: dict[tuple[str, int], pd.Series] = {}

    def load_yearly_metric_series(metric_id: str, year: int) -> pd.Series | None:
        cache_key = (metric_id, year)
        if cache_key in metric_series_cache:
            return metric_series_cache[cache_key]

        if year not in yearly_sheet_cache:
            yearly_sheet_name = f"Y{year}"
            yearly_df = _read_sheet(workbook, yearly_sheet_name)
            if yearly_df.empty:
                return None
            if "area_id" not in yearly_df.columns:
                raise ValueError(f"Sheet '{yearly_sheet_name}' must contain area_id.")
            yearly_sheet_cache[year] = yearly_df.set_index(yearly_df["area_id"].astype(str))

        yearly_df = yearly_sheet_cache[year]
        if metric_id not in yearly_df.columns:
            return None

        series = area_ids.map(yearly_df[metric_id]).reset_index(drop=True)
        metric_series_cache[cache_key] = series
        return series

    value_columns: dict[str, pd.Series] = {}
    metric_year_labels: dict[tuple[str, int], str] = {}
    for _, row in metric_year_rules.iterrows():
        metric_id = _clean_optional_text(row.get("metric_id"))
        source_column = _metric_output_label(row, metrics_by_metric_id)
        year = _clean_year(row.get("year"))
        if not metric_id or not source_column or year is None:
            continue

        metric_year_labels[(metric_id, year)] = source_column
        series = load_yearly_metric_series(metric_id, year)
        if series is None:
            continue
        value_columns[source_column] = series

    if not derived_metrics.empty:
        for _, row in derived_metrics.iterrows():
            source_column = _derived_output_label(row)
            current_year = _clean_year(row.get("current_year"))
            base_year = _clean_year(row.get("base_year"))
            if not source_column or current_year is None or base_year is None:
                continue

            current_metric_id = _clean_optional_text(row.get("current_metric_id"))
            base_metric_id = _clean_optional_text(row.get("base_metric_id"))
            inferred_metric_id = _infer_derived_metric_id(source_column)
            current_metric_id = current_metric_id or inferred_metric_id
            base_metric_id = base_metric_id or current_metric_id
            if not current_metric_id or not base_metric_id:
                continue

            current_values = load_yearly_metric_series(current_metric_id, current_year)
            base_values = load_yearly_metric_series(base_metric_id, base_year)
            if current_values is None or base_values is None:
                continue

            formula_type = _infer_derived_formula_type(
                source_column,
                _clean_optional_text(row.get("formula_type")),
            )
            value_columns[source_column] = _calculate_derived_series(
                current_values,
                base_values,
                formula_type,
            )

    main_df = pd.concat(
        [main_base_df, pd.DataFrame(value_columns)],
        axis=1,
    )

    mapping_df = _build_mapping_from_metadata(metric_year_rules, derived_metrics, metrics_by_metric_id)
    indicator_metadata_df = _build_indicator_metadata_dataframe(
        metric_year_rules,
        derived_metrics,
        metrics_by_metric_id,
    )

    agg_rules_df = _build_agg_rules_dataframe(
        metric_year_rules,
        derived_metrics,
        metrics_by_metric_id,
        metric_year_labels,
    )
    agg_rules = aggregation_rules_from_dataframe(agg_rules_df, include_defaults=False)
    market_growth_df = _build_market_growth_dataframe(areas_df, market_overnights)

    return YearlyDashboardFrames(
        main_df=main_df,
        market_growth_df=market_growth_df,
        mapping_df=mapping_df,
        indicator_metadata_df=indicator_metadata_df,
        agg_rules_df=agg_rules_df,
        agg_rules=agg_rules,
    )


def _build_market_growth_dataframe(
    areas_df: pd.DataFrame,
    market_overnights: pd.DataFrame,
) -> pd.DataFrame | None:
    required_columns = {"area_id", "year", "market", "overnights", "source_column"}
    if market_overnights.empty or not required_columns.issubset(set(market_overnights.columns)):
        return None

    output_area_columns = [column for column in AREA_OUTPUT_COLUMNS if column in areas_df.columns]
    output_base_df = areas_df[output_area_columns].reset_index(drop=True).copy()
    area_ids = areas_df["area_id"].astype(str)

    market_overnights = market_overnights.copy()
    market_overnights["area_id"] = market_overnights["area_id"].astype(str)
    value_columns: dict[str, pd.Series] = {}
    source_columns = market_overnights["source_column"].dropna().astype(str).drop_duplicates().tolist()
    for source_column in source_columns:
        group = market_overnights[market_overnights["source_column"].astype(str) == source_column]
        values_by_area = group.drop_duplicates("area_id", keep="first").set_index("area_id")["overnights"]
        value_columns[source_column] = area_ids.map(values_by_area).reset_index(drop=True)

    return pd.concat([output_base_df, pd.DataFrame(value_columns)], axis=1)
