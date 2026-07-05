from __future__ import annotations

from costguard.claude_code import merge_settings, remove_costguard_settings, settings_fragment


def test_merge_preserves_existing_settings_and_avoids_duplicate_hooks(isolated_env):
    existing = {
        "env": {"USER_KEY": "keep"},
        "hooks": {"PreToolUse": [{"matcher": "UserHook", "hooks": [{"type": "command", "command": "echo user"}]}]},
    }
    fragment = settings_fragment(isolated_env["home"])
    merged = merge_settings(existing, fragment)
    merged_again = merge_settings(merged, fragment)

    assert merged_again["env"]["USER_KEY"] == "keep"
    assert merged_again["env"]["ANTHROPIC_MODEL"] == "cg-standard"
    commands = [
        hook["command"]
        for entry in merged_again["hooks"]["PreToolUse"]
        for hook in entry.get("hooks", [])
    ]
    assert commands.count("echo user") == 1
    assert sum("pre_tool_use.py" in command for command in commands) == 1


def test_remove_costguard_settings_preserves_user_values(isolated_env):
    fragment = settings_fragment(isolated_env["home"])
    merged = merge_settings({"env": {"USER_KEY": "keep"}}, fragment)
    cleaned = remove_costguard_settings(merged)

    assert cleaned["env"] == {"USER_KEY": "keep"}
    assert "hooks" not in cleaned
