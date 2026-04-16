import json
import re
from io import BytesIO
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
        candidates = [
            candidate
            for candidate in directory.glob("*.xlsx")
            if not candidate.name.startswith("~$")
        ]
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


def load_excel(path_or_buffer, sheet_name: int | str = 0) -> pd.DataFrame:
    header_df = pd.read_excel(path_or_buffer, header=0, sheet_name=sheet_name)
    municipality_col = find_col(header_df, ["obcine", "obcina"])
    region_col = find_col(header_df, ["turisticna regija", "turisticne regije", "turisticna"])
    if municipality_col and region_col:
        return header_df

    raw_df = pd.read_excel(path_or_buffer, header=None, sheet_name=sheet_name)
    if raw_df.shape[0] < 2:
        return header_df

    data_df = raw_df.iloc[1:].copy()
    data_df.columns = raw_df.iloc[0].tolist()
    return data_df


@st.cache_data(show_spinner=False)
def load_excel_from_path(path_str: str, sheet_name: int | str = 0) -> pd.DataFrame:
    return load_excel(Path(path_str), sheet_name=sheet_name)


@st.cache_data(show_spinner=False)
def load_excel_from_bytes(raw_bytes: bytes, sheet_name: int | str = 0) -> pd.DataFrame:
    return load_excel(BytesIO(raw_bytes), sheet_name=sheet_name)


def build_numeric_dataframe(df: pd.DataFrame, numeric_columns: list[str]) -> pd.DataFrame:
    numeric_df = df.copy()
    for column in numeric_columns:
        numeric_df[column] = parse_numeric(numeric_df[column])
    return numeric_df


def find_market_overnight_seasonality_files() -> dict[int, Path]:
    files_by_year: dict[int, Path] = {}
    pattern = re.compile(r"sezonskost\s+prenocitev\s+po\s+mesecih\s+in\s+trgih\s*-\s*((?:19|20)\d{2})", re.IGNORECASE)

    for directory in [DATA_DIR, BASE_DIR]:
        if not directory.exists():
            continue
        for candidate in sorted(directory.glob("*.xlsx")):
            if candidate.name.startswith("~$"):
                continue
            normalized_name = strip_diacritics(candidate.name).lower()
            match = pattern.search(normalized_name)
            if not match:
                continue
            files_by_year.setdefault(int(match.group(1)), candidate)

    return files_by_year


def normalize_market_overnight_seasonality_sheet_name(sheet_name: str) -> str | None:
    canonical = canon_col(sheet_name)
    if canonical.startswith("obcine"):
        return "Občine"
    if canonical.startswith(
        (
            "turisticna regija",
            "turisticna regije",
            "turisticne regija",
            "turisticne regije",
        )
    ):
        return "Turistične regije"
    if canonical.startswith("vodilne turisticne destinacije") or canonical.startswith("vodilne destinacije"):
        return "Vodilne destinacije"
    if canonical.startswith("perspektivne turisticne destinacije") or canonical.startswith("perspektivne destinacije"):
        return "Perspektivne destinacije"
    if canonical.startswith("makro turisticne destinacije") or canonical.startswith("makro destinacije"):
        return "Makrodestinacije"
    return None


def _build_market_overnight_seasonality_columns(raw_df: pd.DataFrame) -> list[str]:
    if raw_df.shape[0] < 2:
        return []

    market_header = raw_df.iloc[0]
    month_header = raw_df.iloc[1]
    label_column = safe_str(month_header.iloc[0]).strip() or "Območje"

    columns = ["__label__"]
    current_market = ""
    for idx in range(1, raw_df.shape[1]):
        market_label = safe_str(market_header.iloc[idx]).strip()
        if market_label:
            current_market = market_label

        month_label = safe_str(month_header.iloc[idx]).strip().lower()
        if current_market and month_label:
            columns.append(f"{current_market}__{month_label}")
        else:
            columns.append(f"Unnamed__{idx}")

    columns[0] = label_column
    return columns


@st.cache_data(show_spinner=False)
def load_market_overnight_seasonality_workbook(path_str: str) -> dict[str, pd.DataFrame]:
    path = Path(path_str)
    if not path.exists():
        return {}

    try:
        workbook = pd.ExcelFile(path)
    except Exception:
        return {}

    loaded: dict[str, pd.DataFrame] = {}
    for sheet_name in workbook.sheet_names:
        normalized_sheet_name = normalize_market_overnight_seasonality_sheet_name(sheet_name)
        if normalized_sheet_name is None:
            continue

        raw_df = pd.read_excel(path, sheet_name=sheet_name, header=None)
        columns = _build_market_overnight_seasonality_columns(raw_df)
        if not columns:
            continue

        data_df = raw_df.iloc[2:].copy()
        data_df.columns = columns
        label_column = columns[0]
        data_df = data_df[data_df[label_column].notna()].copy()
        data_df = data_df.rename(columns={label_column: "__label__"})

        numeric_columns = [column for column in data_df.columns if column != "__label__"]
        data_df = build_numeric_dataframe(data_df, numeric_columns)
        loaded[normalized_sheet_name] = data_df

    return loaded


def load_market_overnight_seasonality_data() -> dict[int, dict[str, pd.DataFrame]]:
    loaded: dict[int, dict[str, pd.DataFrame]] = {}
    for year, path in find_market_overnight_seasonality_files().items():
        workbook_data = load_market_overnight_seasonality_workbook(str(path))
        if workbook_data:
            loaded[year] = workbook_data
    return loaded


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
