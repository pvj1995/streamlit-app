from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pandas as pd
import toml
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Connection, Engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tourism_dashboard.config import (  # noqa: E402
    DASHBOARD_DB_CONNECTION_NAME_DEFAULT,
    DASHBOARD_DB_SCHEMA_VERSION,
    DASHBOARD_MAIN_FRAME_KEY,
    DASHBOARD_MAPPING_FRAME_KEY,
    DASHBOARD_MARKET_GROWTH_FRAME_KEY,
    DATA_XLSX_FILENAME,
    MAPPING_XLSX_FILENAME,
)
from tourism_dashboard.helpers import (  # noqa: E402
    find_market_arrivals_seasonality_files,
    find_market_overnight_seasonality_files,
    find_market_pdb_files,
    load_excel,
    load_market_arrivals_seasonality_workbook,
    load_market_overnight_seasonality_workbook,
    load_market_pdb_workbook,
)
from tourism_dashboard.paths import BASE_DIR, DATA_DIR, first_existing  # noqa: E402


@dataclass(frozen=True)
class FrameSpec:
    frame_key: str
    df: pd.DataFrame
    source_filename: str
    sheet_name: str | None
    frame_type: str
    metric: str | None = None
    year: int | None = None
    area_level: str | None = None
    frame_kind: str | None = None


def load_local_secrets() -> dict[str, Any]:
    secrets_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return {}
    return toml.loads(secrets_path.read_text(encoding="utf-8"))


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    split = urlsplit(url)
    if split.scheme.startswith("postgresql") and "supabase" in split.netloc and "sslmode=" not in split.query:
        query = dict(parse_qsl(split.query, keep_blank_values=True))
        query["sslmode"] = "require"
        url = urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))
    return url


def get_database_url() -> str:
    for env_name in ("DASHBOARD_DATABASE_URL", "DATABASE_URL", "SUPABASE_DB_URL"):
        value = os.environ.get(env_name)
        if value:
            return normalize_database_url(value)

    secrets = load_local_secrets()
    for secret_name in ("DASHBOARD_DATABASE_URL", "DATABASE_URL", "SUPABASE_DB_URL"):
        value = secrets.get(secret_name)
        if value:
            return normalize_database_url(str(value))

    connections = secrets.get("connections", {})
    connection_name = str(
        secrets.get(
            "DASHBOARD_DB_CONNECTION_NAME",
            secrets.get("AI_CACHE_CONNECTION_NAME", DASHBOARD_DB_CONNECTION_NAME_DEFAULT),
        )
    )
    candidate_names = [connection_name, "dashboard_db", DASHBOARD_DB_CONNECTION_NAME_DEFAULT, "ai_cache_db"]
    for candidate_name in candidate_names:
        candidate = connections.get(candidate_name, {}) if isinstance(connections, dict) else {}
        value = candidate.get("url") if isinstance(candidate, dict) else None
        if value:
            return normalize_database_url(str(value))

    raise RuntimeError(
        "Database URL not found. Set DASHBOARD_DATABASE_URL, DATABASE_URL, SUPABASE_DB_URL, "
        "or a [connections.<name>].url entry in .streamlit/secrets.toml."
    )


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_").lower()
    return slug or "frame"


