import streamlit as st

from tourism_dashboard.auth import require_password
from tourism_dashboard.assets import render_page_header
from tourism_dashboard.config import (
    DATA_XLSX_FILENAME,
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
from tourism_dashboard.helpers import (
    find_col,
    find_excel_file,
    load_excel,
    load_geojson_from_upload_or_file,
    load_indicator_groups,
    normalize_name,
)
from tourism_dashboard.maps import get_geojson_name_prop
from tourism_dashboard.models import DashboardContext
from tourism_dashboard.paths import BASE_DIR, DATA_DIR, LOGOS_DIR, first_existing
from tourism_dashboard.ui import render_market_structure, render_view


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


if xlsx_file is not None:
    df = load_excel(xlsx_file)
else:
    default_path = find_excel_file()
    if default_path is None or not default_path.exists():
        st.error(
            f"Ne najdem privzetega Excela: {DATA_XLSX_FILENAME}. "
            "Naloži Excel v stranski vrstici."
        )
        st.stop()
    df = load_excel(default_path)


required_columns = {"Občine", "Turistična regija"}
if not required_columns.issubset(df.columns):
    st.error("V Excelu ne najdem stolpcev 'Občine' in/ali 'Turistična regija'.")
    st.stop()


df = df.copy()
df["__obcina_norm__"] = df["Občine"].apply(normalize_name)

meta_cols = {
    "Občine",
    "Turistična regija",
    "__obcina_norm__",
    "Vodilne destinacije",
    "Perspektivne destinacije",
    "Makro destinacije",
    "SLOVENIJA",
}

default_geojson_path = first_existing(
    DATA_DIR / GEOJSON_FILENAME,
    BASE_DIR / GEOJSON_FILENAME,
)
geojson_obj = load_geojson_from_upload_or_file(geojson_file, default_geojson_path)
geojson_name_prop = get_geojson_name_prop(geojson_obj) if geojson_obj else None

mapping_path = first_existing(
    DATA_DIR / MAPPING_XLSX_FILENAME,
    BASE_DIR / MAPPING_XLSX_FILENAME,
)
grouped_indicators = load_indicator_groups(mapping_path)

market_cols = [column for column in df.columns if str(column).startswith(MARKET_PREFIX)]

views = []
for title, wanted in VIEW_CANDIDATES:
    column = find_col(df, wanted)
    if column is not None:
        views.append((title, column))

if not views:
    st.error("V Excelu ne najdem stolpcev za poglede območij.")
    st.stop()

ctx = DashboardContext(
    df=df,
    geojson_obj=geojson_obj,
    geojson_name_prop=geojson_name_prop,
    grouped_indicators=grouped_indicators,
    market_cols=market_cols,
    dashboard_mode=dashboard_mode,
    meta_cols=meta_cols,
)

tab_kazalniki, tab_trgi = st.tabs(["Kazalniki", "Struktura prenočitev po trgih"])

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
if footer_logo_path.exists():
    st.image(str(footer_logo_path), width=200)

st.caption(FOOTER_SOURCE_TEXT)
st.caption(FOOTER_AUTHOR_TEXT)
st.markdown("---")
