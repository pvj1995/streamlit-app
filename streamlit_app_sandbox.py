import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from tourism_dashboard.auth import require_password
from tourism_dashboard.assets import render_page_header
from tourism_dashboard.config import (
    DATA_XLSX_FILENAME,
    DISPLAY_GEOJSON_FILENAME,
    FOOTER_AUTHOR_TEXT,
    FOOTER_LOGO_FILENAME,
    FOOTER_SOURCE_TEXT,
    GEOJSON_FILENAME,
    MAPPING_XLSX_FILENAME,
    MARKET_PREFIX,
    PAGE_TITLE,
    VIEW_CANDIDATES,
    YEAR_NOTE_TEXT,
)
from tourism_dashboard.database import (
    database_has_dashboard_frames,
    get_dashboard_connection_name,
    is_database_backend_enabled,
    load_dashboard_data_signature,
    load_main_dataframe_from_db,
    load_market_growth_dataframe_from_db,
)
from tourism_dashboard.helpers import (
    build_numeric_dataframe,
    find_col,
    find_excel_file,
    load_excel_from_bytes,
    load_excel_from_path,
    load_geojson_from_upload_or_file,
    load_indicator_groups,
    normalize_name,
)
from tourism_dashboard.maps import get_geojson_name_prop
from tourism_dashboard.models import DashboardContext
from tourism_dashboard.paths import BASE_DIR, DATA_DIR, LOGOS_DIR, first_existing
from tourism_dashboard.ui import render_market_structure, render_view

MAIN_SHEET_NAME = "Skupna Tabela"
MARKET_GROWTH_SHEET_NAME = "Rast prenočitev po trgih"


def load_optional_sheet_from_bytes(raw_bytes: bytes, sheet_name: str) -> pd.DataFrame | None:
    try:
        return load_excel_from_bytes(raw_bytes, sheet_name=sheet_name)
    except Exception:
        return None


def load_optional_sheet_from_path(path: Path, sheet_name: str) -> pd.DataFrame | None:
    try:
        return load_excel_from_path(str(path), sheet_name=sheet_name)
    except Exception:
        return None


def build_upload_signature(raw_bytes: bytes) -> str:
    return f"upload:{hashlib.md5(raw_bytes).hexdigest()}"


