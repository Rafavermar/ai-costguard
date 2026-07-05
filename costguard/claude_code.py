from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from . import paths
from .utils import read_json, write_json


COSTGUARD_ENV_KEYS = {
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
    "CLAUDE_CODE_MAX_TURNS",
    "CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY",
    "MAX_THINKING_TOKENS",
    "PATH",
}


def settings_fragment(costguard_home: Path | None = None) -> dict[str, Any]:
    home = (costguard_home or paths.costguard_home()).resolve()
    return {
        "env": {
            "ANTHROPIC_BASE_URL": "http://127.0.0.1:4040",
            "ANTHROPIC_AUTH_TOKEN": "sk-costguard-local",
            "ANTHROPIC_MODEL": "cg-standard",
            "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "4096",
            "CLAUDE_CODE_MAX_TURNS": "12",
            "CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY": "3",
            "MAX_THINKING_TOKENS": "4000",
            "PATH": f"{home / 'bin'}:$PATH",
        },
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|Read|Edit",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python {home / 'hooks' / 'pre_tool_use.py'}",
                        }
                    ],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": "Bash",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python {home / 'hooks' / 'post_tool_use.py'}",
                        }
                    ],
                }
            ],
        },
    }


def _hook_exists(existing_hooks: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    candidate_commands = {
        hook.get("command")
        for hook in candidate.get("hooks", [])
        if isinstance(hook, dict)
    }
    for existing in existing_hooks:
        commands = {
            hook.get("command")
            for hook in existing.get("hooks", [])
            if isinstance(hook, dict)
        }
        if candidate_commands & commands:
            return True
    return False


def merge_settings(existing: dict[str, Any], fragment: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    env = dict(merged.get("env", {}))
    env.update(fragment.get("env", {}))
    merged["env"] = env

    hooks = dict(merged.get("hooks", {}))
    for event_name, entries in fragment.get("hooks", {}).items():
        event_entries = list(hooks.get(event_name, []))
        for entry in entries:
            if not _hook_exists(event_entries, entry):
                event_entries.append(entry)
        hooks[event_name] = event_entries
    merged["hooks"] = hooks
    return merged


def backup_settings(claude_home: Path | None = None, dry_run: bool = False) -> Path | None:
    settings = paths.claude_settings_path(claude_home)
    if not settings.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = settings.with_name(f"settings.json.bak.costguard-{timestamp}")
    if not dry_run:
        settings.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(settings, backup)
    return backup


def configure_claude_settings(
    costguard_home: Path | None = None,
    claude_home: Path | None = None,
    dry_run: bool = False,
) -> Path:
    settings_path = paths.claude_settings_path(claude_home)
    existing = read_json(settings_path, {})
    if settings_path.exists() and not contains_costguard_settings(existing):
        backup_settings(claude_home, dry_run=dry_run)
    merged = merge_settings(existing, settings_fragment(costguard_home))
    write_json(settings_path, merged, dry_run=dry_run)
    return settings_path


def _is_costguard_hook(entry: dict[str, Any]) -> bool:
    for hook in entry.get("hooks", []) or []:
        command = str(hook.get("command", ""))
        if "costguard" in command and ("pre_tool_use.py" in command or "post_tool_use.py" in command):
            return True
    return False


def contains_costguard_settings(settings: dict[str, Any]) -> bool:
    env = settings.get("env", {}) or {}
    if env.get("ANTHROPIC_BASE_URL") == "http://127.0.0.1:4040":
        return True
    if env.get("ANTHROPIC_AUTH_TOKEN") == "sk-costguard-local":
        return True
    if str(env.get("ANTHROPIC_MODEL", "")).startswith("cg-"):
        return True
    if "costguard" in str(env.get("PATH", "")).lower():
        return True

    hooks = settings.get("hooks", {}) or {}
    for entries in hooks.values():
        for entry in entries or []:
            if isinstance(entry, dict) and _is_costguard_hook(entry):
                return True
    return False


def remove_costguard_settings(existing: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(existing or {})
    env = dict(cleaned.get("env", {}))
    for key in COSTGUARD_ENV_KEYS:
        env.pop(key, None)
    if env:
        cleaned["env"] = env
    else:
        cleaned.pop("env", None)

    hooks = dict(cleaned.get("hooks", {}))
    for event_name in list(hooks.keys()):
        hooks[event_name] = [entry for entry in hooks.get(event_name, []) if not _is_costguard_hook(entry)]
        if not hooks[event_name]:
            hooks.pop(event_name, None)
    if hooks:
        cleaned["hooks"] = hooks
    else:
        cleaned.pop("hooks", None)
    return cleaned


def latest_backup(claude_home: Path | None = None) -> Path | None:
    settings = paths.claude_settings_path(claude_home)
    backups = sorted(settings.parent.glob("settings.json.bak.costguard-*"), reverse=True)
    for backup in backups:
        if not contains_costguard_settings(read_json(backup, {})):
            return backup
    return None


def remove_backups(claude_home: Path | None = None, dry_run: bool = False) -> None:
    settings = paths.claude_settings_path(claude_home)
    for backup in settings.parent.glob("settings.json.bak.costguard-*"):
        if not dry_run:
            backup.unlink(missing_ok=True)


def restore_or_clean_settings(claude_home: Path | None = None, dry_run: bool = False) -> str:
    settings_path = paths.claude_settings_path(claude_home)
    backup = latest_backup(claude_home)
    if backup:
        if not dry_run:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(backup, settings_path)
            remove_backups(claude_home)
        return f"restored from {backup}"
    if not settings_path.exists():
        remove_backups(claude_home, dry_run=dry_run)
        return "no Claude Code settings found"
    existing = read_json(settings_path, {})
    write_json(settings_path, remove_costguard_settings(existing), dry_run=dry_run)
    remove_backups(claude_home, dry_run=dry_run)
    return "removed Cost Guard fragments"


def update_anthropic_model(alias: str, claude_home: Path | None = None, dry_run: bool = False) -> bool:
    settings_path = paths.claude_settings_path(claude_home)
    if not settings_path.exists():
        return False
    settings = read_json(settings_path, {})
    env = settings.setdefault("env", {})
    if "ANTHROPIC_MODEL" not in env:
        return False
    env["ANTHROPIC_MODEL"] = alias
    write_json(settings_path, settings, dry_run=dry_run)
    return True
