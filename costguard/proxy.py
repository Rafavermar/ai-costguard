from __future__ import annotations

import json
import os
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from . import budget, cache as cache_mod, config, headroom, paths, rules
from .sqlite_store import record_usage
from .utils import parse_bool


HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


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
    path_only = urlsplit(path).path
    if path_only.startswith("/v1/chat/completions"):
        return "cline"
    if path_only.startswith("/v1/messages"):
        return "claude-code"
    return "unknown"


def _authorized(headers: Any, local_key: str) -> bool:
    auth = headers.get("authorization", "")
    api_key = headers.get("x-api-key", "")
    return auth == f"Bearer {local_key}" or api_key == local_key


def _auth_value(api_key: str, scheme: str) -> str:
    scheme = scheme.strip()
    return f"{scheme} {api_key}" if scheme else api_key


def _anthropic_headers(request_headers: Any, env: dict[str, str], upstream_key: str) -> dict[str, str]:
    auth_header = env.get("ANTHROPIC_UPSTREAM_AUTH_HEADER", "x-api-key").strip() or "x-api-key"
    auth_scheme = env.get("ANTHROPIC_UPSTREAM_AUTH_SCHEME", "")
    headers = {
        auth_header: _auth_value(upstream_key, auth_scheme),
        "content-type": "application/json",
    }
    forwarded_any_version = False
    for key, value in request_headers.items():
        lower = key.lower()
        if lower == "anthropic-version":
            forwarded_any_version = True
        if lower.startswith("anthropic-") or lower.startswith("x-claude-code-"):
            headers[key] = value
    if not forwarded_any_version:
        headers["anthropic-version"] = "2023-06-01"
    return headers