def build_path_signature(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    stat = path.stat()
    return f"path:{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"


def load_source_dataframes(
    uploaded_file: Any,
    default_path: Path | None,
) -> tuple[str | None, pd.DataFrame | None, pd.DataFrame | None]:
    if uploaded_file is not None:
        raw_bytes = uploaded_file.getvalue()
        signature = build_upload_signature(raw_bytes)
        main_df = load_excel_from_bytes(raw_bytes, sheet_name=MAIN_SHEET_NAME)
        growth_df = load_optional_sheet_from_bytes(raw_bytes, MARKET_GROWTH_SHEET_NAME)
        return signature, main_df, growth_df

    if default_path is None or not default_path.exists():
        return None, None, None

    signature = build_path_signature(default_path)
    main_df = load_excel_from_path(str(default_path), sheet_name=MAIN_SHEET_NAME)
    growth_df = load_optional_sheet_from_path(default_path, MARKET_GROWTH_SHEET_NAME)
    return signature, main_df, growth_df


def is_configured_database_backend_ready() -> bool:
    return (
        is_database_backend_enabled()
        and database_has_dashboard_frames(get_dashboard_connection_name())
    )


def load_configured_source_dataframes(
    uploaded_file: Any,
    default_path: Path | None,
) -> tuple[str | None, pd.DataFrame | None, pd.DataFrame | None]:
    database_backend_requested = is_database_backend_enabled()
    database_connection_name = get_dashboard_connection_name()
    database_backend_ready = (
        database_backend_requested
        and database_has_dashboard_frames(database_connection_name)
    )

    if uploaded_file is None and database_backend_ready:
        return (
            load_dashboard_data_signature(database_connection_name),
            load_main_dataframe_from_db(),
            load_market_growth_dataframe_from_db(),
        )

    if uploaded_file is None and database_backend_requested and not database_backend_ready:
        st.warning(
            "Podatkovna baza je nastavljena, vendar uvoženih tabel nisem našel. "
            "Uporabljam lokalni Excel."
        )

    return load_source_dataframes(uploaded_file, default_path)


def build_data_bundle(
    raw_df: pd.DataFrame,
    raw_market_growth_df: pd.DataFrame | None,
    source_signature: str,
) -> dict[str, Any]:
    df = raw_df.copy()
    df["__obcina_norm__"] = df["Občine"].apply(normalize_name)

    market_growth_numeric_df = None
    if raw_market_growth_df is not None and not raw_market_growth_df.empty:
        market_growth_df = raw_market_growth_df.copy()
        if "Občine" in market_growth_df.columns:
            market_growth_df["__obcina_norm__"] = market_growth_df["Občine"].apply(normalize_name)
        growth_meta_cols = {
            "Občine",
            "__obcina_norm__",
            "Tip območja",
            "SLOVENIJA",
            "Makro destinacije",
            "Perspektivne destinacije",
            "Vodilne destinacije",
            "Turistična regija",
        }
        growth_value_cols = [column for column in market_growth_df.columns if column not in growth_meta_cols]
        market_growth_numeric_df = build_numeric_dataframe(market_growth_df, growth_value_cols)

    views = []
    for title, wanted in VIEW_CANDIDATES:
        column = find_col(df, wanted)
        if column is not None:
            views.append((title, column))

    if not views:
        st.error("V podatkih ne najdem stolpcev za poglede območij.")
        st.stop()

    market_cols = [column for column in df.columns if str(column).startswith(MARKET_PREFIX)]
    meta_cols = {
        "Občine",
        "__obcina_norm__",
        "Tip območja",
        "SLOVENIJA",
        *[column for _, column in views],
    }
    value_cols = [column for column in df.columns if column not in meta_cols]
    indicator_cols = [column for column in value_cols if column not in market_cols]
    numeric_df = build_numeric_dataframe(df, value_cols)

    return {
        "signature": source_signature,
        "df": df,
        "numeric_df": numeric_df,
        "market_growth_numeric_df": market_growth_numeric_df,
        "views": views,
        "market_cols": market_cols,
        "indicator_cols": indicator_cols,
    }


st.set_page_config(
    page_title=PAGE_TITLE,
    layout="wide",
    initial_sidebar_state="collapsed",
)

require_password()

render_page_header()

st.markdown("<hr style='margin-top:20px;margin-bottom:20px;'>", unsafe_allow_html=True)
st.markdown(YEAR_NOTE_TEXT)

with st.sidebar:
    st.header("Nastavitve")
    xlsx_file = st.file_uploader("Naloži Excel (če ne uporabiš privzetega)", type=["xlsx"])
    geojson_file = st.file_uploader("Naloži GeoJSON občin (opcijsko)", type=["json", "geojson"])
    st.divider()
    dashboard_mode = st.checkbox("Dashboard način (več kazalnikov)", value=True)


default_path = find_excel_file()
database_backend_ready = is_configured_database_backend_ready()
if xlsx_file is None and not database_backend_ready and (default_path is None or not default_path.exists()):
    st.error(
        f"Ne najdem privzetega Excela: {DATA_XLSX_FILENAME}. "
        "Naloži Excel v stranski vrstici."
    )
    st.stop()

source_signature, raw_df, raw_market_growth_df = load_configured_source_dataframes(
    xlsx_file,
    default_path,
)

if raw_df is None or source_signature is None:
    st.error("Podatkov ni bilo mogoče naložiti.")
    st.stop()


required_columns = {"Občine", "Turistična regija"}
if not required_columns.issubset(raw_df.columns):
    st.error("V podatkih ne najdem stolpcev 'Občine' in/ali 'Turistična regija'.")
    st.stop()

data_bundle_key = "_dashboard_data_bundle"
cached_bundle = st.session_state.get(data_bundle_key)
if cached_bundle is None or cached_bundle.get("signature") != source_signature:
    cached_bundle = build_data_bundle(raw_df, raw_market_growth_df, source_signature)
    st.session_state[data_bundle_key] = cached_bundle

df = cached_bundle["df"]
numeric_df = cached_bundle["numeric_df"]
market_growth_numeric_df = cached_bundle["market_growth_numeric_df"]
views = cached_bundle["views"]
market_cols = cached_bundle["market_cols"]
indicator_cols = cached_bundle["indicator_cols"]

default_geojson_path = first_existing(
    DATA_DIR / DISPLAY_GEOJSON_FILENAME,
    BASE_DIR / DISPLAY_GEOJSON_FILENAME,
    DATA_DIR / GEOJSON_FILENAME,
    BASE_DIR / GEOJSON_FILENAME,
)
geojson_obj = load_geojson_from_upload_or_file(geojson_file, default_geojson_path)
geojson_signature = (
    build_upload_signature(geojson_file.getvalue())
    if geojson_file is not None
    else build_path_signature(default_geojson_path)
)
geojson_prepared = (
    geojson_file is None
    and default_geojson_path is not None
    and default_geojson_path.name == DISPLAY_GEOJSON_FILENAME
)
geojson_name_prop = get_geojson_name_prop(geojson_obj) if geojson_obj else None

mapping_path = first_existing(
    DATA_DIR / MAPPING_XLSX_FILENAME,
    BASE_DIR / MAPPING_XLSX_FILENAME,
)
grouped_indicators = load_indicator_groups(mapping_path)

ctx = DashboardContext(
    data_signature=source_signature,
    df=df,
    numeric_df=numeric_df,
    market_growth_numeric_df=market_growth_numeric_df,
    geojson_obj=geojson_obj,
    geojson_signature=geojson_signature,
    geojson_prepared=geojson_prepared,
    geojson_name_prop=geojson_name_prop,
    grouped_indicators=grouped_indicators,
    market_cols=market_cols,
    indicator_cols=indicator_cols,
    dashboard_mode=dashboard_mode,
)

tab_kazalniki, tab_trgi = st.tabs(["Kazalniki", "Turistični promet in sezonskost po trgih"])

with tab_kazalniki:
    view_labels = [view[0] for view in views]
    selected_view_label = st.selectbox("Pogled", view_labels, index=0, key="view_main")
    view_title, group_col = next(view for view in views if view[0] == selected_view_label)
    render_view(view_title, group_col, ctx)

with tab_trgi:
    view_labels = [view[0] for view in views] + ["SLOVENIJA"]
    selected_view_label = st.selectbox("Pogled", view_labels, index=0, key="view_trgi")
    if selected_view_label == "SLOVENIJA":
        view_title, group_col = "SLOVENIJA", "SLOVENIJA"
    else:
        view_title, group_col = next(view for view in views if view[0] == selected_view_label)
    render_market_structure(view_title, group_col, ctx)

footer_logo_path = first_existing(
    LOGOS_DIR / FOOTER_LOGO_FILENAME,
    BASE_DIR / FOOTER_LOGO_FILENAME,
)

st.markdown("---")

if footer_logo_path.exists():
    st.image(str(footer_logo_path), width=400)

st.caption(FOOTER_SOURCE_TEXT)
st.caption(FOOTER_AUTHOR_TEXT)

