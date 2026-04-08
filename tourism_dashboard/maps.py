from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import streamlit as st
import streamlit.components.v1 as components

from tourism_dashboard.config import SLO_BOUNDS
from tourism_dashboard.formatting import format_indicator_value_map
from tourism_dashboard.helpers import normalize_name

MUNICIPAL_DISPLAY_SIMPLIFY_TOLERANCE = 0.00010
REGION_DISPLAY_SIMPLIFY_TOLERANCE = 0.0005


if TYPE_CHECKING:
    import folium
    import geopandas as gpd
    from shapely.geometry import MultiPolygon, Polygon
else:
    try:
        import folium
    except Exception:
        folium = None

    try:
        import geopandas as gpd
    except Exception:
        gpd = None

    try:
        from shapely.geometry import MultiPolygon, Polygon
    except Exception:
        MultiPolygon = None
        Polygon = None


def get_geojson_name_prop(
    geojson_obj: dict[str, Any],
    candidates: tuple[str, ...] = ("name", "NAME", "Občina", "OBČINA"),
) -> str | None:
    sample_props: dict[str, Any] | None = None
    for feature in geojson_obj.get("features", [])[:15]:
        sample_props = feature.get("properties", {})
        if sample_props:
            break
    if not sample_props:
        return None
    for candidate in candidates:
        if candidate in sample_props:
            return candidate
    return list(sample_props.keys())[0]


def _remove_polygon_holes(geometry: Any) -> Any:
    if geometry is None or Polygon is None or MultiPolygon is None:
        return geometry
    if isinstance(geometry, Polygon):
        return Polygon(geometry.exterior)
    if isinstance(geometry, MultiPolygon):
        return MultiPolygon(
            [Polygon(polygon.exterior) for polygon in geometry.geoms if not polygon.is_empty]
        )
    return geometry


@st.cache_data(show_spinner=False)
def build_region_geojson_from_municipalities(
    geojson_obj: dict[str, Any],
    name_prop: str,
    municipality_to_region: dict[str, str],
    group_col: str,
) -> dict[str, Any] | None:
    if gpd is None or geojson_obj is None:
        return None
    try:
        gpd_module = gpd
        gdf = gpd_module.GeoDataFrame.from_features(geojson_obj.get("features", []))
        if gdf.empty:
            return None
        if gdf.crs is None:
            gdf = gdf.set_crs(4326)

        gdf["__obcina__"] = gdf[name_prop].apply(normalize_name)
        gdf[group_col] = gdf["__obcina__"].map(municipality_to_region)
        gdf = gdf[gdf[group_col].notna()].copy()
        if gdf.empty:
            return None

        reg_gdf = gdf.dissolve(by=group_col, as_index=False)
        try:
            reg_gdf["geometry"] = reg_gdf["geometry"].simplify(
                tolerance=REGION_DISPLAY_SIMPLIFY_TOLERANCE,
                preserve_topology=True,
            )
        except Exception:
            pass
        try:
            reg_gdf["geometry"] = reg_gdf["geometry"].apply(_remove_polygon_holes)
        except Exception:
            pass

        return json.loads(reg_gdf.to_json())
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def build_simplified_municipality_geojson(
    geojson_obj: dict[str, Any],
    tolerance: float = MUNICIPAL_DISPLAY_SIMPLIFY_TOLERANCE,
) -> dict[str, Any] | None:
    if gpd is None or geojson_obj is None:
        return geojson_obj
    try:
        gpd_module = gpd
        gdf = gpd_module.GeoDataFrame.from_features(geojson_obj.get("features", []))
        if gdf.empty:
            return geojson_obj
        if gdf.crs is None:
            gdf = gdf.set_crs(4326)
        gdf["geometry"] = gdf["geometry"].simplify(
            tolerance=tolerance,
            preserve_topology=True,
        )
        return json.loads(gdf.to_json())
    except Exception:
        return geojson_obj


