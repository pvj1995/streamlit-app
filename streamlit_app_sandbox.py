# streamlit_app.py
# Streamlit aplikacija – turistične regije Slovenije (v4)
# - Skupni pogled: regije kot poligoni (dissolve občin) + barvanje
# - Posamezna regija: občine (meje občin)
# - Dodano: pri posamezni regiji prikaz "delež Slovenije" za izbran indikator

import json
import base64
import re
import hashlib
import time
import tempfile
import textwrap
from pathlib import Path
import hmac
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None
    ImageDraw = None
    ImageFont = None

try:
    import folium
except Exception:
    folium = None

try:
    import geopandas as gpd
except Exception:
    gpd = None

try:
    import requests
except Exception:
    requests = None

try:
    from sqlalchemy import text as sql_text
except Exception:
    sql_text = None

try:
    from streamlit_image_select import image_select
except Exception:
    image_select = None


def require_password():
    if "APP_PASSWORD" not in st.secrets:
        st.error("Manjka APP_PASSWORD v Streamlit Secrets.")
        st.stop()

    if st.session_state.get("authenticated", False):
        return

    st.title("Prijava")

    with st.form("login_form", clear_on_submit=False):
        pwd = st.text_input("Geslo", type="password")
        submitted = st.form_submit_button("Vstopi")

        if submitted:
            if hmac.compare_digest(pwd, st.secrets["APP_PASSWORD"]):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Napačno geslo.")

    st.stop()

require_password()


DATA_XLSX_DEFAULT = "Skupna tabela občine.xlsx"
GEOJSON_DEFAULT = "si.json"
MAPPING_XLSX_DEFAULT = "mapping.xlsx"
GROUP_COLOR_EMOJI = {
    "Družbeni kazalniki": "🟦",
    "Okoljski kazalniki": "🟩",
    "Ekonomski nastanitveni in tržni turistični kazalniki": "🟥",
    "Ekonomsko poslovni kazalniki turistične dejavnosti": "🟪",
}
GROUP_BUTTON_IMAGE_FILES = {
    "__all__": "Button - Vsi kazalniki.png",
    "Družbeni kazalniki": "Button - Družbeni kazalniki.png",
    "Okoljski kazalniki": "Button - Okoljski kazalniki.png",
    "Ekonomski nastanitveni in tržni turistični kazalniki": "Button - Ekonomski nastanitveni in tržni turistični kazalniki.png",
    "Ekonomsko poslovni kazalniki turistične dejavnosti": "Button - Ekonomsko poslovni kazalniki turistične dejavnosti.png",
}
TOP_BOTTOM_GROUP_LIMITS = {
    "Družbeni kazalniki": 4,
    "Okoljski kazalniki": 3,
    "Ekonomski nastanitveni in tržni turistični kazalniki": 5,
    "Ekonomsko poslovni kazalniki turistične dejavnosti": 5,
}
TOP_BOTTOM_GROUP_ORDER = list(TOP_BOTTOM_GROUP_LIMITS.keys())
SLO_BOUNDS = [[41.00, 10.38], [49.88, 18.61]]
AI_CACHE_CONNECTION_NAME_DEFAULT = "ai_cache_db"
AI_CACHE_TABLE_NAME = "ai_commentary_cache"

AGG_RULES = {
    'Površina območja (km2)': ("sum", None),
    'Število prebivalcev (H2/2024)': ("sum", None),
    'Število prebivalcev (H2/2025)': ("sum", None),
    'Povprečna starost prebivalcev 2024': ("wmean", 'Število prebivalcev (H2/2024)'),
    'Povprečna starost prebivalcev 2025': ("wmean", 'Število prebivalcev (H2/2025)'),
    'Naravni prirast /1000 prebival.': ("wmean", 'Število prebivalcev (H2/2024)'),
    'Selitveni prirast /1000 prebival.': ("wmean", 'Število prebivalcev (H2/2024)'),
    'Prenočitve turistov SKUPAJ - 2019': ("sum", None),
    'Prenočitve turistov Domači - 2019': ("sum", None),
    'Prenočitve turistov Tuji - 2019': ("sum", None),
    'Prenočitve turistov SKUPAJ - 2024': ("sum", None),
    'Prenočitve turistov Domači - 2024': ("sum", None),
    'Prenočitve turistov Tuji - 2024': ("sum", None),
    'Prenočitve turistov SKUPAJ - 2025': ("sum", None),
    'Prenočitve turistov Domači - 2025': ("sum", None),
    'Prenočitve turistov Tuji - 2025': ("sum", None),
    'Prenočitve - povprečno število prenočitev na mesec': ("sum", None),
    'Delež tujih prenočitev - 2019': ("wmean", 'Prenočitve turistov SKUPAJ - 2019'),
    'Delež tujih prenočitev - 2024': ("wmean", 'Prenočitve turistov SKUPAJ - 2024'),
    'Delež tujih prenočitev - 2025': ("wmean", 'Prenočitve turistov SKUPAJ - 2025'),
    'Rast števila prenočitev 2024/2019 - SKUPAJ': ("wmean", 'Prenočitve turistov SKUPAJ - 2019'),
    'Rast števila prenočitev 2024/2019 - Domači': ("wmean", 'Prenočitve turistov SKUPAJ - 2019'),
    'Rast števila prenočitev 2024/2019 - Tuji': ("wmean", 'Prenočitve turistov SKUPAJ - 2019'),
    'Rast števila prenočitev 2025/2019 - SKUPAJ': ("wmean", 'Prenočitve turistov SKUPAJ - 2019'),
    'Rast števila prenočitev 2025/2019 - Domači': ("wmean", 'Prenočitve turistov SKUPAJ - 2019'),
    'Rast števila prenočitev 2025/2019 - Tuji': ("wmean", 'Prenočitve turistov SKUPAJ - 2019'),
    'Rast števila prenočitev 2025/2024 - SKUPAJ': ("wmean", 'Prenočitve turistov SKUPAJ - 2024'),
    'Rast števila prenočitev 2025/2024 - Domači': ("wmean", 'Prenočitve turistov SKUPAJ - 2024'),
    'Rast števila prenočitev 2025/2024 - Tuji': ("wmean", 'Prenočitve turistov SKUPAJ - 2024'),
    'Prihodi turistov SKUPAJ - 2024': ("sum", None),
    'Prihodi turistov Domači - 2024': ("sum", None),
    'Prihodi turistov Tuji - 2024': ("sum", None),
    'Prihodi turistov SKUPAJ - 2025': ("sum", None),
    'Prihodi turistov Domači - 2025': ("sum", None),
    'Prihodi turistov Tuji - 2025': ("sum", None),
    'PDB turistov SKUPAJ - 2024': ("wmean", 'Prihodi turistov SKUPAJ - 2024'),
    'PDB turistov Domači - 2024': ("wmean", 'Prihodi turistov Domači - 2024'),
    'PDB turistov Tuji - 2024': ("wmean", 'Prihodi turistov Tuji - 2024'),
    'PDB turistov SKUPAJ - 2025': ("wmean", 'Prihodi turistov SKUPAJ - 2025'),
    'PDB turistov Domači - 2025': ("wmean", 'Prihodi turistov Domači - 2025'),
    'PDB turistov Tuji - 2025': ("wmean", 'Prihodi turistov Tuji - 2025'),
    'Nastanitvene kapacitete - Nedeljive enote': ("sum", None),
    'Nastanitvene kapacitete - vsa ležišča': ("sum", None),
    'Nastanitvene kapacitete - stalna ležišča': ("sum", None),
    'Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Hoteli in podobni obrati': ("sum", None),
    'Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Kampi': ("sum", None),
    'Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet': ("sum", None),
    'Struktura nastanitvenih kapacitet - Stalna ležišča - Hoteli in podobni obrati': ("sum", None),
    'Struktura nastanitvenih kapacitet - Stalna ležišča - Kampi': ("sum", None),
    'Struktura nastanitvenih kapacitet - Stalna ležišča - Druge vrste kapacitet': ("sum", None),
    'Delež stalnih ležišč v Hotelih ipd.': ("wmean", 'Nastanitvene kapacitete - stalna ležišča'),
    'Število vseh nastanitvenih obratov 2025': ("sum", None),
    'Nastanitvene kapacitete - Nedeljive enote 2025': ("sum", None),
    'Nastanitvene kapacitete - stalna ležišča 2025': ("sum", None),
    'Število sob (ned.enot) v kapacitetah višje kakovosti - ( 4* in 5*) 2025': ("sum", None),
    'Delež sob (ned.enot) v kapacitetah višje kakovosti - (4* in 5*) 2025': ("wmean", 'Nastanitvene kapacitete - Nedeljive enote 2025'),
    'Število hotelov ipd. NO 2025': ("sum", None),
    'Število sob v hotelih ipd. NO 2025': ("sum", None),
    'Število stalnih ležišč v hotelih ipd. NO 2025': ("sum", None),
    'Delež sob (enot) v hotelih ipd. NO 2025': ("wmean", 'Nastanitvene kapacitete - Nedeljive enote 2025'),
    'Delež stalnih ležišč v hotelih ipd. NO': ("wmean", 'Nastanitvene kapacitete - stalna ležišča 2025'),
    'Število kampov 2025': ("sum", None),
    'Število enot v kampih 2025': ("sum", None),
    'Število ležišč v kampih 2025': ("sum", None),
    'Delež sob (enot) v kampih 2025': ("wmean", 'Nastanitvene kapacitete - Nedeljive enote 2025'),
    'Število turističnih kmetij z nastanitvijo 2025': ("sum", None),
    'Število sob v turističnih kmetijah z nastanitvijo 2025': ("sum", None),
    'Število ležišč v turističnih kmetijah z nastanitvijo 2025': ("sum", None),
    'Delež sob (enot) v turističnih kmetijah z nastanitvijo 2025': ("wmean", 'Nastanitvene kapacitete - Nedeljive enote 2025'),
    'Število vseh drugih vrst NO 2025': ("sum", None),
    'Število sob v vseh drugih vrstah NO 2025': ("sum", None),
    'Število ležišč v vseh drugih vrstah NO 2025': ("sum", None),
    'Delež sob (enot) v vseh drugih vrstah NO 2025': ("wmean", 'Nastanitvene kapacitete - Nedeljive enote 2025'),
    'Povprečna letna zasedenost staln. Ležišč 2024': ("wmean", 'Nastanitvene kapacitete - stalna ležišča'),
    'Povprečna letna zasedenost staln. Ležišč 2025': ("wmean", 'Nastanitvene kapacitete - stalna ležišča 2025'),
    'Ocenjena povp. Letna zased. sob (nedeljivih enot) 2024': ("wmean", 'Nastanitvene kapacitete - Nedeljive enote'),
    'Ocenjena povp. Letna zased. sob (nedeljivih enot) 2025': ("wmean", 'Nastanitvene kapacitete - Nedeljive enote 2025'),
    'Pritisk turizma na družbeni prostor (število stalnih ležišč / 100 prebivalcev)': ("wmean", 'Število prebivalcev (H2/2024)'),
    'Pritisk turizma na družbeni prostor (število stalnih ležišč / 100 prebivalcev) 2025': ("wmean", 'Število prebivalcev (H2/2025)'),
    'Gostota turizma': ("wmean", 'Površina območja (km2)'),
    'Gostota turizma 2025': ("wmean", 'Površina območja (km2)'),
    "Intenzivnost turizma (število nočitev na dan / 100 prebivalcev)": ("wmean", "Število prebivalcev (H2/2024)"),
    "Intenzivnost turizma (število nočitev na dan / 100 prebivalcev) 2025": ("wmean", "Število prebivalcev (H2/2025)"),
    "Delovno aktivno prebivalstvo v turizmu (OECD/WTO)": ("sum", None),
    "Delovno aktivno prebivalstvo v turizmu (OECD/WTO) 2025": ("sum", None),
    "Število zaposl. in samozaposl. v aktivnih podjetjih v Gostinstvu (I)": ("sum", None),
    "Zaposleni v Gostinstvu (I) v registr.podjetjih in s.p.": ("sum", None),
    "Zaposleni v nastan.dejav. (I55) v registr.podjetjih in s.p.": ("sum", None),
    "Vsi delovni aktivni na območju": ("sum", None),
    "Delež delovno aktivnih od vseh prebivalcev območja": ("wmean", "Število prebivalcev (H2/2024)"),
    "Število prebivalcev starih 15 let ali več na območju": ("sum", None),
    "Število prebivalcev starih 15 let ali več s srednješolsko strokovno ali splošno izobrazbo": ("sum", None),
    "Delež prebivalcev starih 15 let ali več s srednješolsko strokovno ali splošno izobrazbo": ("wmean", "Število prebivalcev (H2/2024)"),
    "Število prebivalcev starih 15 let ali več z izobrazbo višjo od srednješolske": ("sum", None),
    "Delež prebivalcev starih 15 let ali več z izobrazbo višjo od srednješolske": ("wmean", "Število prebivalcev (H2/2024)"),
    "Vsi delovno aktivni na območju 2025": ("sum", None),
    "Delež delovno aktivnih od vseh prebivalcev območja 2025": ("wmean", "Število prebivalcev (H2/2025)"),
    "Delež delovno aktivnih v turizmu (OECD/WTO)": ("wmean", "Vsi delovni aktivni na območju"),
    "Delež delovno aktivnih v turizmu (OECD/WTO) 2025": ("wmean", "Vsi delovno aktivni na območju 2025"),
    "Število vseh vrst podjetij na območju": ("sum", None),
    "Prihodek (v 1000 EUR) vseh podjetij na območju": ("sum", None),
    "Število reg. podjetij in s.p.  v Gostinstvu (I)": ("sum", None),
    "Prihodki reg.podjetij in s.p. v Gostinstvu (I)": ("sum", None),
    "Dodana vrednost reg.podjetij v Gostinstvu (I)": ("sum", None),
    "Dodana vrednost/zaposl. reg.podjetij Gostinstvu (I)": ("wmean", "Zaposleni v Gostinstvu (I) v registr.podjetjih in s.p."),
    "Ocenjeni stroški dela v reg. podj. v Gostinski (I) dejavnosti": ("sum", None),
    "Stroški dela na zaposl. na leto v reg. podj. v Gostinski (I) dejavnosti": ("wmean", "Zaposleni v Gostinstvu (I) v registr.podjetjih in s.p."),
    "Delež stroškov dela v prihodkih v reg. podj. v Gostinstvu (I)": ("wmean", "Prihodki reg.podjetij in s.p. v Gostinstvu (I)"),
    "Delež stroškov dela v dod vredn. v reg. podj. v Gostinstvu (I)": ("wmean", "Dodana vrednost reg.podjetij v Gostinstvu (I)"),
    "EBITDA v reg.podjetjih in s.p. v Gostinstvu (I)": ("sum", None),
    "EBITDA marža v reg.podjetjih in s.p. v Gostinstvu (I)": ("wmean", "Prihodki reg.podjetij in s.p. v Gostinstvu (I)"),
    "Čisti dobiček/izguba v reg. podj. in s.p. v Gostinstvu (I)": ("sum", None),
    "Sredstva v reg. Podjetjih in s.p. v Gostinstvu (I)": ("sum", None),
    "Kapital v reg. Podjetjih in s.p. v Gostinstvu (I)": ("sum", None),
    "Donosnost sredstev v reg. podjetjih in s.p. v Gostinstvu (I)": ("wmean", "Sredstva v reg. Podjetjih in s.p. v Gostinstvu (I)"),
    "Donosnost kapitala v reg. podjetjih in s.p. v Gostinstvu (I)": ("wmean", "Kapital v reg. Podjetjih in s.p. v Gostinstvu (I)"),
    "Dobičkovnost prihodkov v podjetjih in s.p. v Gostinstvu (I)": ("wmean", "Prihodki reg.podjetij in s.p. v Gostinstvu (I)"),
    "Število reg. podjetij in s.p. v nastanitveni dejav. (I 55)": ("sum", None),
    "Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)": ("sum", None),
    "Dodana vrednost reg.podjetij v nastanitveni dejav. (I 55)": ("sum", None),
    "Dodana vrednost/zaposl. V reg.podjetjih v nast.dejav. (I 55)": ("wmean", " Zaposleni v nastan.dejav. (I55) v registr.podjetjih in s.p."),
    "Ocenjeni stroški dela v reg. podj. v nastan.gost. (I 55) dejavnosti": ("sum", None),
    "Stroški dela na zaposl. na leto v reg. podj. v nast.gost. (I 55) dejavnosti": ("wmean", " Zaposleni v nastan.dejav. (I55) v registr.podjetjih in s.p."),
    "Delež stroškov dela v prihodkih v reg. podj. v nast.gost.dej. (I 55)": ("wmean", "Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"),
    "Delež stroškov dela v dod vredn. v reg. podj. v nast.gost.dej. (I 55)": ("wmean", "Dodana vrednost reg.podjetij v nastanitveni dejav. (I 55)"),
    "EBITDA v reg.podjetjih in s.p. v nastanitveni dejav. (I 55)": ("sum", None),
    "EBITDA marža v reg.podjetjih v nastanitveni dejav. (I 55)": ("wmean", "Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"),
    "Čisti dobiček/izguba v reg. podj. v nastanitveni dejav. (I 55)": ("sum", None),
    "Sredstva v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)": ("sum", None),
    "Kapital v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)": ("sum", None),
    "Donosnost sredstev v nastanitveni dejav. (I 55)": ("wmean", "Sredstva v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)"),
    "Donosnost kapitala v nastanitveni dejav. (I 55)": ("wmean", "Kapital v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)"),
    "Dobičkovnost prihodkov v nastanitveni dejav. (I 55)": ("wmean", "Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"),
    "Celotni prihodki v nastan. dejav. na prenočitev": ("wmean", "Prenočitve turistov SKUPAJ - 2024"),
    "Ocenjeni prihodki iz nast. dejav. na prenočitev": ("wmean", "Prenočitve turistov SKUPAJ - 2024"),
    "Ocenjeni prihodki iz nastan. dej. na razpoložljivo sobo (enoto)": ("wmean", 'Nastanitvene kapacitete - Nedeljive enote'),
    "Ocenjeni prihodki iz nast.dej. na prodano sobo (ned.enoto)": ("wmean", "Prenočitve turistov SKUPAJ - 2024"),
    "Poraba el.energije (MWh) Dejavnost Gostinstvo (I)": ("sum", None),
    "Poraba el.energije (MWh) Dejavnost Gostinstvo (I) 2025": ("sum", None),
    "Poraba el.energ. v kWh na realiz. 1000 EUR prihodka v Gostinstvu (I)": ("wmean", "Prihodki reg.podjetij in s.p. v Gostinstvu (I)"),
    "Število kmetijskih  gospodarstev": ("sum", None),
    "Ocena skupne ekonomske velikosti kmetij.gospodarstev": ("sum", None),
    "Skupaj neto prejeti dohodek povp. na prebivalca": ("wmean", "Število prebivalcev (H2/2024)"),
    "Neto prejeti dohodek iz dela, povp. na preb.": ("wmean", "Število prebivalcev (H2/2024)"),
    "Neto prejeti dohodek iz premoženja, kapitala, idr.povp. na preb.": ("wmean", "Število prebivalcev (H2/2024)"),
    "Povprečna mesečna neto  plača/zaposl. osebo (EUR)": ("wmean", "Vsi delovni aktivni na območju"),
    "Povprečna mesečna neto  plača/zaposl. osebo (EUR) 2025": ("wmean", "Vsi delovno aktivni na območju 2025"),
    "Povprečna neto plača izplačana na zaposl. osebo v Gostinstvu (I)": ("wmean", "Število zaposl. in samozaposl. v aktivnih podjetjih v Gostinstvu (I)"),
    "Povprečna neto plača izplačana na zaposl. osebo v Gostinstvu (I) 2025": ("wmean", "Število zaposl. in samozaposl. v aktivnih podjetjih v Gostinstvu (I)"),
    "Indeks neto plača v Gostinstvu (I) /pvp. plača v vseh dejavnostih": ("wmean", "Vsi delovni aktivni na območju"),
    "Indeks neto plača v Gostinstvu (I) /pvp. plača v vseh dejavnostih 2025": ("wmean", "Vsi delovno aktivni na območju 2025"),
    "Število izdanih gradbenih dovoljenj/1000 prebivalcev": ("wmean", "Število prebivalcev (H2/2024)"),
    "Število počitniških stanovanj": ("sum", None),
    "Delež naseljenih stanovanj od vseh razp.": ("mean", None),
    "Komunalni odpadki, zbrani  z javnim odvozom (kg/prebivalca)": ("wmean", "Število prebivalcev (H2/2024)"),
    "Štev.dijakov in študentov višjih strok. in visokošolsk.progr./1000 preb.": ("wmean", "Število prebivalcev (H2/2024)"),
    "Število vseh stanovanj": ("sum", None),
    "Delež naseljenih stanovanj": ("wmean", "Število vseh stanovanj"),
    "GINI Indeks - sezonskost prenočitev - 2024": ("wmean", 'Prenočitve - povprečno število prenočitev na mesec'),
    "Delež vseh prenočitev - Domači trg": ("wmean", "Prenočitve turistov SKUPAJ - 2024"),
    "Delež vseh prenočitev - DACH trgi (nemško govoreči trgi: D, A in CH)": ("wmean", "Prenočitve turistov SKUPAJ - 2024"),
    "Delež vseh prenočitev - Italijanski trg": ("wmean", "Prenočitve turistov SKUPAJ - 2024"),
    "Delež vseh prenočitev - Vzh.evropski trgi (PL,CZ,HU,SK,LIT,LTV,EST,RU,UKR)": ("wmean", "Prenočitve turistov SKUPAJ - 2024"),
    "Delež vseh prenočitev - Drugi zah.in sev. evropski trgi (ES,P, F,Benelux, Skandinavske države)": ("wmean", "Prenočitve turistov SKUPAJ - 2024"),
    "Delež vseh prenočitev - Prekomorski trgi (ZDA, VB, CAN, AU, Azija)": ("wmean", "Prenočitve turistov SKUPAJ - 2024"),
    "Delež vseh prenočitev - Trgi JV Evrope": ("wmean", "Prenočitve turistov SKUPAJ - 2024"),
    "Delež vseh prenočitev - Vsi drugi tuji trgi": ("wmean", "Prenočitve turistov SKUPAJ - 2024"),
}

