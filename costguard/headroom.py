from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import config, paths, rules
from .utils import parse_bool


ADAPTER_FUNCTIONS = ("compress", "compress_payload", "compress_request", "transform_payload", "apply")
HEADROOM_CLIENTS = {"cline", "claude-code"}
TOOL_KEYS = {"tools", "tool_choice", "functions", "function_call"}
INPUT_SHAPES = {"openai-payload", "messages-list", "raw-text", "concatenated-messages-text"}
SAMPLE_NAMES = {
    "short",
    "repeated",
    "long-context",
    "multi-turn",
    "tool-output",
    "long-code",
    "markdown",
    "logs",
    "test-failure",
    "cline-terminal-output",
    "cline-test-output",
}
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
SKIPPED_PROTECTED_RECENT = "skipped_protected_recent"
SKIPPED_PROTECTED_ROLE = "skipped_protected_role"
SKIPPED_USER_MESSAGE_PROTECTED = "skipped_user_message_protected"
SKIPPED_NO_COMPRESSIBLE_MESSAGES = "skipped_no_compressible_messages"
SKIPPED_BELOW_THRESHOLD = "skipped_below_threshold"
SKIPPED_SECRET_DETECTED = "skipped_secret_detected"
SKIPPED_RECONSTRUCTION_ERROR = "skipped_reconstruction_error"

COMPRESSIBLE_ROLE_NAMES = {"tool", "function"}
TOOL_OUTPUT_PATTERNS = (
    r"(?im)^\s*(ERROR|WARN|INFO|DEBUG)\b",
    r"(?im)^\d{4}-\d{2}-\d{2}T\d{2}:",
    r"(?im)^FAILED\s+.+::",
    r"(?im)\b(AssertionError|Traceback|Exception|RuntimeError)\b",
    r"(?im)\b(pytest|npm|mvn|gradle)\b.*\b(FAIL|FAILED|ERROR)\b",
    r"(?im)^diff --git\b",
    r"(?im)^@@\s+-\d+,\d+\s+\+\d+,\d+\s+@@",
    r"(?im)^\s*(\./|[A-Za-z]:\\).+",
    r"(?im)\b(databricks|spark|sql|validation)\b.*\b(ERROR|FAILED|WARN)\b",
    r"(?im)^```",
)


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
    adapter_result_details: dict[str, Any] | None = None
    candidate_message_count: int = 0
    compressible_message_count: int = 0
    protected_message_count: int = 0
    roles_seen: str = "n/a"
    roles_compressed: str = "n/a"
    transforms_applied: str = "n/a"
    error_type: str | None = None


@dataclass(frozen=True)
class NormalizedResult:
    payload: dict[str, Any]
    shape: str
    status: str


