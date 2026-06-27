from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st

from tourism_dashboard.config import COMPASS_INDEX_SHEETS, COMPASS_INDEX_XLSX_FILENAME
from tourism_dashboard.helpers import normalize_name
from tourism_dashboard.paths import BASE_DIR, DATA_DIR, first_existing


COMPASS_AREA_COLUMN_MAP = {
    "Občine": "municipality_name",
    "Vodilne destinacije": "leading_destination",
    "Perspektivne destinacije": "perspective_destination",
    "Turistične regije": "tourism_region",
    "Kohezijske regije": "cohesion_region",
    "Makro destinacije": "macro_destination",
    "Slovenija": "slovenia",
}
COMPASS_COHESION_AREA_LEVEL = "Kohezijske regije"
COMPASS_COHESION_COLUMN = "cohesion_region"
COMPASS_COHESION_DISPLAY_ORDER = 5
COMPASS_TOURISM_REGION_TO_COHESION = {
    "Dolenjska, Bela Krajina in Kočevsko": "Vzhodna Slovenija",
    "Goriško, Vipava, Kras": "Zahodna Slovenija",
    "Julijske Alpe": "Zahodna Slovenija",
    "Ljubljana in osrednja Slovenija": "Zahodna Slovenija",
    "Pomurje": "Vzhodna Slovenija",
    "Posavje": "Vzhodna Slovenija",
    "Predalpska Slovenija (Vzh.Gorenjska)": "Zahodna Slovenija",
    "Savinjsko, Celje, Obsotelje in Kozjansko": "Vzhodna Slovenija",
    "Slovenska Istra": "Zahodna Slovenija",
    "Zgornje Savinjska, Šaleška in Koroška": "Vzhodna Slovenija",
    "Štajerska (Maribor, Pohorje, Ptuj)": "Vzhodna Slovenija",
}


def get_compass_index_path() -> Path:
    return first_existing(
        DATA_DIR / COMPASS_INDEX_XLSX_FILENAME,
        BASE_DIR / COMPASS_INDEX_XLSX_FILENAME,
    )


@st.cache_data(show_spinner=False)
def load_compass_workbook_from_path(path_str: str) -> dict[str, pd.DataFrame]:
    path = Path(path_str)
    return {sheet: pd.read_excel(path, sheet_name=sheet) for sheet in COMPASS_INDEX_SHEETS}


def load_compass_workbook_from_db() -> dict[str, pd.DataFrame]:
    try:
        from tourism_dashboard.database import (
            database_has_dashboard_frames,
            get_dashboard_connection_name,
            is_database_backend_enabled,
            load_compass_dataframe_from_db,
        )

        connection_name = get_dashboard_connection_name()
        if not is_database_backend_enabled() or not database_has_dashboard_frames(connection_name):
            return {}

        frames = {sheet: load_compass_dataframe_from_db(sheet) for sheet in COMPASS_INDEX_SHEETS}
        if all(not frame.empty for frame in frames.values()):
            return frames
    except Exception:
        return {}
    return {}


def load_compass_workbook() -> dict[str, pd.DataFrame]:
    db_frames = load_compass_workbook_from_db()
    if db_frames:
        return normalize_compass_frames(db_frames)

    path = get_compass_index_path()
    if not path.exists():
        return {}
    return normalize_compass_frames(load_compass_workbook_from_path(str(path)))


