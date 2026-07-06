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
INPUT_SHAPES = {"openai-payload", "messages-list", "raw-text", "concatenated-messages-text"}
INPUT_SHAPE_ALIASES = {
    "openai_chat_payload": "openai-payload",
    "openai-chat-payload": "openai-payload",
    "payload": "openai-payload",
    "messages_list": "messages-list",
    "raw_text": "raw-text",
    "concatenated_messages_text": "concatenated-messages-text",
}

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
    adapter_input_shape: str | None = None
    adapter_result_type: str | None = None
    adapter_result_keys: str | None = None
    normalized_result_shape: str | None = None
    payload_reconstruction_status: str | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class NormalizedResult:
    payload: dict[str, Any]
    shape: str
    status: str


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


def transform_payload(
    payload: dict[str, Any],
    client: str,
    home: Path | None = None,
    force_enabled: bool = False,
) -> TransformResult:
    home = home or paths.costguard_home()
    if not config.headroom_enabled(home) and not force_enabled:
        return TransformResult(payload=payload, applied=False, skipped_reason=SKIPPED_DISABLED)

    skip_reason = _skip_reason(payload, client)
    if skip_reason is not None:
        return TransformResult(payload=payload, applied=False, skipped_reason=skip_reason)

    adapter = _adapter_callable()
    if adapter is None:
        return TransformResult(payload=payload, applied=False, skipped_reason=SKIPPED_ADAPTER_ERROR)

    adapter_name, adapter_fn = adapter
    adapter_input_shape = _adapter_input_shape(adapter_name)
    original_payload = json.loads(json.dumps(payload))
    working_payload = json.loads(json.dumps(payload))
    result: Any = None
    try:
        if adapter_name == "compress":
            messages = working_payload.get("messages")
            if not isinstance(messages, list):
                return TransformResult(payload=payload, applied=False, skipped_reason=SKIPPED_NO_MESSAGES)
            model = str(working_payload.get("model") or "cg-standard")
            result = _call_compress(adapter_fn, messages, model)
        else:
            result = _call_adapter(adapter_fn, working_payload, client, home)
        adapter_result_type = type(result).__name__
    except Exception as exc:
        return TransformResult(
            payload=payload,
            applied=False,
            adapter=adapter_name,
            skipped_reason=SKIPPED_ADAPTER_ERROR,
            adapter_input_shape=adapter_input_shape,
            adapter_result_type="exception",
            adapter_result_keys="n/a",
            normalized_result_shape="n/a",
            payload_reconstruction_status="error",
            error_type=type(exc).__name__,
        )

    normalized = _normalize_adapter_result(result, working_payload, adapter_input_shape)
    if normalized.status == "unsupported":
        return TransformResult(
            payload=payload,
            applied=False,
            adapter=adapter_name,
            skipped_reason=SKIPPED_ADAPTER_ERROR,
            adapter_input_shape=adapter_input_shape,
            adapter_result_type=type(result).__name__,
            adapter_result_keys=_result_keys(result),
            normalized_result_shape=normalized.shape,
            payload_reconstruction_status=normalized.status,
            error_type="invalid_result",
        )
    transformed = normalized.payload

    if transformed == original_payload:
        return TransformResult(
            payload=transformed,
            applied=False,
            adapter=adapter_name,
            skipped_reason=SKIPPED_NO_CHANGE,
            adapter_input_shape=adapter_input_shape,
            adapter_result_type=adapter_result_type,
            adapter_result_keys=_result_keys(result),
            normalized_result_shape=normalized.shape,
            payload_reconstruction_status=normalized.status,
        )
    return TransformResult(
        payload=transformed,
        applied=True,
        adapter=adapter_name,
        adapter_input_shape=adapter_input_shape,
        adapter_result_type=adapter_result_type,
        adapter_result_keys=_result_keys(result),
        normalized_result_shape=normalized.shape,
        payload_reconstruction_status=normalized.status,
    )