@dataclass(frozen=True)
class PreparedMessages:
    messages: list[dict[str, Any]]
    original_messages: list[dict[str, Any]]
    original_roles: list[str]
    compressible_indexes: set[int]
    candidate_message_count: int
    compressible_message_count: int
    protected_message_count: int
    below_threshold_count: int
    user_protected_count: int
    recent_protected_count: int
    role_protected_count: int
    roles_seen: str
    roles_compressed: str
    skip_reason: str | None = None


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

    if rules.has_secret_like_content(json.dumps(payload)):
        return TransformResult(payload=payload, applied=False, skipped_reason=SKIPPED_SECRET_DETECTED)

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
    prepared: PreparedMessages | None = None
    result: Any = None
    try:
        if adapter_name == "compress":
            messages = working_payload.get("messages")
            if not isinstance(messages, list):
                return TransformResult(payload=payload, applied=False, skipped_reason=SKIPPED_NO_MESSAGES)
            model = str(working_payload.get("model") or "cg-standard")
            prepared = _prepare_messages_for_headroom(working_payload, home)
            if prepared.skip_reason is not None:
                return TransformResult(
                    payload=payload,
                    applied=False,
                    adapter=adapter_name,
                    skipped_reason=prepared.skip_reason,
                    adapter_input_shape=adapter_input_shape,
                    adapter_result_type="n/a",
                    adapter_result_keys="n/a",
                    normalized_result_shape="n/a",
                    payload_reconstruction_status="n/a",
                    adapter_result_details=_empty_result_details(),
                    candidate_message_count=prepared.candidate_message_count,
                    compressible_message_count=prepared.compressible_message_count,
                    protected_message_count=prepared.protected_message_count,
                    roles_seen=prepared.roles_seen,
                    roles_compressed=prepared.roles_compressed,
                )
            result = _call_compress(adapter_fn, prepared.messages, model, _headroom_options(home))
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
            adapter_result_details=_empty_result_details(),
            error_type=type(exc).__name__,
        )

    normalized = _normalize_adapter_result(result, working_payload, adapter_input_shape)
    result_details = _result_details(result)
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
            adapter_result_details=result_details,
            candidate_message_count=prepared.candidate_message_count if prepared else 0,
            compressible_message_count=prepared.compressible_message_count if prepared else 0,
            protected_message_count=prepared.protected_message_count if prepared else 0,
            roles_seen=prepared.roles_seen if prepared else "n/a",
            roles_compressed=prepared.roles_compressed if prepared else "n/a",
            transforms_applied=str(result_details["transforms_applied"]),
            error_type="invalid_result",
        )
    transformed = normalized.payload
    if prepared is not None:
        try:
            transformed = _restore_original_message_shapes(transformed, original_payload, prepared)
        except ValueError as exc:
            return TransformResult(
                payload=payload,
                applied=False,
                adapter=adapter_name,
                skipped_reason=SKIPPED_RECONSTRUCTION_ERROR,
                adapter_input_shape=adapter_input_shape,
                adapter_result_type=adapter_result_type,
                adapter_result_keys=_result_keys(result),
                normalized_result_shape=normalized.shape,
                payload_reconstruction_status="reconstruction_error",
                adapter_result_details=result_details,
                candidate_message_count=prepared.candidate_message_count,
                compressible_message_count=prepared.compressible_message_count,
                protected_message_count=prepared.protected_message_count,
                roles_seen=prepared.roles_seen,
                roles_compressed=prepared.roles_compressed,
                transforms_applied=str(result_details["transforms_applied"]),
                error_type=type(exc).__name__,
            )

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
            adapter_result_details=result_details,
            candidate_message_count=prepared.candidate_message_count if prepared else 0,
            compressible_message_count=prepared.compressible_message_count if prepared else 0,
            protected_message_count=prepared.protected_message_count if prepared else 0,
            roles_seen=prepared.roles_seen if prepared else "n/a",
            roles_compressed=prepared.roles_compressed if prepared else "n/a",
            transforms_applied=str(result_details["transforms_applied"]),
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
        adapter_result_details=result_details,
        candidate_message_count=prepared.candidate_message_count if prepared else 0,
        compressible_message_count=prepared.compressible_message_count if prepared else 0,
        protected_message_count=prepared.protected_message_count if prepared else 0,
        roles_seen=prepared.roles_seen if prepared else "n/a",
        roles_compressed=prepared.roles_compressed if prepared else "n/a",
        transforms_applied=str(result_details["transforms_applied"]),
    )


