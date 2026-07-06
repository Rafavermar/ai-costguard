from __future__ import annotations

import os
from pathlib import Path


ENV_HOME = "COSTGUARD_HOME"
ENV_CLAUDE_HOME = "COSTGUARD_CLAUDE_HOME"
ENV_DRY_RUN = "COSTGUARD_DRY_RUN"


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def costguard_home() -> Path:
    configured = os.environ.get(ENV_HOME)
    if configured:
        return _resolve(configured)
    return _resolve(Path.home() / ".costguard")


def claude_home() -> Path:
    configured = os.environ.get(ENV_CLAUDE_HOME)
    if configured:
        return _resolve(configured)
    return _resolve(Path.home() / ".claude")


def dry_run_enabled(explicit: bool = False) -> bool:
    env_value = os.environ.get(ENV_DRY_RUN, "")
    return explicit or env_value.lower() in {"1", "true", "yes", "on"}


def config_dir(home: Path | None = None) -> Path:
    return (home or costguard_home()) / "config"


def rules_dir(home: Path | None = None) -> Path:
    return (home or costguard_home()) / "rules"


def hooks_dir(home: Path | None = None) -> Path:
    return (home or costguard_home()) / "hooks"


def bin_dir(home: Path | None = None) -> Path:
    return (home or costguard_home()) / "bin"


def logs_dir(home: Path | None = None) -> Path:
    return (home or costguard_home()) / "logs"


def cache_dir(home: Path | None = None) -> Path:
    return (home or costguard_home()) / "cache"


def response_cache_dir(home: Path | None = None) -> Path:
    return cache_dir(home) / "responses"


def vector_cache_dir(home: Path | None = None) -> Path:
    return (home or costguard_home()) / "vector_cache"


def backups_dir(home: Path | None = None) -> Path:
    return (home or costguard_home()) / "backups"


def run_dir(home: Path | None = None) -> Path:
    return (home or costguard_home()) / "run"


def settings_path(home: Path | None = None) -> Path:
    return config_dir(home) / "settings.yaml"


def env_path(home: Path | None = None) -> Path:
    return (home or costguard_home()) / ".env"


def db_path(home: Path | None = None) -> Path:
    return (home or costguard_home()) / "costguard.db"


def pricing_path(home: Path | None = None) -> Path:
    return config_dir(home) / "pricing.yaml"


def models_cache_path(home: Path | None = None) -> Path:
    return cache_dir(home) / "models.json"


def claude_settings_path(home: Path | None = None) -> Path:
    return (home or claude_home()) / "settings.json"


def usage_log_path(home: Path | None = None) -> Path:
    return logs_dir(home) / "usage.jsonl"


def events_log_path(home: Path | None = None) -> Path:
    return logs_dir(home) / "events.jsonl"


def pid_path(home: Path | None = None) -> Path:
    return run_dir(home) / "proxy.pid"


def template_root() -> Path:
    return Path(__file__).resolve().parent.parent / "templates"


def project_root() -> Path:
    return Path.cwd().resolve()