TOP_BOTTOM_EXCLUDED_INDICATORS = {
    "Število prebivalcev (H2/2024)",
    "Povprečna starost prebivalcev 2024",
    'Naravni prirast /1000 prebival.',
    'Selitveni prirast /1000 prebival.',
    "Pritisk turizma na družbeni prostor (število stalnih ležišč / 100 prebivalcev)",
    "Delovno aktivno prebivalstvo v turizmu (OECD/WTO)",
    "Vsi delovni aktivni na območju",
    "Delež delovno aktivnih od vseh prebivalcev območja",
    "Število prebivalcev starih 15 let ali več na območju",
    "Število prebivalcev starih 15 let ali več s srednješolsko strokovno ali splošno izobrazbo",
    "Število prebivalcev starih 15 let ali več z izobrazbo višjo od srednješolske",
    "Vsi delovno aktivni na območju 2025",
    "Delež delovno aktivnih v turizmu (OECD/WTO)",
    "Povprečna mesečna neto  plača/zaposl. osebo (EUR)",
    "Povprečna neto plača izplačana na zaposl. osebo v Gostinstvu (I)",
    "Indeks neto plača v Gostinstvu (I) /pvp. plača v vseh dejavnostih",
    "Poraba el.energije (MWh) Dejavnost Gostinstvo (I)",
    "Prenočitve turistov SKUPAJ - 2019",
    "Prenočitve turistov Domači - 2019",
    "Prenočitve turistov Tuji - 2019",
    "Delež tujih prenočitev - 2019",
    "Prenočitve turistov SKUPAJ - 2024",
    "Prenočitve turistov Domači - 2024",
    "Prenočitve turistov Tuji - 2024",
    "GINI Indeks - sezonskost prenočitev - 2024",
    "Rast števila prenočitev 2024/2019 - SKUPAJ",
    "Rast števila prenočitev 2024/2019 - Domači",
    "Rast števila prenočitev 2024/2019 - Tuji",
    "Delež tujih prenočitev - 2024",
    "Delež vseh prenočitev - Domači trg - 2024",
    "Delež vseh prenočitev - DACH trgi (nemško govoreči trgi: D, A in CH) - 2024",
    "Delež vseh prenočitev - Italijanski trg - 2024",
    "Delež vseh prenočitev - Vzh.evropski trgi (PL,CZ,HU,SK,LIT,LTV,EST,RU,UKR) - 2024",
    "Delež vseh prenočitev - Drugi zah.in sev. evropski trgi (ES,P, F,Benelux, Skandinavske države) - 2024",
    "Delež vseh prenočitev - Prekomorski trgi (ZDA, VB, CAN, AU, Azija) - 2024",
    "Delež vseh prenočitev - Trgi JV Evrope - 2024",
    "Delež vseh prenočitev - Vsi drugi tuji trgi - 2024",
    "Prihodi turistov SKUPAJ - 2024",
    "Prihodi turistov Domači - 2024",
    "Prihodi turistov Tuji - 2024",
    "PDB turistov SKUPAJ - 2024",
    "PDB turistov Domači - 2024",
    "PDB turistov Tuji - 2024",
    "Gibanje GINI Indeksa prenoč. 2024/2019",
    "Nastanitvene kapacitete - Nedeljive enote",
    "Nastanitvene kapacitete - vsa ležišča",
    "Nastanitvene kapacitete - stalna ležišča",
    "Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Hoteli in podobni obrati",
    "Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Kampi",
    "Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet",
    "Struktura nastanitvenih kapacitet - Stalna ležišča - Hoteli in podobni obrati",
    "Struktura nastanitvenih kapacitet - Stalna ležišča - Kampi",
    "Struktura nastanitvenih kapacitet - Stalna ležišča - Druge vrste kapacitet",
    "Delež stalnih ležišč v Hotelih ipd.",
    "Število sob (ned.enot) v kapacitetah višje kakovosti - ( 4* in 5*) 2025",
    "Število sob v hotelih ipd. NO 2025",
    "Število stalnih ležišč v hotelih ipd. NO 2025",
    "Delež stalnih ležišč v hotelih ipd. NO",
    "Število enot v kampih 2025",
    "Število ležišč v kampih 2025",
    "Število sob v turističnih kmetijah z nastanitvijo 2025",
    "Število ležišč v turističnih kmetijah z nastanitvijo 2025",
    "Število sob v vseh drugih vrstah NO 2025",
    "Število ležišč v vseh drugih vrstah NO 2025",
    "Povprečna letna zasedenost staln. Ležišč 2024",
    "Ocenjena povp. Letna zased. sob (nedeljivih enot) 2024",
    "Ocenjeni stroški dela v reg. podj. v Gostinski (I) dejavnosti",
    "Ocenjeni stroški dela v reg. podj. v nastan.gost. (I 55) dejavnosti",
}

INDIKATORJI_Z_INDEKSI = {
    'PDB turistov SKUPAJ - 2024',
    'PDB turistov Domači - 2024',
    'PDB turistov Tuji - 2024',
    'PDB turistov SKUPAJ - 2025',
    'PDB turistov Domači - 2025',
    'PDB turistov Tuji - 2025',
    'Pritisk turizma na družbeni prostor (število stalnih ležišč / 100 prebivalcev)',
    'Pritisk turizma na družbeni prostor (število stalnih ležišč / 100 prebivalcev) 2025',
    'Gostota turizma',
    'Gostota turizma 2025',
    "Intenzivnost turizma (število nočitev na dan / 100 prebivalcev)",
    "Intenzivnost turizma (število nočitev na dan / 100 prebivalcev) 2025",
    "Dodana vrednost/zaposl. reg.podjetij Gostinstvu (I)",
    "Dodana vrednost/zaposl. V reg.podjetjih v nast.dejav. (I 55)",
    "Ocenjeni prihodki iz nast. dejav. na prenočitev",
    "Ocenjeni prihodki iz nastan. dej. na razpoložljivo sobo (enoto)",
    "Poraba el.energ. v kWh na realiz. 1000 EUR prihodka v Gostinstvu (I)",
    'Povprečna starost prebivalcev',
    "Stroški dela na zaposl. na leto v reg. podj. v Gostinski (I) dejavnosti",
    "Dodana vrednost/zaposl. V reg.podjetjih v nast.dejav. (I 55)",
    "Stroški dela na zaposl. na leto v reg. podj. v nast.gost. (I 55) dejavnosti",
    "Celotni prihodki v nastan. dejav. na prenočitev",
    "Ocenjeni prihodki iz nast. dejav. na prenočitev",
    "Ocenjeni prihodki iz nast.dej. na prodano sobo (ned.enoto)",
    "Poraba el.energ. v kWh na realiz. 1000 EUR prihodka v Gostinstvu (I)",
    "Skupaj neto prejeti dohodek povp. na prebivalca",
    "Neto prejeti dohodek iz dela, povp. na preb.",
    "Neto prejeti dohodek iz premoženja, kapitala, idr.povp. na preb.",
    "Povprečna mesečna neto  plača/zaposl. osebo (EUR)",
    "Povprečna mesečna neto  plača/zaposl. osebo (EUR) 2025",
    "Povprečna neto plača izplačana na zaposl. osebo v Gostinstvu (I)",
    "Povprečna neto plača izplačana na zaposl. osebo v Gostinstvu (I) 2025",
    
}