def diagnostic(
    sample: str = "repeated",
    client: str = "cline",
    model: str = config.ACTIVE_MODEL_ALIAS,
    home: Path | None = None,
    force_enabled: bool = False,
    input_shape: str = "messages-list",
    compress_user_messages: bool | None = None,
    protect_recent: int | None = None,
    target_ratio: float | None = None,
    min_tokens_to_compress: int | None = None,
) -> dict[str, Any]:
    home = home or paths.costguard_home()
    normalized_input_shape = _normalize_input_shape(input_shape)
    headroom_options = _headroom_options(
        home,
        compress_user_messages=compress_user_messages,
        protect_recent=protect_recent,
        target_ratio=target_ratio,
        min_tokens_to_compress=min_tokens_to_compress,
    )
    payload = sample_payload(sample, client, model, home)
    before_text = json.dumps(payload)
    before_chars = len(before_text)
    before_tokens = _estimate_tokens(before_chars)
    result = _diagnose_adapter_shape(payload, client, home, normalized_input_shape, force_enabled, headroom_options)
    after_text = json.dumps(result.payload)
    after_chars = len(after_text)
    after_tokens = _estimate_tokens(after_chars)
    tokens_saved = max(0, before_tokens - after_tokens)
    adapter = _adapter_callable()
    status_data = status(home)
    result_details = result.adapter_result_details or _empty_result_details()
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
        "adapter_result_attributes": result_details["attributes"],
        "adapter_result_message_count": result_details["message_count"],
        "adapter_result_tokens_before": result_details["tokens_before"],
        "adapter_result_tokens_after": result_details["tokens_after"],
        "adapter_result_tokens_saved": result_details["tokens_saved"],
        "adapter_result_compression_ratio": result_details["compression_ratio"],
        "adapter_result_transforms_applied": result_details["transforms_applied"],
        "adapter_result_changed_flag": result_details["changed"],
        "adapter_result_reason": result_details["reason"],
        "adapter_result_metadata_keys": result_details["metadata_keys"],
        "normalized_result_shape": result.normalized_result_shape or "n/a",
        "payload_reconstruction_status": result.payload_reconstruction_status or "n/a",
        "headroom_compress_user_messages": headroom_options["compress_user_messages"],
        "headroom_protect_recent": headroom_options["protect_recent"],
        "headroom_target_ratio": headroom_options.get("target_ratio", "n/a"),
        "headroom_min_tokens_to_compress": headroom_options["min_tokens_to_compress"],
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
    headroom_options: dict[str, Any],
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
        result = _call_adapter_with_input(
            adapter_fn,
            adapter_name,
            adapter_input,
            input_shape,
            model,
            client,
            home,
            headroom_options,
        )
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
            adapter_result_details=_empty_result_details(),
            error_type=type(exc).__name__,
        )

    normalized = _normalize_adapter_result(result, original_payload, input_shape)
    result_details = _result_details(result)
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
            adapter_result_details=result_details,
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
            adapter_result_details=result_details,
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
        adapter_result_details=result_details,
    )


def sample_payload(
    sample: str,
    client: str = "cline",
    model: str = config.ACTIVE_MODEL_ALIAS,
    home: Path | None = None,
) -> dict[str, Any]:
    home = home or paths.costguard_home()
    if sample not in SAMPLE_NAMES:
        raise ValueError(f"Sample must be one of: {', '.join(sorted(SAMPLE_NAMES))}.")
    if client not in HEADROOM_CLIENTS:
        raise ValueError("Client must be one of: cline, claude-code.")

    if sample == "short":
        messages = [{"role": "user", "content": "Summarize this short safe sample in one sentence."}]
    elif sample == "repeated":
        messages = [
            {
                "role": "user",
                "content": "Cost Guard validates budgets, rules, pricing, cache, model routing, and safety. " * 220,
            }
        ]
    elif sample == "long-context":
        messages = [
            {
                "role": "user",
                "content": "\n".join(
                    f"Section {index}: Cost Guard local context, budget metadata, cache state, and routing notes."
                    for index in range(1, 260)
                ),
            }
        ]
    elif sample == "multi-turn":
        messages = _conversation_with_tool_output(_sample_logs(260), final_request="Summarize the latest root cause.")
    elif sample == "tool-output":
        messages = _conversation_with_tool_output(_sample_tool_output(), final_request="Extract the relevant failures.")
    elif sample == "long-code":
        messages = _conversation_with_tool_output(_sample_code(), final_request="Point out risky functions.")
    elif sample == "markdown":
        messages = _conversation_with_tool_output(_sample_markdown(), final_request="Summarize decisions and open questions.")
    elif sample == "logs":
        messages = _conversation_with_tool_output(_sample_logs(360), final_request="Find repeated errors and warnings.")
    elif sample == "test-failure":
        messages = _conversation_with_tool_output(_sample_test_failure(), final_request="Explain the failing test briefly.")
    elif sample == "cline-terminal-output":
        messages = _cline_embedded_output(_sample_tool_output(), final_request="Summarize the terminal output.")
    else:
        messages = _cline_embedded_output(_sample_test_failure(), final_request="Summarize the failing tests.")

    env = config.load_env(home)
    alias = config.resolve_model_alias(model, home)
    upstream_model = config.model_for_client(alias, "cline" if client == "cline" else "claude-code", env, home)
    return {
        "model": upstream_model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 64,
    }


