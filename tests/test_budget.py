from __future__ import annotations

from costguard import budget, config
from costguard.install import setup_costguard
from costguard.sqlite_store import record_usage


def test_budget_status_and_mode_update(isolated_env):
    setup_costguard(tool="cline", daily_budget=5, monthly_budget=100, budget_mode="warn", non_interactive=True)
    record_usage(
        {
            "client": "cline",
            "model_alias": "cg-standard",
            "upstream": "test",
            "input_chars": 100,
            "output_chars": 100,
            "estimated_tokens": 50,
            "estimated_cost": 1.25,
            "budget_action": "allow",
        },
        isolated_env["home"] / "costguard.db",
    )

    status = budget.budget_status(isolated_env["home"])
    assert status["daily_used"] == 1.25
    assert status["daily_remaining"] == 3.75

    config.update_budget(daily=2, monthly=10, mode="block-premium", home=isolated_env["home"])
    updated = budget.budget_status(isolated_env["home"])
    assert updated["daily_limit"] == 2
    assert updated["mode"] == "block-premium"


def test_budget_blocks_premium_when_over_limit(isolated_env):
    setup_costguard(tool="cline", daily_budget=0.001, monthly_budget=0.001, budget_mode="block-premium", non_interactive=True)
    decision = budget.check_budget("cg-sonnet", estimated_new_cost=1.0, home=isolated_env["home"])
    assert decision.action == "block-premium"
    assert decision.blocked is True


def test_budget_warn_allows_when_over_limit(isolated_env):
    setup_costguard(tool="cline", daily_budget=0.001, monthly_budget=0.001, budget_mode="warn", non_interactive=True)
    decision = budget.check_budget("cg-sonnet", estimated_new_cost=1.0, home=isolated_env["home"])
    assert decision.action == "warn"
    assert decision.blocked is False
