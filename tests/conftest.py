from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    home = tmp_path / "costguard"
    claude_home = tmp_path / "claude"
    monkeypatch.setenv("COSTGUARD_HOME", str(home))
    monkeypatch.setenv("COSTGUARD_CLAUDE_HOME", str(claude_home))
    monkeypatch.delenv("COSTGUARD_DRY_RUN", raising=False)
    return {"home": home, "claude_home": claude_home}
