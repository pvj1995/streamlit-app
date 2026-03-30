from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DashboardContext:
    df: pd.DataFrame
    geojson_obj: dict | None
    geojson_name_prop: str | None
    grouped_indicators: dict[str, list[str]]
    market_cols: list[str]
    dashboard_mode: bool
    meta_cols: set[str]
