from __future__ import annotations

import os
from typing import Any, cast

import pandas as pd
import streamlit as st

from tourism_dashboard.config import (
    DASHBOARD_DB_CONNECTION_NAME_DEFAULT,
    DASHBOARD_DB_CACHE_TTL_SECONDS,
    DASHBOARD_DB_SCHEMA_VERSION,
    DASHBOARD_MAIN_FRAME_KEY,
    DASHBOARD_MAPPING_FRAME_KEY,
    DASHBOARD_MARKET_GROWTH_FRAME_KEY,
    DATA_BACKEND_DEFAULT,
)


MARKET_METRIC_OVERNIGHTS = "overnights"
MARKET_METRIC_ARRIVALS = "arrivals"
MARKET_METRIC_PDB = "pdb"


def _secret_value(name: str, default: Any = None) -> Any:
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)


def get_data_backend() -> str:
    return str(_secret_value("DATA_BACKEND", DATA_BACKEND_DEFAULT)).strip().lower()


def is_database_backend_enabled() -> bool:
    return get_data_backend() in {"db", "database", "postgres", "postgresql", "supabase"}


def get_dashboard_connection_name() -> str:
    return str(
        _secret_value(
            "DASHBOARD_DB_CONNECTION_NAME",
            DASHBOARD_DB_CONNECTION_NAME_DEFAULT,
        )
    )


def _get_connection(connection_name: str | None = None) -> Any:
    connection_factory = cast(Any, getattr(st, "connection", None))
    if connection_factory is None:
        raise RuntimeError("Streamlit SQL connections are not available.")
    return connection_factory(connection_name or get_dashboard_connection_name(), type="sql")