def normalize_compass_frames(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    normalized = {key: frame.copy() for key, frame in frames.items()}
    if "compass_area_mapping" in normalized:
        area_mapping = normalized["compass_area_mapping"]
        area_mapping["municipality_name"] = area_mapping["municipality_name"].astype(str).map(normalize_name)
        area_mapping["municipality_norm"] = area_mapping["municipality_name"].map(normalize_name)
        area_mapping = add_compass_cohesion_mapping(area_mapping)
        normalized["compass_area_mapping"] = area_mapping
    if "compass_area_levels" in normalized:
        normalized["compass_area_levels"] = add_compass_cohesion_area_level(normalized["compass_area_levels"])
    if "compass_values_long" in normalized:
        values = normalized["compass_values_long"]
        values["value"] = pd.to_numeric(values["value"], errors="coerce")
        for column in ("index_year", "source_year", "reference_year", "comparison_year"):
            if column in values.columns:
                values[column] = pd.to_numeric(values[column], errors="coerce")
        normalized["compass_values_long"] = values
    return normalized


def add_compass_cohesion_mapping(area_mapping: pd.DataFrame) -> pd.DataFrame:
    if "tourism_region" not in area_mapping.columns:
        return area_mapping

    area_mapping = area_mapping.copy()
    tourism_regions = area_mapping["tourism_region"].astype(str).map(normalize_name)
    derived_cohesion = tourism_regions.map(COMPASS_TOURISM_REGION_TO_COHESION)

    if COMPASS_COHESION_COLUMN not in area_mapping.columns:
        area_mapping[COMPASS_COHESION_COLUMN] = derived_cohesion
    else:
        current = area_mapping[COMPASS_COHESION_COLUMN]
        blank_mask = current.isna() | current.astype(str).str.strip().eq("")
        area_mapping.loc[blank_mask, COMPASS_COHESION_COLUMN] = derived_cohesion.loc[blank_mask]
        area_mapping[COMPASS_COHESION_COLUMN] = area_mapping[COMPASS_COHESION_COLUMN].astype(str).map(normalize_name)
    return area_mapping


def add_compass_cohesion_area_level(area_levels: pd.DataFrame) -> pd.DataFrame:
    if area_levels.empty or "area_level" not in area_levels.columns:
        return area_levels

    area_levels = area_levels.copy()
    if area_levels["area_level"].astype(str).eq(COMPASS_COHESION_AREA_LEVEL).any():
        return area_levels

    if "display_order" in area_levels.columns:
        display_order = pd.to_numeric(area_levels["display_order"], errors="coerce")
        area_levels.loc[display_order >= COMPASS_COHESION_DISPLAY_ORDER, "display_order"] = display_order + 1

    new_row = {
        "area_level_id": "cohesion_regions",
        "area_level": COMPASS_COHESION_AREA_LEVEL,
        "source_area_column": "Kohezijska regija",
        "display_order": COMPASS_COHESION_DISPLAY_ORDER,
        "include_map": True,
        "notes": "Agregirano iz občin v kohezijski regiji.",
    }
    for column in area_levels.columns:
        new_row.setdefault(column, "")
    return pd.concat([area_levels, pd.DataFrame([new_row])], ignore_index=True)


def format_compass_metric_label(metric: pd.Series, *, source_year: int | None, reference_year: int | None) -> str:
    template = str(metric.get("display_name_template") or "{metric_name}")
    values = {
        "metric_name": str(metric.get("metric_name") or ""),
        "source_year": source_year or "",
        "reference_year": reference_year or "",
    }
    try:
        return template.format(**values).strip()
    except Exception:
        return values["metric_name"]


def resolve_weight_year(policy: str, source_year: int | None, reference_year: int | None, comparison_year: int | None) -> int | None:
    if policy == "static":
        return None
    if policy == "reference_year_for_growth_else_source_year" and comparison_year is not None:
        return reference_year
    return source_year


def render_weight_column_template(template: str, year: int | None) -> str:
    if "{year}" in template:
        return template.format(year=year or "")
    return template


def normalized_column_lookup(df: pd.DataFrame) -> dict[str, str]:
    return {normalize_column_name(column): str(column) for column in df.columns}


def normalize_column_name(value: Any) -> str:
    text = normalize_name(str(value)).lower()
    text = text.replace("č", "c").replace("š", "s").replace("ž", "z")
    text = re.sub(r"[^a-z0-9{}]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_weight_column(main_df: pd.DataFrame, template: str, year: int | None) -> str | None:
    candidate = render_weight_column_template(template, year)
    if candidate in main_df.columns:
        return candidate
    lookup = normalized_column_lookup(main_df)
    normalized_candidate = normalize_column_name(candidate)
    if normalized_candidate in lookup:
        return lookup[normalized_candidate]
    if "{year}" not in template:
        return None
    static_candidate = normalize_column_name(template.replace("{year}", "").strip())
    return lookup.get(static_candidate)


def get_metric_year_context(values: pd.DataFrame, metric_id: str, index_year: int) -> tuple[int | None, int | None, int | None]:
    metric_values = values[(values["metric_id"] == metric_id) & (values["index_year"] == index_year)]
    if metric_values.empty:
        return index_year, index_year, None
    row = metric_values.iloc[0]
    source_year = int(row["source_year"]) if pd.notna(row.get("source_year")) else index_year
    reference_year = int(row["reference_year"]) if pd.notna(row.get("reference_year")) else source_year
    comparison_year = int(row["comparison_year"]) if pd.notna(row.get("comparison_year")) else None
    return source_year, reference_year, comparison_year


def aggregate_compass_results(
    *,
    frames: dict[str, pd.DataFrame],
    main_df: pd.DataFrame,
    area_level: str,
    metric_id: str,
    index_year: int,
) -> pd.DataFrame:
    values = frames["compass_values_long"]
    area_mapping = frames["compass_area_mapping"]
    metrics = frames["compass_metrics"].set_index("metric_id")
    rules = frames["compass_aggregation_rules"].set_index("metric_id")
    weight_rules = frames["compass_weight_rules"].set_index("weight_metric_id")
    components = frames["compass_metric_components"]
    children_by_parent = {
        parent_id: group.sort_values("display_order")["child_metric_id"].astype(str).tolist()
        for parent_id, group in components.groupby("parent_metric_id", sort=False)
    }

    if area_level not in COMPASS_AREA_COLUMN_MAP:
        return pd.DataFrame(columns=["area_name", "value", "rank", "rank_label", "municipality_count"])

    area_column = COMPASS_AREA_COLUMN_MAP[area_level]
    source_year, reference_year, comparison_year = get_metric_year_context(values, metric_id, index_year)
    value_pivot = (
        values[values["index_year"] == index_year]
        .pivot_table(index="area_key", columns="metric_id", values="value", aggfunc="first")
    )

    area_df = area_mapping.copy()
    area_df["area_name"] = area_df[area_column] if area_column in area_df.columns else np.nan
    area_df = area_df[area_df["area_name"].notna()].copy()
    area_df["area_name"] = area_df["area_name"].astype(str).map(normalize_name)
    area_df = area_df.join(value_pivot, on="municipality_key")

    main_weights = main_df.copy()
    if "__obcina_norm__" not in main_weights.columns and "Občine" in main_weights.columns:
        main_weights["__obcina_norm__"] = main_weights["Občine"].map(normalize_name)
    main_weights = main_weights.set_index("__obcina_norm__", drop=False)

    def metric_value_for_area(group_df: pd.DataFrame, selected_metric_id: str) -> float:
        rule = str(rules.at[selected_metric_id, "aggregation_method"]) if selected_metric_id in rules.index else "weighted_mean"
        if rule == "component_sum":
            child_values = []
            for child_metric_id in children_by_parent.get(selected_metric_id, []):
                component_weight = components[
                    (components["parent_metric_id"] == selected_metric_id)
                    & (components["child_metric_id"] == child_metric_id)
                ]["component_weight"].iloc[0]
                child_value = metric_value_for_area(group_df, child_metric_id)
                if pd.notna(child_value):
                    child_values.append(float(component_weight) * float(child_value))
            return float(np.nansum(child_values)) if child_values else np.nan

        if selected_metric_id not in group_df.columns:
            return np.nan

        metric_values = pd.to_numeric(group_df[selected_metric_id], errors="coerce")
        if area_level == "Občine":
            return float(metric_values.iloc[0]) if len(metric_values) and pd.notna(metric_values.iloc[0]) else np.nan

        weight_metric_id = rules.at[selected_metric_id, "weight_metric_id"] if selected_metric_id in rules.index else None
        if pd.isna(weight_metric_id) or str(weight_metric_id).strip() == "" or str(weight_metric_id) not in weight_rules.index:
            return float(metric_values.mean(skipna=True)) if metric_values.notna().any() else np.nan

        weight_rule = weight_rules.loc[str(weight_metric_id)]
        weight_year = resolve_weight_year(
            str(weight_rule.get("weight_year_policy") or ""),
            source_year,
            reference_year,
            comparison_year,
        )
        weight_column = find_weight_column(main_weights, str(weight_rule.get("source_column_template") or ""), weight_year)
        if weight_column is None:
            return float(metric_values.mean(skipna=True)) if metric_values.notna().any() else np.nan

        weights = group_df["municipality_norm"].map(main_weights[weight_column])
        weights = pd.to_numeric(weights, errors="coerce")
        mask = metric_values.notna() & weights.notna() & (weights > 0)
        if mask.any():
            return float(np.average(metric_values[mask], weights=weights[mask]))
        return float(metric_values.mean(skipna=True)) if metric_values.notna().any() else np.nan

    rows = []
    for area_name, group_df in area_df.groupby("area_name", sort=True):
        rows.append(
            {
                "area_name": area_name,
                "value": metric_value_for_area(group_df, metric_id),
                "municipality_count": int(group_df["municipality_key"].nunique()),
            }
        )
    result = pd.DataFrame(rows).dropna(subset=["value"])
    if result.empty:
        return result
    ascending = str(rules.at[metric_id, "rank_direction"]) == "asc" if metric_id in rules.index else False
    result = result.sort_values("value", ascending=ascending).reset_index(drop=True)
    result["rank"] = result["value"].rank(method="min", ascending=ascending).astype(int)
    result = result.sort_values("rank").reset_index(drop=True)
    result["rank_label"] = result["rank"].astype(str) + ". " + result["area_name"].astype(str)
    if metric_id in metrics.index:
        result["metric_name"] = metrics.at[metric_id, "metric_name"]
    return result


def build_compass_municipality_maps(
    frames: dict[str, pd.DataFrame],
    area_level: str,
    result_df: pd.DataFrame,
) -> tuple[set[str], dict[str, float], dict[str, str]]:
    area_mapping = frames["compass_area_mapping"].copy()
    area_column = COMPASS_AREA_COLUMN_MAP.get(area_level, "municipality_name")
    area_mapping["area_name"] = area_mapping[area_column] if area_column in area_mapping.columns else np.nan
    area_mapping = area_mapping[area_mapping["area_name"].notna()].copy()
    area_mapping["area_name"] = area_mapping["area_name"].astype(str).map(normalize_name)
    area_mapping["municipality_norm"] = area_mapping["municipality_name"].map(normalize_name)

    value_by_area = dict(zip(result_df["area_name"], result_df["value"]))
    municipality_to_area = dict(zip(area_mapping["municipality_norm"], area_mapping["area_name"]))
    municipality_to_value = {
        municipality: float(value_by_area.get(area_name, np.nan))
        for municipality, area_name in municipality_to_area.items()
    }
    return set(municipality_to_area.keys()), municipality_to_value, municipality_to_area


def build_compass_area_maps(
    frames: dict[str, pd.DataFrame],
    area_level: str,
    result_df: pd.DataFrame,
) -> tuple[set[str], dict[str, float], dict[str, str], dict[str, float]]:
    municipalities, municipality_to_value, municipality_to_area = build_compass_municipality_maps(
        frames,
        area_level,
        result_df,
    )
    area_to_value = {
        str(area_name): float(value)
        for area_name, value in zip(result_df["area_name"], result_df["value"])
        if pd.notna(value)
    }
    return municipalities, municipality_to_value, municipality_to_area, area_to_value
