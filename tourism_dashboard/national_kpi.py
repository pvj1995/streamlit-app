from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from tourism_dashboard.config import (
    NATIONAL_KPI_SHEET_NAME,
    NATIONAL_KPI_XLSX_FILENAME,
)
from tourism_dashboard.paths import BASE_DIR, DATA_DIR, first_existing

NATIONAL_SECTOR_LABELS = {
    "I55": "Nastanitvena dejavnost v celoti (I.55)",
    "I55.10": "Hoteli in podobni obrati (I.55.10)",
    "IR92001": "Gostinska in igralniška dejavnost v celoti (I + R 92 001)",
}
NATIONAL_SECTOR_ORDER = ["I55", "I55.10", "IR92001"]

NATIONAL_MAIN_SECTION = "Kazalniki poslovanja"
NATIONAL_NOMINAL_COMPARISON_SECTION = "Primerjava kazalnikov - 2024/2019 - nominalno"
NATIONAL_REAL_COMPARISON_PREFIX = "Primerjava kazalnikov - 2024/2019 - realno"


def get_national_kpi_path() -> Path:
    return first_existing(
        DATA_DIR / NATIONAL_KPI_XLSX_FILENAME,
        BASE_DIR / NATIONAL_KPI_XLSX_FILENAME,
    )


def normalize_national_sector_id(row: pd.Series) -> str:
    sector_id = str(row.get("sector_id") or "").strip()
    sector_label = str(row.get("sector_label") or "").strip().lower()
    if sector_id == "I55":
        return "I55"
    if sector_id == "I55.10":
        return "I55.10"
    if "skupaj gostinstvo" in sector_label and "igralnic" in sector_label:
        return "IR92001"
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
    df["sector_display_label"] = df["sector_id_norm"].map(NATIONAL_SECTOR_LABELS)
    df = df[df["sector_id_norm"].isin(NATIONAL_SECTOR_ORDER)].copy()
    df = df.dropna(subset=["year", "value", "metric", "section"])
    df["year"] = df["year"].astype(int)
    df["source_order"] = range(len(df))
    return df.reset_index(drop=True)


def get_national_sector_options(df: pd.DataFrame) -> list[str]:
    available_ids = set(df["sector_id_norm"].dropna().unique().tolist())
    return [sector_id for sector_id in NATIONAL_SECTOR_ORDER if sector_id in available_ids]


def comparison_section_name(df: pd.DataFrame, sector_id: str, *, real: bool) -> str | None:
    sections = df[df["sector_id_norm"] == sector_id]["section"].dropna().unique().tolist()
    if real:
        for section in sections:
            if str(section).startswith(NATIONAL_REAL_COMPARISON_PREFIX):
                return str(section)
        return None
    if NATIONAL_NOMINAL_COMPARISON_SECTION in sections:
        return NATIONAL_NOMINAL_COMPARISON_SECTION
    return NATIONAL_MAIN_SECTION if NATIONAL_MAIN_SECTION in sections else None


def sector_rows(df: pd.DataFrame, sector_id: str, section: str | None = None) -> pd.DataFrame:
    rows = df[df["sector_id_norm"] == sector_id].copy()
    if section is not None:
        rows = rows[rows["section"] == section].copy()
    return rows.sort_values("source_order").reset_index(drop=True)