def _model_catalog() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {"id": config.ACTIVE_MODEL_ALIAS, "object": "model", "display_name": "Cost Guard active model"},
            {"id": "cg-cheap", "object": "model", "display_name": "Cost Guard cheap"},
            {"id": "cg-standard", "object": "model", "display_name": "Cost Guard standard"},
            {"id": "cg-strong", "object": "model", "display_name": "Cost Guard strong"},
        ],
    }


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
        path_only = urlsplit(self.path).path
        if path_only == "/health":
            _json_response(self, 200, {"status": "ok"})
            return
        if path_only == "/v1/models":
            env = config.load_env(self.home)
            local_key = env.get("COSTGUARD_LOCAL_API_KEY", "sk-costguard-local")
            if not _authorized(self.headers, local_key):
                _json_response(self, 401, {"error": "invalid Cost Guard API key"})
                return
            _json_response(self, 200, _model_catalog())
            return
        _json_response(self, 404, {"error": "not found"})

    def do_HEAD(self) -> None:
        path_only = urlsplit(self.path).path
        if path_only in {"/", "/health", "/v1/messages", "/v1/models"}:
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        env = config.load_env(self.home)
        local_key = env.get("COSTGUARD_LOCAL_API_KEY", "sk-costguard-local")
        if not _authorized(self.headers, local_key):
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
                "headroom_candidate_message_count": headroom_result.candidate_message_count,
                "headroom_compressible_message_count": headroom_result.compressible_message_count,
                "headroom_protected_message_count": headroom_result.protected_message_count,
                "headroom_transforms_applied": headroom_result.transforms_applied,
                "headroom_roles_seen": headroom_result.roles_seen,
                "headroom_roles_compressed": headroom_result.roles_compressed,
            }
        elif headroom_result.skipped_reason:
            headroom_tokens_saved = max(0, headroom_input_tokens_before - headroom_input_tokens_after)
            headroom_metrics = {
                "headroom_skipped": True,
                "headroom_skip_reason": headroom_result.skipped_reason,
            }
            if headroom_result.skipped_reason != headroom.SKIPPED_DISABLED:
                headroom_metrics.update(
                    {
                        "headroom_adapter": headroom_result.adapter,
                        "headroom_input_chars_before": headroom_input_chars_before,
                        "headroom_input_chars_after": headroom_input_chars_after,
                        "headroom_input_tokens_before": headroom_input_tokens_before,
                        "headroom_input_tokens_after": headroom_input_tokens_after,
                        "headroom_tokens_saved": headroom_tokens_saved,
                        "headroom_reduction_ratio": (
                            headroom_tokens_saved / headroom_input_tokens_before
                            if headroom_input_tokens_before
                            else 0.0
                        ),
                        "headroom_candidate_message_count": headroom_result.candidate_message_count,
                        "headroom_compressible_message_count": headroom_result.compressible_message_count,
                        "headroom_protected_message_count": headroom_result.protected_message_count,
                        "headroom_transforms_applied": headroom_result.transforms_applied,
                        "headroom_roles_seen": headroom_result.roles_seen,
                        "headroom_roles_compressed": headroom_result.roles_compressed,
                    }
                )

        input_chars = len(body_text)
        estimated_tokens = budget.estimate_tokens(input_chars)
        estimated_cost = budget.estimate_cost(model_alias, estimated_tokens, self.home)

        if client == "cline":
            upstream = env.get("OPENAI_UPSTREAM_BASE_URL", "")
            upstream_key = env.get("OPENAI_UPSTREAM_API_KEY", "")
            headers = {"authorization": f"Bearer {upstream_key}", "content-type": "application/json"}
        else:
            upstream = env.get("ANTHROPIC_UPSTREAM_BASE_URL", "")
            upstream_key = env.get("ANTHROPIC_UPSTREAM_API_KEY", "")
            headers = _anthropic_headers(self.headers, env, upstream_key)

        if not upstream or not upstream_key:
            _json_response(self, 502, {"error": f"missing upstream configuration for {client}"})
            return

        cache_mode = config.cache_mode(self.home)
        cache_attempt = False
        cache_key_value: str | None = None
        if cache_mode == "basic" and cache_mod.store_content_enabled(env):
            cacheable, _reason = cache_mod.request_cacheable(payload, security_event)
            if cacheable:
                cache_attempt = True
                cache_key_value = cache_mod.cache_key(
                    client=client,
                    path=self.path,
                    model_alias=model_alias,
                    upstream_model=str(payload.get("model", "")),
                    upstream_base_url=upstream,
                    payload=payload,
                )
                cached_response = cache_mod.load_response(cache_key_value, self.home, env)
                if cached_response is not None:
                    cached_body = bytes(cached_response["body"])
                    saved_tokens = int(cached_response.get("estimated_tokens", 0))
                    saved_cost = float(cached_response.get("estimated_cost", 0.0))
                    record_usage(
                        {
                            "client": client,
                            "model_alias": model_alias,
                            "upstream": "cache",
                            "input_chars": input_chars,
                            "output_chars": int(cached_response.get("output_chars", len(cached_body))),
                            "estimated_tokens": 0,
                            "estimated_cost": 0.0,
                            "rule_applied": headroom_rule,
                            "budget_action": "allow",
                            "active_budget": config.load_settings(self.home).get("budget", {}).get("mode", "warn"),
                            "security_event": security_event,
                            "cache_hit": True,
                            "cache_mode": cache_mode,
                            "cache_tokens_saved": saved_tokens,
                            "cache_cost_saved": saved_cost,
                            **headroom_metrics,
                        },
                        paths.db_path(self.home),
                    )
                    self.send_response(int(cached_response["status_code"]))
                    self.send_header("content-type", str(cached_response["content_type"]))
                    self.send_header("content-length", str(len(cached_body)))
                    self.end_headers()
                    self.wfile.write(cached_body)
                    return

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

        upstream_url = _append_path(upstream, self.path)
        if client == "claude-code" and parse_bool(payload.get("stream"), default=False):
            self._forward_streaming_response(
                upstream_url=upstream_url,
                payload=payload,
                headers=headers,
                input_chars=input_chars,
                model_alias=model_alias,
                upstream=upstream,
                decision=decision,
                security_event=security_event,
                headroom_rule=headroom_rule,
                headroom_metrics=headroom_metrics,
            )
            return

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

        total_tokens = budget.estimate_tokens(input_chars, output_chars)
        total_cost = budget.estimate_cost(
            model_alias,
            budget.estimate_tokens(input_chars),
            self.home,
            output_tokens=budget.estimate_tokens(output_chars),
        )
        content_type = response.headers.get("content-type", "application/json")
        if cache_attempt and cache_key_value:
            cache_mod.store_response(
                key=cache_key_value,
                body=final_body,
                status_code=response.status_code,
                content_type=content_type,
                output_chars=len(final_body.decode("utf-8", errors="replace")),
                estimated_tokens=total_tokens,
                estimated_cost=total_cost,
                client=client,
                path=self.path,
                model_alias=model_alias,
                upstream_model=str(payload.get("model", "")),
                home=self.home,
                env=env,
            )

        record_usage(
            {
                "client": client,
                "model_alias": model_alias,
                "upstream": upstream,
                "input_chars": input_chars,
                "output_chars": output_chars,
                "estimated_tokens": total_tokens,
                "estimated_cost": total_cost,
                "rule_applied": headroom_rule,
                "budget_action": decision.action,
                "active_budget": decision.mode,
                "security_event": security_event,
                "output_reduced": output_reduced,
                "cache_miss": cache_attempt,
                "cache_mode": cache_mode if cache_attempt else None,
                **headroom_metrics,
            },
            paths.db_path(self.home),
        )

        self.send_response(response.status_code)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(final_body)))
        self.end_headers()
        self.wfile.write(final_body)

    def _send_upstream_headers(self, status_code: int, headers: httpx.Headers, default_content_type: str) -> str:
        content_type = headers.get("content-type", default_content_type)
        self.send_response(status_code)
        self.send_header("content-type", content_type)
        for key, value in headers.items():
            lower = key.lower()
            if lower in HOP_BY_HOP_HEADERS or lower == "content-type":
                continue
            self.send_header(key, value)
        self.send_header("connection", "close")
        self.end_headers()
        self.close_connection = True
        return content_type

    def _forward_streaming_response(
        self,
        upstream_url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        input_chars: int,
        model_alias: str,
        upstream: str,
        decision: budget.BudgetDecision,
        security_event: str | None,
        headroom_rule: str | None,
        headroom_metrics: dict[str, Any],
    ) -> None:
        chunks: list[bytes] = []
        status_code = 502
        try:
            with httpx.stream("POST", upstream_url, json=payload, headers=headers, timeout=120) as response:
                status_code = response.status_code
                self._send_upstream_headers(status_code, response.headers, "text/event-stream")
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except httpx.HTTPError as exc:
            if not chunks:
                _json_response(self, 502, {"error": f"upstream request failed: {exc}"})
            return

        response_text = b"".join(chunks).decode("utf-8", errors="replace")
        output_chars = len(response_text)
        total_tokens = budget.estimate_tokens(input_chars, output_chars)
        total_cost = budget.estimate_cost(
            model_alias,
            budget.estimate_tokens(input_chars),
            self.home,
            output_tokens=budget.estimate_tokens(output_chars),
        )
        record_usage(
            {
                "client": "claude-code",
                "model_alias": model_alias,
                "upstream": upstream,
                "input_chars": input_chars,
                "output_chars": output_chars,
                "estimated_tokens": total_tokens,
                "estimated_cost": total_cost,
                "rule_applied": headroom_rule,
                "budget_action": decision.action,
                "active_budget": decision.mode,
                "security_event": security_event,
                "output_reduced": False,
                "cache_miss": False,
                "cache_mode": None,
                **headroom_metrics,
            },
            paths.db_path(self.home),
        )


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
