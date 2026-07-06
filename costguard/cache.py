from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from . import config, paths
from .utils import directory_size, parse_bool, read_json, safe_rmtree, write_json


VALID_MODES = {"disabled", "basic", "semantic"}
CACHE_VERSION = 1
SKIP_PAYLOAD_KEYS = {"stream_options"}
TOOL_KEYS = {"tools", "tool_choice", "functions", "function_call"}
NON_TEXT_KEYS = {"image", "image_url", "input_image", "file", "files", "document", "documents", "source"}
NON_TEXT_TYPES = {"image", "image_url", "input_image", "file", "document"}


def status(home: Path | None = None) -> dict[str, Any]:
    home = home or paths.costguard_home()
    env = config.load_env(home)
    mode = config.cache_mode(home)
    cache_path = paths.vector_cache_dir(home) if mode == "semantic" else paths.response_cache_dir(home)
    response_entries = _count_files(paths.response_cache_dir(home), "*.json")
    vector_entries = _count_files(paths.vector_cache_dir(home), "*")
    pricing_cache_exists = paths.models_cache_path(home).exists()
    store_content = store_content_enabled(env)
    ttl = ttl_seconds(env)
    functional = mode == "basic" and store_content
    note = ""
    if mode == "basic" and not store_content:
        note = "basic mode is metadata-only until COSTGUARD_CACHE_STORE_CONTENT=true"
    elif mode == "semantic":
        note = "semantic cache is scaffolded/experimental; embeddings are not active"
    return {
        "mode": mode,
        "path": cache_path,
        "store_content": store_content,
        "ttl_seconds": ttl,
        "functional": functional,
        "entries": response_entries if mode != "semantic" else vector_entries,
        "response_entries": response_entries,
        "pricing_cache": pricing_cache_exists,
        "vector_entries": vector_entries,
        "size_bytes": directory_size(paths.cache_dir(home)) + directory_size(paths.vector_cache_dir(home)),
        "note": note or "n/a",
    }


