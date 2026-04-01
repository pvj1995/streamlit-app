from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast

import streamlit as st

from tourism_dashboard.config import AI_CACHE_CONNECTION_NAME_DEFAULT, AI_CACHE_TABLE_NAME
from tourism_dashboard.helpers import get_secret_value, sql


AI_COMMENTARY_FORMAT_VERSION = "structured_v2"

AI_COMMENTARY_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "short_commentary": {
            "type": "string",
        },
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "group": {"type": "string"},
                    "strengths": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "risks": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["group", "strengths", "risks"],
                "additionalProperties": False,
            },
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["short_commentary", "groups", "recommendations"],
    "additionalProperties": False,
}


if TYPE_CHECKING:
    import requests
else:
    try:
        import requests
    except Exception:
        requests = None


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


def ensure_ai_cache_table(conn: Any) -> bool:
    try:
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
            session.commit()
        return True
    except Exception:
        return False


def get_cached_ai_commentary(cache_key: str) -> Optional[Dict[str, Any]]:
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
    except Exception:
        return


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


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def row_to_commentary_line(row: Dict[str, Any]) -> str:
    indicator = clean_text(row.get("Kazalnik", "Kazalnik"))
    region_val = clean_text(row.get("Vrednost območja", "—"))
    slovenia_val = clean_text(row.get("Osnova (Slovenija)", "—"))
    comparison = clean_text(row.get("Primerjalni odmik", "—"))
    return f"{indicator}: {region_val} (Slovenija: {slovenia_val}; odmik: {comparison})."


def fallback_group_points(rows: List[Dict[str, Any]], fallback_text: str) -> List[str]:
    points = [row_to_commentary_line(row) for row in rows[:5]]
    return points if points else [fallback_text]


