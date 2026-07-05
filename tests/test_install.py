from __future__ import annotations

import json
import sqlite3

from typer.testing import CliRunner

from costguard.cli import app
from costguard.install import attach_project, setup_costguard


def test_setup_creates_structure_sqlite_and_claude_settings(isolated_env):
    setup_costguard(tool="both", daily_budget=5, monthly_budget=100, budget_mode="warn", non_interactive=True)
    home = isolated_env["home"]
    claude_home = isolated_env["claude_home"]

    for relative in [
        ".env",
        "config/settings.yaml",
        "rules/default.yaml",
        "rules/user.yaml",
        "hooks/pre_tool_use.py",
        "hooks/post_tool_use.py",
        "bin/safe-grep",
        "logs",
        "cache",
        "vector_cache",
        "backups",
    ]:
        assert (home / relative).exists()

    db = home / "costguard.db"
    assert db.exists()
    with sqlite3.connect(db) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "usage_events" in tables
    assert "audit_events" in tables

    settings = json.loads((claude_home / "settings.json").read_text(encoding="utf-8"))
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:4040"
    assert "PreToolUse" in settings["hooks"]


def test_setup_dry_run_does_not_write(isolated_env):
    setup_costguard(tool="both", non_interactive=True, dry_run=True)
    assert not isolated_env["home"].exists()
    assert not isolated_env["claude_home"].exists()


def test_attach_project_writes_local_settings_and_git_exclude(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git" / "info").mkdir(parents=True)
    result = attach_project("demo", repo=repo)

    assert result["settings_path"].exists()
    payload = json.loads(result["settings_path"].read_text(encoding="utf-8"))
    assert payload["env"]["COSTGUARD_PROJECT"] == "demo"
    assert ".claude/settings.local.json" in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")


def test_cli_cline_config_prints_expected_values(isolated_env):
    runner = CliRunner()
    result = runner.invoke(app, ["cline-config"])
    assert result.exit_code == 0
    assert "Provider: OpenAI Compatible" in result.output
    assert "Base URL: http://127.0.0.1:4040/v1" in result.output
    assert "API Key: sk-costguard-local" in result.output
    assert "Model ID: cg-standard" in result.output


def test_cli_use_accepts_category_aliases_and_rejects_provider_alias(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)
    runner = CliRunner()

    for alias, expected in [("cheap", "cg-cheap"), ("standard", "cg-standard"), ("strong", "cg-strong")]:
        result = runner.invoke(app, ["use", alias])
        assert result.exit_code == 0
        assert f"Active model: {expected}" in result.output

    result = runner.invoke(app, ["use", "provider-specific"])

    assert result.exit_code == 1
    assert "Unknown model alias: provider-specific" in result.output
    assert "Traceback" not in result.output
