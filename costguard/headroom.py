from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import config, paths


ADAPTER_FUNCTIONS = ("compress_payload", "compress_request", "transform_payload", "apply")


@dataclass(frozen=True)
class TransformResult:
    payload: dict[str, Any]
    applied: bool
    adapter: str | None = None


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
    return {
        "available": available(),
        "compatible": adapter is not None,
        "enabled": enabled,
        "active": enabled and adapter is not None,
        "adapter": adapter_name,
        "install_hint": "install a compatible Python module named headroom",
    }


def enable(home: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    if not available():
        raise RuntimeError("Headroom is not installed. Install a compatible Python module named headroom.")
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
        return TransformResult(payload=payload, applied=False)

    adapter = _adapter_callable()
    if adapter is None:
        functions = ", ".join(ADAPTER_FUNCTIONS)
        raise RuntimeError(f"Headroom is enabled but no compatible adapter was found. Expected one function: {functions}.")

    adapter_name, adapter_fn = adapter
    original_payload = json.loads(json.dumps(payload))
    working_payload = json.loads(json.dumps(payload))
    result = _call_adapter(adapter_fn, working_payload, client, home)

    if result is None:
        transformed = working_payload
    elif isinstance(result, tuple) and result and isinstance(result[0], dict):
        transformed = result[0]
    elif isinstance(result, dict):
        transformed = result
    else:
        raise RuntimeError(f"Headroom adapter {adapter_name} must return a request payload dict or mutate it in place.")

    return TransformResult(payload=transformed, applied=transformed != original_payload, adapter=adapter_name)


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
