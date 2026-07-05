from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from . import claude_code, config, headroom as headroom_mod, paths
from .sqlite_store import init_db
from .utils import copy_file, ensure_dir, make_executable, write_text_if_changed, write_yaml


DIRECTORIES = [
    "config",
    "rules",
    "hooks",
    "bin",
    "logs",
    "cache",
    "vector_cache",
    "backups",
    "run",
]


def _template(path: str) -> Path:
    return paths.template_root() / path


def _copy_template(path: str, destination: Path, dry_run: bool = False, overwrite: bool = False) -> bool:
    source = _template(path)
    if source.exists():
        return copy_file(source, destination, dry_run=dry_run, overwrite=overwrite)
    return False


def _write_fallback_templates(home: Path, dry_run: bool = False) -> None:
    write_yaml(paths.rules_dir(home) / "default.yaml", __import__("costguard.rules").rules.DEFAULT_RULES, dry_run=dry_run)
    write_yaml(paths.rules_dir(home) / "user.yaml", {"blocked_paths": [], "blocked_commands": [], "rewrite_commands": []}, dry_run=dry_run)


def setup_costguard(
    tool: str = "both",
    daily_budget: float = 5,
    monthly_budget: float = 100,
    budget_mode: str = "warn",
    non_interactive: bool = False,
    dry_run: bool = False,
    openai_upstream_base_url: str | None = None,
    anthropic_upstream_base_url: str | None = None,
    openai_model_cheap: str | None = None,
    openai_model_standard: str | None = None,
    openai_model_strong: str | None = None,
    openai_model_sonnet: str | None = None,
    anthropic_model_standard: str | None = None,
    anthropic_model_sonnet: str | None = None,
    cache_mode: str = "disabled",
    headroom_enabled: bool = False,
    autostart_enabled: bool = False,
) -> dict[str, Any]:
    home = paths.costguard_home()
    claude_home = paths.claude_home()
    planned: list[str] = []
    if headroom_enabled and not headroom_mod.compatible():
        raise RuntimeError(
            "Headroom was requested but no compatible adapter was found. "
            'Install Headroom with: pip install "ai-costguard[headroom]". '
            "Expected a Python module named headroom exposing one of: "
            f"{', '.join(headroom_mod.ADAPTER_FUNCTIONS)}."
        )

    for directory in DIRECTORIES:
        ensure_dir(home / directory, dry_run=dry_run)
        planned.append(str(home / directory))

    env_overrides = {
        "OPENAI_UPSTREAM_BASE_URL": openai_upstream_base_url,
        "ANTHROPIC_UPSTREAM_BASE_URL": anthropic_upstream_base_url,
        "OPENAI_MODEL_CHEAP": openai_model_cheap,
        "OPENAI_MODEL_STANDARD": openai_model_standard,
        "OPENAI_MODEL_STRONG": openai_model_strong,
        "OPENAI_MODEL_SONNET": openai_model_sonnet,
        "ANTHROPIC_MODEL_STANDARD": anthropic_model_standard,
        "ANTHROPIC_MODEL_SONNET": anthropic_model_sonnet,
        "COSTGUARD_DAILY_BUDGET": daily_budget,
        "COSTGUARD_MONTHLY_BUDGET": monthly_budget,
        "COSTGUARD_BUDGET_MODE": budget_mode,
        "COSTGUARD_CACHE_MODE": cache_mode,
        "COSTGUARD_HEADROOM_ENABLED": str(headroom_enabled).lower(),
    }
    if not paths.env_path(home).exists():
        write_text_if_changed(paths.env_path(home), config.default_env_text(env_overrides), dry_run=dry_run)
        planned.append(str(paths.env_path(home)))

    settings = config.load_settings(home)
    settings["tools"] = {
        "cline": tool in {"cline", "both"},
        "claude_code": tool in {"claude-code", "claude_code", "both"},
    }
    settings["budget"] = {"daily": float(daily_budget), "monthly": float(monthly_budget), "mode": budget_mode}
    settings["cache"] = {"mode": cache_mode}
    settings["headroom"] = {"enabled": bool(headroom_enabled)}
    settings["autostart"] = {"enabled": bool(autostart_enabled)}
    config.save_settings(settings, home, dry_run=dry_run)
    planned.append(str(paths.settings_path(home)))

    _copy_template("rules/default.yaml", paths.rules_dir(home) / "default.yaml", dry_run=dry_run, overwrite=True)
    _copy_template("rules/user.yaml", paths.rules_dir(home) / "user.yaml", dry_run=dry_run, overwrite=False)
    if not (paths.rules_dir(home) / "default.yaml").exists() and not dry_run:
        _write_fallback_templates(home, dry_run=dry_run)

    for hook_name in ("pre_tool_use.py", "post_tool_use.py"):
        _copy_template(f"hooks/{hook_name}", paths.hooks_dir(home) / hook_name, dry_run=dry_run, overwrite=True)

    for command in ("safe-grep", "short-diff", "summarize-log", "test-failures-only"):
        destination = paths.bin_dir(home) / command
        _copy_template(f"bin/{command}", destination, dry_run=dry_run, overwrite=True)
        if not dry_run:
            make_executable(destination)

    if not dry_run:
        init_db(paths.db_path(home))
    planned.append(str(paths.db_path(home)))

    if tool in {"claude-code", "claude_code", "both"}:
        claude_code.configure_claude_settings(home, claude_home, dry_run=dry_run)
        planned.append(str(paths.claude_settings_path(claude_home)))

    return {
        "home": home,
        "claude_home": claude_home,
        "dry_run": dry_run,
        "planned": planned,
        "non_interactive": non_interactive,
    }


def attach_project(project: str, dry_run: bool = False, repo: Path | None = None) -> dict[str, Any]:
    repo = (repo or Path.cwd()).resolve()
    settings_path = repo / ".claude" / "settings.local.json"
    payload = {
        "env": {
            "COSTGUARD_PROJECT": project,
            "COSTGUARD_REPO": str(repo),
        }
    }
    if not dry_run:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(__import__("json").dumps(payload, indent=2) + "\n", encoding="utf-8")
        git_dir = repo / ".git"
        if git_dir.exists():
            exclude = git_dir / "info" / "exclude"
            exclude.parent.mkdir(parents=True, exist_ok=True)
            existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
            line = ".claude/settings.local.json"
            if line not in existing.splitlines():
                exclude.write_text(existing.rstrip() + os.linesep + line + os.linesep, encoding="utf-8")
    return {"settings_path": settings_path, "project": project, "repo": repo, "dry_run": dry_run}