INDIKATORJI_Z_OPOMBO = {
    "Zaposleni v Gostinstvu (I) v registr.podjetjih in s.p.",
    "Zaposleni v nastan.dejav. (I55) v registr.podjetjih in s.p.",
    "Vsi delovni aktivni na območju",
    "Delež delovno aktivnih v turizmu (OECD/WTO)",
    "Število vseh vrst podjetij na območju",
    "Prihodek (v 1000 EUR) vseh podjetij na območju",
    "Število reg. podjetij in s.p.  v Gostinstvu (I)",
    "Prihodki reg.podjetij in s.p. v Gostinstvu (I)",
    "Dodana vrednost reg.podjetij v Gostinstvu (I)",
    "Dodana vrednost/zaposl. reg.podjetij Gostinstvu (I)",
    "Ocenjeni stroški dela v reg. podj. v Gostinski (I) dejavnosti",
    "Stroški dela na zaposl. na leto v reg. podj. v Gostinski (I) dejavnosti",
    "Delež stroškov dela v prihodkih v reg. podj. v Gostinstvu (I)",
    "Delež stroškov dela v dod vredn. v reg. podj. v Gostinstvu (I)",
    "EBITDA v reg.podjetjih in s.p. v Gostinstvu (I)",
    "EBITDA marža v reg.podjetjih in s.p. v Gostinstvu (I)",
    "Čisti dobiček/izguba v reg. podj. in s.p. v Gostinstvu (I)",
    "Sredstva v reg. Podjetjih in s.p. v Gostinstvu (I)",
    "Kapital v reg. Podjetjih in s.p. v Gostinstvu (I)",
    "Donosnost sredstev v reg. podjetjih in s.p. v Gostinstvu (I)",
    "Donosnost kapitala v reg. podjetjih in s.p. v Gostinstvu (I)",
    "Dobičkovnost prihodkov v podjetjih in s.p. v Gostinstvu (I)",
    "Število reg. podjetij in s.p. v nastanitveni dejav. (I 55)",
    "Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)",
    "Dodana vrednost reg.podjetij v nastanitveni dejav. (I 55)",
    "Dodana vrednost/zaposl. V reg.podjetjih v nast.dejav. (I 55)",
    "Ocenjeni stroški dela v reg. podj. v nastan.gost. (I 55) dejavnosti",
    "Stroški dela na zaposl. na leto v reg. podj. v nast.gost. (I 55) dejavnosti",
    "Delež stroškov dela v prihodkih v reg. podj. v nast.gost.dej. (I 55)",
    "Delež stroškov dela v dod vredn. v reg. podj. v nast.gost.dej. (I 55)",
    "EBITDA v reg.podjetjih in s.p. v nastanitveni dejav. (I 55)",
    "EBITDA marža v reg.podjetjih v nastanitveni dejav. (I 55)",
    "Čisti dobiček/izguba v reg. podj. v nastanitveni dejav. (I 55)",
    "Sredstva v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)",
    "Kapital v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)",
    "Donosnost sredstev v nastanitveni dejav. (I 55)",
    "Donosnost kapitala v nastanitveni dejav. (I 55)",
    "Dobičkovnost prihodkov v nastanitveni dejav. (I 55)",
    "Celotni prihodki v nastan. dejav. na prenočitev",
    "Ocenjeni prihodki iz nast. dejav. na prenočitev",
    "Ocenjeni prihodki iz nastan. dej. na razpoložljivo sobo (enoto)",
    "Ocenjeni prihodki iz nast.dej. na prodano sobo (ned.enoto)",
    "Poraba el.energ. v kWh na realiz. 1000 EUR prihodka v Gostinstvu (I)"
}

INDIKATORJI_Z_VALUTO = {
    "Prihodki reg.podjetij in s.p. v Gostinstvu (I)",
    "Dodana vrednost reg.podjetij v Gostinstvu (I)",
    "Dodana vrednost/zaposl. reg.podjetij Gostinstvu (I)",
    "Ocenjeni stroški dela v reg. podj. v Gostinski (I) dejavnosti",
    "Stroški dela na zaposl. na leto v reg. podj. v Gostinski (I) dejavnosti",
    "Povprečna neto plača izplačana na zaposl. osebo v Gostinstvu (I)",
    "Povprečna neto plača izplačana na zaposl. osebo v Gostinstvu (I)2025",
    "EBITDA v reg.podjetjih in s.p. v Gostinstvu (I)",
    "Čisti dobiček/izguba v reg. podj. in s.p. v Gostinstvu (I)",
    "Sredstva v reg. Podjetjih in s.p. v Gostinstvu (I)",
    "Kapital v reg. Podjetjih in s.p. v Gostinstvu (I)",
    "Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)",
    "Dodana vrednost reg.podjetij v nastanitveni dejav. (I 55)",
    "Dodana vrednost/zaposl. V reg.podjetjih v nast.dejav. (I 55)",
    "Ocenjeni stroški dela v reg. podj. v nastan.gost. (I 55) dejavnosti",
    "Stroški dela na zaposl. na leto v reg. podj. v nast.gost. (I 55) dejavnosti",
    "EBITDA v reg.podjetjih in s.p. v nastanitveni dejav. (I 55)",
    "Čisti dobiček/izguba v reg. podj. v nastanitveni dejav. (I 55)",
    "Sredstva v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)",
    "Kapital v reg. Podjetjih in s.p. v nastanitveni dejav. (I 55)",
    "Celotni prihodki v nastan. dejav. na prenočitev",
    "Ocenjeni prihodki iz nast. dejav. na prenočitev",
    "Ocenjeni prihodki iz nastan. dej. na razpoložljivo sobo (enoto)",
    "Ocenjeni prihodki iz nast.dej. na prodano sobo (ned.enoto)",
    "Ocena skupne ekonomske velikosti kmetij.gospodarstev",
    "Skupaj neto prejeti dohodek povp. na prebivalca",
    "Neto prejeti dohodek iz dela, povp. na preb.",
    "Neto prejeti dohodek iz premoženja, kapitala, idr.povp. na preb.",
    "Povprečna mesečna neto  plača/zaposl. osebo (EUR)",
    "Povprečna mesečna neto  plača/zaposl. osebo (EUR) 2025",
}

# Pri teh kazalnikih je nižja vrednost praviloma ugodnejša.
LOWER_IS_BETTER_INDICATORS = {
    "Povprečna starost prebivalcev 2024",
    "Povprečna starost prebivalcev 2025",
    "Pritisk turizma na družbeni prostor (število stalnih ležišč / 100 prebivalcev)",
    "Pritisk turizma na družbeni prostor (število stalnih ležišč / 100 prebivalcev) 2025",
    "Gostota turizma",
    "Gostota turizma 2025",
    "Intenzivnost turizma (število nočitev na dan / 100 prebivalcev)",
    "Intenzivnost turizma (število nočitev na dan / 100 prebivalcev) 2025",
    "GINI Indeks - sezonskost prenočitev - 2024",
    "GINI Indeks - sezonskost prenočitev - 2025",
    "Gibanje GINI Indeksa prenoč. 2025/2019",
    "Poraba el.energ. v kWh na realiz. 1000 EUR prihodka v Gostinstvu (I)",
    "Poraba el.energije (MWh) Dejavnost Gostinstvo (I) 2025",
    "Delež stroškov dela v prihodkih v reg. podj. v Gostinstvu (I)",
    "Delež stroškov dela v dod vredn. v reg. podj. v Gostinstvu (I)",
    "Delež stroškov dela v prihodkih v reg. podj. v nast.gost.dej. (I 55)",
    "Delež stroškov dela v dod vredn. v reg. podj. v nast.gost.dej. (I 55)",
    "Število počitniških stanovanj",
}