def enable(mode: str, home: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    if mode not in {"basic", "semantic"}:
        raise ValueError("Cache mode must be basic or semantic.")
    home = home or paths.costguard_home()
    settings = config.load_settings(home)
    settings.setdefault("cache", {})["mode"] = mode
    config.save_settings(settings, home, dry_run=dry_run)
    if not dry_run:
        paths.cache_dir(home).mkdir(parents=True, exist_ok=True)
        paths.response_cache_dir(home).mkdir(parents=True, exist_ok=True)
        paths.vector_cache_dir(home).mkdir(parents=True, exist_ok=True)
        path = paths.vector_cache_dir(home) if mode == "semantic" else paths.cache_dir(home)
        index = path / "index.json"
        if not index.exists():
            index.write_text(json.dumps({"entries": []}, indent=2) + "\n", encoding="utf-8")
    return status(home)


def disable(home: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    home = home or paths.costguard_home()
    settings = config.load_settings(home)
    settings.setdefault("cache", {})["mode"] = "disabled"
    config.save_settings(settings, home, dry_run=dry_run)
    return status(home)


def clear(
    home: Path | None = None,
    dry_run: bool = False,
    responses_only: bool = False,
    pricing_only: bool = False,
    vectors_only: bool = False,
) -> dict[str, Any]:
    home = home or paths.costguard_home()
    selected = responses_only or pricing_only or vectors_only
    clear_responses = responses_only or not selected
    clear_vectors = vectors_only or not selected
    clear_pricing = pricing_only
    if clear_responses:
        safe_rmtree(paths.response_cache_dir(home), dry_run=dry_run)
    if clear_vectors:
        safe_rmtree(paths.vector_cache_dir(home), dry_run=dry_run)
    if clear_pricing and not dry_run:
        paths.models_cache_path(home).unlink(missing_ok=True)
    if not dry_run:
        paths.cache_dir(home).mkdir(parents=True, exist_ok=True)
        paths.response_cache_dir(home).mkdir(parents=True, exist_ok=True)
        paths.vector_cache_dir(home).mkdir(parents=True, exist_ok=True)
    return status(home)


def store_content_enabled(env: dict[str, str] | None = None) -> bool:
    values = env or config.load_env()
    return parse_bool(values.get("COSTGUARD_CACHE_STORE_CONTENT"), default=False)


def ttl_seconds(env: dict[str, str] | None = None) -> int:
    values = env or config.load_env()
    try:
        return max(0, int(values.get("COSTGUARD_CACHE_TTL_SECONDS", "86400") or 86400))
    except ValueError:
        return 86400


def request_cacheable(payload: dict[str, Any], security_event: str | None = None) -> tuple[bool, str]:
    if security_event:
        return False, "secret-like payload"
    if parse_bool(payload.get("stream"), default=False):
        return False, "streaming request"
    if any(key in payload for key in TOOL_KEYS):
        return False, "tool/function request"
    if _contains_non_text_input(payload):
        return False, "non-text input"
    return True, "cacheable"


def cache_key(
    *,
    client: str,
    path: str,
    model_alias: str,
    upstream_model: str,
    upstream_base_url: str,
    payload: dict[str, Any],
) -> str:
    material = {
        "version": CACHE_VERSION,
        "client": client,
        "path": path,
        "model_alias": model_alias,
        "upstream_model": upstream_model,
        "upstream_base_url": upstream_base_url,
        "payload": _normalized_payload(payload),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_response(key: str, home: Path | None = None, env: dict[str, str] | None = None) -> dict[str, Any] | None:
    home = home or paths.costguard_home()
    entry_path = _response_path(key, home)
    entry = read_json(entry_path, {})
    if not entry:
        return None
    ttl = ttl_seconds(env)
    created_at = float(entry.get("created_at", 0) or 0)
    if ttl > 0 and created_at and time.time() - created_at > ttl:
        entry_path.unlink(missing_ok=True)
        return None
    if entry.get("version") != CACHE_VERSION or entry.get("key") != key or not entry.get("body_b64"):
        return None
    try:
        body = base64.b64decode(str(entry["body_b64"]).encode("ascii"))
    except Exception:
        return None
    return {
        "status_code": int(entry.get("status_code", 200)),
        "content_type": str(entry.get("content_type") or "application/json"),
        "body": body,
        "output_chars": int(entry.get("output_chars", len(body))),
        "estimated_tokens": int(entry.get("estimated_tokens", 0)),
        "estimated_cost": float(entry.get("estimated_cost", 0.0)),
    }


def store_response(
    *,
    key: str,
    body: bytes,
    status_code: int,
    content_type: str,
    output_chars: int,
    estimated_tokens: int,
    estimated_cost: float,
    client: str,
    path: str,
    model_alias: str,
    upstream_model: str,
    home: Path | None = None,
    env: dict[str, str] | None = None,
) -> Path | None:
    if not store_content_enabled(env) or not (200 <= status_code < 300):
        return None
    home = home or paths.costguard_home()
    entry = {
        "version": CACHE_VERSION,
        "key": key,
        "created_at": time.time(),
        "client": client,
        "path": path,
        "model_alias": model_alias,
        "upstream_model": upstream_model,
        "status_code": status_code,
        "content_type": content_type,
        "output_chars": output_chars,
        "estimated_tokens": estimated_tokens,
        "estimated_cost": estimated_cost,
        "body_b64": base64.b64encode(body).decode("ascii"),
    }
    entry_path = _response_path(key, home)
    write_json(entry_path, entry)
    return entry_path


def _response_path(key: str, home: Path) -> Path:
    return paths.response_cache_dir(home) / f"{key}.json"


def _normalized_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalized_payload(value[key]) for key in sorted(value) if key not in SKIP_PAYLOAD_KEYS}
    if isinstance(value, list):
        return [_normalized_payload(item) for item in value]
    return value


def _contains_non_text_input(value: Any) -> bool:
    if isinstance(value, dict):
        input_type = str(value.get("type", "")).lower()
        if input_type in NON_TEXT_TYPES:
            return True
        if any(key in value for key in NON_TEXT_KEYS):
            return True
        return any(_contains_non_text_input(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_non_text_input(item) for item in value)
    return False


def _count_files(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    return sum(1 for child in path.rglob(pattern) if child.is_file())
