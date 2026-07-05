from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import paths, rules
from .utils import append_jsonl


def _tool_name(payload: dict[str, Any]) -> str:
    return str(
        payload.get("tool_name")
        or payload.get("toolName")
        or payload.get("tool")
        or payload.get("hook_event_name")
        or ""
    )


def _tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or payload.get("parameters")
    if isinstance(value, dict):
        return value
    return payload


def _deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _rewrite(command: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
            "updatedInput": {"command": command},
        }
    }


def handle_pre_tool_use(payload: dict[str, Any], home: Path | None = None, project: Path | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    tool = _tool_name(payload).lower()
    tool_input = _tool_input(payload)

    command = tool_input.get("command") or payload.get("command")
    if command and ("bash" in tool or not tool):
        result = rules.evaluate_command(str(command), home=home, project=project)
        if result.action == "block":
            return _deny(result.reason)
        if result.action == "rewrite" and result.command:
            return _rewrite(result.command, result.reason)

    if any(name in tool for name in ("read", "edit")) or "file_path" in tool_input or "path" in tool_input:
        path_value = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("filePath")
        if path_value:
            result = rules.evaluate_path(str(path_value), home=home, project=project)
            if result.action == "block":
                return _deny(result.reason)

    return {}


def pre_tool_use_from_stdin(stdin_text: str) -> str:
    try:
        payload = json.loads(stdin_text or "{}")
    except json.JSONDecodeError:
        return "{}"
    return json.dumps(handle_pre_tool_use(payload))


def handle_post_tool_use(payload: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    home = home or paths.costguard_home()
    event = {
        "tool": _tool_name(payload),
        "has_output": bool(payload.get("output") or payload.get("tool_output")),
        "output_chars": len(str(payload.get("output") or payload.get("tool_output") or "")),
    }
    append_jsonl(paths.events_log_path(home), event)
    return {}


def post_tool_use_from_stdin(stdin_text: str) -> str:
    try:
        payload = json.loads(stdin_text or "{}")
    except json.JSONDecodeError:
        return "{}"
    return json.dumps(handle_post_tool_use(payload))
