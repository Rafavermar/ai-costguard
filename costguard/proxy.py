from __future__ import annotations

import json
import os
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from . import budget, config, headroom, paths, rules
from .sqlite_store import record_usage


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _append_path(base_url: str, path: str) -> str:
    base = base_url.rstrip("/") + "/"
    if base.endswith("/v1/") and path.startswith("/v1/"):
        path = path[4:]
    return urljoin(base, path.lstrip("/"))


def _client_for_path(path: str) -> str:
    if path.startswith("/v1/chat/completions"):
        return "cline"
    if path.startswith("/v1/messages"):
        return "claude-code"
    return "unknown"


def _limit_text(text: str, max_chars: int, max_lines: int) -> tuple[str, bool]:
    lines = text.splitlines()
    changed = False
    if max_lines and len(lines) > max_lines:
        text = "\n".join(lines[:max_lines])
        changed = True
    if max_chars and len(text) > max_chars:
        text = text[:max_chars]
        changed = True
    if changed:
        text += "\n[Cost Guard truncated oversized output]"
    return text, changed


def _limit_json_payload(payload: Any, max_chars: int, max_lines: int) -> tuple[Any, bool]:
    changed = False
    if isinstance(payload, dict):
        limited: dict[str, Any] = {}
        for key, value in payload.items():
            limited[key], child_changed = _limit_json_payload(value, max_chars, max_lines)
            changed = changed or child_changed
        return limited, changed
    if isinstance(payload, list):
        limited_list = []
        for value in payload:
            limited_value, child_changed = _limit_json_payload(value, max_chars, max_lines)
            limited_list.append(limited_value)
            changed = changed or child_changed
        return limited_list, changed
    if isinstance(payload, str):
        return _limit_text(payload, max_chars, max_lines)
    return payload, False