def diagnostic_from_json(
    payload_path: Path,
    client: str = "cline",
    home: Path | None = None,
    force_enabled: bool = False,
) -> dict[str, Any]:
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("--from-json must point to a JSON object.")
    return diagnostic_payload(
        payload,
        sample=f"from-json:{payload_path.name}",
        client=client,
        home=home,
        force_enabled=force_enabled,
    )


def diagnostic_payload(
    payload: dict[str, Any],
    sample: str = "payload",
    client: str = "cline",
    home: Path | None = None,
    force_enabled: bool = False,
) -> dict[str, Any]:
    home = home or paths.costguard_home()
    before_text = json.dumps(payload)
    before_chars = len(before_text)
    before_tokens = _estimate_tokens(before_chars)
    result = transform_payload(payload, client, home, force_enabled=force_enabled)
    after_text = json.dumps(result.payload)
    after_chars = len(after_text)
    after_tokens = _estimate_tokens(after_chars)
    tokens_saved = max(0, before_tokens - after_tokens)
    adapter = _adapter_callable()
    status_data = status(home)
    result_details = result.adapter_result_details or _empty_result_details()
    return {
        "sample": sample,
        "client": client,
        "model_alias": str(payload.get("model", "")),
        "upstream_model": str(payload.get("model", "")),
        "available": status_data["available"],
        "compatible": status_data["compatible"],
        "enabled": status_data["enabled"],
        "force_enabled": force_enabled,
        "adapter": result.adapter or (adapter[0] if adapter else ""),
        "input_type": "openai_chat_payload",
        "requested_input_shape": "proxy-route",
        "adapter_input_shape": result.adapter_input_shape or (_adapter_input_shape(adapter[0]) if adapter else "n/a"),
        "adapter_result_type": result.adapter_result_type or "n/a",
        "adapter_result_keys": result.adapter_result_keys or "n/a",
        "adapter_result_attributes": result_details["attributes"],
        "adapter_result_message_count": result_details["message_count"],
        "adapter_result_tokens_before": result_details["tokens_before"],
        "adapter_result_tokens_after": result_details["tokens_after"],
        "adapter_result_tokens_saved": result_details["tokens_saved"],
        "adapter_result_compression_ratio": result_details["compression_ratio"],
        "adapter_result_transforms_applied": result_details["transforms_applied"],
        "adapter_result_changed_flag": result_details["changed"],
        "adapter_result_reason": result_details["reason"],
        "adapter_result_metadata_keys": result_details["metadata_keys"],
        "normalized_result_shape": result.normalized_result_shape or "n/a",
        "payload_reconstruction_status": result.payload_reconstruction_status or "n/a",
        "input_message_count": _message_count(payload),
        "headroom_candidate_message_count": result.candidate_message_count,
        "headroom_compressible_message_count": result.compressible_message_count,
        "headroom_protected_message_count": result.protected_message_count,
        "headroom_roles_seen": result.roles_seen,
        "headroom_roles_compressed": result.roles_compressed,
        "headroom_transforms_applied": result.transforms_applied,
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


def _conversation_with_tool_output(content: str, final_request: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "You are a concise engineering assistant. Prefer short, actionable answers."},
        {"role": "user", "content": "Investigate this local development issue using the provided safe diagnostic output."},
        {"role": "assistant", "content": "I will inspect the diagnostic output and summarize only the useful parts."},
        {"role": "tool", "content": content, "tool_call_id": "costguard_diagnostic_sample"},
        {"role": "assistant", "content": "I found repeated patterns and a small number of likely root causes."},
        {"role": "user", "content": "Keep the answer short and avoid restating all raw output."},
        {"role": "assistant", "content": "Understood. I will provide the minimal diagnosis."},
        {"role": "user", "content": final_request},
    ]


