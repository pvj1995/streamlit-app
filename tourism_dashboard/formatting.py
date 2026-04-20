from typing import Any, Literal, TypeAlias

import numpy as np
import pandas as pd
import streamlit as st

from tourism_dashboard.config import (
    INDIKATORJI_Z_VALUTO,
    LOWER_IS_BETTER_INDICATORS,
)

ColumnWidth: TypeAlias = Literal["small", "medium", "large"]


def _number_column(
    *,
    format: str,
    width: ColumnWidth | None = None,
) -> Any:
    if width is None:
        return st.column_config.NumberColumn(format=format)
    return st.column_config.NumberColumn(format=format, width=width)


def _text_column(width: ColumnWidth | None = None) -> Any:
    if width is None:
        return st.column_config.TextColumn()
    return st.column_config.TextColumn(width=width)


def is_rate_like(column_name: str) -> bool:
    keywords = [
        "Naravni prirast /1000 prebival.",
        "Selitveni prirast /1000 prebival.",
        "Delež tujih prenočitev - 2019",
        "Delež tujih prenočitev - 2024",
        "Delež tujih prenočitev - 2025",
        "Rast števila prenočitev 2024/2019 - SKUPAJ",
        "Rast števila prenočitev 2024/2019 - Domači",
        "Rast števila prenočitev 2024/2019 - Tuji",
        "Rast števila prenočitev 2025/2019 - SKUPAJ",
        "Rast števila prenočitev 2025/2019 - Domači",
        "Rast števila prenočitev 2025/2019 - Tuji",
        "Rast števila prenočitev 2025/2024 - SKUPAJ",
        "Rast števila prenočitev 2025/2024 - Domači",
        "Rast števila prenočitev 2025/2024 - Tuji",
        "Delež stalnih ležišč v Hotelih ipd.",
        "Delež sob (ned.enot) v kapacitetah višje kakovosti - (4* in 5*) 2025",
        "Delež sob (enot) v hotelih ipd. NO 2025",
        "Delež stalnih ležišč v hotelih ipd. NO",
        "Delež sob (enot) v kampih 2025",
        "Delež sob (enot) v turističnih kmetijah z nastanitvijo 2025",
        "Delež sob (enot) v vseh drugih vrstah NO 2025",
        "Povprečna letna zasedenost staln. ležišč 2024",
        "Povprečna letna zasedenost staln. ležišč 2025",
        "Ocenjena povp. Letna zased. sob (nedeljivih enot)",
        "Ocenjena povp. Letna zased. sob (nedeljivih enot) 2025",
        "Delež delovno aktivnih od vseh prebivalcev območja",
        "Delež prebivalcev starih 15 let ali več s srednješolsko strokovno ali splošno izobrazbo",
        "Delež prebivalcev starih 15 let ali več z izobrazbo višjo od srednješolske",
        "Delež delovno aktivnih od vseh prebivalcev območja 2025",
        "Delež delovno aktivnih v turizmu (OECD/WTO) 2025",
        "EBITDA marža v reg.podjetjih in s.p. v Gostinstvu (I)",
        "Donosnost sredstev v reg. podjetjih in s.p. v Gostinstvu (I)",
        "Donosnost kapitala v reg. podjetjih in s.p. v Gostinstvu (I)",
        "Dobičkovnost prihodkov v podjetjih in s.p. v Gostinstvu (I)",
        "Delež stroškov dela v prihodkih v reg. podj. v nast.gost.dej. (I 55)",
        "Delež stroškov dela v dod vredn. v reg. podj. v nast.gost.dej. (I 55)",
        "EBITDA marža v reg.podjetjih v nastanitveni dejav. (I 55)",
        "Donosnost sredstev v nastanitveni dejav. (I 55)",
        "Donosnost kapitala v nastanitveni dejav. (I 55)",
        "Dobičkovnost prihodkov v nastanitveni dejav. (I 55)",
        "Indeks neto plača v Gostinstvu (I) /pvp. plača v vseh dejavnostih",
        "Indeks neto plača v Gostinstvu (I) /pvp. plača v vseh dejavnostih 2025",
        "Število izdanih gradbenih dovoljenj/1000 prebivalcev",
        "Delež naseljenih stanovanj od vseh razp.",
        "Komunalni odpadki, zbrani  z javnim odvozom (kg/prebivalca)",
        "Štev.dijakov in študentov višjih strok. in visokošolsk.progr./1000 preb.",
        "Delež naseljenih stanovanj",
        "Delež delovno aktivnih v turizmu (OECD/WTO)",
        "Delež stroškov dela v prihodkih v reg. podj. v Gostinstvu (I)",
        "Delež stroškov dela v dod vredn. v reg. podj. v Gostinstvu (I)",
    ]
    return any(keyword in column_name for keyword in keywords)


def is_lower_better(indicator: str) -> bool:
    return indicator in LOWER_IS_BETTER_INDICATORS


def is_percent_like(column_name: str) -> bool:
    lower_name = column_name.lower()
    positive = [
        "delež",
        "marža",
        "%",
        "stopnja",
        "povprečna letna zasedenost",
        "ocenjena povp",
        "donosnost",
        "dobičkovnost",
        "rast števila prenočitev",
    ]
    negative = ["/1000", "na 1000", "na 1", "na preb", "kg/preb", "€/preb", "na km2", "gostota"]
    return any(item in lower_name for item in positive) and not any(item in lower_name for item in negative)


def format_si_number(value, decimals=None):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    try:
        number = float(value)
        if decimals is None:
            decimals = 0 if abs(number - round(number)) < 1e-9 else 1
        formatted = f"{{:,.{decimals}f}}".format(number)
        return formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(value)


def format_pct(value, decimals=1):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    try:
        return format_si_number(float(value), decimals) + " %"
    except Exception:
        return "—"


def format_comparison_delta(value, unit: str) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    if unit == "%":
        suffix = " %"
    elif unit == "o.t.":
        suffix = " o.t."
    elif unit:
        suffix = f" {unit}"
    else:
        suffix = ""
    return f"{'+' if float(value) >= 0 else ''}{format_si_number(float(value), 1)}{suffix}"


def get_indicator_gap_unit(indicator: str) -> str:
    if is_percent_like(indicator):
        return "o.t."
    if indicator in INDIKATORJI_Z_VALUTO:
        return "€"
    return ""


def format_indicator_value_tables(indicator: str, value):
    if is_percent_like(indicator):
        return round(value, 3)
    return round(value, 2)


def format_indicator_value_map(indicator: str, value):
    if is_percent_like(indicator):
        return format_pct(float(value) * 100.0, 1)
    if "GINI" in indicator:
        return format(round(value, 2), ".2f")
    if indicator in INDIKATORJI_Z_VALUTO:
        return f"{format_si_number(value)} €"
    return format_si_number(value)


def make_localized_column_config(
    df: pd.DataFrame,
    source_columns: dict[str, str] | None = None,
    width_overrides: dict[str, ColumnWidth] | None = None,
) -> dict[str, Any]:
    source_columns = source_columns or {}
    width_overrides = width_overrides or {}
    config: dict[str, Any] = {}
    for column in df.columns:
        if pd.api.types.is_numeric_dtype(df[column]):
            source_column = source_columns.get(column, column)
            width = width_overrides.get(column)
            if is_percent_like(source_column):
                config[column] = _number_column(format="percent", width=width)
            elif source_column in INDIKATORJI_Z_VALUTO:
                config[column] = _number_column(format="euro", width=width)
            else:
                config[column] = _number_column(format="localized", width=width)
        elif column in width_overrides:
            config[column] = _text_column(width_overrides[column])
    return config