def is_null_cell(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def cell_to_text(value: Any) -> str | None:
    if is_null_cell(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


def frame_content_hash(df: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update(f"{df.shape[0]}x{df.shape[1]}".encode("utf-8"))
    for column_index, column_name in enumerate(df.columns):
        digest.update(f"c:{column_index}:{cell_to_text(column_name) or ''}\n".encode("utf-8"))
    for row_index in range(df.shape[0]):
        for column_index in range(df.shape[1]):
            value = cell_to_text(df.iat[row_index, column_index])
            digest.update(f"v:{row_index}:{column_index}:{value if value is not None else '<NULL>'}\n".encode("utf-8"))
    return digest.hexdigest()


def market_frame_key(metric: str, year: int, area_level: str, frame_kind: str) -> str:
    return f"market:{metric}:{year}:{slugify(area_level)}:{slugify(frame_kind)}"


def build_frames() -> list[FrameSpec]:
    main_path = first_existing(DATA_DIR / DATA_XLSX_FILENAME, BASE_DIR / DATA_XLSX_FILENAME)
    mapping_path = first_existing(DATA_DIR / MAPPING_XLSX_FILENAME, BASE_DIR / MAPPING_XLSX_FILENAME)
    if not main_path.exists():
        raise FileNotFoundError(f"Missing main workbook: {main_path}")
    if not mapping_path.exists():
        raise FileNotFoundError(f"Missing mapping workbook: {mapping_path}")

    frames = [
        FrameSpec(
            frame_key=DASHBOARD_MAIN_FRAME_KEY,
            df=load_excel(main_path, sheet_name="Skupna Tabela"),
            source_filename=main_path.name,
            sheet_name="Skupna Tabela",
            frame_type="main",
        ),
        FrameSpec(
            frame_key=DASHBOARD_MARKET_GROWTH_FRAME_KEY,
            df=load_excel(main_path, sheet_name="Rast prenočitev po trgih"),
            source_filename=main_path.name,
            sheet_name="Rast prenočitev po trgih",
            frame_type="market_growth",
        ),
        FrameSpec(
            frame_key=DASHBOARD_MAPPING_FRAME_KEY,
            df=pd.read_excel(mapping_path),
            source_filename=mapping_path.name,
            sheet_name="Sheet1",
            frame_type="mapping",
        ),
    ]

    monthly_sources = [
        ("overnights", find_market_overnight_seasonality_files, load_market_overnight_seasonality_workbook),
        ("arrivals", find_market_arrivals_seasonality_files, load_market_arrivals_seasonality_workbook),
    ]
    for metric, finder, loader in monthly_sources:
        for year, path in sorted(finder().items()):
            for area_level, df in loader(str(path)).items():
                frames.append(
                    FrameSpec(
                        frame_key=market_frame_key(metric, year, area_level, "seasonality"),
                        df=df,
                        source_filename=path.name,
                        sheet_name=area_level,
                        frame_type="market_monthly",
                        metric=metric,
                        year=year,
                        area_level=area_level,
                        frame_kind="seasonality",
                    )
                )

    for year, path in sorted(find_market_pdb_files().items()):
        for area_level, workbook_frames in load_market_pdb_workbook(str(path)).items():
            for frame_kind, df in workbook_frames.items():
                frames.append(
                    FrameSpec(
                        frame_key=market_frame_key("pdb", year, area_level, frame_kind),
                        df=df,
                        source_filename=path.name,
                        sheet_name=area_level,
                        frame_type="market_monthly",
                        metric="pdb",
                        year=year,
                        area_level=area_level,
                        frame_kind=frame_kind,
                    )
                )

    return frames


def ensure_schema(conn: Connection) -> None:
    schema_path = PROJECT_ROOT / "db" / "dashboard_frames.sql"
    for statement in schema_path.read_text(encoding="utf-8").split(";"):
        cleaned = statement.strip()
        if cleaned:
            conn.execute(text(cleaned))


def copy_rows(conn: Connection, table_name: str, columns: list[str], rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    raw_connection = getattr(conn.connection, "driver_connection", None)
    if raw_connection is None:
        raw_connection = conn.connection.connection

    null_marker = "__DASHBOARD_COPY_NULL__"
    buffer = StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow([
            row[column] if row[column] is not None else null_marker
            for column in columns
        ])
    buffer.seek(0)

    column_sql = ", ".join(columns)
    copy_sql = (
        f"COPY {table_name} ({column_sql}) "
        f"FROM STDIN WITH (FORMAT CSV, NULL '{null_marker}')"
    )
    with raw_connection.cursor() as cursor:
        cursor.copy_expert(copy_sql, buffer)


def insert_frame(conn: Connection, spec: FrameSpec) -> tuple[int, int]:
    df = spec.df.copy()
    column_rows = [
        {
            "frame_key": spec.frame_key,
            "column_index": column_index,
            "column_name": cell_to_text(column_name) or "",
        }
        for column_index, column_name in enumerate(df.columns)
    ]
    cell_rows: list[dict[str, Any]] = []
    for row_index in range(df.shape[0]):
        for column_index in range(df.shape[1]):
            raw_value = cell_to_text(df.iat[row_index, column_index])
            if raw_value is None:
                continue
            cell_rows.append(
                {
                    "frame_key": spec.frame_key,
                    "row_index": row_index,
                    "column_index": column_index,
                    "raw_value": raw_value,
                }
            )

    conn.execute(
        text(
            """
            INSERT INTO dashboard_frames (
                frame_key, schema_version, source_filename, sheet_name, frame_type,
                metric, year, area_level, frame_kind, row_count, column_count, content_hash
            )
            VALUES (
                :frame_key, :schema_version, :source_filename, :sheet_name, :frame_type,
                :metric, :year, :area_level, :frame_kind, :row_count, :column_count, :content_hash
            )
            """
        ),
        {
            "frame_key": spec.frame_key,
            "schema_version": DASHBOARD_DB_SCHEMA_VERSION,
            "source_filename": spec.source_filename,
            "sheet_name": spec.sheet_name,
            "frame_type": spec.frame_type,
            "metric": spec.metric,
            "year": spec.year,
            "area_level": spec.area_level,
            "frame_kind": spec.frame_kind,
            "row_count": int(df.shape[0]),
            "column_count": int(df.shape[1]),
            "content_hash": frame_content_hash(df),
        },
    )
    copy_rows(
        conn,
        "dashboard_frame_columns",
        ["frame_key", "column_index", "column_name"],
        column_rows,
    )
    copy_rows(
        conn,
        "dashboard_frame_cells",
        ["frame_key", "row_index", "column_index", "raw_value"],
        cell_rows,
    )
    return len(column_rows), len(cell_rows)


def load_frame_from_db(engine: Engine, frame_key: str) -> pd.DataFrame:
    with engine.connect() as conn:
        meta_df = pd.read_sql(
            text("SELECT row_count FROM dashboard_frames WHERE frame_key = :frame_key"),
            conn,
            params={"frame_key": frame_key},
        )
        if meta_df.empty:
            return pd.DataFrame()
        row_count = int(meta_df.iloc[0]["row_count"])
        columns_df = pd.read_sql(
            text(
                """
                SELECT column_index, column_name
                FROM dashboard_frame_columns
                WHERE frame_key = :frame_key
                ORDER BY column_index
                """
            ),
            conn,
            params={"frame_key": frame_key},
        )
        cells_df = pd.read_sql(
            text(
                """
                SELECT row_index, column_index, raw_value
                FROM dashboard_frame_cells
                WHERE frame_key = :frame_key
                ORDER BY row_index, column_index
                """
            ),
            conn,
            params={"frame_key": frame_key},
        )

    index = range(row_count)
    series_list: list[pd.Series] = []
    if not cells_df.empty:
        wide_df = cells_df.pivot(index="row_index", columns="column_index", values="raw_value")
    else:
        wide_df = pd.DataFrame()

    for row in columns_df.itertuples(index=False):
        column_index = int(getattr(row, "column_index"))
        column_name = str(getattr(row, "column_name"))
        if column_index in wide_df.columns:
            series = wide_df[column_index].reindex(index)
        else:
            series = pd.Series([None] * row_count, index=index)
        series.name = column_name
        series_list.append(series)
    return pd.concat(series_list, axis=1) if series_list else pd.DataFrame(index=index)


def frame_values_as_text(df: pd.DataFrame) -> list[list[str | None]]:
    return [
        [cell_to_text(df.iat[row_index, column_index]) for column_index in range(df.shape[1])]
        for row_index in range(df.shape[0])
    ]


def verify_import(engine: Engine, frames: list[FrameSpec]) -> None:
    for spec in frames:
        db_df = load_frame_from_db(engine, spec.frame_key)
        if db_df.shape != spec.df.shape:
            raise AssertionError(f"{spec.frame_key}: shape mismatch {db_df.shape} != {spec.df.shape}")
        source_columns = [cell_to_text(column) or "" for column in spec.df.columns]
        db_columns = [cell_to_text(column) or "" for column in db_df.columns]
        if db_columns != source_columns:
            raise AssertionError(f"{spec.frame_key}: column mismatch")
        if frame_values_as_text(db_df) != frame_values_as_text(spec.df):
            raise AssertionError(f"{spec.frame_key}: cell value mismatch")


def import_frames(engine: Engine, frames: list[FrameSpec]) -> tuple[int, int]:
    frame_keys = [frame.frame_key for frame in frames]
    total_columns = 0
    total_cells = 0
    with engine.begin() as conn:
        ensure_schema(conn)
        prune_stmt = text(
            """
            DELETE FROM dashboard_frames
            WHERE schema_version = :schema_version
              AND frame_key NOT IN :frame_keys
            """
        ).bindparams(bindparam("frame_keys", expanding=True))
        conn.execute(
            prune_stmt,
            {
                "schema_version": DASHBOARD_DB_SCHEMA_VERSION,
                "frame_keys": frame_keys,
            },
        )
        replace_stmt = text("DELETE FROM dashboard_frames WHERE frame_key IN :frame_keys").bindparams(
            bindparam("frame_keys", expanding=True)
        )
        conn.execute(replace_stmt, {"frame_keys": frame_keys})
        for spec in frames:
            column_count, cell_count = insert_frame(conn, spec)
            total_columns += column_count
            total_cells += cell_count
    return total_columns, total_cells


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import dashboard Excel data into PostgreSQL/Supabase.")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip the post-import database parity check.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frames = build_frames()
    database_url = get_database_url()
    engine = create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 15})

    print(f"Prepared {len(frames)} frames from Excel files.")
    total_columns, total_cells = import_frames(engine, frames)
    print(f"Imported {len(frames)} frames, {total_columns} columns, and {total_cells} populated cells.")

    if not args.no_verify:
        verify_import(engine, frames)
        print("Verified database contents against the parsed Excel frames.")


if __name__ == "__main__":
    main()
