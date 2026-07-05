from __future__ import annotations

from costguard import paths


def test_paths_respect_isolated_env(isolated_env):
    assert paths.costguard_home() == isolated_env["home"].resolve()
    assert paths.claude_home() == isolated_env["claude_home"].resolve()
    assert paths.env_path() == isolated_env["home"].resolve() / ".env"
    assert paths.db_path() == isolated_env["home"].resolve() / "costguard.db"


def test_dry_run_env(monkeypatch):
    monkeypatch.setenv("COSTGUARD_DRY_RUN", "true")
    assert paths.dry_run_enabled() is True
    assert paths.dry_run_enabled(explicit=True) is True
