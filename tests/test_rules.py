from __future__ import annotations

from typer.testing import CliRunner

from costguard import rules
from costguard.cli import app
from costguard.install import setup_costguard


def test_rules_block_secret_paths_and_commands(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)
    assert rules.evaluate_command("cat .env").action == "block"
    assert rules.evaluate_path("terraform.tfstate").action == "block"


def test_rules_rewrite_expensive_commands(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)
    git_diff = rules.evaluate_command("git diff")
    find_all = rules.evaluate_command("find .")

    assert git_diff.action == "rewrite"
    assert git_diff.command == "git diff --stat && git diff --name-only"
    assert find_all.action == "rewrite"
    assert find_all.command == "find . -maxdepth 3"


def test_rules_allow_when_no_rule_applies(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)
    assert rules.evaluate_command("git status --short").action == "allow"


def test_cli_rules_test_outputs_rewrite(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)
    runner = CliRunner()
    result = runner.invoke(app, ["rules", "test", "git diff"])
    assert result.exit_code == 0
    assert "REWRITE" in result.output
    assert "git diff --stat && git diff --name-only" in result.output
