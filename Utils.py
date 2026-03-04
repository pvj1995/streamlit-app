import json
import re
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st

try:
    import folium
except Exception:
    folium = None

try:
    import geopandas as gpd
except Exception:
    gpd = None

DATA_XLSX_DEFAULT = "Skupna tabela občine.xlsx"
SLO_BOUNDS = [[41.00, 10.38], [49.88, 18.61]]

def find_excel_file():
    # 1) poskusi točno ime
    p = Path.cwd() / DATA_XLSX_DEFAULT
    if p.exists():
        return p

    # 2) fallback: vzorec (deluje tudi pri šumnikih/normalizaciji)
    candidates = list(Path.cwd().glob("*.xlsx"))
    if not candidates:
        return None

    # če jih je več, izberi tistega, ki vsebuje "Skupna" ali "tabela"
    for c in candidates:
        if "skupna" in c.name.lower() and "tabela" in c.name.lower():
            return c

    # sicer vzemi prvega
    return candidates[0]

def _safe_str(x):
    return "" if x is None or (isinstance(x, float) and np.isnan(x)) else str(x)

def normalize_name(s: str) -> str:
    s = _safe_str(s).strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("\u2013", "-").replace("\u2014", "-").replace("–", "-").replace("—", "-")
    s = re.sub(r"\s*-\s*", " - ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def is_rate_like(col: str) -> bool:
    c = col.lower()
    keywords = [
        "%", "delež", "/1000", "povpre", "indeks", "stopnja", "na 1", "na 1000", "na preb",
        "kg/preb", "€/preb", "na km2", "gostota", "marža", "povprečna letna zasedenost", "cenjena povp", "donosnost", "dobičkovnost"
    ]
    return any(k in c for k in keywords)

def is_percent_like(col: str) -> bool:
    c = col.lower()

    # stvari, ki so *deleži/indeksi* 
    positive = ["delež", "marža", "%", "stopnja", "povprečna letna zasedenost", "ocenjena povp", "donosnost", "dobičkovnost"]

    # stvari, ki so rate-i in jih *ne* želiš kot %
    negative = ["/1000", "na 1000", "na 1", "na preb", "kg/preb", "€/preb", "na km2", "gostota"]

    return any(k in c for k in positive) and not any(k in c for k in negative)


def parse_numeric(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    s = s.replace({"nan": "", "None": ""})
    s = s.str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False)

    def conv(x):
        if x == "" or x == "-" or str(x).lower() == "nan":
            return np.nan
        x2 = re.sub(r"[^0-9\-,\.]", "", str(x))
        # SI: 1.234,56 -> 1234.56
        if "," in x2 and x2.rfind(",") > x2.rfind("."):
            x2 = x2.replace(".", "")
            x2 = x2.replace(",", ".")
        else:
            parts = x2.split(".")
            if len(parts) > 2:
                x2 = x2.replace(".", "")
            x2 = x2.replace(",", "")
        try:
            return float(x2)
        except Exception:
            return np.nan

    return s.apply(conv)

def format_si_number(x, decimals=None):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    try:
        x = float(x)
        if decimals is None:
            if abs(x - round(x)) < 1e-3:
                decimals = 0
            else:
                decimals = 1
        fmt = f"{{:,.{decimals}f}}".format(x)
        fmt = fmt.replace(",", "X").replace(".", ",").replace("X", ".")
        return fmt
    except Exception:
        return str(x)

def format_pct(x, decimals=1):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    try:
        return format_si_number(float(x), decimals) + " %"
    except Exception:
        return "—"
    
def format_indicator_value_tables(indicator: str, x):
    # deleži/indeksi so v podatkih v obliki 0.45 -> prikaz 45 %
    if is_percent_like(indicator):
        num = x * 100
        return round(num, 1)
    # vse ostalo ostane normalno število
    return round(x, 2)

def format_indicator_value_map(indicator: str, x):
    # deleži/indeksi so v podatkih v obliki 0.45 -> prikaz 45 %

    if is_percent_like(indicator):
        return format_pct(float(x) * 100.0, 1)
    #GINI indeks izjema
    if "GINI" in indicator:
        return round(x,2)
    # vse ostalo ostane normalno števil
    return format_si_number(x)

def strip_diacritics(s: str) -> str:
    return (s.replace("č","c").replace("š","s").replace("ž","z")
             .replace("Č","C").replace("Š","S").replace("Ž","Z"))

def canon_col(s: str) -> str:
    s = normalize_name(s)
    s = strip_diacritics(s).lower()
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s
   
def find_col(df: pd.DataFrame, wanted: list[str]) -> str | None:
    mapping = {canon_col(c): c for c in df.columns}
    for w in wanted:
        if w in mapping:
            return mapping[w]
    for cc, orig in mapping.items():
        for w in wanted:
            if w in cc:
                return orig
    return None

def load_excel(path_or_buffer) -> pd.DataFrame:
    df0 = pd.read_excel(path_or_buffer, header=0)
    c_ob = find_col(df0, ["obcine", "obcina"])
    c_reg = find_col(df0, ["turisticna regija", "turisticne regije", "turisticna"])
    if c_ob and c_reg:
        return df0
    raw = pd.read_excel(path_or_buffer, header=None)
    if raw.shape[0] < 2:
        return df0
    cols = raw.iloc[0].tolist()
    df1 = raw.iloc[1:].copy()
    df1.columns = cols
    return df1

def try_load_geojson(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None



def aggregate_indicator_with_rules(df: pd.DataFrame, indicator: str, agg_rules: dict):
    if "Celotni prihodki v nastan. dejav. na prenočitev" in indicator :

        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"].astype(float))
        values2 = sum(df['Prenočitve turistov SKUPAJ'])


        
        return values1/values2

    if "Ocenjeni prihodki iz nast. dejav. na prenočitev" in indicator :

        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"].astype(float)) * 0.8
        values2 = sum(df['Prenočitve turistov SKUPAJ'])
  

        
        return values1/values2

    if "Ocenjeni prihodki iz nast.dej. na prodano sobo (ned.enoto)" in indicator:

        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"] * 0.8)
        
        hoteli = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote)\t- Hoteli in podobni obrati'])
        druge_enote = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet'])
        kampi = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote)\t- Kampi'])

        vse_enote = hoteli + druge_enote + kampi

        hoteli_zasedenost = 1.6* (hoteli/vse_enote)
        kampi_zasedenost = 2.5* (kampi/vse_enote)
        druge_zasedenost = 2 * (druge_enote/vse_enote)
        
        values2 = sum(df["Prenočitve turistov SKUPAJ"])/ (hoteli_zasedenost + kampi_zasedenost + druge_zasedenost)
           
        return values1/values2
    
    if "Ocenjeni prihodki iz nastan. dej. na razpoložljivo sobo (enoto)" in indicator:
        
        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"] * 0.8)
        
        hoteli = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote)\t- Hoteli in podobni obrati'])
        druge_enote = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet'])
        kampi = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote)\t- Kampi'])

        values2 = (hoteli + druge_enote) * 365 + kampi * 153

        return values1/values2

    if indicator not in agg_rules:
    
        return df[indicator].sum(skipna=True)
    
    rule, weight_col = agg_rules[indicator]

    values = df[indicator].astype(float)

    if rule == "sum":
        return float(values.sum(skipna=True))
    if rule == "mean":
        return float(values.mean(skipna=True))
    if rule == "wmean":
        
        if weight_col is None or weight_col not in df.columns:
            return float(values.mean(skipna=True))
        
        weights = df[weight_col].astype(float)
        mask = (~values.isna()) & (~weights.isna()) & (weights > 0)

        if not mask.any():
            
            return np.nan
        
        return float(np.average(values[mask], weights= weights[mask]))
    
    return float(values.sum(skipna = True))