SKUPNO_OPOZORILO_AGREGACIJA = {
    "type": "warning",
    "title": "Glej opozorilo spodaj glede interpretacije tega kazalnika",
    "text": (
        "Opozorilo oz. razkritje avtorja izračunov kazalnikov: pri izračunih ekonomskih in poslovnih kazalnikov, pri katerih se kombinirajo finančni podatki iz bilanc podjetij in s.p. (vir AJPES) in fizični podatki o številu prenočitev turistov, sob, ležišč ali drugi fizični podatki o določenih količinah kot so poraba energije v kWh, ipd.(vir: SURS), lahko prihaja do nerealnih oz. delno popačenih vrednosti v primerih, kjer so sedeži družb, ki realizirajo finančne kategorije poslovanja v drugih občinah oz. regijah, kot so realizirane prenočitve oz. registrirana ležišča ali sobe, ki jih upravljajo in realizirajo določene količinske rezultate. Takšen primer je recimo: sedež družbe Sava Turizem d.d. je v Ljubljani, kjer so prikazani prihodki in druge poslovne kategorije te družbe, medtem, ko so prenočitve, sobe, ležišča, količinska poraba energije, ipd. prikazani v dejanski občini, kjer delujejo nastanitveni gostinski obrati v lasti in upravljanju te družbe, ipd.. Prav tako v takšnih primerih niso prikazane realne poslovno-finančne kategorije, ki jih realizirajo takšne družbe v občinah oz. regijah, kjer ti učinki dejansko nastajajo (na območjih, kjer nastajajo učinki so torej prikazane poslovno-finančne kategorije nižje od realnih), temveč se pojavljajo v višjih zneskih v enakih kategorijah v občinah oz. regijah kjer so registrirani sedeži takšnih družb oz. podjetij ali s.p. (tam pa so torej prikazane finančne kategorije višje od realnih). Kljub temu je smiselno opazovati te poslovno-finančne kategorije (ki so edine javno na voljo), ob zavedanju tovrstnega popačenja v enakih oz. podobnih primerih. Poslovno finančni kazalniki pa se seveda izravnajo in so realno prikazani na ravni celotne Slovenije."
    )
}


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
    c = col
    keywords = [
        'Naravni prirast /1000 prebival.',
        'Selitveni prirast /1000 prebival.',
        'Delež tujih prenočitev - 2019',
        'Delež tujih prenočitev - 2024',
        'Delež tujih prenočitev - 2025',
        'Rast števila prenočitev 2024/2019 - SKUPAJ',
        'Rast števila prenočitev 2024/2019 - Domači',
        'Rast števila prenočitev 2024/2019 - Tuji',
        'Rast števila prenočitev 2025/2019 - SKUPAJ',
        'Rast števila prenočitev 2025/2019 - Domači',
        'Rast števila prenočitev 2025/2019 - Tuji',
        'Rast števila prenočitev 2025/2024 - SKUPAJ',
        'Rast števila prenočitev 2025/2024 - Domači',
        'Rast števila prenočitev 2025/2024 - Tuji',
        'Delež stalnih ležišč v Hotelih ipd.',
        'Delež sob (ned.enot) v kapacitetah višje kakovosti - (4* in 5*) 2025',
        'Delež sob (enot) v hotelih ipd. NO 2025',
        'Delež stalnih ležišč v hotelih ipd. NO',
        'Delež sob (enot) v kampih 2025',
        'Delež sob (enot) v turističnih kmetijah z nastanitvijo 2025',
        'Delež sob (enot) v vseh drugih vrstah NO 2025',
        'Povprečna letna zasedenost staln. ležišč',
        'Ocenjena povp. Letna zased. sob (nedeljivih enot)',
        'Ocenjena povp. Letna zased. sob (nedeljivih enot) 2025',
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
    return any(k in c for k in keywords)

def is_lower_better(indicator: str) -> bool:
    return indicator in LOWER_IS_BETTER_INDICATORS

def is_percent_like(col: str) -> bool:
    c = col.lower()

    # stvari, ki so *deleži/indeksi* 
    positive = ["delež", "marža", "%", "stopnja", "povprečna letna zasedenost", "ocenjena povp", "donosnost", "dobičkovnost", "rast števila prenočitev"]

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

def get_agg_rule(indicator: str, agg_rules: dict) -> tuple[str, str | None]:
    return agg_rules.get(indicator, ("sum", None))

def get_default_population_base(indicator: str) -> str:
    if "2025" in indicator:
        return "Število prebivalcev (H2/2025)"
    return "Število prebivalcev (H2/2024)"

def get_sum_comparison_base(indicator: str) -> tuple[str, str]:
    lower = indicator.lower()
    pop_base = get_default_population_base(indicator)

    if indicator in {"Število prebivalcev (H2/2024)", "Število prebivalcev (H2/2025)"}:
        return "Površina območja (km2)", "delež površine"
    if indicator == "Površina območja (km2)":
        return pop_base, "delež prebivalstva"
    if "starih 15 let ali več s srednješolsko" in lower or "starih 15 let ali več z izobrazbo višjo" in lower:
        return "Število prebivalcev starih 15 let ali več na območju", "delež prebivalcev 15+"
    if "starih 15 let ali več na območju" in lower:
        return pop_base, "delež prebivalstva"
    if "delovno aktivno prebivalstvo v turizmu" in lower:
        if "2025" in indicator:
            return "Vsi delovno aktivni na območju 2025", "delež vseh delovno aktivnih"
        return "Vsi delovni aktivni na območju", "delež vseh delovno aktivnih"
    if "zaposl" in lower and "gostinstvu" in lower:
        return "Vsi delovni aktivni na območju", "delež vseh delovno aktivnih"
    if "zaposleni v nastan.dejav" in lower:
        return "Vsi delovni aktivni na območju", "delež vseh delovno aktivnih"
    if "število reg. podjetij" in lower and ("gostinstvu" in lower or "nastanitveni dejav" in lower):
        return "Število vseh vrst podjetij na območju", "delež vseh podjetij"
    if any(k in lower for k in ["prihodki", "dodana vrednost", "stroški dela", "ebitda", "dobiček", "izguba", "sredstva", "kapital"]):
        if "gostinstvu" in lower:
            return "Zaposleni v Gostinstvu (I) v registr.podjetjih in s.p.", "delež zaposlenih v gostinstvu"
        if "nastanitveni dejav" in lower:
            return "Zaposleni v nastan.dejav. (I55) v registr.podjetjih in s.p.", "delež zaposlenih v nastanitvi"
    if "poraba el.energije" in lower and "gostinstvo" in lower:
        return "Prihodki reg.podjetij in s.p. v Gostinstvu (I)", "delež prihodkov v gostinstvu"
    if any(k in lower for k in ["prenočitve", "prihodi turistov", "nastanitvene kapacitete", "nastanitvenih obratov", "hotelov", "kampov", "turističnih kmetij", "ležišč", "sob ", "nedeljive enote"]):
        return pop_base, "delež prebivalstva"
    if any(k in lower for k in ["stanovanj", "gradbenih dovoljenj", "dijakov", "študentov", "odpadki", "dohodek", "plača"]):
        return pop_base, "delež prebivalstva"
    if any(k in lower for k in ["kmetijskih", "kmetij."]):
        return "Površina območja (km2)", "delež površine"
    return pop_base, "delež prebivalstva"

def compute_indicator_comparison(
    reg_df: pd.DataFrame,
    indicator: str,
    agg_rules: dict,
    region_name: str,
    df_slo_total_num: pd.Series,
):
    v_reg = aggregate_indicator_with_rules(reg_df, indicator, agg_rules, region_name)
    v_slo = df_slo_total_num.get(indicator, np.nan)

    if pd.isna(v_reg) or pd.isna(v_slo) or float(v_slo) == 0:
        return None

    rule, _ = get_agg_rule(indicator, agg_rules)
    direction = -1.0 if is_lower_better(indicator) else 1.0
    delta_raw = ((float(v_reg) - float(v_slo)) / abs(float(v_slo))) * 100.0
    delta_unit = "%"
    comparison_method = "Neposredno glede na slovensko osnovo"

    if rule == "sum":
        base_indicator, base_label = get_sum_comparison_base(indicator)
        if base_indicator in reg_df.columns:
            base_reg = aggregate_indicator_with_rules(reg_df, base_indicator, agg_rules, region_name)
            base_slo = df_slo_total_num.get(base_indicator, np.nan)
            if not pd.isna(base_reg) and not pd.isna(base_slo) and float(base_slo) != 0:
                indicator_share = float(v_reg) / float(v_slo)
                benchmark_share = float(base_reg) / float(base_slo)
                delta_raw = (indicator_share - benchmark_share) * 100.0
                delta_unit = "o.t."
                comparison_method = f"Delež kazalnika glede na {base_label}"

    delta_aligned = direction * delta_raw
    return {
        "Kazalnik": indicator,
        "Smer kazalnika": "Nižje je bolje" if direction < 0 else "Višje je bolje",
        "Vrednost območja": format_indicator_value_map(indicator, v_reg),
        "Osnova (Slovenija)": format_indicator_value_map(indicator, v_slo),
        "Metoda primerjave": comparison_method,
        "Odstopanje_raw": delta_raw,
        "Odstopanje_aligned_raw": delta_aligned,
        "Enota odstopanja": delta_unit,
    }

def build_top_bottom_group_sections(
    reg_df: pd.DataFrame,
    df_slo_total_num: pd.Series,
    grouped_filtered: dict[str, list[str]],
    agg_rules: dict,
    region_name: str,
) -> list[dict]:
    sections = []
    for group_name in TOP_BOTTOM_GROUP_ORDER:
        group_indicators = [
            ind for ind in grouped_filtered.get(group_name, [])
            if ind not in TOP_BOTTOM_EXCLUDED_INDICATORS
        ]
        comparison_rows = []
        for ind in group_indicators:
            row = compute_indicator_comparison(
                reg_df=reg_df,
                indicator=ind,
                agg_rules=agg_rules,
                region_name=region_name,
                df_slo_total_num=df_slo_total_num,
            )
            if row is not None:
                row["Skupina kazalnikov"] = group_name
                comparison_rows.append(row)

        if not comparison_rows:
            continue

        group_df = pd.DataFrame(comparison_rows)
        limit = min(TOP_BOTTOM_GROUP_LIMITS.get(group_name, 5), len(group_df))
        best_df = group_df.nlargest(limit, "Odstopanje_aligned_raw").copy()

        remaining_df = group_df.drop(best_df.index)
        if len(remaining_df) >= limit:
            worst_df = remaining_df.nsmallest(limit, "Odstopanje_aligned_raw").copy()
        else:
            worst_df = group_df.nsmallest(limit, "Odstopanje_aligned_raw").copy()

        for tbl in (best_df, worst_df):
            tbl["Odstopanje glede na smer"] = tbl.apply(
                lambda row: format_comparison_delta(row["Odstopanje_aligned_raw"], row["Enota odstopanja"]),
                axis=1,
            )
            tbl["Primerjalni odmik"] = tbl.apply(
                lambda row: format_comparison_delta(row["Odstopanje_raw"], row["Enota odstopanja"]),
                axis=1,
            )

        ai_cols = [
            "Kazalnik",
            "Smer kazalnika",
            "Vrednost območja",
            "Osnova (Slovenija)",
            "Metoda primerjave",
            "Odstopanje glede na smer",
            "Primerjalni odmik",
        ]
        sections.append({
            "group": group_name,
            "limit": limit,
            "best_df": best_df,
            "worst_df": worst_df,
            "top_rows": best_df[ai_cols].to_dict("records"),
            "bottom_rows": worst_df[ai_cols].to_dict("records"),
        })

    return sections

def format_si_number(x, decimals=None):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    try:
        x = float(x)
        if decimals is None:
            if abs(x - round(x)) < 1e-9:
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

def format_comparison_delta(x, unit: str) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    suffix = " %" if unit == "%" else " o.t."
    return f"{'+' if float(x) >= 0 else ''}{format_si_number(float(x), 1)}{suffix}"
    
def format_indicator_value_tables(indicator: str, x):
    # deleži/indeksi so v podatkih v obliki 0.45 -> prikaz 45 %
    if is_percent_like(indicator):
        
        return round(x, 3)
    # vse ostalo ostane normalno število
    return round(x, 2)

def format_indicator_value_map(indicator: str, x):
    # deleži/indeksi so v podatkih v obliki 0.45 -> prikaz 45 %
    if is_percent_like(indicator):
        return format_pct(float(x) * 100.0, 1)
    #GINI indeks izjema
    elif "GINI" in indicator:
        return format(round(x,2), ".2f")
    elif indicator in INDIKATORJI_Z_VALUTO:
        return f"{format_si_number(x)} €"
    # vse ostalo ostane normalno število
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

@st.cache_data(show_spinner=False)
def image_path_to_data_uri(path_str: str) -> str | None:
    source = Path(path_str)
    if not source.exists():
        return None
    suffix = source.suffix.lower()
    mime = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    raw = base64.b64encode(source.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{raw}"

@st.cache_data(show_spinner=False)
def load_title_slideshow_images() -> list[str]:
    title_dir = Path(__file__).parent / "Title"
    if not title_dir.exists() or not title_dir.is_dir():
        fallback = image_path_to_data_uri(str(Path(__file__).parent / "Title.jpg"))
        return [fallback] if fallback else []

    def natural_sort_key(path: Path):
        parts = re.split(r"(\d+)", path.name.lower())
        return [int(part) if part.isdigit() else part for part in parts]

    image_paths = sorted(
        [p for p in title_dir.iterdir() if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}],
        key=natural_sort_key,
    )
    image_uris = [image_path_to_data_uri(str(path)) for path in image_paths]
    image_uris = [uri for uri in image_uris if uri]

    if image_uris:
        return image_uris

    fallback = image_path_to_data_uri(str(Path(__file__).parent / "Title.jpg"))
    return [fallback] if fallback else []

def load_button_font(font_size: int):
    if ImageFont is None:
        return None
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
    except Exception:
        try:
            return ImageFont.truetype("Arial Bold.ttf", font_size)
        except Exception:
            return ImageFont.load_default()

@st.cache_data(show_spinner=False)
def prepare_group_button_image(
    path_str: str,
    label: str = "",
    canvas_px: int = 360,
    inset_ratio: float = 0.78,
) -> str | None:
    source = Path(path_str)
    if not source.exists():
        return None
    if Image is None or ImageDraw is None:
        return str(source)

    try:
        render_version = "v4"
        signature = f"{render_version}|{source.resolve()}|{source.stat().st_mtime_ns}|{label}|{canvas_px}|{inset_ratio}"
        cache_name = hashlib.md5(signature.encode("utf-8")).hexdigest()[:16]
        cache_dir = Path(tempfile.gettempdir()) / "streamlit_button_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        out_path = cache_dir / f"{source.stem}_{cache_name}.png"
        if out_path.exists():
            return str(out_path)

        with Image.open(source) as img:
            img = img.convert("RGBA")
            side = max(120, int(canvas_px))
            has_label = bool(label.strip())
            label_band_height = int(side * 0.31) if has_label else 0
            image_area_height = side - label_band_height - int(side * 0.04)
            fit_width = max(1, int(side * inset_ratio))
            fit_height = max(1, int(image_area_height * 0.88))
            scale = min(fit_width / max(1, img.width), fit_height / max(1, img.height))
            new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            resized = img.resize(new_size, resampling)

            # Square canvas prevents cropping when the component enforces square tiles.
            square = Image.new("RGBA", (side, side), (248, 250, 252, 255))
            offset = ((side - new_size[0]) // 2, max(8, (image_area_height - new_size[1]) // 2))
            square.paste(resized, offset, resized)

            if has_label:
                band_top = side - label_band_height
                draw = ImageDraw.Draw(square)
                draw.rectangle([(0, band_top), (side, side)], fill=(255, 255, 255, 245))
                text_color = (28, 37, 54, 255)
                best_text = label
                best_font = load_button_font(max(14, int(side * 0.06)))
                best_overflow = None
                spacing = 4
                max_text_width = side * 0.88
                band_inner_top = band_top + int(side * 0.025)
                band_inner_bottom = side - int(side * 0.04)
                max_text_height = max(1, band_inner_bottom - band_inner_top)

                manual_multiline = "\n" in label

                for font_size in range(max(18, int(side * 0.074)), 11, -1):
                    font = load_button_font(font_size)
                    if font is None:
                        continue
                    candidate_texts = [label] if manual_multiline else [textwrap.fill(label, width=wrap_width) for wrap_width in range(10, 22)]
                    for wrapped in candidate_texts:
                        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, align="center", spacing=spacing)
                        text_width = bbox[2] - bbox[0]
                        text_height = bbox[3] - bbox[1]
                        overflow = max(text_width - max_text_width, 0) + max(text_height - max_text_height, 0)

                        if best_overflow is None or overflow < best_overflow:
                            best_overflow = overflow
                            best_text = wrapped
                            best_font = font

                        if overflow <= 0:
                            best_text = wrapped
                            best_font = font
                            best_overflow = overflow
                            break
                    if best_overflow == 0:
                        break

                text_bbox = draw.multiline_textbbox((0, 0), best_text, font=best_font, align="center", spacing=spacing)
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]
                text_x = (side - text_width) / 2
                text_y = band_inner_top + max((max_text_height - text_height) / 2, 0) - text_bbox[1]
                draw.multiline_text(
                    (text_x, text_y),
                    best_text,
                    fill=text_color,
                    font=best_font,
                    align="center",
                    spacing=spacing,
                )

            square.save(out_path, format="PNG", optimize=True)
        return str(out_path)
    except Exception:
        return str(source)

