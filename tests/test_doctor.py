from __future__ import annotations

from typer.testing import CliRunner

from costguard.cli import app
from costguard.doctor import has_errors, run_checks
from costguard.install import setup_costguard


def test_doctor_detects_missing_config(isolated_env):
    checks = run_checks()
    assert has_errors(checks) is True
    assert any(check.name == ".env" and check.level == "ERROR" for check in checks)


def test_doctor_after_setup_has_no_errors(isolated_env):
    setup_costguard(tool="both", non_interactive=True)
    checks = run_checks()
    assert has_errors(checks) is False
    assert any(check.name == "Proxy health" and check.level == "WARN" for check in checks)


def test_cli_budget_set_and_status(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)
    runner = CliRunner()
    set_result = runner.invoke(app, ["budget", "set", "--daily", "5"])
    status_result = runner.invoke(app, ["budget", "status"])

    assert set_result.exit_code == 0
    assert status_result.exit_code == 0
    assert "daily limit" in status_result.output