def _cline_embedded_output(content: str, final_request: str) -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "You are a concise engineering assistant. Prefer short answers."},
        {"role": "user", "content": "Review the previous terminal output and explain what matters."},
        {
            "role": "assistant",
            "content": "Terminal output:\n\n" + content,
        },
        {"role": "assistant", "content": "I can summarize the repeated output without restating it."},
        {"role": "user", "content": final_request},
    ]


def _sample_tool_output() -> str:
    rows = []
    for index in range(1, 280):
        status = "ERROR" if index % 37 == 0 else "WARN" if index % 11 == 0 else "INFO"
        rows.append(
            json.dumps(
                {
                    "step": index,
                    "status": status,
                    "component": f"worker-{index % 9}",
                    "duration_ms": 1200 + (index % 17) * 31,
                    "message": "retryable timeout while reading local test fixture"
                    if status == "ERROR"
                    else "processed batch with repeated metadata",
                }
            )
        )
    return "\n".join(rows)


def _sample_code() -> str:
    template = """
def transform_record_{index}(record):
    value = record.get("value", 0)
    category = record.get("category", "unknown")
    if category == "legacy":
        value = value * 2
    if value > {limit}:
        return {{"status": "warn", "value": value, "category": category}}
    return {{"status": "ok", "value": value, "category": category}}
"""
    return "\n".join(template.format(index=index, limit=100 + index) for index in range(1, 90))


def _sample_markdown() -> str:
    sections = []
    for index in range(1, 120):
        sections.append(
            "\n".join(
                [
                    f"## Decision Note {index}",
                    "- Scope: local Cost Guard validation.",
                    "- Risk: repeated agent context can inflate token usage.",
                    "- Action: keep rules editable and validate with isolated home paths.",
                    "- Open question: confirm optional compression evidence before claiming savings.",
                ]
            )
        )
    return "\n\n".join(sections)


def _sample_logs(lines: int) -> str:
    output = []
    for index in range(1, lines + 1):
        level = "ERROR" if index % 53 == 0 else "WARN" if index % 13 == 0 else "INFO"
        output.append(
            f"2026-01-01T10:{index % 60:02d}:00Z {level} local-job-{index % 7} "
            f"partition={index % 19} attempt={index % 5} message='safe repeated validation event'"
        )
    return "\n".join(output)


def _sample_test_failure() -> str:
    blocks = []
    for index in range(1, 80):
        blocks.append(
            "\n".join(
                [
                    f"FAILED tests/test_pipeline_{index % 6}.py::test_case_{index}",
                    "AssertionError: expected local status 'ok' but got 'retry'",
                    "Captured stdout:",
                    "  validating offline smoke with isolated COSTGUARD_HOME",
                    "  command output omitted because it repeats the same stack frame",
                    "Stack:",
                    f"  File local_module_{index % 4}.py, line {20 + index}, in validate_batch",
                    "  RuntimeError: safe synthetic retry threshold exceeded",
                ]
            )
        )
    return "\n\n".join(blocks)


