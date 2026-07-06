from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .paths import db_path


SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    client TEXT NOT NULL,
    model_alias TEXT NOT NULL,
    upstream TEXT NOT NULL,
    input_chars INTEGER NOT NULL,
    output_chars INTEGER NOT NULL,
    estimated_tokens INTEGER NOT NULL,
    estimated_cost REAL NOT NULL,
    rule_applied TEXT,
    active_budget TEXT,
    budget_action TEXT NOT NULL,
    security_event TEXT,
    output_reduced INTEGER NOT NULL DEFAULT 0,
    headroom_applied INTEGER NOT NULL DEFAULT 0,
    headroom_adapter TEXT,
    headroom_input_chars_before INTEGER NOT NULL DEFAULT 0,
    headroom_input_chars_after INTEGER NOT NULL DEFAULT 0,
    headroom_input_tokens_before INTEGER NOT NULL DEFAULT 0,
    headroom_input_tokens_after INTEGER NOT NULL DEFAULT 0,
    headroom_tokens_saved INTEGER NOT NULL DEFAULT 0,
    headroom_reduction_ratio REAL NOT NULL DEFAULT 0.0,
    headroom_skipped INTEGER NOT NULL DEFAULT 0,
    headroom_skip_reason TEXT,
    cache_hit INTEGER NOT NULL DEFAULT 0,
    cache_miss INTEGER NOT NULL DEFAULT 0,
    cache_mode TEXT,
    cache_tokens_saved INTEGER NOT NULL DEFAULT 0,
    cache_cost_saved REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    metadata TEXT NOT NULL
);
"""

USAGE_EVENT_COLUMNS: dict[str, str] = {
    "output_reduced": "INTEGER NOT NULL DEFAULT 0",
    "headroom_applied": "INTEGER NOT NULL DEFAULT 0",
    "headroom_adapter": "TEXT",
    "headroom_input_chars_before": "INTEGER NOT NULL DEFAULT 0",
    "headroom_input_chars_after": "INTEGER NOT NULL DEFAULT 0",
    "headroom_input_tokens_before": "INTEGER NOT NULL DEFAULT 0",
    "headroom_input_tokens_after": "INTEGER NOT NULL DEFAULT 0",
    "headroom_tokens_saved": "INTEGER NOT NULL DEFAULT 0",
    "headroom_reduction_ratio": "REAL NOT NULL DEFAULT 0.0",
    "headroom_skipped": "INTEGER NOT NULL DEFAULT 0",
    "headroom_skip_reason": "TEXT",
    "cache_hit": "INTEGER NOT NULL DEFAULT 0",
    "cache_miss": "INTEGER NOT NULL DEFAULT 0",
    "cache_mode": "TEXT",
    "cache_tokens_saved": "INTEGER NOT NULL DEFAULT 0",
    "cache_cost_saved": "REAL NOT NULL DEFAULT 0.0",
}


@contextmanager
def connect(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    database = path or db_path()
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db(path: Path | None = None) -> Path:
    database = path or db_path()
    with connect(database) as connection:
        connection.executescript(SCHEMA)
        _ensure_usage_columns(connection)
    return database


def _ensure_usage_columns(connection: sqlite3.Connection) -> None:
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(usage_events)")}
    for column, definition in USAGE_EVENT_COLUMNS.items():
        if column not in existing:
            connection.execute(f"ALTER TABLE usage_events ADD COLUMN {column} {definition}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_usage(event: dict[str, Any], path: Path | None = None) -> None:
    init_db(path)
    payload = {
        "timestamp": event.get("timestamp") or now_iso(),
        "client": event.get("client", "unknown"),
        "model_alias": event.get("model_alias", "unknown"),
        "upstream": event.get("upstream", "unknown"),
        "input_chars": int(event.get("input_chars", 0)),
        "output_chars": int(event.get("output_chars", 0)),
        "estimated_tokens": int(event.get("estimated_tokens", 0)),
        "estimated_cost": float(event.get("estimated_cost", 0.0)),
        "rule_applied": event.get("rule_applied"),
        "active_budget": event.get("active_budget"),
        "budget_action": event.get("budget_action", "allow"),
        "security_event": event.get("security_event"),
        "output_reduced": int(bool(event.get("output_reduced", False))),
        "headroom_applied": int(bool(event.get("headroom_applied", False))),
        "headroom_adapter": event.get("headroom_adapter"),
        "headroom_input_chars_before": int(event.get("headroom_input_chars_before", 0)),
        "headroom_input_chars_after": int(event.get("headroom_input_chars_after", 0)),
        "headroom_input_tokens_before": int(event.get("headroom_input_tokens_before", 0)),
        "headroom_input_tokens_after": int(event.get("headroom_input_tokens_after", 0)),
        "headroom_tokens_saved": int(event.get("headroom_tokens_saved", 0)),
        "headroom_reduction_ratio": float(event.get("headroom_reduction_ratio", 0.0)),
        "headroom_skipped": int(bool(event.get("headroom_skipped", False))),
        "headroom_skip_reason": event.get("headroom_skip_reason"),
        "cache_hit": int(bool(event.get("cache_hit", False))),
        "cache_miss": int(bool(event.get("cache_miss", False))),
        "cache_mode": event.get("cache_mode"),
        "cache_tokens_saved": int(event.get("cache_tokens_saved", 0)),
        "cache_cost_saved": float(event.get("cache_cost_saved", 0.0)),
    }
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO usage_events (
                timestamp, client, model_alias, upstream, input_chars, output_chars,
                estimated_tokens, estimated_cost, rule_applied, active_budget,
                budget_action, security_event, output_reduced, headroom_applied,
                headroom_adapter, headroom_input_chars_before, headroom_input_chars_after,
                headroom_input_tokens_before, headroom_input_tokens_after,
                headroom_tokens_saved, headroom_reduction_ratio, headroom_skipped,
                headroom_skip_reason, cache_hit, cache_miss, cache_mode,
                cache_tokens_saved, cache_cost_saved
            )
            VALUES (
                :timestamp, :client, :model_alias, :upstream, :input_chars, :output_chars,
                :estimated_tokens, :estimated_cost, :rule_applied, :active_budget,
                :budget_action, :security_event, :output_reduced, :headroom_applied,
                :headroom_adapter, :headroom_input_chars_before, :headroom_input_chars_after,
                :headroom_input_tokens_before, :headroom_input_tokens_after,
                :headroom_tokens_saved, :headroom_reduction_ratio, :headroom_skipped,
                :headroom_skip_reason, :cache_hit, :cache_miss, :cache_mode,
                :cache_tokens_saved, :cache_cost_saved
            )
            """,
            payload,
        )