class CostGuardHandler(BaseHTTPRequestHandler):
    server_version = "CostGuard/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    @property
    def home(self) -> Path:
        return self.server.costguard_home  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        if self.path == "/health":
            _json_response(self, 200, {"status": "ok"})
            return
        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:
        env = config.load_env(self.home)
        local_key = env.get("COSTGUARD_LOCAL_API_KEY", "sk-costguard-local")
        auth = self.headers.get("authorization", "")
        api_key = self.headers.get("x-api-key", "")
        if auth != f"Bearer {local_key}" and api_key != local_key:
            _json_response(self, 401, {"error": "invalid Cost Guard API key"})
            return

        length = int(self.headers.get("content-length", "0") or 0)
        raw_body = self.rfile.read(length)
        body_text = raw_body.decode("utf-8", errors="replace")
        security_event = rules.has_secret_like_content(body_text)
        if security_event and env.get("COSTGUARD_ENABLE_SECRET_FILTER", "true").lower() == "true":
            _json_response(self, 400, {"error": "payload blocked by secret filter", "event": security_event})
            return

        try:
            payload = json.loads(body_text) if body_text else {}
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "request body must be JSON"})
            return

        client = _client_for_path(self.path)
        if client == "unknown":
            _json_response(self, 404, {"error": "unsupported path"})
            return

        requested_model = payload.get("model")
        model_alias = config.resolve_model_alias(str(requested_model) if requested_model else None, self.home)
        payload["model"] = config.model_for_client(model_alias, "cline" if client == "cline" else "claude-code", env, self.home)
        headroom_rule = None
        headroom_metrics: dict[str, Any] = {}
        headroom_input_before = json.dumps(payload)
        headroom_input_chars_before = len(headroom_input_before)
        headroom_input_tokens_before = budget.estimate_tokens(headroom_input_chars_before)
        try:
            headroom_result = headroom.transform_payload(payload, client, self.home)
        except RuntimeError as exc:
            _json_response(self, 500, {"error": str(exc)})
            return
        payload = headroom_result.payload
        body_text = json.dumps(payload)
        headroom_input_chars_after = len(body_text)
        headroom_input_tokens_after = budget.estimate_tokens(headroom_input_chars_after)
        if headroom_result.applied:
            headroom_rule = f"headroom:{headroom_result.adapter}"
            headroom_tokens_saved = max(0, headroom_input_tokens_before - headroom_input_tokens_after)
            headroom_metrics = {
                "headroom_applied": True,
                "headroom_adapter": headroom_result.adapter,
                "headroom_input_chars_before": headroom_input_chars_before,
                "headroom_input_chars_after": headroom_input_chars_after,
                "headroom_input_tokens_before": headroom_input_tokens_before,
                "headroom_input_tokens_after": headroom_input_tokens_after,
                "headroom_tokens_saved": headroom_tokens_saved,
                "headroom_reduction_ratio": (
                    headroom_tokens_saved / headroom_input_tokens_before if headroom_input_tokens_before else 0.0
                ),
            }

        input_chars = len(body_text)
        estimated_tokens = budget.estimate_tokens(input_chars)
        estimated_cost = budget.estimate_cost(model_alias, estimated_tokens, self.home)
        decision = budget.check_budget(model_alias, estimated_cost, self.home)
        if decision.blocked:
            record_usage(
                {
                    "client": client,
                    "model_alias": model_alias,
                    "upstream": "blocked",
                    "input_chars": input_chars,
                    "output_chars": 0,
                    "estimated_tokens": estimated_tokens,
                    "estimated_cost": estimated_cost,
                    "rule_applied": headroom_rule,
                    "budget_action": decision.action,
                    "active_budget": decision.mode,
                    "security_event": security_event,
                    **headroom_metrics,
                },
                paths.db_path(self.home),
            )
            _json_response(self, 402, {"error": decision.reason, "budget_action": decision.action})
            return

        if client == "cline":
            upstream = env.get("OPENAI_UPSTREAM_BASE_URL", "")
            upstream_key = env.get("OPENAI_UPSTREAM_API_KEY", "")
            headers = {"authorization": f"Bearer {upstream_key}", "content-type": "application/json"}
        else:
            upstream = env.get("ANTHROPIC_UPSTREAM_BASE_URL", "")
            upstream_key = env.get("ANTHROPIC_UPSTREAM_API_KEY", "")
            headers = {
                "x-api-key": upstream_key,
                "anthropic-version": self.headers.get("anthropic-version", "2023-06-01"),
                "content-type": "application/json",
            }

        if not upstream or not upstream_key:
            _json_response(self, 502, {"error": f"missing upstream configuration for {client}"})
            return

        upstream_url = _append_path(upstream, self.path)
        try:
            response = httpx.post(upstream_url, json=payload, headers=headers, timeout=120)
        except httpx.HTTPError as exc:
            _json_response(self, 502, {"error": f"upstream request failed: {exc}"})
            return

        response_text = response.text
        output_chars = len(response_text)
        final_body = response.content
        output_reduced = False
        if env.get("COSTGUARD_ENABLE_OUTPUT_LIMITS", "true").lower() == "true":
            max_chars = int(env.get("COSTGUARD_MAX_OUTPUT_CHARS", "20000") or 20000)
            max_lines = int(env.get("COSTGUARD_MAX_OUTPUT_LINES", "500") or 500)
            try:
                response_payload = response.json()
                limited_payload, changed = _limit_json_payload(response_payload, max_chars, max_lines)
                if changed:
                    final_body = json.dumps(limited_payload).encode("utf-8")
                    output_reduced = True
            except ValueError:
                limited_text, changed = _limit_text(response_text, max_chars, max_lines)
                if changed:
                    final_body = limited_text.encode("utf-8")
                    output_reduced = True

        record_usage(
            {
                "client": client,
                "model_alias": model_alias,
                "upstream": upstream,
                "input_chars": input_chars,
                "output_chars": output_chars,
                "estimated_tokens": budget.estimate_tokens(input_chars, output_chars),
                "estimated_cost": budget.estimate_cost(
                    model_alias,
                    budget.estimate_tokens(input_chars),
                    self.home,
                    output_tokens=budget.estimate_tokens(output_chars),
                ),
                "rule_applied": headroom_rule,
                "budget_action": decision.action,
                "active_budget": decision.mode,
                "security_event": security_event,
                "output_reduced": output_reduced,
                **headroom_metrics,
            },
            paths.db_path(self.home),
        )

        self.send_response(response.status_code)
        self.send_header("content-type", response.headers.get("content-type", "application/json"))
        self.send_header("content-length", str(len(final_body)))
        self.end_headers()
        self.wfile.write(final_body)


def start_proxy(host: str = "127.0.0.1", port: int = 4040, home: Path | None = None) -> None:
    home = home or paths.costguard_home()
    if host != "127.0.0.1":
        print(f"WARNING: Cost Guard is listening on {host}. Default is 127.0.0.1.")
    paths.run_dir(home).mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), CostGuardHandler)
    server.costguard_home = home  # type: ignore[attr-defined]
    paths.pid_path(home).write_text(str(os.getpid()), encoding="utf-8")
    try:
        server.serve_forever()
    finally:
        paths.pid_path(home).unlink(missing_ok=True)
        server.server_close()


def stop_from_pid(home: Path | None = None) -> str:
    from .uninstall import stop_proxy

    return stop_proxy(home)
