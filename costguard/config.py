from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from . import paths
from .utils import parse_bool, read_yaml, write_yaml


MODEL_ALIASES = {
    "cheap": "cg-cheap",
    "standard": "cg-standard",
    "strong": "cg-strong",
}

PREMIUM_ALIASES = {"cg-strong"}

DEFAULT_ENV = {
    "COSTGUARD_HOST": "127.0.0.1",
    "COSTGUARD_PORT": "4040",
    "COSTGUARD_LOCAL_API_KEY": "sk-costguard-local",
    "OPENAI_UPSTREAM_BASE_URL": "",
    "OPENAI_UPSTREAM_API_KEY": "",
    "OPENAI_MODEL_CHEAP": "",
    "OPENAI_MODEL_STANDARD": "",
    "OPENAI_MODEL_STRONG": "",
    "ANTHROPIC_UPSTREAM_BASE_URL": "",
    "ANTHROPIC_UPSTREAM_API_KEY": "",
    "ANTHROPIC_MODEL_CHEAP": "",
    "ANTHROPIC_MODEL_STANDARD": "",
    "ANTHROPIC_MODEL_STRONG": "",
    "COSTGUARD_DEFAULT_MODEL": "cg-standard",
    "COSTGUARD_LOG_CONTENT": "false",
    "COSTGUARD_ENABLE_SECRET_FILTER": "true",
    "COSTGUARD_ENABLE_OUTPUT_LIMITS": "true",
    "COSTGUARD_MAX_OUTPUT_CHARS": "20000",
    "COSTGUARD_MAX_OUTPUT_LINES": "500",
    "COSTGUARD_DAILY_BUDGET": "5",
    "COSTGUARD_MONTHLY_BUDGET": "100",
    "COSTGUARD_BUDGET_MODE": "warn",
    "COSTGUARD_PRICING_URL": "",
    "COSTGUARD_PRICING_API_KEY_ENV": "",
    "COSTGUARD_PRICING_API_KEY": "",
    "COSTGUARD_PRICING_AUTH_HEADER": "x-api-key",
    "COSTGUARD_PRICING_AUTH_SCHEME": "",
    "COSTGUARD_CACHE_MODE": "disabled",
    "COSTGUARD_HEADROOM_ENABLED": "false",
}

DEFAULT_SETTINGS = {
    "tools": {"cline": True, "claude_code": True},
    "proxy": {"host": "127.0.0.1", "port": 4040},
    "active_model": "cg-standard",
    "budget": {"daily": 5.0, "monthly": 100.0, "mode": "warn"},
    "cache": {"mode": "disabled"},
    "headroom": {"enabled": False},
    "autostart": {"enabled": False},
    "output_limits": {"max_chars": 20000, "max_lines": 500},
    "pricing": {
        "cg-cheap": 0.0002,
        "cg-standard": 0.001,
        "cg-strong": 0.003,
    },
}


def default_env_text(overrides: dict[str, Any] | None = None) -> str:
    values = dict(DEFAULT_ENV)
    if overrides:
        for key, value in overrides.items():
            if value is not None:
                values[key] = str(value)
    return "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


def load_env(home: Path | None = None) -> dict[str, str]:
    env_file = paths.env_path(home)
    values = dict(DEFAULT_ENV)
    if env_file.exists():
        values.update({k: v or "" for k, v in dotenv_values(env_file).items() if k})
    for key in DEFAULT_ENV:
        if key in os.environ:
            values[key] = os.environ[key]
    return values


def load_settings(home: Path | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    loaded = read_yaml(paths.settings_path(home), {})
    return merge_dicts(settings, loaded)


def save_settings(settings: dict[str, Any], home: Path | None = None, dry_run: bool = False) -> None:
    write_yaml(paths.settings_path(home), settings, dry_run=dry_run)


def merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def update_budget(
    daily: float | None = None,
    monthly: float | None = None,
    mode: str | None = None,
    home: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    settings = load_settings(home)
    budget = settings.setdefault("budget", {})
    if daily is not None:
        budget["daily"] = float(daily)
    if monthly is not None:
        budget["monthly"] = float(monthly)
    if mode is not None:
        budget["mode"] = mode
    save_settings(settings, home, dry_run=dry_run)
    return settings


def set_active_model(alias: str, home: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    if alias in MODEL_ALIASES:
        alias = MODEL_ALIASES[alias]
    if alias not in set(MODEL_ALIASES.values()):
        raise ValueError(f"Unknown model alias: {alias}")
    settings = load_settings(home)
    settings["active_model"] = alias
    save_settings(settings, home, dry_run=dry_run)
    return settings


def cache_mode(home: Path | None = None) -> str:
    env = load_env(home)
    settings = load_settings(home)
    return str(settings.get("cache", {}).get("mode") or env.get("COSTGUARD_CACHE_MODE") or "disabled")


def headroom_enabled(home: Path | None = None) -> bool:
    env = load_env(home)
    settings = load_settings(home)
    return bool(settings.get("headroom", {}).get("enabled", parse_bool(env.get("COSTGUARD_HEADROOM_ENABLED"))))


def model_for_client(alias: str, client: str, env: dict[str, str] | None = None) -> str:
    values = env or load_env()
    if client == "cline":
        mapping = {
            "cg-cheap": values.get("OPENAI_MODEL_CHEAP", ""),
            "cg-standard": values.get("OPENAI_MODEL_STANDARD", ""),
            "cg-strong": values.get("OPENAI_MODEL_STRONG", ""),
        }
    else:
        mapping = {
            "cg-cheap": values.get("ANTHROPIC_MODEL_CHEAP", ""),
            "cg-standard": values.get("ANTHROPIC_MODEL_STANDARD", ""),
            "cg-strong": values.get("ANTHROPIC_MODEL_STRONG", ""),
        }
    return mapping.get(alias, "") or alias
