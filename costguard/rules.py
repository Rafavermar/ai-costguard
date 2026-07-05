from __future__ import annotations

import fnmatch
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths
from .utils import read_yaml


DEFAULT_RULES = {
    "blocked_paths": [
        ".env",
        "*.pem",
        "*.key",
        "id_rsa",
        "terraform.tfstate",
        "*.tfvars",
        "*secret*",
        "*password*",
        "*credential*",
        "*token*",
    ],
    "blocked_commands": [
        {"pattern": r"\benv\b", "reason": "Environment variables may contain secrets."},
        {"pattern": r"\bprintenv\b", "reason": "Environment variables may contain secrets."},
        {"pattern": r"cat\s+\.env", "reason": "Reading .env is blocked."},
        {
            "pattern": r"cat\s+.*(key|secret|token|credential).*",
            "reason": "Secret-like file access is blocked.",
        },
    ],
    "rewrite_commands": [
        {
            "pattern": r"^git diff$",
            "replacement": "git diff --stat && git diff --name-only",
            "reason": "Avoid sending a full diff before seeing the summary.",
        },
        {
            "pattern": r"^find \.$",
            "replacement": "find . -maxdepth 3",
            "reason": "Limit full repository scan.",
        },
        {
            "pattern": r"\bpytest\b",
            "pipe": r"grep -A 10 -B 4 -E 'FAIL|FAILED|ERROR|Exception|Traceback|AssertionError' | head -250",
            "reason": "Return only failing test output.",
        },
        {
            "pattern": r"\bnpm test\b",
            "pipe": r"grep -A 10 -B 4 -E 'FAIL|FAILED|ERROR|Exception|Traceback|AssertionError' | head -250",
            "reason": "Return only failing test output.",
        },
        {
            "pattern": r"\bmvn test\b",
            "pipe": r"grep -A 10 -B 4 -E 'FAIL|FAILED|ERROR|Exception|Traceback|AssertionError' | head -250",
            "reason": "Return only failing test output.",
        },
        {
            "pattern": r"\bgradle test\b",
            "pipe": r"grep -A 10 -B 4 -E 'FAIL|FAILED|ERROR|Exception|Traceback|AssertionError' | head -250",
            "reason": "Return only failing test output.",
        },
    ],
    "log_rules": [
        {
            "pattern": r".*\.log",
            "action": "tail",
            "lines": 300,
            "reason": "Avoid sending complete log files.",
        }
    ],
    "output_limits": {"max_chars": 20000, "max_lines": 500},
}


@dataclass(frozen=True)
class RuleResult:
    action: str
    reason: str = ""
    command: str | None = None
    origin: str | None = None
    rule: str | None = None

    @property
    def allowed(self) -> bool:
        return self.action == "allow"


def _merge_rules(*rulesets: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "blocked_paths": [],
        "blocked_commands": [],
        "rewrite_commands": [],
        "log_rules": [],
        "output_limits": dict(DEFAULT_RULES["output_limits"]),
    }
    for ruleset in rulesets:
        for key in ("blocked_paths", "blocked_commands", "rewrite_commands", "log_rules"):
            merged[key].extend(ruleset.get(key, []) or [])
        if "output_limits" in ruleset:
            merged["output_limits"].update(ruleset.get("output_limits") or {})
    return merged


def load_rules(home: Path | None = None, project: Path | None = None) -> dict[str, Any]:
    home = home or paths.costguard_home()
    default_path = paths.rules_dir(home) / "default.yaml"
    user_path = paths.rules_dir(home) / "user.yaml"
    project_path = (project or Path.cwd()) / ".costguard" / "rules.yaml"
    default_rules = read_yaml(default_path, DEFAULT_RULES)
    user_rules = read_yaml(user_path, {})
    project_rules = read_yaml(project_path, {}) if project_path.exists() else {}
    return _merge_rules(default_rules, user_rules, project_rules)


def list_rules(home: Path | None = None, project: Path | None = None) -> list[dict[str, str]]:
    home = home or paths.costguard_home()
    project = project or Path.cwd()
    sources = [
        ("default", paths.rules_dir(home) / "default.yaml"),
        ("user", paths.rules_dir(home) / "user.yaml"),
        ("project", project / ".costguard" / "rules.yaml"),
    ]
    rows: list[dict[str, str]] = []
    for origin, path in sources:
        data = read_yaml(path, {}) if path.exists() else {}
        for key in ("blocked_paths", "blocked_commands", "rewrite_commands", "log_rules"):
            for item in data.get(key, []) or []:
                if isinstance(item, str):
                    label = item
                else:
                    label = item.get("pattern") or item.get("replacement") or str(item)
                rows.append({"origin": origin, "type": key, "rule": label})
    return rows


def _command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def _path_blocked(path_value: str, ruleset: dict[str, Any]) -> str | None:
    normalized = path_value.replace("\\", "/")
    base = Path(normalized).name
    for pattern in ruleset.get("blocked_paths", []):
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(base, pattern):
            return f"Path matches blocked pattern: {pattern}"
    return None


def evaluate_path(path_value: str, home: Path | None = None, project: Path | None = None) -> RuleResult:
    ruleset = load_rules(home, project)
    reason = _path_blocked(path_value, ruleset)
    if reason:
        return RuleResult(action="block", reason=reason, rule=path_value)
    return RuleResult(action="allow")


def evaluate_command(command: str, home: Path | None = None, project: Path | None = None) -> RuleResult:
    ruleset = load_rules(home, project)

    for token in _command_tokens(command):
        reason = _path_blocked(token, ruleset)
        if reason:
            return RuleResult(action="block", reason=reason, command=command, rule=token)

    for rule in ruleset.get("blocked_commands", []):
        pattern = rule.get("pattern", "")
        if pattern and re.search(pattern, command):
            return RuleResult(
                action="block",
                reason=rule.get("reason", "Command blocked by Cost Guard."),
                command=command,
                rule=pattern,
            )

    for rule in ruleset.get("rewrite_commands", []):
        pattern = rule.get("pattern", "")
        if pattern and re.search(pattern, command):
            if rule.get("replacement"):
                replacement = rule["replacement"]
            elif rule.get("pipe"):
                replacement = f"{command} | {rule['pipe']}"
            else:
                replacement = command
            return RuleResult(
                action="rewrite",
                reason=rule.get("reason", "Command rewritten by Cost Guard."),
                command=replacement,
                rule=pattern,
            )

    return RuleResult(action="allow", command=command)


def has_secret_like_content(text: str) -> str | None:
    patterns = {
        "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        "api key assignment": r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, text):
            return label
    return None