def _prepare_messages_for_headroom(payload: dict[str, Any], home: Path) -> PreparedMessages:
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return PreparedMessages(
            messages=[],
            original_messages=[],
            original_roles=[],
            compressible_indexes=set(),
            candidate_message_count=0,
            compressible_message_count=0,
            protected_message_count=0,
            below_threshold_count=0,
            user_protected_count=0,
            recent_protected_count=0,
            role_protected_count=0,
            roles_seen="n/a",
            roles_compressed="n/a",
            skip_reason=SKIPPED_NO_MESSAGES,
        )

    options = _headroom_options(home)
    protect_recent = max(0, int(options["protect_recent"]))
    min_tokens = max(1, int(options["min_tokens_to_compress"]))
    compress_user_messages = bool(options["compress_user_messages"])
    protected_start = max(0, len(messages) - protect_recent) if protect_recent else len(messages)

    prepared: list[dict[str, Any]] = []
    original_messages: list[dict[str, Any]] = []
    original_roles: list[str] = []
    compressible_indexes: set[int] = set()
    candidate_count = 0
    protected_count = 0
    below_threshold_count = 0
    user_protected_count = 0
    recent_protected_count = 0
    role_protected_count = 0

    for index, raw_message in enumerate(messages):
        if not isinstance(raw_message, dict):
            raw_message = {"role": "unknown", "content": str(raw_message)}
        original = json.loads(json.dumps(raw_message))
        message = json.loads(json.dumps(raw_message))
        role = str(message.get("role", "unknown"))
        original_roles.append(role)
        original_messages.append(original)
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        content_tokens = _estimate_tokens(len(text)) if text else 0
        looks_compressible = _looks_like_compressible_output(role, text)
        is_candidate = bool(text) and looks_compressible
        if is_candidate:
            candidate_count += 1

        protected_recent = index >= protected_start
        protected_user = role == "user" and not compress_user_messages
        protected_shape = not isinstance(content, str)
        below_threshold = bool(text) and content_tokens < min_tokens

        if is_candidate and protected_recent:
            recent_protected_count += 1
        if is_candidate and protected_user:
            user_protected_count += 1
        if is_candidate and protected_shape:
            role_protected_count += 1
        if is_candidate and below_threshold:
            below_threshold_count += 1

        protected = protected_recent or protected_user or protected_shape or below_threshold
        if protected and is_candidate:
            protected_count += 1

        if is_candidate and not protected:
            compressible_indexes.add(index)
            if role not in COMPRESSIBLE_ROLE_NAMES:
                message["role"] = "tool"
                message.setdefault("tool_call_id", f"costguard_headroom_{index}")
        prepared.append(message)

    roles_seen = _join_unique(original_roles)
    roles_compressed = _join_unique(original_roles[index] for index in sorted(compressible_indexes))
    skip_reason = _prepared_skip_reason(
        candidate_count=candidate_count,
        compressible_count=len(compressible_indexes),
        below_threshold_count=below_threshold_count,
        user_protected_count=user_protected_count,
        recent_protected_count=recent_protected_count,
        role_protected_count=role_protected_count,
    )
    return PreparedMessages(
        messages=prepared,
        original_messages=original_messages,
        original_roles=original_roles,
        compressible_indexes=compressible_indexes,
        candidate_message_count=candidate_count,
        compressible_message_count=len(compressible_indexes),
        protected_message_count=protected_count,
        below_threshold_count=below_threshold_count,
        user_protected_count=user_protected_count,
        recent_protected_count=recent_protected_count,
        role_protected_count=role_protected_count,
        roles_seen=roles_seen,
        roles_compressed=roles_compressed,
        skip_reason=skip_reason,
    )


def _prepared_skip_reason(
    candidate_count: int,
    compressible_count: int,
    below_threshold_count: int,
    user_protected_count: int,
    recent_protected_count: int,
    role_protected_count: int,
) -> str | None:
    if compressible_count > 0:
        return None
    if candidate_count == 0:
        return SKIPPED_NO_COMPRESSIBLE_MESSAGES
    if user_protected_count >= candidate_count:
        return SKIPPED_USER_MESSAGE_PROTECTED
    if recent_protected_count >= candidate_count:
        return SKIPPED_PROTECTED_RECENT
    if below_threshold_count >= candidate_count:
        return SKIPPED_BELOW_THRESHOLD
    if role_protected_count >= candidate_count:
        return SKIPPED_PROTECTED_ROLE
    return SKIPPED_NO_COMPRESSIBLE_MESSAGES


