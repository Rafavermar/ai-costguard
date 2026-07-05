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
    security_event TEXT
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    metadata TEXT NOT NULL
);
"""


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
    return database


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
    }
    with connect(path) as connection:
        connection.execute(
            """
            INSERT INTO usage_events (
                timestamp, client, model_alias, upstream, input_chars, output_chars,
                estimated_tokens, estimated_cost, rule_applied, active_budget,
                budget_action, security_event
            )
            VALUES (
                :timestamp, :client, :model_alias, :upstream, :input_chars, :output_chars,
                :estimated_tokens, :estimated_cost, :rule_applied, :active_budget,
                :budget_action, :security_event
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
                   COALESCE(SUM(CASE WHEN security_event IS NOT NULL THEN 1 ELSE 0 END), 0) AS security_blocks
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
    return {
        "requests": int(row["requests"]),
        "tokens": int(row["tokens"]),
        "cost": float(row["cost"]),
        "rules": int(row["rules"]),
        "budget_blocks": int(row["budget_blocks"]),
        "security_blocks": int(row["security_blocks"]),
        "top_model": model["model_alias"] if model else "n/a",
        "outputs_reduced": 0,
    }
