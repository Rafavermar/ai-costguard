from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx

from . import config, paths
from .utils import read_yaml, write_yaml


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _model_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("data", "models", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _model_name(entry: dict[str, Any]) -> str | None:
    for key in ("systemName", "name", "id", "model", "modelId"):
        value = entry.get(key)
        if value:
            return str(value)
    return None


def _model_identifiers(entry: dict[str, Any]) -> list[str]:
    identifiers = []
    for key in ("systemName", "name", "id", "model", "modelId"):
        value = entry.get(key)
        if value:
            identifiers.append(str(value))
    return list(dict.fromkeys(identifiers))


def parse_catalog(payload: Any) -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = {}
    for entry in _model_entries(payload):
        name = _model_name(entry)
        input_price = _as_float(entry.get("inputPrice") or entry.get("input_price") or entry.get("promptPrice"))
        output_price = _as_float(entry.get("outputPrice") or entry.get("output_price") or entry.get("completionPrice"))
        if not name or input_price is None or output_price is None:
            continue
        model = {
            "input_per_million": input_price,
            "output_per_million": output_price,
        }
        cached_read = _as_float(entry.get("cachedTokenReadPrice") or entry.get("cached_read_price"))
        cached_create = _as_float(entry.get("cachedTokenCreationPrice") or entry.get("cached_creation_price"))
        if cached_read is not None:
            model["cached_read_per_million"] = cached_read
        if cached_create is not None:
            model["cached_creation_per_million"] = cached_create
        for metadata_key in ("provider", "name", "systemName"):
            if entry.get(metadata_key):
                model[metadata_key] = str(entry[metadata_key])
        for identifier in _model_identifiers(entry):
            models[identifier] = dict(model)
    return models


def load_pricing(home: Path | None = None) -> dict[str, dict[str, Any]]:
    data = read_yaml(paths.pricing_path(home), {})
    models = data.get("models", data) if isinstance(data, dict) else {}
    return models if isinstance(models, dict) else {}


def save_pricing(models: dict[str, dict[str, Any]], home: Path | None = None, source: str = "") -> Path:
    payload: dict[str, Any] = {"models": models}
    if source:
        payload["source"] = source
    destination = paths.pricing_path(home)
    write_yaml(destination, payload)
    return destination


def configure(
    home: Path | None = None,
    endpoint: str | None = None,
    api_key_env: str | None = None,
    auth_header: str = "x-api-key",
    auth_scheme: str | None = "",
) -> dict[str, Any]:
    if not endpoint:
        raise RuntimeError("Pricing endpoint is required.")
    home = home or paths.costguard_home()
    values = {
        "COSTGUARD_PRICING_URL": endpoint,
        "COSTGUARD_PRICING_API_KEY_ENV": api_key_env or "",
        "COSTGUARD_PRICING_API_KEY": "",
        "COSTGUARD_PRICING_AUTH_HEADER": auth_header,
        "COSTGUARD_PRICING_AUTH_SCHEME": auth_scheme or "",
    }
    env_path = paths.env_path(home)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    existing = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updated: list[str] = []
    seen: set[str] = set()
    for line in existing:
        if "=" not in line or line.strip().startswith("#"):
            updated.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in values:
            updated.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            updated.append(line)
    missing = [key for key in values if key not in seen]
    if missing and updated and updated[-1].strip():
        updated.append("")
    for key in missing:
        updated.append(f"{key}={values[key]}")
    env_path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
    return {
        "env_file": env_path,
        "endpoint": "configured",
        "api_key_env": api_key_env or "",
        "auth_header": auth_header,
        "auth_scheme": auth_scheme or "",
        "api_key": "not stored",
    }


def _auth_headers(
    env: dict[str, str],
    api_key_env: str | None = None,
    auth_header: str | None = None,
    auth_scheme: str | None = None,
) -> dict[str, str]:
    headers = {"accept": "application/json"}
    key_env = api_key_env or env.get("COSTGUARD_PRICING_API_KEY_ENV", "")
    key = os.environ.get(key_env, "") if key_env else env.get("COSTGUARD_PRICING_API_KEY", "")
    if key_env and not key:
        raise RuntimeError(f"Pricing API key environment variable is not set: {key_env}")
    header = auth_header or env.get("COSTGUARD_PRICING_AUTH_HEADER", "x-api-key")
    scheme = auth_scheme if auth_scheme is not None else env.get("COSTGUARD_PRICING_AUTH_SCHEME", "")
    if key and header:
        headers[header] = f"{scheme} {key}".strip() if scheme else key
    return headers


def refresh(
    home: Path | None = None,
    endpoint: str | None = None,
    api_key_env: str | None = None,
    auth_header: str | None = None,
    auth_scheme: str | None = None,
    dry_run: bool = False,
    timeout: float = 30,
) -> dict[str, Any]:
    home = home or paths.costguard_home()
    env = config.load_env(home)
    url = endpoint or env.get("COSTGUARD_PRICING_URL", "")
    if not url:
        raise RuntimeError("Pricing endpoint is not configured. Set COSTGUARD_PRICING_URL or pass --endpoint.")
    response = httpx.get(url, headers=_auth_headers(env, api_key_env, auth_header, auth_scheme), timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    models = parse_catalog(payload)
    if not models:
        raise RuntimeError("Pricing endpoint returned no supported model prices.")
    if dry_run:
        return {
            "dry_run": True,
            "models": len(models),
            "pricing_file": paths.pricing_path(home),
            "models_cache": paths.models_cache_path(home),
            "written": False,
        }
    paths.models_cache_path(home).parent.mkdir(parents=True, exist_ok=True)
    paths.models_cache_path(home).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    pricing_file = save_pricing(models, home, source=url)
    return {
        "dry_run": False,
        "models": len(models),
        "pricing_file": pricing_file,
        "models_cache": paths.models_cache_path(home),
        "written": True,
    }


def _candidate_model_names(model_alias: str, home: Path | None = None) -> list[str]:
    env = config.load_env(home)
    candidates = [
        model_alias,
        config.model_for_client(model_alias, "cline", env),
        config.model_for_client(model_alias, "claude-code", env),
    ]
    return [candidate for candidate in dict.fromkeys(candidates) if candidate]


def model_pricing(model_alias: str, home: Path | None = None) -> dict[str, Any] | None:
    models = load_pricing(home)
    for candidate in _candidate_model_names(model_alias, home):
        value = models.get(candidate)
        if isinstance(value, dict):
            return value
    return None


def estimate_cost(model_alias: str, input_tokens: int, output_tokens: int = 0, home: Path | None = None) -> float | None:
    model = model_pricing(model_alias, home)
    if not model:
        return None
    input_price = _as_float(model.get("input_per_million"))
    output_price = _as_float(model.get("output_per_million"))
    if input_price is None or output_price is None:
        return None
    return (input_tokens / 1_000_000.0) * input_price + (output_tokens / 1_000_000.0) * output_price


def status(home: Path | None = None) -> dict[str, Any]:
    home = home or paths.costguard_home()
    env = config.load_env(home)
    models = load_pricing(home)
    return {
        "configured": bool(env.get("COSTGUARD_PRICING_URL")),
        "models": len(models),
        "pricing_file": paths.pricing_path(home),
        "models_cache": paths.models_cache_path(home),
        "fallback": "settings.yaml pricing estimates",
    }
