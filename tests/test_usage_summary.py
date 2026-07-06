from __future__ import annotations

from costguard.sqlite_store import record_usage, usage_summary


def test_usage_summary_separates_output_limits_and_headroom_metrics(isolated_env):
    db = isolated_env["home"] / "costguard.db"
    base_event = {
        "client": "cline",
        "model_alias": "cg-standard",
        "upstream": "test",
        "input_chars": 100,
        "output_chars": 100,
        "estimated_tokens": 50,
        "estimated_cost": 0.01,
        "budget_action": "allow",
    }
    record_usage({**base_event, "output_reduced": True}, db)
    record_usage(
        {
            **base_event,
            "rule_applied": "headroom:compress",
            "headroom_applied": True,
            "headroom_adapter": "compress",
            "headroom_input_chars_before": 400,
            "headroom_input_chars_after": 100,
            "headroom_input_tokens_before": 100,
            "headroom_input_tokens_after": 25,
            "headroom_tokens_saved": 75,
            "headroom_reduction_ratio": 0.75,
        },
        db,
    )
    record_usage(
        {
            **base_event,
            "headroom_skipped": True,
            "headroom_skip_reason": "skipped_tools",
            "headroom_input_chars_before": 200,
            "headroom_input_chars_after": 200,
            "headroom_input_tokens_before": 50,
            "headroom_input_tokens_after": 50,
        },
        db,
    )

    summary = usage_summary("today", db)

    assert summary["outputs_reduced"] == 1
    assert summary["headroom_applied_count"] == 1
    assert summary["headroom_input_chars_before"] == 600
    assert summary["headroom_input_chars_after"] == 300
    assert summary["headroom_input_tokens_before"] == 150
    assert summary["headroom_input_tokens_after"] == 75
    assert summary["headroom_tokens_saved"] == 75
    assert summary["headroom_reduction_ratio"] == 0.5
    assert summary["headroom_skipped_count"] == 1
    assert summary["headroom_last_skip_reason"] == "skipped_tools"
