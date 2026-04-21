from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast

import streamlit as st

from tourism_dashboard.config import (
    AI_CACHE_CONNECTION_NAME_DEFAULT,
    AI_CACHE_SCHEMA_TTL_SECONDS,
    AI_CACHE_TABLE_NAME,
)
from tourism_dashboard.helpers import get_secret_value, sql

if TYPE_CHECKING:
    import requests
else:
    try:
        import requests
    except Exception:
        requests = None


OPENAI_CONNECT_TIMEOUT_SECONDS = 10
OPENAI_READ_TIMEOUT_SECONDS = 75
OPENAI_MAX_ATTEMPTS = 3


def get_ai_cache_connection() -> Tuple[Optional[Any], str]:
    connection_name: str = str(
        get_secret_value("AI_CACHE_CONNECTION_NAME", AI_CACHE_CONNECTION_NAME_DEFAULT)
    )
    connection_factory = cast(Any, getattr(st, "connection", None))
    if connection_factory is None:
        return None, connection_name
    try:
        connection = connection_factory(connection_name, type="sql")
    except Exception:
        connection = None
    return connection, connection_name


@st.cache_data(show_spinner=False, ttl=AI_CACHE_SCHEMA_TTL_SECONDS)
def _ensure_ai_cache_table_for_connection_cached(connection_name: str) -> bool:
    connection_factory = cast(Any, getattr(st, "connection", None))
    if connection_factory is None:
        raise RuntimeError("Streamlit SQL connections are not available.")

    conn = connection_factory(connection_name, type="sql")
    with conn.session as session:
        session.execute(
            sql(
                f"""
                CREATE TABLE IF NOT EXISTS {AI_CACHE_TABLE_NAME} (
                    cache_key TEXT PRIMARY KEY,
                    payload_hash TEXT NOT NULL,
                    region TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    response_text TEXT NOT NULL,
                    model TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        session.execute(sql(f"ALTER TABLE {AI_CACHE_TABLE_NAME} ENABLE ROW LEVEL SECURITY"))
        session.execute(sql(f"REVOKE ALL ON TABLE {AI_CACHE_TABLE_NAME} FROM anon, authenticated"))
        session.commit()
    return True


def ensure_ai_cache_table_for_connection(connection_name: str) -> bool:
    try:
        return _ensure_ai_cache_table_for_connection_cached(connection_name)
    except Exception:
        return False


def get_cached_ai_commentary(cache_key: str) -> Optional[Dict[str, Any]]:
    conn, connection_name = get_ai_cache_connection()
    if conn is None or not ensure_ai_cache_table_for_connection(connection_name):
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
) -> bool:
    conn, connection_name = get_ai_cache_connection()
    if conn is None or not ensure_ai_cache_table_for_connection(connection_name):
        return False

    try:
        with conn.session as session:
            session.execute(
                sql(
                    f"""
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
                    """
                ),
                {
                    "cache_key": cache_key,
                    "payload_hash": payload_hash,
                    "region": region_name,
                    "group_name": group_name,
                    "response_text": text,
                    "model": model,
                },
            )
            session.commit()
        return True
    except Exception:
        return False


def rows_to_prompt_lines(rows: List[Dict[str, Any]]) -> str:
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
            f"- {indicator} | smer: {direction} | območje: {region_val} | "
            f"Slovenija: {baseline_val} | primerjava: {comparison_method} | "
            f"odstopanje glede na smer: {aligned_delta} | primerjalni odmik: {raw_delta}"
        )
    return "\n".join(lines)


def grouped_rows_to_prompt_text(group_sections: List[Dict[str, Any]]) -> str:
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


def normalize_market_label_for_prompt(label: str) -> str:
    mapping = {
        "DACH trgi": "DACH trgi (nemško govoreči trgi: D, A in CH)",
    }
    return mapping.get(str(label).strip(), str(label).strip())


def market_rows_to_prompt_lines(
    rows: List[Dict[str, Any]],
    *,
    value_key: str,
    limit: int | None = None,
) -> str:
    if not rows:
        return "- Ni podatkov."

    lines = []
    for row in rows[: limit or len(rows)]:
        market = normalize_market_label_for_prompt(str(row.get("Trg", "—")))
        value = row.get(value_key, "—")
        lines.append(f"- {market}: {value}")
    return "\n".join(lines)


def market_analysis_to_prompt_text(market_analysis: Dict[str, Any] | None) -> str:
    if not market_analysis:
        return "Ni dodatnih podatkov o strukturi in gibanju prenočitev po trgih."

    latest_year = market_analysis.get("latest_year", "zadnje leto")
    structure_lines = market_rows_to_prompt_lines(
        cast(List[Dict[str, Any]], market_analysis.get("structure_rows", [])),
        value_key="Delež_norm",
    )

    growth_periods = cast(Dict[str, Dict[str, Any]], market_analysis.get("growth_periods", {}))
    growth_blocks = []
    for period in sorted(growth_periods.keys(), reverse=True):
        growth_rows = cast(List[Dict[str, Any]], growth_periods[period].get("rows", []))
        growth_blocks.append(
            f"Rast prenočitev po trgih ({period}):\n"
            f"{market_rows_to_prompt_lines(growth_rows, value_key='Rast')}"
        )

    growth_text = "\n\n".join(growth_blocks) if growth_blocks else "Ni podatkov o rasti po trgih."
    return (
        f"Struktura prenočitev po trgih v letu {latest_year}:\n"
        f"{structure_lines}\n\n"
        f"{growth_text}"
    )


def build_market_section_markdown(market_analysis: Dict[str, Any] | None) -> str:
    if not market_analysis:
        return ""
    return (
        "**3.1. Struktura in gibanje prenočitev po skupinah trgov**\n"
        f"{market_analysis_to_prompt_text(market_analysis)}"
    )


def ensure_market_section(text: str, market_analysis: Dict[str, Any] | None) -> str:
    if not market_analysis:
        return text

    lower_text = text.lower()
    if "3.1. struktura in gibanje prenočitev po skupinah trgov" in lower_text:
        return text

    market_section = build_market_section_markdown(market_analysis)
    if not market_section:
        return text

    insertion_markers = [
        "\n**4. Ekonomsko-poslovni kazalniki turistične dejavnosti**",
        "\n4. Ekonomsko-poslovni kazalniki turistične dejavnosti",
        "\n**4 konkretna priporočila**",
        "\n4 konkretna priporočila",
    ]
    for marker in insertion_markers:
        if marker in text:
            return text.replace(marker, f"\n\n{market_section}\n\n{marker.lstrip()}", 1)

    return f"{text.rstrip()}\n\n{market_section}"


def fallback_region_commentary(
    region_name: str,
    group_sections: List[Dict[str, Any]],
    market_analysis: Dict[str, Any] | None = None,
) -> str:
    summary_parts = []
    for section in group_sections:
        group_name = section.get("group", "Neznana skupina")
        top_names = ", ".join(row.get("Kazalnik", "—") for row in section.get("top_rows", [])[:2]) or "ni podatkov"
        bottom_names = ", ".join(row.get("Kazalnik", "—") for row in section.get("bottom_rows", [])[:2]) or "ni podatkov"
        summary_parts.append(f"{group_name}: prednosti {top_names}; tveganja {bottom_names}")

    summary_text = " | ".join(summary_parts) if summary_parts else "Ni dovolj podatkov za skupinsko primerjavo."
    market_context_text = market_analysis_to_prompt_text(market_analysis)
    return (
        f"**Povzetek za območje {region_name}:** {summary_text}. "
        f"Primerjava je glede na slovensko osnovo.\n\n"
        f"**3.1. Struktura in gibanje prenočitev po skupinah trgov**\n"
        f"{market_context_text}\n\n"
        f"**Priporočila:**\n"
        f"1. Ukrepe določite ločeno po skupinah kazalnikov, ne samo na ravni celotnega območja.\n"
        f"2. Pri najslabših kazalnikih v vsaki skupini določite 2-3 ciljne ukrepe z nosilci in roki.\n"
        f"3. Spremljajte napredek po skupinah in preverjajte, ali se slabši kazalniki približujejo slovenski osnovi.\n"
        f"4. Upravljajte strukturo trgov ločeno kratkoročno in dolgoročno: kratkoročno krepiti bolj dostopne "
        f"bližnje trge za stabilnost zasedenosti, dolgoročno pa razvijati bolj donosne in manj sezonsko občutljive "
        f"trge, pri čemer pazite na preveliko odvisnost od enega samega izvora."
    )


def extract_response_text(resp_json: Dict[str, Any]) -> Optional[str]:
    direct = resp_json.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    for item in resp_json.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                    return text.strip()
    return None


def extract_openai_error_fields(resp: Any) -> Tuple[Optional[str], Optional[str], Optional[str]]:
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
    return (
        str(message).strip() if message is not None else None,
        str(err_type).strip() if err_type is not None else None,
        str(code).strip() if code is not None else None,
    )


def format_openai_http_error(resp: Any) -> str:
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
        if err_code == "insufficient_quota" or err_type == "insufficient_quota":
            return False
        return True
    return False


def compute_retry_delay_seconds(resp: Any, attempt_index: int) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            seconds = float(retry_after)
            if seconds > 0:
                return min(seconds, 20.0)
        except Exception:
            pass
    return min(1.5 * (2 ** attempt_index), 20.0)


def compute_exception_retry_delay_seconds(attempt_index: int) -> float:
    return min(2.0 * (2 ** attempt_index), 15.0)


def generate_region_ai_commentary(
    region_name: str,
    group_sections: List[Dict[str, Any]],
    market_analysis: Dict[str, Any] | None = None,
) -> Tuple[str, str, Optional[str]]:
    api_key = get_secret_value("OPENAI_API_KEY")
    if not api_key or requests is None:
        return fallback_region_commentary(region_name, group_sections, market_analysis), "fallback", None

    requests_module = cast(Any, requests)
    model = get_secret_value("OPENAI_MODEL", "gpt-5.4")
    system_prompt = (
        "Si analitik regionalnega razvoja turizma. Uporabi samo podane "
        "kazalnike in podaj kratko, praktično razlago ter priporočila. "
        "Odgovor napiši v stabilni, jasno členjeni strukturi z navedenimi naslovi."
    )
    user_prompt = (
        f"Območje: {region_name}\n\n"
        f"Top/Bottom po skupinah kazalnikov:\n{grouped_rows_to_prompt_text(group_sections)}\n\n"
        f"Struktura in gibanje prenočitev po skupinah trgov:\n{market_analysis_to_prompt_text(market_analysis)}\n\n"
        "Naloga:\n"
        "1) Uporabi točno naslednjo strukturo naslovov:\n"
        "Kratek celosten komentar\n"
        "1. Družbeni kazalniki\n"
        "2. Okoljski kazalniki\n"
        "3. Ekonomski nastanitveni in tržni kazalniki\n"
        "3.1. Struktura in gibanje prenočitev po skupinah trgov\n"
        "4. Ekonomsko-poslovni kazalniki turistične dejavnosti\n"
        "5 konkretnih priporočil\n"
        "2) Pri poglavjih 1, 2, 3 in 4 jasno loči podnaslova Prednosti in Tveganja ter pri teh poglavjih napiši maksimalno 3 tveganja in 3 prednosti\n"
        "3) V podpoglavju 3.1 analiziraj strukturo trgov v zadnjem opazovanem letu ter komentiraj rast posameznih trgov "
        "glede na predhodno leto in glede na leto 2019.\n"
        "4) V priporočilih obvezno dodaj vsaj eno priporočilo za upravljanje strukture trgov v kratkoročnem in dolgoročnem obdobju "
        "z vidika donosnosti in dosegljivosti. Pri tem lahko uporabiš splošno znano presojo o bližnjih, cestno dosegljivih trgih "
        "v primerjavi z bolj oddaljenimi, praviloma letalsko odvisnimi trgi, vendar ne izmišljaj specifičnih številk ali virov.\n"
        "5) Uporabi samo podane podatke, brez izmišljenih razlag ali številk.\n"
        "6) Piši v slovenščini, profesionalno, jedrnato."
    )

    payload = {
        "model": model,
        "temperature": 0.3,
        "max_output_tokens": 3000,
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
        for attempt in range(OPENAI_MAX_ATTEMPTS):
            try:
                resp = requests_module.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    data=json.dumps(payload),
                    timeout=(OPENAI_CONNECT_TIMEOUT_SECONDS, OPENAI_READ_TIMEOUT_SECONDS),
                )
            except Exception as exc:
                request_exceptions = getattr(requests_module, "exceptions", None)
                timeout_types = tuple(
                    exception_type
                    for exception_type in (
                        getattr(request_exceptions, "Timeout", None),
                        getattr(request_exceptions, "ReadTimeout", None),
                        getattr(request_exceptions, "ConnectionError", None),
                    )
                    if exception_type is not None
                )
                is_retryable_exception = bool(timeout_types) and isinstance(exc, timeout_types)
                if is_retryable_exception and attempt < OPENAI_MAX_ATTEMPTS - 1:
                    time.sleep(compute_exception_retry_delay_seconds(attempt))
                    continue
                return (
                    fallback_region_commentary(region_name, group_sections, market_analysis),
                    "fallback",
                    str(exc),
                )

            if resp.status_code < 400:
                text = extract_response_text(resp.json())
                if not text:
                    return (
                        fallback_region_commentary(region_name, group_sections, market_analysis),
                        "fallback",
                        "AI odgovor je bil prazen.",
                    )
                return ensure_market_section(text, market_analysis), "ai", None

            message, err_type, err_code = extract_openai_error_fields(resp)
            if attempt < OPENAI_MAX_ATTEMPTS - 1 and should_retry_openai_call(resp.status_code, err_type, err_code):
                time.sleep(compute_retry_delay_seconds(resp, attempt))
                continue

            if resp.status_code == 429 and (err_code == "insufficient_quota" or err_type == "insufficient_quota"):
                err = (
                    "AI klic ni uspel (HTTP 429). Kvota za OPENAI_API_KEY je porabljena "
                    "(insufficient_quota). Preveri billing/kvote na platform.openai.com."
                )
            else:
                err = format_openai_http_error(resp)
            return fallback_region_commentary(region_name, group_sections, market_analysis), "fallback", err
    except Exception as exc:
        return fallback_region_commentary(region_name, group_sections, market_analysis), "fallback", str(exc)

    return fallback_region_commentary(region_name, group_sections, market_analysis), "fallback", "AI klic se ni izvedel."