def diagnostic(
    sample: str = "repeated",
    client: str = "cline",
    model: str = config.ACTIVE_MODEL_ALIAS,
    home: Path | None = None,
    force_enabled: bool = False,
    input_shape: str = "messages-list",
) -> dict[str, Any]:
    home = home or paths.costguard_home()
    normalized_input_shape = _normalize_input_shape(input_shape)
    payload = sample_payload(sample, client, model, home)
    before_text = json.dumps(payload)
    before_chars = len(before_text)
    before_tokens = _estimate_tokens(before_chars)
    result = _diagnose_adapter_shape(payload, client, home, normalized_input_shape, force_enabled)
    after_text = json.dumps(result.payload)
    after_chars = len(after_text)
    after_tokens = _estimate_tokens(after_chars)
    tokens_saved = max(0, before_tokens - after_tokens)
    adapter = _adapter_callable()
    status_data = status(home)
    return {
        "sample": sample,
        "client": client,
        "model_alias": model,
        "upstream_model": str(payload.get("model", "")),
        "available": status_data["available"],
        "compatible": status_data["compatible"],
        "enabled": status_data["enabled"],
        "force_enabled": force_enabled,
        "adapter": result.adapter or (adapter[0] if adapter else ""),
        "input_type": "openai_chat_payload",
        "requested_input_shape": normalized_input_shape,
        "adapter_input_shape": result.adapter_input_shape or (_adapter_input_shape(adapter[0]) if adapter else "n/a"),
        "adapter_result_type": result.adapter_result_type or "n/a",
        "adapter_result_keys": result.adapter_result_keys or "n/a",
        "normalized_result_shape": result.normalized_result_shape or "n/a",
        "payload_reconstruction_status": result.payload_reconstruction_status or "n/a",
        "input_message_count": _message_count(payload),
        "input_chars_before": before_chars,
        "input_chars_after": after_chars,
        "input_tokens_before": before_tokens,
        "input_tokens_after": after_tokens,
        "tokens_saved": tokens_saved,
        "reduction_ratio": tokens_saved / before_tokens if before_tokens else 0.0,
        "changed": result.applied,
        "skip_reason": result.skipped_reason or "n/a",
        "error_type": result.error_type or "n/a",
        "content_printed": False,
    }


def _diagnose_adapter_shape(
    payload: dict[str, Any],
    client: str,
    home: Path,
    input_shape: str,
    force_enabled: bool,
) -> TransformResult:
    input_shape = _normalize_input_shape(input_shape)
    if not config.headroom_enabled(home) and not force_enabled:
        return TransformResult(payload=payload, applied=False, skipped_reason=SKIPPED_DISABLED)

    skip_reason = _skip_reason(payload, client)
    if skip_reason is not None:
        return TransformResult(payload=payload, applied=False, skipped_reason=skip_reason)

    adapter = _adapter_callable()
    if adapter is None:
        return TransformResult(payload=payload, applied=False, skipped_reason=SKIPPED_ADAPTER_ERROR)

    adapter_name, adapter_fn = adapter
    original_payload = json.loads(json.dumps(payload))
    adapter_input = _adapter_input_for_shape(original_payload, input_shape)
    model = str(original_payload.get("model") or "cg-standard")
    result: Any = None
    try:
        result = _call_adapter_with_input(adapter_fn, adapter_name, adapter_input, input_shape, model, client, home)
    except Exception as exc:
        return TransformResult(
            payload=payload,
            applied=False,
            adapter=adapter_name,
            skipped_reason=SKIPPED_ADAPTER_ERROR,
            adapter_input_shape=_diagnostic_input_shape_label(input_shape),
            adapter_result_type="exception",
            adapter_result_keys="n/a",
            normalized_result_shape="n/a",
            payload_reconstruction_status="error",
            error_type=type(exc).__name__,
        )

    normalized = _normalize_adapter_result(result, original_payload, input_shape)
    if normalized.status == "unsupported":
        return TransformResult(
            payload=payload,
            applied=False,
            adapter=adapter_name,
            skipped_reason=SKIPPED_ADAPTER_ERROR,
            adapter_input_shape=_diagnostic_input_shape_label(input_shape),
            adapter_result_type=type(result).__name__,
            adapter_result_keys=_result_keys(result),
            normalized_result_shape=normalized.shape,
            payload_reconstruction_status=normalized.status,
            error_type="invalid_result",
        )
    if normalized.payload == original_payload:
        return TransformResult(
            payload=normalized.payload,
            applied=False,
            adapter=adapter_name,
            skipped_reason=SKIPPED_NO_CHANGE,
            adapter_input_shape=_diagnostic_input_shape_label(input_shape),
            adapter_result_type=type(result).__name__,
            adapter_result_keys=_result_keys(result),
            normalized_result_shape=normalized.shape,
            payload_reconstruction_status=normalized.status,
        )
    return TransformResult(
        payload=normalized.payload,
        applied=True,
        adapter=adapter_name,
        adapter_input_shape=_diagnostic_input_shape_label(input_shape),
        adapter_result_type=type(result).__name__,
        adapter_result_keys=_result_keys(result),
        normalized_result_shape=normalized.shape,
        payload_reconstruction_status=normalized.status,
    )