def palette(value: float | None, vmin: float, vmax: float) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "#cccccc"
    if vmax == vmin:
        return "#3182bd"
    quantile = (value - vmin) / (vmax - vmin)
    bins = [0.2, 0.4, 0.6, 0.8]
    colors = ["#deebf7", "#9ecae1", "#6baed6", "#3182bd", "#08519c"]
    return colors[sum(quantile > bound for bound in bins)]


def _map_html_cache() -> dict[str, str]:
    cache = st.session_state.get("_map_html_cache")
    if not isinstance(cache, dict):
        cache = {}
        st.session_state["_map_html_cache"] = cache
    return cast(dict[str, str], cache)


def _cache_key_digest(*parts: object) -> str:
    raw = "||".join(str(part) for part in parts)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def cache_key_for_regions_map(
    *,
    data_signature: str,
    geojson_signature: str | None,
    group_col: str,
    indicator_label: str,
) -> str:
    return "regions:" + _cache_key_digest(
        data_signature,
        geojson_signature or "no_geojson",
        group_col,
        indicator_label,
    )


def cache_key_for_municipalities_map(
    *,
    data_signature: str,
    geojson_signature: str | None,
    group_col: str,
    selected_region: str,
    indicator_label: str,
) -> str:
    return "municipalities:" + _cache_key_digest(
        data_signature,
        geojson_signature or "no_geojson",
        group_col,
        selected_region,
        indicator_label,
    )


def build_regions_map_html(
    regions_geojson: dict[str, Any],
    region_to_value: dict[str, float],
    indicator_label: str,
    group_col: str,
) -> str | None:
    if folium is None or regions_geojson is None:
        return None

    folium_module = folium
    geojson_copy = json.loads(json.dumps(regions_geojson))
    for feature in geojson_copy.get("features", []):
        props = feature.get("properties", {}) or {}
        region_name = props.get(group_col)
        value = region_to_value.get(region_name, np.nan) if isinstance(region_name, str) else np.nan
        props["_vrednost_fmt"] = format_indicator_value_map(indicator_label, value)
        feature["properties"] = props

    map_obj = folium_module.Map(
        location=[45.65, 14.82],
        tiles="cartodbpositron",
        zoom_start=8,
        max_bounds=True,
        min_zoom=7,
    )
    map_obj.options["maxBounds"] = SLO_BOUNDS
    map_obj.options["maxBoundsViscosity"] = 0.7

    values = [
        value
        for value in region_to_value.values()
        if value is not None and not (isinstance(value, float) and np.isnan(value))
    ]
    vmin = float(np.nanmin(values)) if values else 0.0
    vmax = float(np.nanmax(values)) if values else 1.0

    def style_fn(feature):
        region_name = feature.get("properties", {}).get(group_col)
        value = region_to_value.get(region_name, np.nan)
        return {
            "fillColor": palette(value, vmin, vmax),
            "color": "#111111",
            "weight": 2.2,
            "fillOpacity": 0.70,
        }

    layer = folium_module.GeoJson(
        geojson_copy,
        name="Turistične regije",
        style_function=style_fn,
        tooltip=folium_module.GeoJsonTooltip(
            fields=[group_col, "_vrednost_fmt"],
            aliases=["Območje:", f"{indicator_label}:"],
            sticky=True,
        ),
    ).add_to(map_obj)

    bounds = cast(Any, layer.get_bounds())
    map_obj.fit_bounds(bounds, padding=(40, 40), max_zoom=8)
    return map_obj._repr_html_()


def render_map_regions(
    regions_geojson: dict[str, Any],
    region_to_value: dict[str, float],
    indicator_label: str,
    group_col: str,
    height: int = 680,
    cache_key: str | None = None,
) -> None:
    def build_html() -> str | None:
        return build_regions_map_html(
            regions_geojson=regions_geojson,
            region_to_value=region_to_value,
            indicator_label=indicator_label,
            group_col=group_col,
        )

    _render_cached_map(cache_key=cache_key, height=height, build_html=build_html)