def compute_region_aggregates1(num_df, regions, indicator_cols, agg_rules, group_col:str):
    out = pd.DataFrame({group_col : regions})

    for ind in indicator_cols:
        out[ind] = [aggregate_indicator_with_rules(
            num_df[num_df[group_col] == r],
            ind,
            agg_rules
        )
        for r in regions]
    
    return out

def get_geojson_name_prop(geojson_obj, candidates=("name","NAME","Občina","OBČINA")):
    sample_props = None
    for feat in geojson_obj.get("features", [])[:15]:
        sample_props = feat.get("properties", {})
        if sample_props:
            break
    if not sample_props:
        return None
    for c in candidates:
        if c in sample_props:
            return c
    return list(sample_props.keys())[0]



@st.cache_data(show_spinner=False)
def build_region_geojson_from_municipalities(geojson_obj: dict, name_prop: str, muni_to_region: dict, group_col:str) -> dict | None:
    if gpd is None or geojson_obj is None:
        return None
    try:
        gdf = gpd.GeoDataFrame.from_features(geojson_obj.get("features", []))
        if gdf.empty:
            return None
        if gdf.crs is None:
            gdf = gdf.set_crs(4326)

        gdf["__obcina__"] = gdf[name_prop].apply(normalize_name)
        gdf[group_col] = gdf["__obcina__"].map(muni_to_region)
        gdf = gdf[gdf[group_col].notna()].copy()
        if gdf.empty:
            return None

        reg_gdf = gdf.dissolve(by=group_col, as_index=False)
        try:
            reg_gdf["geometry"] = reg_gdf["geometry"].simplify(tolerance=0.0005, preserve_topology=True)
        except Exception:
            pass

        return json.loads(reg_gdf.to_json())
    except Exception:
        return None