def sample_payload(
    sample: str,
    client: str = "cline",
    model: str = config.ACTIVE_MODEL_ALIAS,
    home: Path | None = None,
) -> dict[str, Any]:
    home = home or paths.costguard_home()
    if sample not in {"short", "repeated", "long-context"}:
        raise ValueError("Sample must be one of: short, repeated, long-context.")
    if client not in HEADROOM_CLIENTS:
        raise ValueError("Client must be one of: cline, claude-code.")

    if sample == "short":
        text = "Summarize this short safe sample in one sentence."
    elif sample == "repeated":
        text = (
            "Cost Guard validates budgets, rules, pricing, cache, model routing, and safety. "
            * 220
        )
    else:
        text = "\n".join(
            f"Section {index}: Cost Guard local context, budget metadata, cache state, and routing notes."
            for index in range(1, 260)
        )

    env = config.load_env(home)
    alias = config.resolve_model_alias(model, home)
    upstream_model = config.model_for_client(alias, "cline" if client == "cline" else "claude-code", env, home)
    return {
        "model": upstream_model,
        "messages": [
            {
                "role": "user",
                "content": text,
            }
        ],
        "temperature": 0,
        "max_tokens": 64,
    }


def _adapter_input_shape(adapter_name: str) -> str:
    return "messages_list" if adapter_name == "compress" else "payload_dict"


def _normalize_input_shape(input_shape: str) -> str:
    normalized = input_shape.strip().lower()
    normalized = INPUT_SHAPE_ALIASES.get(normalized, normalized.replace("_", "-"))
    if normalized not in INPUT_SHAPES:
        raise ValueError("Input shape must be one of: openai-payload, messages-list, raw-text, concatenated-messages-text.")
    return normalized


def _diagnostic_input_shape_label(input_shape: str) -> str:
    return input_shape.replace("-", "_")


def _adapter_input_for_shape(payload: dict[str, Any], input_shape: str) -> Any:
    input_shape = _normalize_input_shape(input_shape)
    if input_shape == "openai-payload":
        return payload
    if input_shape == "messages-list":
        return payload.get("messages", [])
    if input_shape == "raw-text":
        return _first_text_content(payload)
    if input_shape == "concatenated-messages-text":
        return _concatenated_messages_text(payload)
    raise ValueError("Unsupported input shape.")


def _call_adapter_with_input(
    adapter_fn: Callable[..., Any],
    adapter_name: str,
    adapter_input: Any,
    input_shape: str,
    model: str,
    client: str,
    home: Path,
) -> Any:
    if adapter_name == "compress":
        return _call_compress(adapter_fn, adapter_input, model)
    if input_shape == "openai-payload":
        return _call_adapter(adapter_fn, adapter_input, client, home)
    return adapter_fn(adapter_input)