def _looks_like_compressible_output(role: str, text: str) -> bool:
    if not text:
        return False
    if role in COMPRESSIBLE_ROLE_NAMES:
        return True
    if role == "user":
        return len(text) > 12000
    if len(text) > 12000 and role in {"assistant", "system"}:
        return True
    return any(re.search(pattern, text) for pattern in TOOL_OUTPUT_PATTERNS)


def _restore_original_message_shapes(
    compressed_payload: dict[str, Any],
    original_payload: dict[str, Any],
    prepared: PreparedMessages,
) -> dict[str, Any]:
    compressed_messages = compressed_payload.get("messages")
    if not isinstance(compressed_messages, list):
        raise ValueError("compressed payload has no messages list")
    if len(compressed_messages) != len(prepared.original_messages):
        raise ValueError("compressed message count changed")

    restored_messages: list[dict[str, Any]] = []
    for index, original in enumerate(prepared.original_messages):
        restored = json.loads(json.dumps(original))
        compressed = compressed_messages[index]
        if index in prepared.compressible_indexes and isinstance(compressed, dict) and isinstance(compressed.get("content"), str):
            restored["content"] = compressed["content"]
        restored_messages.append(restored)

    restored_payload = json.loads(json.dumps(original_payload))
    restored_payload["messages"] = restored_messages
    return restored_payload


def _join_unique(values: Any) -> str:
    seen = []
    for value in values:
        label = str(value)
        if label and label not in seen:
            seen.append(label)
    return ",".join(seen) if seen else "n/a"


def _adapter_input_shape(adapter_name: str) -> str:
    return "messages_list" if adapter_name == "compress" else "payload_dict"


def _headroom_options(
    home: Path,
    compress_user_messages: bool | None = None,
    protect_recent: int | None = None,
    target_ratio: float | None = None,
    min_tokens_to_compress: int | None = None,
) -> dict[str, Any]:
    env = config.load_env(home)
    options: dict[str, Any] = {
        "compress_user_messages": _bool_option(
            env,
            "COSTGUARD_HEADROOM_COMPRESS_USER_MESSAGES",
            compress_user_messages,
            default=False,
        ),
        "protect_recent": _int_option(env, "COSTGUARD_HEADROOM_PROTECT_RECENT", protect_recent, default=4),
        "min_tokens_to_compress": _int_option(
            env,
            "COSTGUARD_HEADROOM_MIN_TOKENS_TO_COMPRESS",
            min_tokens_to_compress,
            default=250,
        ),
    }
    ratio = _float_option(env, "COSTGUARD_HEADROOM_TARGET_RATIO", target_ratio)
    if ratio is not None:
        options["target_ratio"] = ratio
    return options


def _bool_option(env: dict[str, str], name: str, override: bool | None, default: bool) -> bool:
    if override is not None:
        return bool(override)
    return parse_bool(env.get(name, str(default).lower()), default=default)


def _int_option(env: dict[str, str], name: str, override: int | None, default: int) -> int:
    if override is not None:
        return int(override)
    value = env.get(name, "")
    if value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _float_option(env: dict[str, str], name: str, override: float | None) -> float | None:
    if override is not None:
        return float(override)
    value = env.get(name, "")
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


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
    headroom_options: dict[str, Any],
) -> Any:
    if adapter_name == "compress":
        return _call_compress(adapter_fn, adapter_input, model, headroom_options)
    if input_shape == "openai-payload":
        return _call_adapter(adapter_fn, adapter_input, client, home)
    return adapter_fn(adapter_input)


def _call_compress(
    compress_fn: Callable[..., Any],
    value: Any,
    model: str,
    headroom_options: dict[str, Any] | None = None,
) -> Any:
    options = dict(headroom_options or {})
    try:
        return compress_fn(value, model=model, **options)
    except TypeError:
        pass
    try:
        return compress_fn(value, model=model)
    except TypeError:
        pass
    try:
        payload = {"model": model, **options}
        return compress_fn(value, payload)
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


