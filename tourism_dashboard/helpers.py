import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from tourism_dashboard.config import DATA_XLSX_FILENAME
from tourism_dashboard.paths import BASE_DIR, DATA_DIR, first_existing


try:
    from sqlalchemy import text as sql_text
except Exception:
    sql_text = None


def find_excel_file() -> Path | None:
    default_path = first_existing(
        DATA_DIR / DATA_XLSX_FILENAME,
        BASE_DIR / DATA_XLSX_FILENAME,
    )
    if default_path.exists():
        return default_path

    search_dirs = [DATA_DIR, BASE_DIR]
    for directory in search_dirs:
        candidates = list(directory.glob("*.xlsx"))
        if not candidates:
            continue
        for candidate in candidates:
            name = candidate.name.lower()
            if "skupna" in name and "tabela" in name:
                return candidate
        return candidates[0]
    return None


def safe_str(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return str(value)


def normalize_name(value: str) -> str:
    normalized = safe_str(value).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = (
        normalized
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("–", "-")
        .replace("—", "-")
    )
    normalized = re.sub(r"\s*-\s*", " - ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def strip_diacritics(value: str) -> str:
    return (
        value.replace("č", "c")
        .replace("š", "s")
        .replace("ž", "z")
        .replace("Č", "C")
        .replace("Š", "S")
        .replace("Ž", "Z")
    )


def canon_col(value: str) -> str:
    normalized = normalize_name(value)
    normalized = strip_diacritics(normalized).lower()
    normalized = re.sub(r"[^a-z0-9 ]+", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def find_col(df: pd.DataFrame, wanted: list[str]) -> str | None:
    mapping = {canon_col(column): column for column in df.columns}
    for item in wanted:
        if item in mapping:
            return mapping[item]
    for canonical_name, original_name in mapping.items():
        for item in wanted:
            if item in canonical_name:
                return original_name
    return None


def parse_numeric(series: pd.Series) -> pd.Series:
    normalized = series.astype(str).str.strip()
    normalized = normalized.replace({"nan": "", "None": ""})
    normalized = normalized.str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False)

    def convert(value):
        if value == "" or value == "-" or str(value).lower() == "nan":
            return np.nan
        cleaned = re.sub(r"[^0-9\-,\.]", "", str(value))
        if "," in cleaned and cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "")
            cleaned = cleaned.replace(",", ".")
        else:
            parts = cleaned.split(".")
            if len(parts) > 2:
                cleaned = cleaned.replace(".", "")
            cleaned = cleaned.replace(",", "")
        try:
            return float(cleaned)
        except Exception:
            return np.nan

    return normalized.apply(convert)


def shorten_label(value: str, max_len: int = 22) -> str:
    text = str(value).strip()
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def col_for_year(col_name: str, year: int) -> str:
    return re.sub(r"(19|20)\d{2}", str(year), col_name)


def load_excel(path_or_buffer) -> pd.DataFrame:
    header_df = pd.read_excel(path_or_buffer, header=0)
    municipality_col = find_col(header_df, ["obcine", "obcina"])
    region_col = find_col(header_df, ["turisticna regija", "turisticne regije", "turisticna"])
    if municipality_col and region_col:
        return header_df

    raw_df = pd.read_excel(path_or_buffer, header=None)
    if raw_df.shape[0] < 2:
        return header_df

    data_df = raw_df.iloc[1:].copy()
    data_df.columns = raw_df.iloc[0].tolist()
    return data_df


def try_load_geojson(path: Path):
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def load_indicator_groups(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    try:
        df_map = pd.read_excel(path)
    except Exception:
        return {}

    groups: dict[str, list[str]] = {}
    for column in df_map.columns:
        series = df_map[column].dropna().astype(str).str.strip()
        values = [value for value in series.tolist() if value]
        if values:
            groups[column] = values
    return groups


@st.cache_data(show_spinner=False)
def load_geojson_from_upload_or_file(uploaded, default_path: Path):
    if uploaded is not None:
        return json.load(uploaded)
    return try_load_geojson(default_path)


def get_secret_value(name: str, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return default


def sql(stmt: str):
    return sql_text(stmt) if sql_text is not None else stmt
