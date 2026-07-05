from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config
from .sqlite_store import usage_summary


@dataclass(frozen=True)
class BudgetDecision:
    action: str
    reason: str
    daily_used: float
    daily_limit: float
    monthly_used: float
    monthly_limit: float
    mode: str

    @property
    def blocked(self) -> bool:
        return self.action in {"block-premium", "block-all"}


def estimate_tokens(input_chars: int, output_chars: int = 0) -> int:
    return max(1, int((input_chars + output_chars + 3) / 4))


def estimate_cost(model_alias: str, tokens: int, home: Path | None = None) -> float:
    settings = config.load_settings(home)
    price_per_1k = float(settings.get("pricing", {}).get(model_alias, 0.001))
    return (tokens / 1000.0) * price_per_1k


def budget_status(home: Path | None = None) -> dict[str, Any]:
    settings = config.load_settings(home)
    budget = settings.get("budget", {})
    today = usage_summary("today", path=None if home is None else home / "costguard.db")
    month = usage_summary("month", path=None if home is None else home / "costguard.db")
    daily_limit = float(budget.get("daily", 0) or 0)
    monthly_limit = float(budget.get("monthly", 0) or 0)
    return {
        "daily_used": today["cost"],
        "daily_limit": daily_limit,
        "daily_remaining": max(0.0, daily_limit - today["cost"]),
        "monthly_used": month["cost"],
        "monthly_limit": monthly_limit,
        "monthly_remaining": max(0.0, monthly_limit - month["cost"]),
        "mode": budget.get("mode", "warn"),
        "action": current_action(today["cost"], month["cost"], daily_limit, monthly_limit, budget.get("mode", "warn")),
    }


def current_action(daily_used: float, monthly_used: float, daily_limit: float, monthly_limit: float, mode: str) -> str:
    over = (daily_limit > 0 and daily_used >= daily_limit) or (monthly_limit > 0 and monthly_used >= monthly_limit)
    if not over:
        return "allow"
    return mode


def check_budget(model_alias: str, estimated_new_cost: float, home: Path | None = None) -> BudgetDecision:
    settings = config.load_settings(home)
    budget = settings.get("budget", {})
    daily_limit = float(budget.get("daily", 0) or 0)
    monthly_limit = float(budget.get("monthly", 0) or 0)
    mode = str(budget.get("mode", "warn"))
    today = usage_summary("today", path=None if home is None else home / "costguard.db")
    month = usage_summary("month", path=None if home is None else home / "costguard.db")
    daily_after = today["cost"] + estimated_new_cost
    monthly_after = month["cost"] + estimated_new_cost
    over_daily = daily_limit > 0 and daily_after >= daily_limit
    over_monthly = monthly_limit > 0 and monthly_after >= monthly_limit

    if not (over_daily or over_monthly):
        return BudgetDecision("allow", "Budget available.", today["cost"], daily_limit, month["cost"], monthly_limit, mode)

    if mode == "warn":
        return BudgetDecision("warn", "Budget reached; warning only.", today["cost"], daily_limit, month["cost"], monthly_limit, mode)

    if mode == "block-premium" and model_alias in config.PREMIUM_ALIASES:
        return BudgetDecision(
            "block-premium",
            "Budget reached; premium models are blocked.",
            today["cost"],
            daily_limit,
            month["cost"],
            monthly_limit,
            mode,
        )

    if mode == "block-all":
        return BudgetDecision(
            "block-all",
            "Budget reached; all new calls are blocked.",
            today["cost"],
            daily_limit,
            month["cost"],
            monthly_limit,
            mode,
        )

    return BudgetDecision("allow", "Budget reached but this model is allowed.", today["cost"], daily_limit, month["cost"], monthly_limit, mode)