def _call_compress(compress_fn: Callable[..., Any], value: Any, model: str) -> Any:
    try:
        return compress_fn(value, model=model)
    except TypeError:
        pass
    try:
        return compress_fn(value, {"model": model})
    except TypeError:
        pass
    return compress_fn(value)


def _normalize_adapter_result(result: Any, original_payload: dict[str, Any], input_shape: str) -> NormalizedResult:
    if result is None:
        return NormalizedResult(payload=original_payload, shape="none", status="no_result_uses_mutated_input")

    if isinstance(result, tuple) and result:
        result = result[0]

    if _has_messages(result):
        return NormalizedResult(payload=_payload_with_messages(original_payload, result["messages"]), shape="dict_messages", status="messages_reconstructed")

    if isinstance(result, dict):
        for key in ("payload", "request", "body"):
            nested = result.get(key)
            if _has_messages(nested):
                payload = dict(original_payload)
                payload.update(nested)
                return NormalizedResult(payload=payload, shape=f"dict_{key}_messages", status="payload_reconstructed")
        for key in ("compressed_messages", "optimized_messages"):
            messages = result.get(key)
            if isinstance(messages, list):
                return NormalizedResult(payload=_payload_with_messages(original_payload, messages), shape=f"dict_{key}", status="messages_reconstructed")
        for key in ("text", "content", "compressed_text", "optimized_text", "compressed_prompt", "output", "result"):
            value = result.get(key)
            if isinstance(value, str):
                return NormalizedResult(payload=_payload_with_first_text(original_payload, value), shape=f"dict_{key}", status="text_reconstructed")
        return NormalizedResult(payload=original_payload, shape="dict_metadata_only", status="metadata_only")

    if isinstance(result, list):
        return NormalizedResult(payload=_payload_with_messages(original_payload, result), shape="messages_list", status="messages_reconstructed")

    if isinstance(result, str):
        return NormalizedResult(payload=_payload_with_first_text(original_payload, result), shape="text", status="text_reconstructed")

    messages = getattr(result, "messages", None)
    if isinstance(messages, list):
        return NormalizedResult(payload=_payload_with_messages(original_payload, messages), shape="object_messages", status="messages_reconstructed")
    for attr in ("text", "content", "compressed_text", "output"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return NormalizedResult(payload=_payload_with_first_text(original_payload, value), shape=f"object_{attr}", status="text_reconstructed")
    return NormalizedResult(payload=original_payload, shape=type(result).__name__, status="unsupported")


def _has_messages(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("messages"), list)


def _payload_with_messages(payload: dict[str, Any], messages: list[Any]) -> dict[str, Any]:
    new_payload = json.loads(json.dumps(payload))
    new_payload["messages"] = messages
    return new_payload


def _payload_with_first_text(payload: dict[str, Any], text: str) -> dict[str, Any]:
    new_payload = json.loads(json.dumps(payload))
    messages = new_payload.get("messages")
    if not isinstance(messages, list):
        return new_payload
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            message["content"] = text
            break
    return new_payload


def _first_text_content(payload: dict[str, Any]) -> str:
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return ""
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return str(message["content"])
    return ""


def _concatenated_messages_text(payload: dict[str, Any]) -> str:
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return ""
    parts = []
    for message in messages:
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            parts.append(f"{message.get('role', 'unknown')}: {message['content']}")
    return "\n\n".join(parts)


def _result_keys(result: Any) -> str:
    if isinstance(result, tuple) and result:
        result = result[0]
    if isinstance(result, dict):
        return ",".join(sorted(str(key) for key in result.keys())) or "n/a"
    return "n/a"


def _message_count(payload: dict[str, Any]) -> int:
    messages = payload.get("messages")
    return len(messages) if isinstance(messages, list) else 0


def _estimate_tokens(chars: int) -> int:
    return max(1, int((chars + 3) / 4))


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