def _empty_result_details() -> dict[str, Any]:
    return {
        "attributes": "n/a",
        "message_count": "n/a",
        "tokens_before": "n/a",
        "tokens_after": "n/a",
        "tokens_saved": "n/a",
        "compression_ratio": "n/a",
        "transforms_applied": "n/a",
        "changed": "n/a",
        "reason": "n/a",
        "metadata_keys": "n/a",
    }


def _result_details(result: Any) -> dict[str, Any]:
    if isinstance(result, tuple) and result:
        result = result[0]

    details = _empty_result_details()
    details["attributes"] = _result_attribute_names(result)
    details["message_count"] = _result_message_count(result)
    details["tokens_before"] = _first_result_value(result, "tokens_before", "tokensBefore", "original_tokens")
    details["tokens_after"] = _first_result_value(result, "tokens_after", "tokensAfter", "compressed_tokens")
    details["tokens_saved"] = _first_result_value(result, "tokens_saved", "tokensSaved")
    details["compression_ratio"] = _first_result_value(result, "compression_ratio", "compressionRatio", "savings_percent")
    details["transforms_applied"] = _result_transforms(result)
    details["changed"] = _result_changed(result, details["tokens_saved"])
    details["reason"] = _result_reason(result)
    details["metadata_keys"] = _result_metadata_keys(result)
    return details


def _result_attribute_names(result: Any) -> str:
    if result is None or isinstance(result, dict):
        return "n/a"
    try:
        names = sorted(key for key in vars(result) if not key.startswith("_"))
    except TypeError:
        names = []
    return ",".join(names) if names else "n/a"


def _first_result_value(result: Any, *names: str) -> Any:
    if result is None:
        return "n/a"
    if isinstance(result, dict):
        for name in names:
            if name in result and _safe_scalar(result[name]):
                return result[name]
        return "n/a"
    for name in names:
        value = getattr(result, name, None)
        if _safe_scalar(value):
            return value
    return "n/a"


def _safe_scalar(value: Any) -> bool:
    return isinstance(value, (bool, int, float)) or (isinstance(value, str) and len(value) <= 160)


def _result_message_count(result: Any) -> Any:
    messages = _result_messages(result)
    return len(messages) if isinstance(messages, list) else "n/a"


def _result_messages(result: Any) -> Any:
    if isinstance(result, tuple) and result:
        result = result[0]
    if isinstance(result, dict):
        return result.get("messages")
    return getattr(result, "messages", None)


def _result_transforms(result: Any) -> str:
    value = _first_result_list(result, "transforms_applied", "transformsApplied", "transforms")
    if not value:
        return "n/a"
    safe_values = [str(item) for item in value if isinstance(item, (str, int, float, bool))]
    return ",".join(safe_values[:20]) if safe_values else "n/a"


def _first_result_list(result: Any, *names: str) -> list[Any]:
    if isinstance(result, dict):
        for name in names:
            value = result.get(name)
            if isinstance(value, list):
                return value
        return []
    for name in names:
        value = getattr(result, name, None)
        if isinstance(value, list):
            return value
    return []


def _result_changed(result: Any, tokens_saved: Any) -> Any:
    explicit = _first_result_value(result, "compressed", "changed", "applied")
    if explicit != "n/a":
        return explicit
    if isinstance(tokens_saved, (int, float)):
        return tokens_saved > 0
    return "n/a"


def _result_reason(result: Any) -> Any:
    return _first_result_value(result, "noop_reason", "reason", "skip_reason", "status", "error_type")


def _result_metadata_keys(result: Any) -> str:
    metadata: Any = None
    if isinstance(result, dict):
        metadata = result.get("metadata")
    elif result is not None:
        metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict):
        keys = sorted(str(key) for key in metadata.keys())
        return ",".join(keys) if keys else "n/a"
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
