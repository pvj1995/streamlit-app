from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import streamlit as st

from tourism_dashboard.config import (
    NATIONAL_KPI_INVESTMENTS_SHEET_NAME,
    NATIONAL_KPI_INVESTMENTS_SUMMARY_SHEET_NAME,
    NATIONAL_KPI_MARKET_ANALYSIS_SHEET_NAME,
    NATIONAL_KPI_SHEET_NAME,
    NATIONAL_KPI_XLSX_FILENAME,
)
from tourism_dashboard.paths import BASE_DIR, DATA_DIR, first_existing

NATIONAL_SECTOR_LABELS = {
    "IR92001": "Gostinska in igralniška dejavnost v celoti (I + S 92 001)",
    "I": "Gostinstvo v celoti (I)",
    "I55": "Gostinske nastanitvene dejavnosti (I55)",
    "I55.1": "Hoteli in podobni obrati (I 55.1)",
    "I56": "Dejavnost strežbe jedi in pijač (I 56)",
    "S92001": "Dejavnost igralnic (S 92.001)",
}
NATIONAL_SECTOR_ORDER = ["IR92001", "I", "I55", "I55.1", "I56", "S92001"]

NATIONAL_MAIN_SECTION = "Kazalniki poslovanja"
NATIONAL_REAL_SECTION = "Kazalniki poslovanja - realno"
NATIONAL_DEFAULT_REFERENCE_YEAR = 2019


def get_national_kpi_path() -> Path:
    return first_existing(
        DATA_DIR / NATIONAL_KPI_XLSX_FILENAME,
        BASE_DIR / NATIONAL_KPI_XLSX_FILENAME,
    )


def normalize_national_sector_id(row: pd.Series) -> str:
    sector_id = str(row.get("sector_id") or "").strip()
    sector_label = str(row.get("sector_label") or "").strip().lower()
    sector_id_clean = sector_id.replace(" ", "")
    if sector_id_clean == "I":
        return "I"
    if sector_id_clean == "I55":
        return "I55"
    if sector_id_clean in {"I55.1", "I55.10", "155.1"}:
        return "I55.1"
    if sector_id_clean in {"I56", "I.56"}:
        return "I56"
    if sector_id_clean in {"S92001", "S92.001", "R92.001"}:
        return "S92001"
    if sector_id_clean in {"IR92001", "I+R92.001", "I+S92001", "I+S92.001"}:
        return "IR92001"
    if "skupaj gostinstvo" in sector_label and "igralnic" in sector_label:
        return "IR92001"
    if "gostinska in igralniška" in sector_label:
        return "IR92001"
    if "gostinstvo v celoti" in sector_label:
        return "I"
    if "strežbe" in sector_label or "prodaja hrane" in sector_label:
        return "I56"
    if "igralnic" in sector_label:
        return "S92001"
    if "hotel" in sector_label:
        return "I55.1"
    if "nastanitvene" in sector_label:
        return "I55"
    return sector_id


@st.cache_data(show_spinner=False)
def load_national_business_kpi_data() -> pd.DataFrame:
    db_df = load_national_business_kpi_data_from_db()
    if not db_df.empty:
        return normalize_national_business_kpi_frame(db_df)

    path = get_national_kpi_path()
    if not path.exists():
        return pd.DataFrame()

    raw_df = pd.read_excel(path, sheet_name=NATIONAL_KPI_SHEET_NAME)
    return normalize_national_business_kpi_frame(raw_df)


def load_national_business_kpi_data_from_db() -> pd.DataFrame:
    try:
        from tourism_dashboard.database import (
            database_has_dashboard_frames,
            get_dashboard_connection_name,
            is_database_backend_enabled,
            load_national_kpi_dataframe_from_db,
        )

        connection_name = get_dashboard_connection_name()
        if is_database_backend_enabled() and database_has_dashboard_frames(connection_name):
            return load_national_kpi_dataframe_from_db()
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame()