def try_load_geojson(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
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
    groups = {}
    for col in df_map.columns:
        series = df_map[col].dropna().astype(str).str.strip()
        values = [v for v in series.tolist() if v]
        if values:
            groups[col] = values
    return groups

def get_secret_value(name: str, default=None):
    try:
        return st.secrets[name]
    except Exception:
        return default

def _sql(stmt: str):
    return sql_text(stmt) if sql_text is not None else stmt

def get_ai_cache_connection():
    conn_name = get_secret_value("AI_CACHE_CONNECTION_NAME", AI_CACHE_CONNECTION_NAME_DEFAULT)
    try:
        return st.connection(conn_name, type="sql"), conn_name
    except Exception:
        return None, conn_name

def ensure_ai_cache_table(conn) -> bool:
    try:
        with conn.session as s:
            s.execute(_sql(f"""
                CREATE TABLE IF NOT EXISTS {AI_CACHE_TABLE_NAME} (
                    cache_key TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    region TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    response_text TEXT NOT NULL,
                    model TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            s.commit()
        return True
    except Exception:
        return False

def get_cached_ai_commentary(cache_key: str) -> dict | None:
    conn, _ = get_ai_cache_connection()
    if conn is None or not ensure_ai_cache_table(conn):
        return None
    try:
        df_cached = conn.query(
            f"""
            SELECT region, group_name, response_text, model, updated_at
            FROM {AI_CACHE_TABLE_NAME}
            WHERE cache_key = :cache_key
            LIMIT 1
            """,
            params={"cache_key": cache_key},
            ttl=0,
        )
    except Exception:
        return None

    if df_cached is None or df_cached.empty:
        return None
    row = df_cached.iloc[0]
    return {
        "region": row.get("region"),
        "group_name": row.get("group_name"),
        "text": row.get("response_text", ""),
        "source": "db_cache",
        "model": row.get("model"),
        "updated_at": row.get("updated_at"),
    }

def store_cached_ai_commentary(
    cache_key: str,
    *,
    payload_hash: str,
    region_name: str,
    group_name: str,
    text: str,
    model: str,
) -> None:
    conn, _ = get_ai_cache_connection()
    if conn is None or not ensure_ai_cache_table(conn):
        return
    try:
        with conn.session as s:
            s.execute(
                _sql(f"""
                    INSERT INTO {AI_CACHE_TABLE_NAME}
                        (cache_key, payload_hash, region, group_name, response_text, model, updated_at)
                    VALUES
                        (:cache_key, :payload_hash, :region, :group_name, :response_text, :model, NOW())
                    ON CONFLICT (cache_key)
                    DO UPDATE SET
                        payload_hash = EXCLUDED.payload_hash,
                        region = EXCLUDED.region,
                        group_name = EXCLUDED.group_name,
                        response_text = EXCLUDED.response_text,
                        model = EXCLUDED.model,
                        updated_at = NOW()
                """),
                {
                    "cache_key": cache_key,
                    "payload_hash": payload_hash,
                    "region": region_name,
                    "group_name": group_name,
                    "response_text": text,
                    "model": model,
                },
            )
            s.commit()
    except Exception:
        return

def rows_to_prompt_lines(rows: list[dict]) -> str:
    if not rows:
        return "- Ni podatkov."
    lines = []
    for row in rows[:5]:
        indicator = row.get("Kazalnik", "—")
        direction = row.get("Smer kazalnika", "—")
        region_val = row.get("Vrednost območja", "—")
        baseline_val = row.get("Osnova (Slovenija)", "—")
        comparison_method = row.get("Metoda primerjave", "—")
        aligned_delta = row.get("Odstopanje glede na smer", row.get("Odstopanje od osnove", "—"))
        raw_delta = row.get("Primerjalni odmik", row.get("Odstopanje od osnove", "—"))
        lines.append(
            f"- {indicator} | smer: {direction} | območje: {region_val} | Slovenija: {baseline_val} | "
            f"primerjava: {comparison_method} | odstopanje glede na smer: {aligned_delta} | primerjalni odmik: {raw_delta}"
        )
    return "\n".join(lines)

def grouped_rows_to_prompt_text(group_sections: list[dict]) -> str:
    if not group_sections:
        return "Ni podatkov po skupinah."
    blocks = []
    for section in group_sections:
        group_name = section.get("group", "Neznana skupina")
        top_rows = section.get("top_rows", [])
        bottom_rows = section.get("bottom_rows", [])
        blocks.append(
            f"{group_name}\n"
            f"TOP:\n{rows_to_prompt_lines(top_rows)}\n"
            f"BOTTOM:\n{rows_to_prompt_lines(bottom_rows)}"
        )
    return "\n\n".join(blocks)

def fallback_region_commentary(region_name: str, group_sections: list[dict]) -> str:
    summary_parts = []
    for section in group_sections:
        group_name = section.get("group", "Neznana skupina")
        top_names = ", ".join([r.get("Kazalnik", "—") for r in section.get("top_rows", [])[:2]]) or "ni podatkov"
        bottom_names = ", ".join([r.get("Kazalnik", "—") for r in section.get("bottom_rows", [])[:2]]) or "ni podatkov"
        summary_parts.append(f"{group_name}: prednosti {top_names}; tveganja {bottom_names}")

    summary_txt = " | ".join(summary_parts) if summary_parts else "Ni dovolj podatkov za skupinsko primerjavo."
    return (
        f"**Povzetek za območje {region_name}:** {summary_txt}. Primerjava je glede na slovensko osnovo.\n\n"
        f"**Priporočila:**\n"
        f"1. Ukrepe določite ločeno po skupinah kazalnikov, ne samo na ravni celotnega območja.\n"
        f"2. Pri najslabših kazalnikih v vsaki skupini določite 2-3 ciljne ukrepe z nosilci in roki.\n"
        f"3. Spremljajte napredek po skupinah in preverjajte, ali se slabši kazalniki približujejo slovenski osnovi."
    )

def extract_response_text(resp_json: dict) -> str | None:
    direct = resp_json.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    for item in resp_json.get("output", []):
        for content in item.get("content", []):
            txt = content.get("text")
            if isinstance(txt, str) and txt.strip():
                return txt.strip()
    return None

def extract_openai_error_fields(resp) -> tuple[str | None, str | None, str | None]:
    try:
        data = resp.json()
    except Exception:
        return None, None, None
    err = data.get("error", {}) if isinstance(data, dict) else {}
    if not isinstance(err, dict):
        return None, None, None
    message = err.get("message")
    err_type = err.get("type")
    code = err.get("code")
    if message is not None:
        message = str(message).strip()
    if err_type is not None:
        err_type = str(err_type).strip()
    if code is not None:
        code = str(code).strip()
    return message or None, err_type or None, code or None

def format_openai_http_error(resp) -> str:
    status = resp.status_code
    message, err_type, code = extract_openai_error_fields(resp)
    parts = [f"AI klic ni uspel (HTTP {status})"]
    if code:
        parts.append(f"koda: {code}")
    if err_type:
        parts.append(f"tip: {err_type}")
    if message:
        parts.append(f"podrobnosti: {message}")
    return ". ".join(parts) + "."

def should_retry_openai_call(status_code: int, err_type: str | None, err_code: str | None) -> bool:
    if status_code in {500, 502, 503, 504}:
        return True
    if status_code == 429:
        # Do not retry if account quota is exhausted.
        if err_code == "insufficient_quota" or err_type == "insufficient_quota":
            return False
        return True
    return False

def compute_retry_delay_seconds(resp, attempt_index: int) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            sec = float(retry_after)
            if sec > 0:
                return min(sec, 20.0)
        except Exception:
            pass
    # Exponential backoff: 1.5s, 3s, 6s
    return min(1.5 * (2 ** attempt_index), 20.0)

def generate_region_ai_commentary(region_name: str, group_sections: list[dict]) -> tuple[str, str, str | None]:
    api_key = get_secret_value("OPENAI_API_KEY")
    if not api_key or requests is None:
        return fallback_region_commentary(region_name, group_sections), "fallback", None

    model = get_secret_value("OPENAI_MODEL", "gpt-5.4")
    system_prompt = (
        "Si analitik regionalnega razvoja turizma. Uporabi samo podane kazalnike in podaj kratko, "
        "praktično razlago ter priporočila."
    )
    user_prompt = (
        f"Območje: {region_name}\n\n"
        f"Top/Bottom po skupinah kazalnikov:\n{grouped_rows_to_prompt_text(group_sections)}\n\n"
        "Naloga:\n"
        "1) Napiši kratek celosten komentar (5-7 stavkov), ki povzema stanje po vseh štirih skupinah kazalnikov.\n"
        "2) Jasno loči, katere so glavne prednosti in katera tveganja izstopajo po posameznih skupinah.\n"
        "3) Dodaj 4 konkretna priporočila za izboljšanje, pri čemer naj priporočila pokrijejo več skupin kazalnikov.\n"
        "4) Uporabi samo podane podatke, brez izmišljenih razlag ali številk.\n"
        "5) Piši v slovenščini, profesionalno, jedrnato."
    )

    payload = {
        "model": model,
        "temperature": 0.3,
        "max_output_tokens": 2000,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_prompt}],
            },
        ],
    }

    try:
        max_attempts = 3
        for attempt in range(max_attempts):
            resp = requests.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(payload),
                timeout=35,
            )

            if resp.status_code < 400:
                text = extract_response_text(resp.json())
                if not text:
                    err = "AI odgovor je bil prazen."
                    return fallback_region_commentary(region_name, group_sections), "fallback", err
                return text, "ai", None

            message, err_type, err_code = extract_openai_error_fields(resp)
            if attempt < max_attempts - 1 and should_retry_openai_call(resp.status_code, err_type, err_code):
                time.sleep(compute_retry_delay_seconds(resp, attempt))
                continue

            if resp.status_code == 429 and (err_code == "insufficient_quota" or err_type == "insufficient_quota"):
                err = (
                    "AI klic ni uspel (HTTP 429). Kvota za OPENAI_API_KEY je porabljena "
                    "(insufficient_quota). Preveri billing/kvote na platform.openai.com."
                )
            else:
                err = format_openai_http_error(resp)
            return fallback_region_commentary(region_name, group_sections), "fallback", err
    except Exception as e:
        return fallback_region_commentary(region_name, group_sections), "fallback", str(e)



def aggregate_indicator_with_rules(df: pd.DataFrame, indicator: str, agg_rules: dict, region):
    if "Gibanje GINI Indeksa prenoč. 2024/2019" in indicator :
        num_dict = {
            "Slovenska Istra" :102.0,
            "Julijske Alpe": 108.7, 
            "Gorenjska": 128.3,
            "Goriško, Vipava, Kras": 117.2,
            "Savinjsko, Celje, Obsotelje in Kozjansko": 112.3,
            "Dolenjska, Bela Krajina in Kočevsko": 99.7,
            "Ljubljana in osrednja Slovenija": 98.2, 
            "Štajerska (Maribor, Pohorje, Ptuj)": 98.2,
            "Zgornje Savinjska, Šaleška in Koroška": 117.3,
            "Pomurje": 131.9,
            "Posavje": 89.8,
            "Ankaran": 92.5,
            "Bela Krajina": 107.8,
            "Bled": 108.5,
            "Bohinj": 95.3,
            "Brda": 121.1,
            "Celje": 109.1,
            "Cerklje": 108.5,
            "Cerkno": 104.6,
            "Čatež in Posavje": 89.9,
            "Dobrna": 60.2,
            "Dolenjska ": 76.7,
            "Dolina Soče": 105.7,
            "Idrija": 120.4,
            "Izola": 90.9,
            "Kamnik": 104.5,
            "Kočevsko" : 129.6,
            "Koper": 119.4,
            "Koroška": 114.9,
            "Kranj": 182.6,
            "Kranjska Gora": 109.5,
            "Kras": 109.2,
            "Laško": 90.4,
            "Ljubljana": 98.5,
            "Maribor - Pohorje": 92.8,
            "Nova Gorica in Vipavska dolina": 142.1,
            "Podčetrtek": 86.6,
            "Portorož - Piran": 103.5,
            "Ptuj": 99.5,
            "Radovljica": 109.5,
            "Rogaška Slatina": 130.9,
            "Rogla-Pohorje": 95.4,
            "Škofja Loka": 104.0,
            "Velenje - Topolšica": 159.5,
            "Zeleni Kras": 103.7,
            "Zgornja Savinjska dolina": 111.1,
            "Zasavje": 59.4,
            "Dežela pod Karavankami": 109.5,
            "Dežela pod Storžičem-Jezersko": 107.2,
            "Dežela suhe robe": 121.6,
            "Haloze": 103.1,
            "Jeruzalem - Ormož": 177.7,
            "Dolina Voglajne": 107.2,
            "Spodnja Savinjska Dolina": 92.8,
            "Alpska Slovenija": 110.3,
            "Mediteranska Slovenija": 104.4,
            "Osrednja Slovenija in Ljubljana": 101.5,
            "Termalna panonska Slovenija": 105.7
        }

        if region in num_dict.keys():
            return num_dict[region]
    
    if "GINI Indeks - sezonskost prenočitev - 2025" in indicator :
        num_dict = {'Slovenska Istra': 0.3764876496411522,
                    'Julijske Alpe': 0.4452252370330385,
                    'Gorenjska': 0.324787552694939,
                    'Goriško, Vipava, Kras': 0.3414449949424754,
                    'Savinjsko, Celje, Obsotelje in Kozjansko': 0.1055199517632115,
                    'Dolenjska, Bela Krajina in Kočevsko': 0.21124381463520803,
                    'Ljubljana in osrednja Slovenija': 0.23523946737768442,
                    'Štajerska (Maribor, Pohorje, Ptuj)': 0.145742716311569,
                    'Zgornje Savinjska, Šaleška in Koroška': 0.32694317150645247,
                    'Pomurje': 0.13403248647190102,
                    'Posavje': 0.23229533347200115,
                    'Ankaran': 0.4357100234542697,
                    'Bela Krajina': 0.49020975251494125,
                    'Bled': 0.3785475744949536,
                    'Bohinj': 0.4385352632723508,
                    'Brda': 0.4241196241692765,
                    'Celje': 0.13992582342435111,
                    'Cerklje': 0.2876691696968393,
                    'Cerkno': 0.31919275123558477,
                    'Čatež in Posavje': 0.23229533347200115,
                    'Dobrna': 0.05329213827211854,
                    'Dolenjska ': 0.1276364275442664,
                    'Dolina Soče': 0.6111132181663749,
                    'Idrija': 0.3037915445201851,
                    'Izola': 0.39217616699426416,
                    'Kamnik': 0.40680442604879463,
                    'Kočevsko': 0.2750451151982596,
                    'Koper': 0.4840011412545189,
                    'Koroška': 0.2408271237963142,
                    'Kranj': 0.2472390007857861,
                    'Kranjska Gora': 0.31810803618508043,
                    'Kras': 0.32721589471019985,
                    'Laško': 0.08005493853615064,
                    'Ljubljana': 0.23109570701222903,
                    'Maribor - Pohorje': 0.1362495454695022,
                    'Nova Gorica in Vipavska dolina': 0.2547356691501057,
                    'Podčetrtek': 0.11699362319358553,
                    'Portorož - Piran': 0.34168165678568696,
                    'Ptuj': 0.2591979023329253,
                    'Radovljica': 0.6448870066592807,
                    'Rogaška Slatina': 0.09465496429016551,
                    'Rogla-Pohorje': 0.2435891574652148,
                    'Škofja Loka': 0.422940747435654,
                    'Velenje - Topolšica': 0.19122149799355148,
                    'Zeleni Kras': 0.4365909696026986,
                    'Zgornja Savinjska dolina': 0.5523832496044765,
                    'Zasavje': 0.1335160562942227,
                    'Dežela pod Karavankami': 0.4795796579337286,
                    'Dežela pod Storžičem-Jezersko': 0.5119221497708111,
                    'Dežela suhe robe': 0.3336629312239068,
                    'Haloze': 0.40572149616420394,
                    'Jeruzalem - Ormož': 0.3480701561177296,
                    'Dolina Voglajne': 0.40829511876768687,
                    'Spodnja Savinjska Dolina': 0.2996528610541874,
                    'Alpska Slovenija': 0.3823581168367557,
                    'Mediteranska Slovenija': 0.3692930910480988,
                    'Osrednja Slovenija in Ljubljana': 0.244510198775449,
                    'Termalna panonska Slovenija': 0.15291999846843807}

        if region in num_dict.keys():
            return num_dict[region]
    
    if "Gibanje GINI Indeksa prenoč. 2025/2019" in indicator :
        num_dict = {'Slovenska Istra': 100.35428320601302,
                    'Julijske Alpe': 109.08183907036356,
                    'Gorenjska': 138.17761836782358,
                    'Goriško, Vipava, Kras': 123.93983073505606,
                    'Savinjsko, Celje, Obsotelje in Kozjansko': 114.17358932883543,
                    'Dolenjska, Bela Krajina in Kočevsko': 99.37950296201717,
                    'Ljubljana in osrednja Slovenija': 101.78732335827748,
                    'Štajerska (Maribor, Pohorje, Ptuj)': 98.6291836773505,
                    'Zgornje Savinjska, Šaleška in Koroška': 119.0771350171818,
                    'Pomurje': 138.7309133821649,
                    'Posavje': 97.76073149648599,
                    'Ankaran': 92.35218855377471,
                    'Bela Krajina': 105.13300231802984,
                    'Bled': 108.46566568560738,
                    'Bohinj': 96.67032584341408,
                    'Brda': 116.76433083357014,
                    'Celje': 88.92045230642707,
                    'Cerklje': 115.10301046968338,
                    'Cerkno': 97.0137628745858,
                    'Čatež in Posavje': 97.76073149648599,
                    'Dobrna': 67.0382724607493,
                    'Dolenjska ': 86.48870644335027,
                    'Dolina Soče': 103.28052563675041,
                    'Idrija': 144.1640208841851,
                    'Izola': 91.44066982231449,
                    'Kamnik': 118.58559806455222,
                    'Kočevsko': 128.71788046244959,
                    'Koper': 122.80266415850882,
                    'Koroška': 109.48199553659683,
                    'Kranj': 205.79402855354454,
                    'Kranjska Gora': 104.28209053110457,
                    'Kras': 118.20650808896198,
                    'Laško': 92.35427301207905,
                    'Ljubljana': 101.4617842164609,
                    'Maribor - Pohorje': 98.977665016376,
                    'Nova Gorica in Vipavska dolina': 159.02226833306662,
                    'Podčetrtek': 98.58677797312706,
                    'Portorož - Piran': 99.60928607460905,
                    'Ptuj': 113.5872700037615,
                    'Radovljica': 108.6934513206192,
                    'Rogaška Slatina': 119.07019480894918,
                    'Rogla-Pohorje': 90.5254248526441,
                    'Škofja Loka': 108.468867299028,
                    'Velenje - Topolšica': 155.86505353942923,
                    'Zeleni Kras': 108.03087528956112,
                    'Zgornja Savinjska dolina': 107.84809907090667,
                    'Zasavje': 63.29069475254023,
                    'Dežela pod Karavankami': 106.71978301292395,
                    'Dežela pod Storžičem-Jezersko': 105.14079772808469,
                    'Dežela suhe robe': 113.50082182405778,
                    'Haloze': 104.65038871299363,
                    'Jeruzalem - Ormož': 187.31875729086752,
                    'Dolina Voglajne': 123.86607553639335,
                    'Spodnja Savinjska Dolina': 94.98662017366016,
                    'Alpska Slovenija': 0.3823581168367557,
                    'Mediteranska Slovenija': 0.3692930910480988,
                    'Osrednja Slovenija in Ljubljana': 0.244510198775449,
                    'Termalna panonska Slovenija': 0.15291999846843807
                    }

        if region in num_dict.keys():
            return num_dict[region]
    
    if "Celotni prihodki v nastan. dejav. na prenočitev" in indicator :

        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"].astype(float))
        values2 = sum(df['Prenočitve turistov SKUPAJ - 2024'])


        
        return values1/values2

    if "Ocenjeni prihodki iz nast. dejav. na prenočitev" in indicator :

        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"].astype(float)) * 0.8
        values2 = sum(df['Prenočitve turistov SKUPAJ - 2024'])
  

        
        return values1/values2

    if "Ocenjeni prihodki iz nast.dej. na prodano sobo (ned.enoto)" in indicator:

        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"] * 0.8)
        
        hoteli = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Hoteli in podobni obrati'])
        druge_enote = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet'])
        kampi = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Kampi'])

        vse_enote = hoteli + druge_enote + kampi

        hoteli_zasedenost = 1.6* (hoteli/vse_enote)
        kampi_zasedenost = 2.5* (kampi/vse_enote)
        druge_zasedenost = 2 * (druge_enote/vse_enote)
        
        values2 = sum(df["Prenočitve turistov SKUPAJ - 2024"])/ (hoteli_zasedenost + kampi_zasedenost + druge_zasedenost)
           
        return values1/values2
    
    if "Ocenjeni prihodki iz nastan. dej. na razpoložljivo sobo (enoto)" in indicator:
        
        values1 = sum(df["Prihodki reg.podjetij in s.p. v nastanitveni dejav. (I 55)"] * 0.8)
        
        hoteli = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Hoteli in podobni obrati'])
        druge_enote = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Druge vrste kapacitet'])
        kampi = sum(df['Struktura nastanitvenih kapacitet - Sobe (nedeljive enote) - Kampi'])

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
            agg_rules,
            r
        )
        for r in regions]
    
    return out

def shorten_label(s: str, max_len: int = 22) -> str:
    s = str(s).strip()
    return s if len(s) <= max_len else s[: max_len - 1] + "…"

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



def make_localized_column_config(df: pd.DataFrame):
    cfg = {}
    for c in df.columns:
        if pd.api.types.is_numeric_dtype(df[c]):
            if is_percent_like(c):
                cfg[c] = st.column_config.NumberColumn(format="percent")
            elif c in INDIKATORJI_Z_VALUTO:
                cfg[c] = st.column_config.NumberColumn(format="euro")
            else:
                cfg[c] = st.column_config.NumberColumn(format="localized")
    return cfg

def get_market_cols_for_year(df: pd.DataFrame, year: int) -> tuple[list[str], list[str]]:
    # pobere samo stolpce: "Delež vseh prenočitev - ... - YYYY"
    pattern = re.compile(rf"^{re.escape(MARKET_PREFIX)}(.+?)\s*-\s*{year}\s*$")
    cols = []
    labels = []
    for c in df.columns:
        m = pattern.match(str(c))
        if m:
            cols.append(c)
            labels.append(m.group(1).strip())  # ime trga brez letnice
    return cols, labels

def col_for_year(col_name: str, year: int) -> str:
    """
    Zamenja katerokoli 4-mestno letnico v imenu stolpca z izbrano letnico.
    Primer: 'Prenočitve turistov SKUPAJ - 2024' -> '... - 2025'
            'Delež vseh prenočitev - Domači trg - 2024' -> '... - 2025' (če ima letnico)
    """
    return re.sub(r"(19|20)\d{2}", str(year), col_name)

def show_shared_warning_if_needed_indicator(indicator_name: str):
    if indicator_name not in INDIKATORJI_Z_OPOMBO:
        return

    msg = SKUPNO_OPOZORILO_AGREGACIJA
    body = f"{msg['title']}"

    st.warning(body, icon="⚠️")

def show_shared_warning_if_needed_map(indicator_name: str):
    if indicator_name not in INDIKATORJI_Z_OPOMBO:
        return

    msg = SKUPNO_OPOZORILO_AGREGACIJA
    body = f"{msg['text']}"

    st.warning(body, icon="⚠️")

def green_metric(label, value):
    st.markdown(
        f"""
        <div style="
            padding: 0.75rem;
            border-radius: 0.5rem;
            background-color: #f0fdf4;
            border: 1px solid #16a34a;
            text-align: center;
        ">
            <div style="color:#15803d; font-size:0.85rem;">
                {label}
            </div>
            <div style="color:#166534; font-size:1.5rem; font-weight:600;">
                {value}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

def green_metric_small(label, value):
    st.markdown(
        f"""
        <div style="
            margin-top: 0.35rem;
            padding: 0.45rem 0.55rem;
            border-radius: 0.45rem;
            background-color: #f0fdf4;
            border: 1px solid #16a34a;
            line-height: 1.15;
        ">
            <div style="color:#15803d; font-size:0.75rem;">
                {label}
            </div>
            <div style="color:#166534; font-size:1.05rem; font-weight:600;">
                {value}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

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
            aliases=["Območje:", f"{indicator_label}:"],
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
   


@st.cache_data(show_spinner=False)
def load_geojson_from_upload_or_file(uploaded, default_path: Path):
    if uploaded is not None:
        return json.load(uploaded)
    return try_load_geojson(default_path)



# ---------------------------
# UI
# ---------------------------
st.set_page_config(page_title="Upravljanje turističnih destinacij Slovenije© \n Ključni podatki in kazalniki", layout="wide", initial_sidebar_state="collapsed")

title_slideshow_images = load_title_slideshow_images()
title_slideshow_step_seconds = 6
title_slideshow_spacer = title_slideshow_images[0] if title_slideshow_images else ""
title_slideshow_count = max(1, len(title_slideshow_images))
title_slideshow_total_seconds = title_slideshow_count * title_slideshow_step_seconds
title_slide_visible_pct = (title_slideshow_step_seconds * 0.78 / title_slideshow_total_seconds) * 100
title_slide_fade_end_pct = (title_slideshow_step_seconds / title_slideshow_total_seconds) * 100
title_slide_animation_css = (
    "animation: none; opacity: 1;"
    if len(title_slideshow_images) <= 1
    else f"animation: titleSlideFade {title_slideshow_total_seconds}s linear infinite; animation-fill-mode: both;"
)
title_slideshow_html = "\n".join(
    f'<img class="title-slide" src="{image_uri}" alt="Naslovna slika {idx + 1}" style="animation-delay: {-idx * title_slideshow_step_seconds}s;" />'
    for idx, image_uri in enumerate(title_slideshow_images)
)
st.html(
    f"""
    <style>
    body {{
        margin: 0;
        font-family: "Source Sans Pro", sans-serif;
    }}
    .title-panel {{
        position: relative;
        overflow: hidden;
        border-radius: 24px;
        margin: 0 0 8px 0;
        box-shadow: 0 16px 36px rgba(17, 24, 39, 0.10);
        color: #1f2937;
        background: #eef2f7;
    }}
    .title-panel-media {{
        position: relative;
        width: 100%;
    }}
    .title-slide-spacer {{
        display: block;
        width: 100%;
        height: auto;
        visibility: hidden;
    }}
    .title-slide-layer {{
        position: absolute;
        inset: 0;
        overflow: hidden;
    }}
    .title-slide {{
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        object-fit: contain;
        opacity: 0;
        {title_slide_animation_css}
    }}
    .title-slide:first-child {{
        opacity: 1;
    }}
    @keyframes titleSlideFade {{
        0% {{ opacity: 1; }}
        {title_slide_visible_pct:.4f}% {{ opacity: 1; }}
        {title_slide_fade_end_pct:.4f}% {{ opacity: 0; }}
        100% {{ opacity: 0; }}
    }}
    .title-panel-overlay {{
        position: absolute;
        inset: 0;
        background: linear-gradient(
            180deg,
            rgba(10, 18, 32, 0.04) 0%,
            rgba(10, 18, 32, 0.10) 42%,
            rgba(10, 18, 32, 0.42) 100%
        );
    }}
    .title-panel-content {{
        position: absolute;
        left: 28px;
        right: auto;
        bottom: 28px;
        top: auto;
        width: min(74%, 1200px);
        padding: 22px 26px;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        box-sizing: border-box;
        background: linear-gradient(
            180deg,
            rgba(15, 23, 42, 0.08) 0%,
            rgba(15, 23, 42, 0.18) 100%
        );
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 20px;
        backdrop-filter: blur(2px);
    }}
    .app-kicker {{
        font-size: 26px;
        font-style: italic;
        font-weight: 500;
        letter-spacing: 0.02em;
        line-height: 1.05;
        margin-bottom: 10px;
        color: rgba(255, 255, 255, 0.98);
        text-shadow: 0 2px 12px rgba(15, 23, 42, 0.30);
    }}
    .app-title {{
        font-size: 42px;
        font-weight: 800;
        line-height: 1.1;
        margin-bottom: 4px;
        color: #ffffff;
        text-shadow: 0 2px 14px rgba(15, 23, 42, 0.35);
    }}
    .app-title .copyright {{
        font-weight: 400;
        font-size: 0.6em;
        vertical-align: super;
    }}
    .app-subtitle {{
        font-size: 34px;
        font-style: italic;
        font-weight: 500;
        color: rgba(255, 255, 255, 0.96);
        margin-bottom: 8px;
        line-height: 1.1;
        text-shadow: 0 2px 12px rgba(15, 23, 42, 0.30);
    }}
    .app-description {{
        font-size: 16px;
        font-style: italic;
        color: rgba(255, 255, 255, 0.92);
        line-height: 1.4;
        max-width: 1200px;
        text-shadow: 0 2px 10px rgba(15, 23, 42, 0.28);
    }}
    @media (max-width: 900px) {{
        .title-panel {{
            border-radius: 18px;
        }}
        .title-panel-content {{
            left: 16px;
            right: 16px;
            bottom: 16px;
            top: auto;
            width: auto;
            padding: 16px 16px;
            border-radius: 16px;
        }}
        .app-kicker {{
            font-size: 20px;
            margin-bottom: 8px;
        }}
        .app-title {{
            font-size: 30px;
        }}
        .app-subtitle {{
            font-size: 24px;
        }}
        .app-description {{
            font-size: 14px;
        }}
    }}
    </style>
    <div class="title-panel">
        <div class="title-panel-media">
            <img class="title-slide-spacer" src="{title_slideshow_spacer}" alt="" />
            <div class="title-slide-layer">
                {title_slideshow_html}
            </div>
            <div class="title-panel-overlay"></div>
            <div class="title-panel-content">
                <div class="app-kicker">
                    Interaktivna aplikacija
                </div>
                <div class="app-title">
                    Upravljanje turističnih destinacij Slovenije <span class="copyright">©</span>
                </div>
                <div class="app-subtitle">
                    Ključni podatki in kazalniki stanja, stopnje razvoja, vpliva in učinkovitosti upravljanja turizma
                </div>
                <div class="app-description">
                    Preko 100 podatkov in strukturiranih tržnih, poslovnih, ekonomskih, družbenih in okoljskih kazalnikov za vsako od 5 ravni ožje in širše zaokroženih turističnih območij: Občine, Vodilne turistične destinacije, Perspektivne turistične destinacije, Turistične regije, Makro destinacije in nacionalne ravni slovenskega turizma. Medsebojne primerjave in konkurenčno uvrščanje posameznih območij, primerjave s kazalniki na ravni Slovenije. Diagnostika stanja in generiranje priporočil  o razvoju in delovanju turizma na ravni destinacij. Stalna nadgradnja z aktualnimi podatki, novimi kazalniki in prikazi, tudi s pomočjo umetne inteligence.
                </div>
            </div>
        </div>
    </div>
    """
)

st.markdown("<hr style='margin-top:20px;margin-bottom:20px;'>", unsafe_allow_html=True)
st.markdown("***Podatki in kazalniki se nanašajo na leto 2024 (v kolikor leto ni posebej navedeno), leto 2025 in primerjalne podatke z letom 2019 (posebej označeno)***")

with st.sidebar:
    st.header("Nastavitve")
    xlsx_file = st.file_uploader("Naloži Excel (če ne uporabiš privzetega)", type=["xlsx"])
    geojson_file = st.file_uploader("Naloži GeoJSON občin (opcijsko)", type=["json", "geojson"])
    st.divider()
    dashboard_mode = st.checkbox("Dashboard način (več kazalnikov)", value=True)


# Load data
if xlsx_file is not None:
    df = load_excel(xlsx_file)
else:
    default_path = find_excel_file()
    if not default_path.exists():
        st.error(f"Ne najdem privzetega Excela: {default_path.name}. Naloži Excel v stranski vrstici.")
        st.stop()
    df = load_excel(default_path)

if "Občine" not in df.columns or "Turistična regija" not in df.columns:
    st.error("V Excelu ne najdem stolpcev 'Občine' in/ali 'Turistična regija'.")
    st.stop()

df = df.copy()
df["__obcina_norm__"] = df["Občine"].apply(normalize_name)

meta_cols = {"Občine", "Turistična regija", "__obcina_norm__", "Vodilne destinacije", "Perspektivne destinacije", "Makro destinacije", "SLOVENIJA"}
indicator_cols = [c for c in df.columns if c not in meta_cols]

pop_candidates = [c for c in indicator_cols if "prebival" in c.lower() and "število" in c.lower()]
pop_col = pop_candidates[0] if pop_candidates else None

geojson_obj = load_geojson_from_upload_or_file(
    geojson_file,
    Path(__file__).parent / GEOJSON_DEFAULT
)
name_prop = get_geojson_name_prop(geojson_obj) if geojson_obj else None

MARKET_PREFIX = "Delež vseh prenočitev - "
market_cols = [c for c in df.columns if str(c).startswith(MARKET_PREFIX)]
market_labels = [c.replace(MARKET_PREFIX, "").strip() for c in market_cols]

MARKET_COLOR_MAP = {
    "Domači trg": "#1f77b4",
    "DACH trgi (nemško govoreči trgi: D, A in CH)": "#ff7f0e",
    "Italijanski trg": "#2ca02c",
    "Vzh.evropski trgi (PL,CZ,HU,SK,LIT,LTV,EST,RU,UKR)": "#d62728",  
    "Drugi zah.in sev. evropski trgi (ES,P, F,Benelux, Skandinavske države)": "#9467bd",  
    "Prekomorski trgi (ZDA, VB, CAN, AU, Azija)": "#17becf",  
    "Trgi JV Evrope": "#bcbd22",  
    "Vsi drugi tuji trgi": "#7f7f7f",  
}

# Kandidati za poglede (zavihki)
VIEW_CANDIDATES = [
    ("Turistične regije", ["turisticna regija", "turisticne regije"]),
    ("Vodilne destinacije", ["vodilna destinacija", "vodilne destinacije"]),
    ("Makrodestinacije", ["makrodestinacija", "makrodestinacije", "makro destinacije"]),
    ("Regijske destinacije", ["regijska destinacija", "regijske destinacije"]),
    ("Perspektivne destinacije", ["perspektivna destinacija", "perspektivne destinacije"]),
]

views = []

for title, wanted in VIEW_CANDIDATES:
    col = find_col(df, wanted)
    if col is not None:
        views.append((title, col))




def render_view(view_title: str, group_col: str):
    st.caption(f"**Pogled:** {view_title}")

    meta = meta_cols | {group_col}
    
    indicator_cols = [c for c in df.columns if c not in meta and c not in market_cols]
    group_map = load_indicator_groups(Path(MAPPING_XLSX_DEFAULT))
    grouped_filtered = {}
    leftover = []
    if group_map:
        indicator_set = set(indicator_cols)
        for g, items in group_map.items():
            filtered = [i for i in items if i in indicator_set]
            if filtered:
                grouped_filtered[g] = filtered
        grouped_all = set(i for items in grouped_filtered.values() for i in items)
        leftover = [i for i in indicator_cols if i not in grouped_all]
    indicator_to_group = {}
    for g, items in grouped_filtered.items():
        for i in items:
            indicator_to_group.setdefault(i, g)

    #Za regijo
    df_regions = df[df[group_col].notna()].copy()
    regions = sorted(df_regions[group_col].dropna().unique().tolist())
    regions_with_all = ["Vsa območja"] + regions

    num_df = df_regions.copy()
    
    for c in indicator_cols:
        num_df[c] = parse_numeric(num_df[c])
    

    #za Celotno slovenijo
    df_slo_total = df.iloc[0]
    
    df_slo_total_num = parse_numeric(df_slo_total[indicator_cols])

    # mapping občina -> regija (normalizirano)
    muni_to_region = {normalize_name(o): r for o, r in zip(df_regions["Občine"], df_regions[group_col])}

    # izbor regije + skupine kazalnikov (levo, nad izborom kazalnika za zemljevid)
    selected_region = st.selectbox(group_col, regions_with_all, index=0, key=f"sel_group_{group_col}")
    selector_state_key = f"sel_group_img_{group_col}"
    if selector_state_key not in st.session_state:
        st.session_state[selector_state_key] = "__all__"

    image_group_specs = [
        {"key": "__all__", "label": "Vsi kazalniki", "count": len(indicator_cols)},
        {"key": "Družbeni kazalniki", "label": "Družbeni kazalniki", "count": len(grouped_filtered.get("Družbeni kazalniki", []))},
        {"key": "Okoljski kazalniki", "label": "Okoljski kazalniki", "count": len(grouped_filtered.get("Okoljski kazalniki", []))},
        {
            "key": "Ekonomski nastanitveni in tržni turistični kazalniki",
            "label": "Nastanitveni\nin tržni",
            "count": len(grouped_filtered.get("Ekonomski nastanitveni in tržni turistični kazalniki", [])),
        },
        {
            "key": "Ekonomsko poslovni kazalniki turistične dejavnosti",
            "label": "Ekon.\nposlovni",
            "count": len(grouped_filtered.get("Ekonomsko poslovni kazalniki turistične dejavnosti", [])),
        },
    ]

    valid_group_keys = {spec["key"] for spec in image_group_specs}
    if st.session_state[selector_state_key] not in valid_group_keys:
        st.session_state[selector_state_key] = "__all__"
    st.markdown("---")
    selector_col, map_indicator_col = st.columns([1, 1], gap="large")
    with selector_col:
        st.markdown("**Skupina kazalnikov**")
        selector_images = []
        image_selector_ready = image_select is not None

        for spec in image_group_specs:
            key = spec["key"]
            image_name = GROUP_BUTTON_IMAGE_FILES.get(key, "")
            image_path = (Path(__file__).parent / image_name) if image_name else None
            if not image_path or not image_path.exists():
                image_selector_ready = False
                selector_images.append("")
            else:
                prepared_path = prepare_group_button_image(str(image_path), "")
                selector_images.append(prepared_path or str(image_path))

        default_idx = next(
            (i for i, spec in enumerate(image_group_specs) if spec["key"] == st.session_state[selector_state_key]),
            0,
        )

        if image_selector_ready:
            selected_value = image_select(
                label="",
                images=selector_images,
                index=default_idx,
                use_container_width=False,
                return_value="index",
                key=f"sel_group_img_component_{group_col}",
            )

            selected_idx = default_idx
            if isinstance(selected_value, int) and 0 <= selected_value < len(image_group_specs):
                selected_idx = selected_value

            candidate = image_group_specs[selected_idx]
            if candidate["key"] == "__all__" or candidate["count"] > 0:
                st.session_state[selector_state_key] = candidate["key"]
        else:
            st.warning("Manjka komponenta `streamlit-image-select` ali ena od slik za gumbe. Uporabljam rezervni izbor.")
            fallback_options = [spec["key"] for spec in image_group_specs]
            fallback_labels = {
                "__all__": f"Vsi kazalniki ({len(indicator_cols)})",
                "Družbeni kazalniki": f"Družbeni kazalniki ({len(grouped_filtered.get('Družbeni kazalniki', []))})",
                "Okoljski kazalniki": f"Okoljski kazalniki ({len(grouped_filtered.get('Okoljski kazalniki', []))})",
                "Ekonomski nastanitveni in tržni turistični kazalniki": f"Ekonomski nastanitveni in tržni turistični kazalniki ({len(grouped_filtered.get('Ekonomski nastanitveni in tržni turistični kazalniki', []))})",
                "Ekonomsko poslovni kazalniki turistične dejavnosti": f"Ekonomsko poslovni kazalniki turistične dejavnosti ({len(grouped_filtered.get('Ekonomsko poslovni kazalniki turistične dejavnosti', []))})",
            }
            selected_fallback = st.selectbox(
                "Skupina kazalnikov",
                fallback_options,
                index=default_idx,
                format_func=lambda k: fallback_labels.get(k, k),
                key=f"sel_group_ind_{group_col}",
            )
            st.session_state[selector_state_key] = selected_fallback

    selected_group_key = st.session_state[selector_state_key]
    if selected_group_key == "__all__":
        group_indicator_cols = indicator_cols
    else:
        group_indicator_cols = grouped_filtered.get(selected_group_key, [])

    if not group_indicator_cols:
        group_indicator_cols = indicator_cols
    with map_indicator_col:
        st.markdown("<div style='min-height: 10rem;'></div>", unsafe_allow_html=True)
        map_indicator = st.selectbox(
            "Kazalnik za zemljevid",
            group_indicator_cols,
            index=0,
            key=f"sel_ind_{group_col}",
            format_func=lambda ind: f"{GROUP_COLOR_EMOJI.get(indicator_to_group.get(ind), '•')} {ind}",
        )
        show_shared_warning_if_needed_indicator(map_indicator)

    dash_inds = []
    if dashboard_mode:
        default_inds = group_indicator_cols[:0] if len(group_indicator_cols) >= 4 else group_indicator_cols
        dash_inds = st.multiselect(
            "Kazalniki za dashboard (do 6)",
            group_indicator_cols,
            default=default_inds,
            max_selections=6,
            placeholder="Izberi kazalnik",
            key=f"dash_{group_col}",
            format_func=lambda ind: f"{GROUP_COLOR_EMOJI.get(indicator_to_group.get(ind), '•')} {ind}",
        )

    # agregati regij
    agg_needed = [map_indicator] + [i for i in dash_inds if i != map_indicator]
    region_agg = compute_region_aggregates1(num_df, regions, agg_needed, AGG_RULES, group_col=group_col)
    region_to_value_map = dict(zip(region_agg[group_col], region_agg[map_indicator]))

    # regijski geojson (dissolve)
    regions_geojson = None
    if selected_region == "Vsa območja" and geojson_obj and name_prop:
        regions_geojson = build_region_geojson_from_municipalities(geojson_obj, name_prop, muni_to_region, group_col=group_col)

    # KPI / pregled
    if selected_region == "Vsa območja":
        st.subheader("Primerjava območij")
        cols_to_show = [group_col] + agg_needed
        show_df = region_agg[cols_to_show].copy()
        for c in cols_to_show[1:]:
            show_df[c] = show_df[c].apply(lambda x: format_indicator_value_tables(c, x))
            

        show_df = show_df.sort_values(cols_to_show[1], ascending=False, na_position="last" )

        st.dataframe(
            show_df,
            use_container_width = True,
            height=260,
            hide_index=True,
            column_config = make_localized_column_config(show_df),
            )
        
        col1, col2, col3 = st.columns([1,2,1])
        with col3:
            green_metric(f" Celotna Slovenija - {map_indicator}", format_indicator_value_map(map_indicator, df_slo_total[map_indicator]))
        

        
    else:
        st.subheader("Povzetek izbranega območja")
        
        reg_df = num_df[num_df[group_col] == selected_region].copy()
        reg_total = aggregate_indicator_with_rules(reg_df, map_indicator, AGG_RULES, selected_region)

        # "Slovenija total" – smiselno le za seštevne indikatorje
        sl_total = df_slo_total[map_indicator]
        
        
        share_si = np.nan
        if (not is_rate_like(map_indicator)) and sl_total and not np.isnan(sl_total) and sl_total != 0:
            share_si = (reg_total / sl_total) * 100.0
        # KPI: prvi je indikator + delež SLO
        if map_indicator in INDIKATORJI_Z_INDEKSI:
            kpi_text_main = "Indeks s povprečjem v Sloveniji"
            kpi_value_main = format_si_number(share_si, 1)
        else:
            kpi_text_main = "Delež v Sloveniji"
            kpi_value_main = format_pct(share_si, 1)

        left_kpi, right_kpi = st.columns([1.2, 1])
        with left_kpi:
            if not np.isnan(share_si): 
                st.metric(map_indicator, f"{format_indicator_value_map(map_indicator,reg_total)}", f"{kpi_text_main}: {kpi_value_main}")
            else:
                st.metric(map_indicator, f"{format_indicator_value_map(map_indicator, reg_total)}")
            st.caption("Opomba: »Delež v Sloveniji« je prikazan za kazalnike, kjer se vrednosti seštevajo (ne za stopnje/indekse).")
        with right_kpi:
            green_metric(f" Celotna Slovenija - {map_indicator}", format_indicator_value_map(map_indicator, sl_total))
  
       

        # dodatni KPI-ji (dashboard)
        if dashboard_mode and dash_inds:
            kpi_cols = st.columns(min(6, len(dash_inds)))
            for idx, ind in enumerate(dash_inds[:6]):

                # vrednost regije
                v_reg = float(region_agg.loc[region_agg[group_col] == selected_region, ind].iloc[0])

                # total Slovenije za ta indikator
                v_slo = df_slo_total_num.get(ind, np.nan)

                # delež Slovenije (samo za seštevne indikatorje)
                share = np.nan
                if (not is_rate_like(ind)) and v_slo and not np.isnan(v_slo) and v_slo != 0:
                    share = (v_reg / v_slo) * 100.0

                # prikaz
                with kpi_cols[idx]:
                    if ind in INDIKATORJI_Z_INDEKSI:
                        kpi_text_dashboard = "Indeks s povprečjem v Sloveniji"
                        kpi_value_dashboard = format_si_number(share, 1)
                    else:
                        kpi_text_dashboard = "Delež v Sloveniji"
                        kpi_value_dashboard = format_pct(share, 1)
                    # spodaj: Slovenija total (zelena mini kartica)
                    if v_slo is not None and not (isinstance(v_slo, float) and np.isnan(v_slo)):
                        green_metric_small("Slovenija", format_indicator_value_map(ind, v_slo))
                    # glavni KPI (regija)
                    if not np.isnan(share):
                        st.metric(
                            ind,
                            format_indicator_value_map(ind, v_reg),
                            f"{kpi_text_dashboard}: {kpi_value_dashboard}"
                        )
                    else:
                        st.metric(ind, format_indicator_value_map(ind, v_reg))

        group_sections = build_top_bottom_group_sections(
            reg_df=reg_df,
            df_slo_total_num=df_slo_total_num,
            grouped_filtered=grouped_filtered,
            agg_rules=AGG_RULES,
            region_name=selected_region,
        )

    st.markdown("---")
    st.subheader("Zemljevid in razčlenitev")
    st.caption("Skupni pogled: Skupni podatki za posamezna območja. Posamezno območje: meje občin ter deleži znotraj območja. Dodan je tudi delež Občine glede na območje (kjer je smiselno).")

    map_col, table_col = st.columns([2.2, 1.0], gap="large")

    with map_col:
        if geojson_obj is None or name_prop is None:
            st.info("Za zemljevid naloži občinski GeoJSON (npr. `si.json`).")
        else:
            if selected_region == "Vsa območja":
                if regions_geojson is None:

                    st.warning("Ne uspem sestaviti poligonov regij (dissolve). Prikazujem občine obarvane po regijski vrednosti.")
                    muni_region_val = {m: region_to_value_map.get(r, np.nan) for m, r in muni_to_region.items()}
                    render_map_municipalities(geojson_obj, name_prop, set(muni_to_region.keys()), muni_region_val,indicator_label=map_indicator, height=680)
                else:
                    render_map_regions(regions_geojson, region_to_value_map,indicator_label=map_indicator,group_col=group_col, height=780)
            else:
                reg_df = num_df[num_df[group_col] == selected_region].copy()
                muni_in_region = set(reg_df["__obcina_norm__"].tolist())
                muni_to_value = {normalize_name(o): float(v) for o, v in zip(reg_df["Občine"], reg_df[map_indicator])}
                render_map_municipalities(geojson_obj, name_prop, muni_in_region, muni_to_value,indicator_label=map_indicator, height=780)
        show_shared_warning_if_needed_map(map_indicator)
    with table_col:
        if selected_region == "Vsa območja":
            st.markdown(f"**Tabela območij** \n \n **:blue[{map_indicator}]**")
            t = region_agg[[group_col, map_indicator]].copy()
            t = t.sort_values(map_indicator, ascending=False, na_position="last")
            t[map_indicator] = t[map_indicator].apply(lambda x: format_indicator_value_tables(map_indicator, x))
            cfg = make_localized_column_config(t)
            
            old_key= next(iter(cfg))
            cfg["Vrednost"] = cfg.pop(old_key)


            t = t.rename(columns={map_indicator: "Vrednost"})

            st.dataframe(
                t,
                use_container_width = True,
                height=680,
                hide_index=True,
                column_config = cfg,
                )
        else:
            st.markdown(f"**Tabela občin znotraj območja** \n \n **:blue[{map_indicator}]**")
            reg_df = num_df[num_df[group_col] == selected_region].copy()
            reg_total = aggregate_indicator_with_rules(reg_df, map_indicator, AGG_RULES, None)
            
            cfg_df = pd.DataFrame({
                "Občina": reg_df["Občine"].astype(str),
                map_indicator: reg_df[map_indicator].astype(float).apply(lambda x: format_indicator_value_tables(map_indicator, x))
            })

            if (reg_total and not np.isnan(reg_total) and reg_total != 0 and not is_rate_like(map_indicator)):
                if map_indicator in INDIKATORJI_Z_INDEKSI:
                    cfg_df[f"Indeks {view_title}"] = round(((cfg_df[map_indicator] / reg_total)*100), 1)
                else:
                    cfg_df[f"Delež {view_title} (%)"] = round(((cfg_df[map_indicator] / reg_total)), 3)
            else:
                pass

            cfg = make_localized_column_config(cfg_df)
            
            old_key= next(iter(cfg))
            cfg["Vrednost"] = cfg.pop(old_key)

            tbl = pd.DataFrame({
                "Občina": reg_df["Občine"].astype(str),
                "Vrednost": reg_df[map_indicator].astype(float).apply(lambda x: format_indicator_value_tables(map_indicator, x))
            })

            if (reg_total and not np.isnan(reg_total) and reg_total != 0 and not is_rate_like(map_indicator)):
                if map_indicator in INDIKATORJI_Z_INDEKSI:
                    tbl[f"Indeks {view_title}"] = round(((tbl["Vrednost"] / reg_total)*100), 1)
                else:
                    tbl[f"Delež {view_title} (%)"] = round(((tbl["Vrednost"] / reg_total)), 3)
            else:
                pass


            tbl = tbl.sort_values("Vrednost", ascending=False, na_position="last")

            st.dataframe(
                tbl,
                use_container_width = True,
                height=680,
                hide_index=True,
                column_config = cfg,
                )
            if (reg_total and not np.isnan(reg_total) and reg_total != 0 and not is_rate_like(map_indicator)):
                if view_title == "Turistične regije":
                    st.caption(f"**Opomba:** Delež posamezne občine znotraj opazovane turistične regije (%) je prikazan za kazalnike, kjer se vrednosti seštevajo. Primerjalni indeks vrednosti kazalnika posamezne občine v primerjavi z vrednostjo enakega kazalnika na ravni opazovane turistične regije pa je prikazan za kompleksnejše oz. izračunane kazalnike, katerih vrednosti se ne seštevajo. ")
                elif view_title == "Vodilne destinacije":
                    st.caption("**Opomba:** Delež posamezne občine znotraj opazovane vodilne destinacije (%) je prikazan za kazalnike, kjer se vrednosti seštevajo. Primerjalni indeks vrednosti kazalnika posamezne občine v primerjavi z vrednostjo enakega kazalnika na ravni opazovane vodilne destinacije pa je prikazan za kompleksnejše oz. izračunane kazalnike, katerih vrednosti se ne seštevajo. ")
                elif view_title == "Makrodestinacije":
                    st.caption("**Opomba:** Delež posamezne občine znotraj opazovane makro destinacije (%) je prikazan za kazalnike, kjer se vrednosti seštevajo. Primerjalni indeks vrednosti kazalnika posamezne občine v primerjavi z vrednostjo enakega kazalnika na ravni opazovane makro destinacije pa je prikazan za kompleksnejše oz. izračunane kazalnike, katerih vrednosti se ne seštevajo. ")
                elif view_title == "Perspektivne destinacije":
                    st.caption("**Opomba:** Delež posamezne občine znotraj opazovane perspektivne destinacije (%) je prikazan za kazalnike, kjer se vrednosti seštevajo. Primerjalni indeks vrednosti kazalnika posamezne občine v primerjavi z vrednostjo enakega kazalnika na ravni opazovane perspektivne destinacije pa je prikazan za kompleksnejše oz. izračunane kazalnike, katerih vrednosti se ne seštevajo. ")    

    if selected_region != "Vsa območja":
        st.markdown("---")
        if group_sections:
            st.markdown("**Najboljši/Najslabši kazalniki po skupinah**")
            st.caption("Vsaka skupina kazalnikov ima ločeno razvrstitev. Za povprečja in indekse je uporabljen neposreden odmik glede na Slovenijo (%). Za kumulativne kazalnike je uporabljen odmik deleža kazalnika glede na referenčni delež regije (o.t.), da velikost območja ne izkrivlja rezultatov.")

            tab_labels = [
                f"{GROUP_COLOR_EMOJI.get(section['group'], '•')} {section['group']} ({section['limit']}/{section['limit']})"
                for section in group_sections
            ]
            group_tabs = st.tabs(tab_labels)
            table_cols = [
                "Kazalnik",
                "Smer kazalnika",
                "Vrednost območja",
                "Osnova (Slovenija)",
                "Metoda primerjave",
                "Odstopanje glede na smer",
                "Primerjalni odmik",
            ]

            for tab, section in zip(group_tabs, group_sections):
                with tab:
                    best_col, worst_col = st.columns(2)
                    with best_col:
                        st.markdown(f"**Najboljši {section['limit']}**")
                        st.dataframe(
                            section["best_df"][table_cols],
                            use_container_width=True,
                            hide_index=True,
                        )
                    with worst_col:
                        st.markdown(f"**Najslabši {section['limit']}**")
                        st.dataframe(
                            section["worst_df"][table_cols],
                            use_container_width=True,
                            hide_index=True,
                        )

            st.markdown("**AI komentar in priporočila za območje**")
            ai_sig_raw = json.dumps(
                {
                    "region": selected_region,
                    "groups": [
                        {
                            "group": section["group"],
                            "top": section["top_rows"],
                            "bottom": section["bottom_rows"],
                        }
                        for section in group_sections
                    ],
                },
                ensure_ascii=False,
            )
            ai_sig = hashlib.md5(ai_sig_raw.encode("utf-8")).hexdigest()[:12]
            ai_payload_hash = hashlib.sha256(ai_sig_raw.encode("utf-8")).hexdigest()
            ai_cache_key = ai_payload_hash
            ai_state_key = f"ai_comment_{group_col}_{selected_region}_{ai_sig}"

            if ai_state_key not in st.session_state:
                cached_ai_payload = get_cached_ai_commentary(ai_cache_key)
                if cached_ai_payload:
                    st.session_state[ai_state_key] = {
                        "text": cached_ai_payload.get("text", ""),
                        "source": "db_cache",
                        "error": None,
                    }
                else:
                    with st.spinner("Generiram komentar in priporočila..."):
                        ai_text, ai_source, ai_error = generate_region_ai_commentary(
                            selected_region,
                            group_sections,
                        )
                    st.session_state[ai_state_key] = {
                        "text": ai_text,
                        "source": ai_source,
                        "error": ai_error,
                    }
                    if ai_source == "ai" and ai_text:
                        store_cached_ai_commentary(
                            ai_cache_key,
                            payload_hash=ai_payload_hash,
                            region_name=selected_region,
                            group_name=group_col,
                            text=ai_text,
                            model=get_secret_value("OPENAI_MODEL", "gpt-5.4"),
                        )

            ai_payload = st.session_state.get(ai_state_key, {})
            if ai_payload.get("source") == "db_cache":
                st.caption("AI komentar je prebran iz trajnega podatkovnega cache-a.")
            elif ai_payload.get("source") == "fallback":
                err_txt = str(ai_payload.get("error") or "")
                if "insufficient_quota" in err_txt:
                    st.caption("OPENAI_API_KEY nima več razpoložljive kvote. Prikazan je samodejni komentar na osnovi kazalnikov.")
                elif "HTTP 429" in err_txt:
                    st.caption("AI klic je omejen zaradi preveč zahtevkov (rate limit). Prikazan je samodejni komentar na osnovi kazalnikov.")
                else:
                    st.caption("OPENAI_API_KEY ni nastavljen ali AI klic ni uspel. Prikazan je samodejni komentar na osnovi kazalnikov.")
            if ai_payload.get("error"):
                st.caption(f"Podrobnosti: {ai_payload['error']}")
            if ai_payload.get("text"):
                st.markdown(ai_payload["text"])
        else:
            st.info("Za Top/Bottom analizo po skupinah ni na voljo dovolj kazalnikov.")

def render_market_structure(view_title: str, group_col: str, market_cols: list[str], market_labels: list[str]):
    st.caption(f"**Pogled:** {view_title}")
    st.subheader("Struktura prenočitev po trgih")

    YEARS = [2024, 2025]
    selected_year = st.selectbox("Leto", YEARS, index=len(YEARS)-1, key=f"trgi_year_{group_col}")

    if not market_cols:
        st.warning("V Excelu ne najdem stolpcev, ki se začnejo z: 'Delež vseh prenočitev - '.")
        return

    # DF za izbrani pogled (samo vrstice, kjer je group_col definiran)
    df_groups = df[df[group_col].notna()].copy()

    # numeric parsing (potrebno za izračune)
    num_df = df_groups.copy()
   
    # ---- Stolpci za izbrano leto
    base_weight_col_template = "Prenočitve turistov SKUPAJ - 2024"
    base_weight_col = col_for_year(base_weight_col_template, selected_year)

    market_cols_year, market_labels_year = get_market_cols_for_year(df, selected_year)

    # Preveri, kateri stolpci dejansko obstajajo (da se ne sesuje, če kje manjka)
    cols_needed = [base_weight_col] + market_cols_year
    missing = [c for c in cols_needed if c not in num_df.columns]
    if missing:
        st.warning("Manjkajo stolpci za izbrano leto: " + ", ".join(missing))
        return

    for c in cols_needed:
        if c in num_df.columns:
            num_df[c] = parse_numeric(num_df[c])

    groups = sorted(num_df[group_col].dropna().unique().tolist())
    if not groups:
        st.warning("Ne najdem nobenih območij za izbran pogled.")
        return

    # UI: izberi območje (ne priporočam "vsa območja" za torto, raje ena regija)
    selected_group = st.selectbox(f"Izberi območje ({group_col})", groups, index=0, key=f"trgi_sel_{group_col}")

    mode = st.radio(
        "Prikaz",
        ["Celotno območje", "Občine znotraj območja"],
        horizontal=True,
        key=f"trgi_mode_{group_col}"
    )

    sub = num_df[num_df[group_col] == selected_group].copy()
    if sub.empty:
        st.info("Ni podatkov za izbrano območje.")
        return

    # ---- Celotno območje: utežena struktura po prenočitvah
    # Region share = sum(share_i * total_i) / sum(total_i)
    total_w = sub[base_weight_col].astype(float)
    denom = float(np.nansum(total_w.values)) if base_weight_col in sub.columns else np.nan

    if denom and not np.isnan(denom) and denom > 0:
        vals = {}
        for col, lab in zip(market_cols_year, market_labels_year):
            s = sub[col].astype(float)
            mask = (~s.isna()) & (~total_w.isna()) & (total_w > 0)
            if mask.any():
                vals[lab] = float(np.nansum((s[mask] * total_w[mask]).values) / np.nansum(total_w[mask].values))
            else:
                vals[lab] = np.nan

        struct = pd.DataFrame({"Trg": list(vals.keys()), "Delež": list(vals.values())}).dropna()
    else:
        st.warning("Manjkajo prenočitve SKUPAJ (utež) ali so 0, zato strukture ne morem izračunati.")
        return

    # normalizacija, če seštevek ni ~1 (v praksi se včasih zgodi zaradi zaokroževanja ali manjkajočih trgov)
    ssum = float(struct["Delež"].sum()) if not struct.empty else 0.0
    if ssum > 0:
        struct["Delež_norm"] = struct["Delež"] / ssum
    else:
        struct["Delež_norm"] = np.nan

    if mode == "Celotno območje":
        st.markdown(f"### {selected_group}")
        c1, c2 = st.columns([1.2, 1])

        with c1:
            st.markdown("**Tortni prikaz (normalizirano na 100%)**")
            pie_df = struct.sort_values("Delež_norm", ascending=False)
            pie_df["Trg_short"] = pie_df["Trg"].apply(lambda x: shorten_label(x, 24))
            fig = px.pie(
                pie_df,
                names="Trg_short",
                values="Delež_norm",
                color="Trg",
                color_discrete_map=MARKET_COLOR_MAP,
                hole=0.4,  # donut style (optional, looks nice),
            )

            fig.update_traces(
                textposition="inside",
                textinfo="percent+label",
                hovertemplate="<b>%{customdata[0]}</b><br>Delež: %{percent}<extra></extra>",
                customdata=pie_df[["Trg"]].values
            )

            fig.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                showlegend=True,
                legend_title_text="Trgi"
            )


            st.plotly_chart(fig, use_container_width = True)

        with c2:
            st.markdown("**Tabela**")
            t = struct.copy()
            t["Delež (%)"] = (t["Delež_norm"] * 100).round(1)
            t = t[["Trg", "Delež (%)"]].sort_values("Delež (%)", ascending=False)
            st.dataframe(t, use_container_width = True, hide_index=True)

        st.caption("Opomba: deleži so izračunani uteženo glede na celotno število prenočitev in nato normalizirani na 100% (zaradi zaokroževanja/manjkajočih trgov).")

    else:
        # ---- Občine znotraj območja
        st.markdown(f"### Občine znotraj območja: {selected_group}")

        # izberi občino za graf
        muni_col = "Občine"
        sub_m = sub[[muni_col, base_weight_col] + market_cols_year].copy()
        sub_m = sub_m.rename(columns={muni_col: "Občina"})

        chosen_muni = st.selectbox(
            "Izberi občino",
            sub_m["Občina"].dropna().astype(str).tolist(),
            index=0,
            key=f"trgi_muni_{group_col}"
        )

        muni_row = sub_m[sub_m["Občina"] == chosen_muni].iloc[0]
        muni_vals = []
        for col, lab in zip(market_cols_year, market_labels_year):
            muni_vals.append({"Trg": lab, "Delež": float(muni_row[col]) if pd.notna(muni_row[col]) else np.nan})

        muni_struct = pd.DataFrame(muni_vals).dropna()
        ssum = float(muni_struct["Delež"].sum()) if not muni_struct.empty else 0.0
        if ssum > 0:
            muni_struct["Delež_norm"] = muni_struct["Delež"] / ssum
        else:
            muni_struct["Delež_norm"] = np.nan

        c1, c2 = st.columns([1.2, 1])
        with c1:
            st.markdown(f"**{chosen_muni} – tortni prikaz (normalizirano na 100%)**")
            pie_df = muni_struct.sort_values("Delež_norm", ascending=False)
            pie_df["Trg_short"] = pie_df["Trg"].apply(lambda x: shorten_label(x, 24))

            fig = px.pie(
                pie_df,
                names="Trg_short",
                values="Delež_norm",
                color_discrete_map=MARKET_COLOR_MAP,
                color = "Trg",
                hole=0.4
            )

            fig.update_traces(
                textposition="inside",
                textinfo="percent+label",
                hovertemplate="<b>%{customdata[0]}</b><br>Delež: %{percent}<extra></extra>",
                customdata=pie_df[["Trg"]].values
            )

            fig.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                showlegend=True,
                legend_title_text = "Trgi"
            )

            st.plotly_chart(fig, use_container_width = True)
        with c2:
            st.markdown("**Tabela**")
            t = muni_struct.copy()
            t["Delež (%)"] = (t["Delež_norm"] * 100).round(1)
            t = t[["Trg", "Delež (%)"]].sort_values("Delež (%)", ascending=False)
            st.dataframe(t, use_container_width = True, hide_index=True)

        st.markdown("**Tabela občin (povzetek)**")
        # povzetek: prikaži top trg (največji delež) za vsako občino + prenočitve
        def top_market(row):
            pairs = [(lab, row[col]) for col, lab in zip(market_cols_year, market_labels_year) if pd.notna(row[col])]
            if not pairs:
                return ("—", np.nan)
            lab, val = max(pairs, key=lambda x: x[1])
            return (lab, val)

        tops = sub_m.copy()
        tops["Top trg"] = tops.apply(lambda r: top_market(r)[0], axis=1)
        tops["Top trg delež (%)"] = tops.apply(lambda r: top_market(r)[1] * 100 if pd.notna(top_market(r)[1]) else np.nan, axis=1)
        tops["Top trg delež (%)"] = tops["Top trg delež (%)"].round(1)

        tops_view = tops[["Občina", base_weight_col, "Top trg", "Top trg delež (%)"]].copy()
        tops_view = tops_view.sort_values(base_weight_col, ascending=False, na_position="last")
        st.dataframe(tops_view, use_container_width = True, hide_index=True)


tab_kazalniki, tab_trgi = st.tabs(["Kazalniki", "Struktura prenočitev po trgih"])

with tab_kazalniki:
    view_labels = [v[0] for v in views]
    selected_view_label = st.selectbox("Pogled", view_labels, index=0, key="view_main")
    title, group_col = next(v for v in views if v[0] == selected_view_label)
    render_view(title, group_col)

with tab_trgi:
    view_labels = [v[0] for v in views]
    view_labels.append("SLOVENIJA")
    selected_view_label_trgi = st.selectbox("Pogled", view_labels, index=0, key="view_trgi")
    if selected_view_label_trgi == "SLOVENIJA":
        title_trgi, group_col_trgi = ("SLOVENIJA", "SLOVENIJA")
    else:
        title_trgi, group_col_trgi = next(v for v in views if v[0] == selected_view_label_trgi)
    render_market_structure(title_trgi, group_col_trgi, market_cols, market_labels)


st.image("footer_logo.jpg", width= 200)

st.caption("Viri podatkov: SURS, AJPES, Narodna Banka Slovenije, Slovenska Turistična Organizacija, Lastna obdelava, izračuni in dodatne ocene manjkajočih podatkov - Hosting Management & Consulting d.o.o.")
st.caption("Avtor, izvajalec in skrbnik aplikacije: Hosting Management & Consulting d.o.o., kontakt: info@hosting.si, tel. +386 (0)41 514 020")
st.markdown("---")
