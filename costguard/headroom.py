from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import config, paths
from .utils import parse_bool


ADAPTER_FUNCTIONS = ("compress", "compress_payload", "compress_request", "transform_payload", "apply")
HEADROOM_CLIENTS = {"cline", "claude-code"}
TOOL_KEYS = {"tools", "tool_choice", "functions", "function_call"}

SKIPPED_DISABLED = "skipped_disabled"
SKIPPED_NOT_ELIGIBLE = "skipped_not_eligible"
SKIPPED_STREAMING = "skipped_streaming"
SKIPPED_TOOLS = "skipped_tools"
SKIPPED_NO_MESSAGES = "skipped_no_messages"
SKIPPED_ADAPTER_ERROR = "skipped_adapter_error"
SKIPPED_NO_CHANGE = "skipped_no_change"


@dataclass(frozen=True)
class TransformResult:
    payload: dict[str, Any]
    applied: bool
    adapter: str | None = None
    skipped_reason: str | None = None


def available() -> bool:
    if "headroom" in sys.modules:
        return True
    return importlib.util.find_spec("headroom") is not None


def _load_module() -> Any:
    return importlib.import_module("headroom")


def _adapter_callable() -> tuple[str, Callable[..., Any]] | None:
    if not available():
        return None
    module = _load_module()
    for name in ADAPTER_FUNCTIONS:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return name, candidate
    return None


def compatible() -> bool:
    return _adapter_callable() is not None


def status(home: Path | None = None) -> dict[str, Any]:
    home = home or paths.costguard_home()
    adapter = _adapter_callable()
    adapter_name = adapter[0] if adapter else ""
    enabled = config.headroom_enabled(home)
    install_hint = "n/a" if adapter is not None else 'pip install "ai-costguard[headroom]" or pip install headroom-ai'
    return {
        "available": available(),
        "compatible": adapter is not None,
        "enabled": enabled,
        "active": enabled and adapter is not None,
        "adapter": adapter_name,
        "install_hint": install_hint,
    }


def enable(home: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    if not available():
        raise RuntimeError('Headroom is not installed. Run: pip install "ai-costguard[headroom]"')
    if not compatible():
        functions = ", ".join(ADAPTER_FUNCTIONS)
        raise RuntimeError(f"Headroom is installed but incompatible. Expected one function: {functions}.")
    home = home or paths.costguard_home()
    settings = config.load_settings(home)
    settings.setdefault("headroom", {})["enabled"] = True
    config.save_settings(settings, home, dry_run=dry_run)
    return status(home)


def disable(home: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    home = home or paths.costguard_home()
    settings = config.load_settings(home)
    settings.setdefault("headroom", {})["enabled"] = False
    config.save_settings(settings, home, dry_run=dry_run)
    return status(home)


def transform_payload(payload: dict[str, Any], client: str, home: Path | None = None) -> TransformResult:
    home = home or paths.costguard_home()
    if not config.headroom_enabled(home):
        return TransformResult(payload=payload, applied=False, skipped_reason=SKIPPED_DISABLED)

    skip_reason = _skip_reason(payload, client)
    if skip_reason is not None:
        return TransformResult(payload=payload, applied=False, skipped_reason=skip_reason)

    adapter = _adapter_callable()
    if adapter is None:
        return TransformResult(payload=payload, applied=False, skipped_reason=SKIPPED_ADAPTER_ERROR)

    adapter_name, adapter_fn = adapter
    original_payload = json.loads(json.dumps(payload))
    working_payload = json.loads(json.dumps(payload))
    try:
        if adapter_name == "compress":
            result = _call_headroom_compress(adapter_fn, working_payload)
        else:
            result = _call_adapter(adapter_fn, working_payload, client, home)
    except Exception:
        return TransformResult(
            payload=payload,
            applied=False,
            adapter=adapter_name,
            skipped_reason=SKIPPED_ADAPTER_ERROR,
        )

    if result is None:
        transformed = working_payload
    elif isinstance(result, tuple) and result and isinstance(result[0], dict):
        transformed = result[0]
    elif isinstance(result, dict):
        transformed = result
    else:
        return TransformResult(
            payload=payload,
            applied=False,
            adapter=adapter_name,
            skipped_reason=SKIPPED_ADAPTER_ERROR,
        )

    if transformed == original_payload:
        return TransformResult(
            payload=transformed,
            applied=False,
            adapter=adapter_name,
            skipped_reason=SKIPPED_NO_CHANGE,
        )
    return TransformResult(payload=transformed, applied=True, adapter=adapter_name)


def _skip_reason(payload: dict[str, Any], client: str) -> str | None:
    if client not in HEADROOM_CLIENTS:
        return SKIPPED_NOT_ELIGIBLE
    if parse_bool(payload.get("stream"), default=False):
        return SKIPPED_STREAMING
    if _has_tools(payload):
        return SKIPPED_TOOLS
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return SKIPPED_NO_MESSAGES
    return None


def _has_tools(payload: dict[str, Any]) -> bool:
    for key in TOOL_KEYS:
        value = payload.get(key)
        if value not in (None, False, "", [], {}):
            return True
    return False


def _call_adapter(adapter_fn: Callable[..., Any], payload: dict[str, Any], client: str, home: Path) -> Any:
    try:
        return adapter_fn(payload, client=client, home=str(home))
    except TypeError:
        pass
    try:
        return adapter_fn(payload, client=client)
    except TypeError:
        pass
    try:
        return adapter_fn(payload, client)
    except TypeError:
        pass
    return adapter_fn(payload)


def _call_headroom_compress(compress_fn: Callable[..., Any], payload: dict[str, Any]) -> dict[str, Any]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return payload

    model = str(payload.get("model") or "cg-standard")
    result = compress_fn(messages, model=model)
    compressed_messages = getattr(result, "messages", None)
    if compressed_messages is None and isinstance(result, dict):
        compressed_messages = result.get("messages")
    if not isinstance(compressed_messages, list):
        raise RuntimeError("Headroom compress() must return an object or dict with a messages list.")

    payload["messages"] = compressed_messages
    return payload