def build_municipalities_map_html(
    geojson_obj: dict[str, Any] | None,
    name_prop: str,
    municipalities_in_region: set[str],
    municipality_to_value: dict[str, float],
    indicator_label: str = "Vrednost",
) -> str | None:
    if folium is None or geojson_obj is None:
        return None

    folium_module = folium
    geojson_copy = json.loads(json.dumps(geojson_obj))
    features_in = []
    features_out = []

    values = [
        value
        for municipality, value in municipality_to_value.items()
        if municipality in municipalities_in_region
        and value is not None
        and not (isinstance(value, float) and np.isnan(value))
    ]
    vmin = float(np.nanmin(values)) if values else 0.0
    vmax = float(np.nanmax(values)) if values else 1.0

    for feature in geojson_copy.get("features", []):
        props = feature.get("properties", {}) or {}
        municipality_name = normalize_name(props.get(name_prop, ""))

        if municipality_name in municipalities_in_region:
            value = municipality_to_value.get(municipality_name, np.nan)
            props["_indikator"] = indicator_label
            props["_vrednost_fmt"] = format_indicator_value_map(indicator_label, value)
            feature["properties"] = props
            features_in.append(feature)
        else:
            features_out.append(feature)

    geojson_in = {"type": "FeatureCollection", "features": features_in}
    geojson_out = {"type": "FeatureCollection", "features": features_out}

    map_obj = folium_module.Map(
        location=[45.65, 14.82],
        tiles="cartodbpositron",
        max_bounds=True,
        min_zoom=7,
    )
    map_obj.options["maxBounds"] = SLO_BOUNDS
    map_obj.options["maxBoundsViscosity"] = 0.7

    def style_out(_feature):
        return {
            "fillColor": "#e0e0e0",
            "color": "#aaaaaa",
            "weight": 0.4,
            "fillOpacity": 0.25,
        }

    folium_module.GeoJson(
        geojson_out,
        name="Občine (izven regije)",
        style_function=style_out,
    ).add_to(map_obj)

    def style_in(feature):
        municipality_name = normalize_name(feature.get("properties", {}).get(name_prop, ""))
        value = municipality_to_value.get(municipality_name, np.nan)
        return {
            "fillColor": palette(value, vmin, vmax),
            "color": "#111111",
            "weight": 0.9,
            "fillOpacity": 0.75,
        }

    layer = folium_module.GeoJson(
        geojson_in,
        name="Občine (v regiji)",
        style_function=style_in,
        tooltip=folium_module.GeoJsonTooltip(
            fields=[name_prop, "_vrednost_fmt"],
            aliases=["Občina:", f"{indicator_label}:"],
            sticky=True,
        ),
    ).add_to(map_obj)

    bounds = cast(Any, layer.get_bounds())
    map_obj.fit_bounds(bounds, padding=(40, 40), max_zoom=9)
    return map_obj._repr_html_()


def _render_cached_map(
    *,
    cache_key: str | None,
    height: int,
    build_html: Any,
) -> None:
    html = None
    if cache_key is not None:
        html = _map_html_cache().get(cache_key)
    if html is None:
        html = build_html()
        if cache_key is not None and html is not None:
            _map_html_cache()[cache_key] = html
    if html is None:
        st.info("Zemljevid ni na voljo (manjka folium ali GeoJSON).")
        return
    components.html(html, height=height, scrolling=False)


def render_map_municipalities(
    geojson_obj: dict[str, Any] | None,
    name_prop: str,
    municipalities_in_region: set[str],
    municipality_to_value: dict[str, float],
    indicator_label: str = "Vrednost",
    height: int = 680,
    cache_key: str | None = None,
) -> None:
    def build_html() -> str | None:
        return build_municipalities_map_html(
            geojson_obj=geojson_obj,
            name_prop=name_prop,
            municipalities_in_region=municipalities_in_region,
            municipality_to_value=municipality_to_value,
            indicator_label=indicator_label,
        )

    _render_cached_map(cache_key=cache_key, height=height, build_html=build_html)