def normalize_national_business_kpi_frame(raw_df: pd.DataFrame) -> pd.DataFrame:
    required_columns = {
        "sector_id",
        "sector_label",
        "section",
        "metric",
        "year",
        "value",
        "unit",
        "format_type",
        "higher_is_better",
    }
    missing_columns = required_columns.difference(raw_df.columns)
    if missing_columns:
        raise ValueError(
            "Nacionalni KPI Excel nima zahtevanih stolpcev: "
            + ", ".join(sorted(missing_columns))
        )

    df = raw_df.copy()
    for column in ["sector_id", "sector_label", "section", "metric", "unit", "format_type"]:
        df[column] = df[column].astype(str).str.strip()
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["higher_is_better"] = df["higher_is_better"].fillna(True).astype(bool)
    df["sector_id_norm"] = df.apply(normalize_national_sector_id, axis=1)
    df["sector_display_label"] = df["sector_id_norm"].map(NATIONAL_SECTOR_LABELS).fillna(df["sector_label"])
    df = df[df["sector_id_norm"].isin(NATIONAL_SECTOR_ORDER)].copy()
    df = df.dropna(subset=["year", "value", "metric", "section"])
    df["year"] = df["year"].astype(int)
    df["source_order"] = range(len(df))
    return df.reset_index(drop=True)


def get_national_sector_options(df: pd.DataFrame) -> list[str]:
    available_ids = set(df["sector_id_norm"].dropna().unique().tolist())
    return [sector_id for sector_id in NATIONAL_SECTOR_ORDER if sector_id in available_ids]


def sector_rows(df: pd.DataFrame, sector_id: str, section: str | None = None) -> pd.DataFrame:
    rows = df[df["sector_id_norm"] == sector_id].copy()
    if section is not None:
        rows = rows[rows["section"] == section].copy()
    return rows.sort_values("source_order").reset_index(drop=True)


def _load_national_extra_sheet(sheet_name: str) -> pd.DataFrame:
    path = get_national_kpi_path()
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_excel(path, sheet_name=sheet_name)
    except ValueError:
        return pd.DataFrame()


def _load_national_extra_from_db(loader_name: str) -> pd.DataFrame:
    try:
        from tourism_dashboard.database import (
            database_has_dashboard_frames,
            get_dashboard_connection_name,
            is_database_backend_enabled,
        )

        connection_name = get_dashboard_connection_name()
        if not (is_database_backend_enabled() and database_has_dashboard_frames(connection_name)):
            return pd.DataFrame()
        from tourism_dashboard import database as db

        loader = getattr(db, loader_name)
        return loader()
    except Exception:
        return pd.DataFrame()


def _normalize_extra_frame(raw_df: pd.DataFrame, required_columns: set[str]) -> pd.DataFrame:
    if raw_df.empty or required_columns.difference(raw_df.columns):
        return pd.DataFrame()
    df = raw_df.copy()
    for column in df.columns:
        if column in {"section", "category", "metric", "unit", "format_type", "basis"}:
            df[column] = df[column].astype(str).str.strip()
    if "year" in df.columns:
        def normalize_year_value(value: object) -> object:
            if value is None or value is pd.NA:
                return value
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                if math.isnan(value):
                    return value
                numeric = value
            else:
                text_value = str(value).strip()
                try:
                    numeric = float(text_value)
                except ValueError:
                    return text_value
            if numeric.is_integer():
                return int(numeric)
            return numeric

        df["year"] = df["year"].map(normalize_year_value)
    if "value" in df.columns:
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"])
    return df.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_national_i55_market_analysis_data() -> pd.DataFrame:
    db_df = _load_national_extra_from_db("load_national_kpi_market_analysis_dataframe_from_db")
    raw_df = db_df if not db_df.empty else _load_national_extra_sheet(NATIONAL_KPI_MARKET_ANALYSIS_SHEET_NAME)
    return _normalize_extra_frame(
        raw_df,
        {"section", "category", "metric", "year", "value", "unit", "format_type"},
    )


@st.cache_data(show_spinner=False)
def load_national_i55_investments_data() -> pd.DataFrame:
    db_df = _load_national_extra_from_db("load_national_kpi_investments_dataframe_from_db")
    raw_df = db_df if not db_df.empty else _load_national_extra_sheet(NATIONAL_KPI_INVESTMENTS_SHEET_NAME)
    return _normalize_extra_frame(
        raw_df,
        {"section", "metric", "year", "value", "unit", "format_type"},
    )


@st.cache_data(show_spinner=False)
def load_national_i55_investments_summary_data() -> pd.DataFrame:
    db_df = _load_national_extra_from_db("load_national_kpi_investments_summary_dataframe_from_db")
    raw_df = db_df if not db_df.empty else _load_national_extra_sheet(NATIONAL_KPI_INVESTMENTS_SUMMARY_SHEET_NAME)
    return _normalize_extra_frame(
        raw_df,
        {"section", "metric", "basis", "value", "unit", "format_type"},
    )
