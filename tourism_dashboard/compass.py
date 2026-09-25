from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from tourism_dashboard.config import COMPASS_INDEX_SHEETS, COMPASS_INDEX_XLSX_FILENAME
from tourism_dashboard.helpers import normalize_name
from tourism_dashboard.paths import BASE_DIR, DATA_DIR, first_existing


COMPASS_DEFAULT_COLOR_SCALE = ["#dbeafe", "#93c5fd", "#2563eb", "#1e40af"]


def get_compass_index_path() -> Path:
    return first_existing(
        DATA_DIR / COMPASS_INDEX_XLSX_FILENAME,
        BASE_DIR / COMPASS_INDEX_XLSX_FILENAME,
    )


def _path_signature(path: Path) -> str:
    stat = path.stat()
    return f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"


@st.cache_data(show_spinner=False)
def load_compass_workbook_from_path(
    path_str: str,
    path_signature: str,
) -> dict[str, pd.DataFrame]:
    del path_signature  # Included in the cache key so changed workbooks are reloaded.
    path = Path(path_str)
    return pd.read_excel(path, sheet_name=COMPASS_INDEX_SHEETS)


def load_compass_workbook_from_db() -> dict[str, pd.DataFrame]:
    try:
        from tourism_dashboard.database import (
            database_has_dashboard_frames,
            get_dashboard_connection_name,
            is_database_backend_enabled,
            load_compass_dataframe_from_db,
            load_dashboard_data_signature,
        )

        connection_name = get_dashboard_connection_name()
        if not is_database_backend_enabled() or not database_has_dashboard_frames(connection_name):
            return {}

        data_signature = load_dashboard_data_signature(connection_name)
        frames = {
            sheet: load_compass_dataframe_from_db(sheet, data_signature=data_signature)
            for sheet in COMPASS_INDEX_SHEETS
        }
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
    frames = load_compass_workbook_from_path(str(path), _path_signature(path))
    return normalize_compass_frames(frames)


def _normalize_boolean_series(series: pd.Series) -> pd.Series:
    normalized = series.astype(str).str.strip().str.lower()
    return normalized.isin({"true", "1", "yes", "da"})