def fallback_recommendations(group_sections: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    recommendations: List[Dict[str, str]] = []
    for section in group_sections:
        group_name = clean_text(section.get("group", "Neznana skupina"))
        top_names = ", ".join(clean_text(row.get("Kazalnik", "—")) for row in section.get("top_rows", [])[:2]) or "ključne prednosti"
        bottom_names = (
            ", ".join(clean_text(row.get("Kazalnik", "—")) for row in section.get("bottom_rows", [])[:2])
            or "ključna tveganja"
        )
        recommendations.append(
            {
                "title": f"Ukrepi v sklopu: {group_name}",
                "description": (
                    f"Ohranite prednosti ({top_names}) in prioritetno naslovite tveganja "
                    f"({bottom_names}) z jasnimi nosilci, roki in merljivimi cilji."
                ),
            }
        )

    generic_tail = [
        {
            "title": "Vzpostavite redno spremljanje po skupinah kazalnikov",
            "description": (
                "Napredek spremljajte ločeno po družbenih, okoljskih, nastanitveno-tržnih "
                "in poslovnih kazalnikih, da bodo ukrepi bolj ciljno usmerjeni."
            ),
        },
        {
            "title": "Povežite razvojne ukrepe med vsebinskimi sklopi",
            "description": (
                "Razvoj ponudbe, upravljanje obiskov, poslovno uspešnost in vplive na okolje "
                "obravnavajte povezano, ne kot ločene teme."
            ),
        },
    ]

    while len(recommendations) < 4 and generic_tail:
        recommendations.append(generic_tail.pop(0))

    return recommendations[:4]


def build_commentary_markdown(
    short_commentary: str,
    group_payloads: List[Dict[str, Any]],
    recommendations: List[Dict[str, str]],
) -> str:
    lines = ["**Kratek celosten komentar**", clean_text(short_commentary) or "Ni dovolj podatkov za komentar.", ""]
    lines.extend(["## Glavne prednosti in tveganja po skupinah", ""])

    for index, group_payload in enumerate(group_payloads, start=1):
        group_name = clean_text(group_payload.get("group", f"Skupina {index}"))
        strengths = [clean_text(item) for item in group_payload.get("strengths", []) if clean_text(item)]
        risks = [clean_text(item) for item in group_payload.get("risks", []) if clean_text(item)]
        if not strengths:
            strengths = ["Ni dovolj podatkov za izpostavljene prednosti."]
        if not risks:
            risks = ["Ni dovolj podatkov za izpostavljena tveganja."]

        lines.append(f"### {index}) {group_name}")
        lines.append("")
        lines.append("**Prednosti**")
        for item in strengths[:5]:
            lines.append(f"- {item}")
        lines.append("")
        lines.append("**Tveganja**")
        for item in risks[:5]:
            lines.append(f"- {item}")
        lines.append("")

    lines.extend(["## 4 konkretna priporočila", ""])
    for index, recommendation in enumerate(recommendations[:4], start=1):
        title = clean_text(recommendation.get("title", f"Priporočilo {index}"))
        description = clean_text(recommendation.get("description", ""))
        lines.append(f"{index}. **{title}**")
        if description:
            lines.append(description)
        lines.append("")

    return "\n".join(lines).strip()


def fallback_region_commentary(region_name: str, group_sections: List[Dict[str, Any]]) -> str:
    summary_parts = []
    group_payloads = []
    for section in group_sections:
        group_name = clean_text(section.get("group", "Neznana skupina"))
        top_rows = section.get("top_rows", [])
        bottom_rows = section.get("bottom_rows", [])
        top_names = ", ".join(clean_text(row.get("Kazalnik", "—")) for row in top_rows[:2]) or "ni podatkov"
        bottom_names = ", ".join(clean_text(row.get("Kazalnik", "—")) for row in bottom_rows[:2]) or "ni podatkov"
        summary_parts.append(f"{group_name}: prednosti {top_names}; tveganja {bottom_names}")
        group_payloads.append(
            {
                "group": group_name,
                "strengths": fallback_group_points(top_rows, "Ni dovolj podatkov za izpostavljene prednosti."),
                "risks": fallback_group_points(bottom_rows, "Ni dovolj podatkov za izpostavljena tveganja."),
            }
        )

    short_commentary = (
        f"Območje {region_name} je ocenjeno glede na slovensko osnovo in rezultate po posameznih skupinah "
        f"kazalnikov. {' '.join(summary_parts) if summary_parts else 'Ni dovolj podatkov za skupinsko primerjavo.'}"
    )
    return build_commentary_markdown(
        short_commentary=short_commentary,
        group_payloads=group_payloads,
        recommendations=fallback_recommendations(group_sections),
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


def parse_ai_commentary_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    text = raw_text.strip()
    if not text:
        return None

    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        payload = json.loads(text[start : end + 1])
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def build_group_payloads_from_ai(
    payload: Dict[str, Any],
    group_sections: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    groups_raw = payload.get("groups", [])
    group_mapping: Dict[str, Dict[str, Any]] = {}
    if isinstance(groups_raw, list):
        for item in groups_raw:
            if not isinstance(item, dict):
                continue
            group_name = clean_text(item.get("group", ""))
            if group_name:
                group_mapping[group_name] = item

    rendered_groups: List[Dict[str, Any]] = []
    for section in group_sections:
        group_name = clean_text(section.get("group", "Neznana skupina"))
        item = group_mapping.get(group_name, {})
        strengths_raw = item.get("strengths", [])
        risks_raw = item.get("risks", [])
        strengths = [clean_text(entry) for entry in strengths_raw if clean_text(entry)] if isinstance(strengths_raw, list) else []
        risks = [clean_text(entry) for entry in risks_raw if clean_text(entry)] if isinstance(risks_raw, list) else []
        rendered_groups.append(
            {
                "group": group_name,
                "strengths": strengths or fallback_group_points(
                    section.get("top_rows", []),
                    "Ni dovolj podatkov za izpostavljene prednosti.",
                ),
                "risks": risks or fallback_group_points(
                    section.get("bottom_rows", []),
                    "Ni dovolj podatkov za izpostavljena tveganja.",
                ),
            }
        )
    return rendered_groups


def normalize_ai_recommendations(
    payload: Dict[str, Any],
    group_sections: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    recommendations_raw = payload.get("recommendations", [])
    recommendations: List[Dict[str, str]] = []
    if isinstance(recommendations_raw, list):
        for item in recommendations_raw:
            if not isinstance(item, dict):
                continue
            title = clean_text(item.get("title", ""))
            description = clean_text(item.get("description", ""))
            if title and description:
                recommendations.append({"title": title, "description": description})

    if len(recommendations) < 4:
        fallback = fallback_recommendations(group_sections)
        existing_titles = {item["title"] for item in recommendations}
        for item in fallback:
            if item["title"] not in existing_titles:
                recommendations.append(item)
            if len(recommendations) >= 4:
                break
    return recommendations[:4]


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


def generate_region_ai_commentary(
    region_name: str,
    group_sections: List[Dict[str, Any]],
) -> Tuple[str, str, Optional[str]]:
    api_key = get_secret_value("OPENAI_API_KEY")
    if not api_key or requests is None:
        return fallback_region_commentary(region_name, group_sections), "fallback", None

    requests_module = cast(Any, requests)
    model = get_secret_value("OPENAI_MODEL", "gpt-5.4")
    group_names = [clean_text(section.get("group", "Neznana skupina")) for section in group_sections]
    system_prompt = (
        "Si analitik regionalnega razvoja turizma. Uporabi samo podane kazalnike. "
        "Vedno vrni izključno veljaven JSON brez markdowna in brez dodatnega besedila."
    )
    user_prompt = (
        f"Območje: {region_name}\n\n"
        f"Top/Bottom po skupinah kazalnikov:\n{grouped_rows_to_prompt_text(group_sections)}\n\n"
        "Vrni izključno JSON v naslednji strukturi:\n"
        "{\n"
        '  "short_commentary": "5-7 stavkov, celosten komentar.",\n'
        '  "groups": [\n'
        '    {"group": "ime skupine", "strengths": ["..."], "risks": ["..."]}\n'
        "  ],\n"
        '  "recommendations": [\n'
        '    {"title": "kratek naslov", "description": "1-2 stavka"}\n'
        "  ]\n"
        "}\n\n"
        f"Pravila:\n"
        f"- Skupine vrni v istem vrstnem redu kot so podane: {', '.join(group_names)}.\n"
        "- Za vsako skupino vrni 3 do 5 alinej v `strengths` in 3 do 5 alinej v `risks`.\n"
        "- `short_commentary` naj bo kratek, celosten in jedrnat.\n"
        "- `recommendations` naj vsebuje točno 4 priporočila.\n"
        "- Uporabi samo podane podatke, brez izmišljenih številk in brez dodatnega besedila zunaj JSON.\n"
        "- Piši v slovenščini, profesionalno in jasno."
    )

    payload = {
        "model": model,
        "temperature": 0.15,
        "max_output_tokens": 2000,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "regional_tourism_commentary",
                "strict": True,
                "schema": AI_COMMENTARY_JSON_SCHEMA,
            }
        },
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
            resp = requests_module.post(
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
                    return fallback_region_commentary(region_name, group_sections), "fallback", "AI odgovor je bil prazen."
                payload = parse_ai_commentary_payload(text)
                if payload is None:
                    return (
                        fallback_region_commentary(region_name, group_sections),
                        "fallback",
                        "AI odgovor ni bil v pričakovani JSON strukturi.",
                    )
                rendered = build_commentary_markdown(
                    short_commentary=clean_text(payload.get("short_commentary", "")),
                    group_payloads=build_group_payloads_from_ai(payload, group_sections),
                    recommendations=normalize_ai_recommendations(payload, group_sections),
                )
                return rendered, "ai", None

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
    except Exception as exc:
        return fallback_region_commentary(region_name, group_sections), "fallback", str(exc)

    return fallback_region_commentary(region_name, group_sections), "fallback", "AI klic se ni izvedel."