@st.cache_data(show_spinner=False, ttl=DASHBOARD_DB_CACHE_TTL_SECONDS)
def database_has_dashboard_frames(connection_name: str) -> bool:
    conn = _get_connection(connection_name)
    try:
        table_result = conn.query(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'dashboard_frames'
            ) AS exists
            """,
            ttl=0,
        )
        table_exists = (
            bool(table_result.iloc[0]["exists"])
            if table_result is not None and not table_result.empty
            else False
        )
        if not table_exists:
            return False
        frame_result = conn.query(
            """
            SELECT EXISTS (
                SELECT 1
                FROM dashboard_frames
                WHERE schema_version = :schema_version
                  AND frame_key = :frame_key
            ) AS exists
            """,
            params={
                "schema_version": DASHBOARD_DB_SCHEMA_VERSION,
                "frame_key": DASHBOARD_MAIN_FRAME_KEY,
            },
            ttl=0,
        )
    except Exception:
        return False
    return bool(frame_result.iloc[0]["exists"]) if frame_result is not None and not frame_result.empty else False


@st.cache_data(show_spinner=False, ttl=DASHBOARD_DB_CACHE_TTL_SECONDS)
def load_dashboard_data_signature(connection_name: str) -> str:
    conn = _get_connection(connection_name)
    result = conn.query(
        """
        SELECT COALESCE(
            STRING_AGG(frame_key || ':' || content_hash, '|' ORDER BY frame_key),
            ''
        ) AS signature
        FROM dashboard_frames
        WHERE schema_version = :schema_version
        """,
        params={"schema_version": DASHBOARD_DB_SCHEMA_VERSION},
        ttl=0,
    )
    signature = str(result.iloc[0]["signature"]) if result is not None and not result.empty else ""
    return f"db:{signature}"


@st.cache_data(show_spinner=False, ttl=DASHBOARD_DB_CACHE_TTL_SECONDS)
def load_dashboard_frame(connection_name: str, frame_key: str) -> pd.DataFrame:
    conn = _get_connection(connection_name)
    meta_df = conn.query(
        """
        SELECT row_count
        FROM dashboard_frames
        WHERE frame_key = :frame_key
        LIMIT 1
        """,
        params={"frame_key": frame_key},
        ttl=0,
    )
    if meta_df is None or meta_df.empty:
        return pd.DataFrame()

    row_count = int(meta_df.iloc[0]["row_count"])
    columns_df = conn.query(
        """
        SELECT column_index, column_name
        FROM dashboard_frame_columns
        WHERE frame_key = :frame_key
        ORDER BY column_index
        """,
        params={"frame_key": frame_key},
        ttl=0,
    )
    if columns_df is None or columns_df.empty:
        return pd.DataFrame(index=range(row_count))

    cells_df = conn.query(
        """
        SELECT row_index, column_index, raw_value
        FROM dashboard_frame_cells
        WHERE frame_key = :frame_key
        ORDER BY row_index, column_index
        """,
        params={"frame_key": frame_key},
        ttl=0,
    )
    return _build_frame_from_parts(row_count, columns_df, cells_df)


def _build_frame_from_parts(
    row_count: int,
    columns_df: pd.DataFrame,
    cells_df: pd.DataFrame | None,
) -> pd.DataFrame:
    columns_df = columns_df.sort_values("column_index")
    column_indexes = [int(value) for value in columns_df["column_index"].tolist()]
    column_names = [str(value) for value in columns_df["column_name"].tolist()]
    index = range(row_count)
    if cells_df is None or cells_df.empty:
        return pd.concat(
            [pd.Series([None] * row_count, index=index, name=name) for name in column_names],
            axis=1,
        )

    wide_df = cells_df.pivot(index="row_index", columns="column_index", values="raw_value")
    series_list: list[pd.Series] = []
    for column_index, column_name in zip(column_indexes, column_names):
        if column_index in wide_df.columns:
            series = wide_df[column_index].reindex(index)
        else:
            series = pd.Series([None] * row_count, index=index)
        series.name = column_name
        series_list.append(series)
    return pd.concat(series_list, axis=1)


@st.cache_data(show_spinner=False, ttl=DASHBOARD_DB_CACHE_TTL_SECONDS)
def load_dashboard_frames(connection_name: str, frame_keys: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    if not frame_keys:
        return {}

    conn = _get_connection(connection_name)
    params = {"frame_keys": list(frame_keys)}
    meta_df = conn.query(
        """
        SELECT frame_key, row_count
        FROM dashboard_frames
        WHERE frame_key = ANY(:frame_keys)
        """,
        params=params,
        ttl=0,
    )
    columns_df = conn.query(
        """
        SELECT frame_key, column_index, column_name
        FROM dashboard_frame_columns
        WHERE frame_key = ANY(:frame_keys)
        ORDER BY frame_key, column_index
        """,
        params=params,
        ttl=0,
    )
    cells_df = conn.query(
        """
        SELECT frame_key, row_index, column_index, raw_value
        FROM dashboard_frame_cells
        WHERE frame_key = ANY(:frame_keys)
        ORDER BY frame_key, row_index, column_index
        """,
        params=params,
        ttl=0,
    )

    loaded: dict[str, pd.DataFrame] = {}
    if meta_df is None or meta_df.empty or columns_df is None or columns_df.empty:
        return loaded

    cells_by_frame = (
        {str(key): group.drop(columns=["frame_key"]) for key, group in cells_df.groupby("frame_key")}
        if cells_df is not None and not cells_df.empty
        else {}
    )
    for row in meta_df.itertuples(index=False):
        frame_key = str(getattr(row, "frame_key"))
        frame_columns = columns_df[columns_df["frame_key"] == frame_key].drop(columns=["frame_key"])
        loaded[frame_key] = _build_frame_from_parts(
            row_count=int(getattr(row, "row_count")),
            columns_df=frame_columns,
            cells_df=cells_by_frame.get(frame_key),
        )
    return loaded


def load_main_dataframe_from_db() -> pd.DataFrame:
    return load_dashboard_frame(get_dashboard_connection_name(), DASHBOARD_MAIN_FRAME_KEY)


def load_market_growth_dataframe_from_db() -> pd.DataFrame | None:
    df = load_dashboard_frame(get_dashboard_connection_name(), DASHBOARD_MARKET_GROWTH_FRAME_KEY)
    return None if df.empty else df


def load_indicator_groups_from_db() -> dict[str, list[str]]:
    df_map = load_dashboard_frame(get_dashboard_connection_name(), DASHBOARD_MAPPING_FRAME_KEY)
    if df_map.empty:
        return {}

    groups: dict[str, list[str]] = {}
    for column in df_map.columns:
        series = df_map[column].dropna().astype(str).str.strip()
        values = [value for value in series.tolist() if value]
        if values:
            groups[str(column)] = values
    return groups


@st.cache_data(show_spinner=False, ttl=DASHBOARD_DB_CACHE_TTL_SECONDS)
def _load_market_frame_catalog(connection_name: str, metric: str) -> pd.DataFrame:
    conn = _get_connection(connection_name)
    try:
        return conn.query(
            """
            SELECT frame_key, metric, year, area_level, frame_kind
            FROM dashboard_frames
            WHERE frame_type = 'market_monthly'
              AND metric = :metric
              AND schema_version = :schema_version
            ORDER BY year, area_level, frame_kind
            """,
            params={"metric": metric, "schema_version": DASHBOARD_DB_SCHEMA_VERSION},
            ttl=0,
        )
    except Exception:
        return pd.DataFrame()


def load_market_monthly_data_from_db(metric: str) -> dict[int, dict[str, pd.DataFrame]]:
    connection_name = get_dashboard_connection_name()
    catalog = _load_market_frame_catalog(connection_name, metric)
    loaded: dict[int, dict[str, pd.DataFrame]] = {}
    if catalog.empty:
        return loaded

    frame_keys = tuple(str(value) for value in catalog["frame_key"].tolist())
    frames_by_key = load_dashboard_frames(connection_name, frame_keys)
    for row in catalog.itertuples(index=False):
        frame_kind = getattr(row, "frame_kind", None)
        if frame_kind not in {None, "", "seasonality"}:
            continue
        year = int(getattr(row, "year"))
        area_level = str(getattr(row, "area_level"))
        frame_key = str(getattr(row, "frame_key"))
        df = frames_by_key.get(frame_key, pd.DataFrame())
        if not df.empty:
            loaded.setdefault(year, {})[area_level] = df
    return loaded


def load_market_pdb_data_from_db() -> dict[int, dict[str, dict[str, pd.DataFrame]]]:
    connection_name = get_dashboard_connection_name()
    catalog = _load_market_frame_catalog(connection_name, MARKET_METRIC_PDB)
    loaded: dict[int, dict[str, dict[str, pd.DataFrame]]] = {}
    if catalog.empty:
        return loaded

    frame_keys = tuple(str(value) for value in catalog["frame_key"].tolist())
    frames_by_key = load_dashboard_frames(connection_name, frame_keys)
    for row in catalog.itertuples(index=False):
        frame_kind = str(getattr(row, "frame_kind") or "")
        if frame_kind not in {"seasonality", "annual_avg"}:
            continue
        year = int(getattr(row, "year"))
        area_level = str(getattr(row, "area_level"))
        frame_key = str(getattr(row, "frame_key"))
        df = frames_by_key.get(frame_key, pd.DataFrame())
        if not df.empty:
            loaded.setdefault(year, {}).setdefault(area_level, {})[frame_kind] = df
    return loaded