def normalize_compass_frames(frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    normalized = {key: frame.copy() for key, frame in frames.items()}

    numeric_columns = {
        "compass_datasets": ("index_year",),
        "compass_values": ("index_year", "value"),
        "compass_metrics": ("display_order", "decimal_places", "max_points"),
        "compass_area_levels": ("display_order",),
        "compass_areas": ("display_order",),
        "compass_area_years": ("index_year", "municipality_count"),
        "compass_memberships": ("valid_from_year", "valid_to_year"),
        "compass_explanation": ("display_order",),
    }
    for sheet_name, columns in numeric_columns.items():
        frame = normalized.get(sheet_name)
        if frame is None:
            continue
        for column in columns:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

    boolean_columns = {
        "compass_datasets": ("is_active",),
        "compass_metrics": ("higher_is_better",),
        "compass_area_levels": ("map_enabled",),
    }
    for sheet_name, columns in boolean_columns.items():
        frame = normalized.get(sheet_name)
        if frame is None:
            continue
        for column in columns:
            if column in frame.columns:
                frame[column] = _normalize_boolean_series(frame[column])

    return normalized


def compass_data_signature(frames: dict[str, pd.DataFrame]) -> str:
    digest = hashlib.sha256()
    for sheet_name in ("compass_datasets", "compass_values", "compass_memberships"):
        frame = frames.get(sheet_name, pd.DataFrame())
        digest.update(sheet_name.encode("utf-8"))
        digest.update(str(frame.shape).encode("utf-8"))
        if not frame.empty:
            frame_hashes = pd.util.hash_pandas_object(frame, index=True).to_numpy(
                dtype="uint64",
                copy=False,
            )
            digest.update(frame_hashes.tobytes())
    return digest.hexdigest()[:20]


def available_compass_years(frames: dict[str, pd.DataFrame]) -> list[int]:
    datasets = frames.get("compass_datasets", pd.DataFrame())
    if not datasets.empty and "index_year" in datasets.columns:
        years = pd.to_numeric(datasets["index_year"], errors="coerce").dropna()
    else:
        values = frames.get("compass_values", pd.DataFrame())
        years = pd.to_numeric(values.get("index_year", pd.Series(dtype=float)), errors="coerce").dropna()
    return sorted({int(year) for year in years.tolist()})


def resolve_compass_dataset_id(frames: dict[str, pd.DataFrame], index_year: int) -> str | None:
    datasets = frames.get("compass_datasets", pd.DataFrame())
    if not datasets.empty and {"dataset_id", "index_year"}.issubset(datasets.columns):
        candidates = datasets[datasets["index_year"] == index_year].copy()
        if not candidates.empty:
            if "is_active" in candidates.columns and candidates["is_active"].any():
                candidates = candidates[candidates["is_active"]]
            return str(candidates.iloc[-1]["dataset_id"])

    values = frames.get("compass_values", pd.DataFrame())
    if values.empty:
        return None
    candidates = values[values["index_year"] == index_year]["dataset_id"].dropna().astype(str)
    return str(candidates.iloc[-1]) if not candidates.empty else None


def build_compass_results(
    *,
    frames: dict[str, pd.DataFrame],
    area_level_id: str,
    metric_id: str,
    index_year: int,
) -> pd.DataFrame:
    values = frames["compass_values"]
    areas = frames["compass_areas"]
    area_years = frames["compass_area_years"]
    metrics = frames["compass_metrics"]
    dataset_id = resolve_compass_dataset_id(frames, index_year)
    if dataset_id is None:
        return pd.DataFrame()

    selected = values[
        (values["dataset_id"].astype(str) == dataset_id)
        & (values["index_year"] == index_year)
        & (values["area_level_id"].astype(str) == area_level_id)
        & (values["metric_id"].astype(str) == metric_id)
    ][["area_id", "value"]].copy()
    if selected.empty:
        return selected

    selected["area_id"] = selected["area_id"].astype(str)
    selected["value"] = pd.to_numeric(selected["value"], errors="coerce")
    area_lookup = areas[["area_id", "area_name"]].copy()
    area_lookup["area_id"] = area_lookup["area_id"].astype(str)
    selected = selected.merge(area_lookup, on="area_id", how="left", validate="one_to_one")

    counts = area_years[
        (area_years["dataset_id"].astype(str) == dataset_id)
        & (area_years["index_year"] == index_year)
    ][["area_id", "municipality_count"]].copy()
    counts["area_id"] = counts["area_id"].astype(str)
    selected = selected.merge(counts, on="area_id", how="left", validate="one_to_one")
    selected = selected.dropna(subset=["area_name", "value"])
    if selected.empty:
        return selected

    metric_rows = metrics[metrics["metric_id"].astype(str) == metric_id]
    higher_is_better = True if metric_rows.empty else bool(metric_rows.iloc[0]["higher_is_better"])
    selected["rank"] = selected["value"].rank(
        method="min",
        ascending=not higher_is_better,
    ).astype(int)
    selected = selected.sort_values(
        ["rank", "area_name"],
        ascending=[True, True],
    ).reset_index(drop=True)
    selected["municipality_count"] = (
        pd.to_numeric(selected["municipality_count"], errors="coerce").fillna(0).astype(int)
    )
    selected["rank_label"] = selected["rank"].astype(str) + ". " + selected["area_name"].astype(str)
    return selected[
        ["area_id", "area_name", "value", "municipality_count", "rank", "rank_label"]
    ]


def build_compass_area_maps(
    frames: dict[str, pd.DataFrame],
    area_level_id: str,
    result_df: pd.DataFrame,
    *,
    index_year: int,
) -> tuple[set[str], dict[str, float], dict[str, str], dict[str, float]]:
    memberships = frames["compass_memberships"].copy()
    valid_from = pd.to_numeric(memberships["valid_from_year"], errors="coerce")
    valid_to = pd.to_numeric(memberships["valid_to_year"], errors="coerce")
    memberships = memberships[
        (memberships["area_level_id"].astype(str) == area_level_id)
        & valid_from.le(index_year)
        & (valid_to.isna() | valid_to.ge(index_year))
    ].copy()
    if memberships.empty or result_df.empty:
        return set(), {}, {}, {}

    memberships = memberships.sort_values("valid_from_year").drop_duplicates(
        subset=["municipality_area_id", "area_level_id"],
        keep="last",
    )
    value_by_area_id = {
        str(area_id): float(value)
        for area_id, value in zip(result_df["area_id"], result_df["value"])
        if pd.notna(value)
    }
    memberships = memberships[memberships["area_id"].astype(str).isin(value_by_area_id)].copy()
    memberships["municipality_norm"] = memberships["municipality_name"].map(normalize_name)
    memberships["area_name"] = memberships["area_name"].astype(str).map(normalize_name)
    memberships["area_value"] = memberships["area_id"].astype(str).map(value_by_area_id)

    municipality_to_value = dict(zip(memberships["municipality_norm"], memberships["area_value"]))
    municipality_to_area = dict(zip(memberships["municipality_norm"], memberships["area_name"]))
    area_to_value = {
        normalize_name(str(area_name)): float(value)
        for area_name, value in zip(result_df["area_name"], result_df["value"])
        if pd.notna(value)
    }
    return set(municipality_to_area), municipality_to_value, municipality_to_area, area_to_value


def compass_metric_color_scale(metric: pd.Series) -> list[str]:
    colors = []
    for column in ("color_scale_1", "color_scale_2", "color_scale_3", "color_scale_4"):
        value: Any = metric.get(column)
        if pd.notna(value) and str(value).strip():
            colors.append(str(value).strip())
    return colors if len(colors) >= 2 else COMPASS_DEFAULT_COLOR_SCALE


def compass_metric_decimal_places(metric: pd.Series) -> int:
    value: Any = metric.get("decimal_places", 1)
    if isinstance(value, (int, float)) and pd.notna(value):
        return max(0, int(value))
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return 1
