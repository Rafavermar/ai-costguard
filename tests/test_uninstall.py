from __future__ import annotations

import json

from costguard.install import setup_costguard
from costguard.uninstall import uninstall_costguard


def test_uninstall_restores_claude_settings_from_backup(isolated_env):
    claude_home = isolated_env["claude_home"]
    claude_home.mkdir(parents=True)
    original = {"env": {"KEEP": "1"}, "hooks": {"PreToolUse": [{"matcher": "User", "hooks": []}]}}
    (claude_home / "settings.json").write_text(json.dumps(original), encoding="utf-8")

    setup_costguard(tool="claude-code", non_interactive=True)
    configured = json.loads((claude_home / "settings.json").read_text(encoding="utf-8"))
    assert configured["env"]["ANTHROPIC_AUTH_TOKEN"] == "sk-costguard-local"

    result = uninstall_costguard()
    restored = json.loads((claude_home / "settings.json").read_text(encoding="utf-8"))
    assert restored == original
    assert "restored from" in result["claude"]
    assert list(claude_home.glob("settings.json.bak.costguard-*")) == []


def test_repeated_setup_uninstall_restores_original_claude_settings(isolated_env):
    claude_home = isolated_env["claude_home"]
    claude_home.mkdir(parents=True)
    original = {"env": {"KEEP": "1"}}
    (claude_home / "settings.json").write_text(json.dumps(original), encoding="utf-8")

    setup_costguard(tool="claude-code", non_interactive=True)
    setup_costguard(tool="claude-code", non_interactive=True)

    result = uninstall_costguard()
    restored = json.loads((claude_home / "settings.json").read_text(encoding="utf-8"))
    assert restored == original
    assert "restored from" in result["claude"]
    assert list(claude_home.glob("settings.json.bak.costguard-*")) == []


def test_uninstall_ignores_costguard_contaminated_backup(isolated_env):
    claude_home = isolated_env["claude_home"]
    claude_home.mkdir(parents=True)
    original = {"env": {"KEEP": "1"}}
    settings_path = claude_home / "settings.json"
    settings_path.write_text(json.dumps(original), encoding="utf-8")

    setup_costguard(tool="claude-code", non_interactive=True)
    configured = json.loads(settings_path.read_text(encoding="utf-8"))
    contaminated = claude_home / "settings.json.bak.costguard-99999999999999"
    contaminated.write_text(json.dumps(configured), encoding="utf-8")

    uninstall_costguard()
    restored = json.loads(settings_path.read_text(encoding="utf-8"))
    assert restored == original
    assert list(claude_home.glob("settings.json.bak.costguard-*")) == []


def test_uninstall_without_backup_removes_only_costguard_fragments(isolated_env):
    setup_costguard(tool="claude-code", non_interactive=True)
    claude_home = isolated_env["claude_home"]
    settings_path = claude_home / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["env"]["USER_VALUE"] = "keep"
    settings_path.write_text(json.dumps(settings), encoding="utf-8")
    for backup in claude_home.glob("settings.json.bak.costguard-*"):
        backup.unlink()

    uninstall_costguard()
    cleaned = json.loads(settings_path.read_text(encoding="utf-8"))
    assert cleaned["env"]["USER_VALUE"] == "keep"
    assert "ANTHROPIC_AUTH_TOKEN" not in cleaned.get("env", {})
    assert "hooks" not in cleaned
    assert list(claude_home.glob("settings.json.bak.costguard-*")) == []


def test_uninstall_purge_deletes_costguard_home(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)
    assert isolated_env["home"].exists()
    result = uninstall_costguard(purge=True, yes=True)
    assert result["purged"] is True
    assert not isolated_env["home"].exists()
