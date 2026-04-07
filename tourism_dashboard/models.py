from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DashboardContext:
    df: pd.DataFrame
    numeric_df: pd.DataFrame
    market_growth_numeric_df: pd.DataFrame | None
    geojson_obj: dict | None
    geojson_name_prop: str | None
    grouped_indicators: dict[str, list[str]]
    market_cols: list[str]
    indicator_cols: list[str]
    dashboard_mode: bool