def _palette(val, vmin, vmax):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "#cccccc"
    if vmax == vmin:
        return "#3182bd"
    q = (val - vmin) / (vmax - vmin)
    bins = [0.2, 0.4, 0.6, 0.8]
    colors = ["#deebf7", "#9ecae1", "#6baed6", "#3182bd", "#08519c"]
    idx = sum(q > b for b in bins)
    return colors[idx]

@st.cache_data(show_spinner=False)
def render_map_regions(regions_geojson: dict, region_to_value: dict, indicator_label: str,group_col: str, height=680):
    if folium is None or regions_geojson is None:
        st.info("Zemljevid ni na voljo (manjka folium ali GeoJSON).")
        return

    # kopija, da ne spreminjamo originalnega geojson-a
    gj = json.loads(json.dumps(regions_geojson))

    # dodamo vrednost v properties za tooltip
    for feat in gj.get("features", []):
        props = feat.get("properties", {}) or {}
        reg = props.get(group_col)
        val = region_to_value.get(reg, np.nan)
        props["_vrednost_fmt"] = format_indicator_value_map(indicator_label,val)
        feat["properties"] = props

    m = folium.Map(location=[45.65, 14.82], tiles="cartodbpositron",zoom_start= 8, max_bounds=True, min_zoom= 7)


    m.options['maxBounds'] = SLO_BOUNDS
    m.options['maxBoundsViscosity'] = 0.7

    vals = [v for v in region_to_value.values() if v is not None and not (isinstance(v, float) and np.isnan(v))]
    vmin = float(np.nanmin(vals)) if vals else 0.0
    vmax = float(np.nanmax(vals)) if vals else 1.0

    def style_fn(feature):
        reg = feature.get("properties", {}).get(group_col)
        val = region_to_value.get(reg, np.nan)
        return {"fillColor": _palette(val, vmin, vmax), "color": "#111111", "weight": 2.2, "fillOpacity": 0.70}

    layer = folium.GeoJson(
        gj,
        name="Turistične regije",
        style_function=style_fn,
        tooltip=folium.GeoJsonTooltip(
            fields=[group_col, "_vrednost_fmt"],
            aliases=["Regija:", f"{indicator_label}:"],
            sticky=True
        )
    ).add_to(m)

    bounds = layer.get_bounds()
    m.fit_bounds(bounds, padding= (40, 40), max_zoom=8)

    st.components.v1.html(m._repr_html_(), height=height, scrolling=False)