def record_audit(event_type: str, metadata: str, path: Path | None = None) -> None:
    init_db(path)
    with connect(path) as connection:
        connection.execute(
            "INSERT INTO audit_events (timestamp, event_type, metadata) VALUES (?, ?, ?)",
            (now_iso(), event_type, metadata),
        )


def _period_clause(period: str) -> tuple[str, str]:
    today = date.today()
    if period == "today":
        return "date(timestamp) = date(?)", today.isoformat()
    if period == "month":
        return "substr(timestamp, 1, 7) = ?", today.strftime("%Y-%m")
    raise ValueError(f"Unsupported period: {period}")


def usage_summary(period: str = "today", path: Path | None = None) -> dict[str, Any]:
    init_db(path)
    clause, value = _period_clause(period)
    with connect(path) as connection:
        row = connection.execute(
            f"""
            SELECT COUNT(*) AS requests,
                   COALESCE(SUM(estimated_tokens), 0) AS tokens,
                   COALESCE(SUM(estimated_cost), 0) AS cost,
                   COALESCE(SUM(CASE WHEN rule_applied IS NOT NULL THEN 1 ELSE 0 END), 0) AS rules,
                   COALESCE(SUM(CASE WHEN budget_action LIKE 'block%' THEN 1 ELSE 0 END), 0) AS budget_blocks,
                   COALESCE(SUM(CASE WHEN security_event IS NOT NULL THEN 1 ELSE 0 END), 0) AS security_blocks,
                   COALESCE(SUM(output_reduced), 0) AS outputs_reduced,
                   COALESCE(SUM(headroom_applied), 0) AS headroom_applied_count,
                   COALESCE(SUM(headroom_input_chars_before), 0) AS headroom_input_chars_before,
                   COALESCE(SUM(headroom_input_chars_after), 0) AS headroom_input_chars_after,
                   COALESCE(SUM(headroom_input_tokens_before), 0) AS headroom_input_tokens_before,
                   COALESCE(SUM(headroom_input_tokens_after), 0) AS headroom_input_tokens_after,
                   COALESCE(SUM(headroom_tokens_saved), 0) AS headroom_tokens_saved,
                   COALESCE(SUM(headroom_skipped), 0) AS headroom_skipped_count,
                   COALESCE(SUM(cache_hit), 0) AS cache_hits,
                   COALESCE(SUM(cache_miss), 0) AS cache_misses,
                   COALESCE(SUM(cache_tokens_saved), 0) AS cache_tokens_saved,
                   COALESCE(SUM(cache_cost_saved), 0) AS cache_cost_saved
            FROM usage_events
            WHERE {clause}
            """,
            (value,),
        ).fetchone()
        model = connection.execute(
            f"""
            SELECT model_alias, COUNT(*) AS count
            FROM usage_events
            WHERE {clause}
            GROUP BY model_alias
            ORDER BY count DESC
            LIMIT 1
            """,
            (value,),
        ).fetchone()
        headroom_skip = connection.execute(
            f"""
            SELECT headroom_skip_reason
            FROM usage_events
            WHERE {clause}
              AND headroom_skip_reason IS NOT NULL
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (value,),
        ).fetchone()
    headroom_tokens_before = int(row["headroom_input_tokens_before"])
    headroom_tokens_saved = int(row["headroom_tokens_saved"])
    headroom_reduction_ratio = (
        headroom_tokens_saved / headroom_tokens_before if headroom_tokens_before > 0 else 0.0
    )
    cache_hits = int(row["cache_hits"])
    cache_misses = int(row["cache_misses"])
    cache_total = cache_hits + cache_misses
    return {
        "requests": int(row["requests"]),
        "tokens": int(row["tokens"]),
        "cost": float(row["cost"]),
        "rules": int(row["rules"]),
        "budget_blocks": int(row["budget_blocks"]),
        "security_blocks": int(row["security_blocks"]),
        "top_model": model["model_alias"] if model else "n/a",
        "outputs_reduced": int(row["outputs_reduced"]),
        "headroom_applied_count": int(row["headroom_applied_count"]),
        "headroom_input_chars_before": int(row["headroom_input_chars_before"]),
        "headroom_input_chars_after": int(row["headroom_input_chars_after"]),
        "headroom_input_tokens_before": headroom_tokens_before,
        "headroom_input_tokens_after": int(row["headroom_input_tokens_after"]),
        "headroom_tokens_saved": headroom_tokens_saved,
        "headroom_reduction_ratio": headroom_reduction_ratio,
        "headroom_skipped_count": int(row["headroom_skipped_count"]),
        "headroom_last_skip_reason": headroom_skip["headroom_skip_reason"] if headroom_skip else "n/a",
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_hit_ratio": cache_hits / cache_total if cache_total else 0.0,
        "cache_tokens_saved": int(row["cache_tokens_saved"]),
        "cache_cost_saved": float(row["cache_cost_saved"]),
    }
