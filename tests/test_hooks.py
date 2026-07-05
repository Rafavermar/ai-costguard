from __future__ import annotations

from costguard.hooks_runtime import handle_pre_tool_use, pre_tool_use_from_stdin
from costguard.install import setup_costguard


def test_hook_blocks_cat_env(isolated_env):
    setup_costguard(tool="claude-code", non_interactive=True)
    result = handle_pre_tool_use({"tool_name": "Bash", "tool_input": {"command": "cat .env"}})
    output = result["hookSpecificOutput"]
    assert output["permissionDecision"] == "deny"
    assert "blocked" in output["permissionDecisionReason"].lower()


def test_hook_blocks_terraform_state_read(isolated_env):
    setup_costguard(tool="claude-code", non_interactive=True)
    result = handle_pre_tool_use({"tool_name": "Read", "tool_input": {"file_path": "terraform.tfstate"}})
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_hook_rewrites_git_diff_and_find(isolated_env):
    setup_costguard(tool="claude-code", non_interactive=True)
    diff_result = handle_pre_tool_use({"tool_name": "Bash", "tool_input": {"command": "git diff"}})
    find_result = handle_pre_tool_use({"tool_name": "Bash", "tool_input": {"command": "find ."}})

    assert diff_result["hookSpecificOutput"]["updatedInput"]["command"] == "git diff --stat && git diff --name-only"
    assert find_result["hookSpecificOutput"]["updatedInput"]["command"] == "find . -maxdepth 3"


def test_hook_returns_empty_for_unknown_or_unmatched(isolated_env):
    setup_costguard(tool="claude-code", non_interactive=True)
    assert handle_pre_tool_use({"tool_name": "Bash", "tool_input": {"command": "git status --short"}}) == {}
    assert pre_tool_use_from_stdin("not-json") == "{}"