@st.cache_data(show_spinner=False)
def render_map_municipalities(
    geojson_obj,
    name_prop: str,
    muni_in_region: set,
    muni_to_value: dict,
    indicator_label: str = "Vrednost",
    height=680
):
    
    if folium is None or geojson_obj is None:
        st.info("Zemljevid ni na voljo (manjka folium ali GeoJSON).")
        return

    # kopija geojson-a
    gj_all = json.loads(json.dumps(geojson_obj))

    # razdeli feature-je na: v regiji / izven regije
    feats_in = []
    feats_out = []

    # pripravimo vrednosti za barvno lestvico (samo znotraj regije)
    vals = [
        v for k, v in muni_to_value.items()
        if k in muni_in_region and v is not None and not (isinstance(v, float) and np.isnan(v))
    ]
    vmin = float(np.nanmin(vals)) if vals else 0.0
    vmax = float(np.nanmax(vals)) if vals else 1.0

    for feat in gj_all.get("features", []):
        props = feat.get("properties", {}) or {}
        nm = normalize_name(props.get(name_prop, ""))

        if nm in muni_in_region:
            val = muni_to_value.get(nm, np.nan)
            props["_indikator"] = indicator_label
            props["_vrednost_fmt"] = format_indicator_value_map(indicator_label,val)
            feat["properties"] = props
            feats_in.append(feat)
        else:
            feats_out.append(feat)
    
    gj_in = {"type": "FeatureCollection", "features": feats_in}
    gj_out = {"type": "FeatureCollection", "features": feats_out}

    m = folium.Map(location=[45.65, 14.82], tiles="cartodbpositron", max_bounds=True, min_zoom= 7)
    

    m.options['maxBounds'] = SLO_BOUNDS
    m.options['maxBoundsViscosity'] = 0.7

    # 1) IZVEN REGIJE (brez tooltipa)
    def style_out(feature):
        return {"fillColor": "#e0e0e0", "color": "#aaaaaa", "weight": 0.4, "fillOpacity": 0.25}

    folium.GeoJson(
        gj_out,
        name="Občine (izven regije)",
        style_function=style_out
    ).add_to(m)

    # 2) V REGIJI (s tooltipom)
    def style_in(feature):
        props = feature.get("properties", {}) or {}
        nm = normalize_name(props.get(name_prop, ""))
        val = muni_to_value.get(nm, np.nan)
        return {"fillColor": _palette(val, vmin, vmax), "color": "#111111", "weight": 0.9, "fillOpacity": 0.75}

    layer = folium.GeoJson(
        gj_in,
        name="Občine (v regiji)",
        style_function=style_in,
        tooltip=folium.GeoJsonTooltip(
            fields=[name_prop, "_vrednost_fmt"],
            aliases=["Občina:", f"{indicator_label}:"],
            sticky=True
        )
    ).add_to(m)

    bounds = layer.get_bounds()
    m.fit_bounds(bounds, padding= (40, 40), max_zoom=9)
    st.components.v1.html(m._repr_html_(), height=height, scrolling=False)
   

def make_localized_column_config(df: pd.DataFrame):
    cfg = {}
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            if is_percent_like(c):
                cfg[c] = st.column_config.NumberColumn(format="percentage")
            else:
                cfg[c] = st.column_config.NumberColumn(format="localized")
    return cfg




@st.cache_data(show_spinner=False)
def load_geojson_from_upload_or_file(uploaded, default_path: Path):
    if uploaded is not None:
        return json.load(uploaded)
    return try_load_geojson(default_path)


