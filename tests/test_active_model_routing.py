from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from typing import Any

import httpx
from typer.testing import CliRunner

from costguard import config, proxy
from costguard.cli import app
from costguard.install import setup_costguard


def _proxy_request(home, payload: dict[str, Any], monkeypatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: int) -> httpx.Response:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(proxy.httpx, "post", fake_post)
    server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.CostGuardHandler)
    server.costguard_home = home  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=json.dumps(payload),
            headers={"authorization": "Bearer sk-costguard-local", "content-type": "application/json"},
        )
        response = connection.getresponse()
        response_body = response.read()
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert json.loads(response_body) == {"ok": True}
    return captured


def test_cg_active_tracks_costguard_use_command(isolated_env):
    setup_costguard(
        tool="cline",
        non_interactive=True,
        openai_model_cheap="real-cheap",
        openai_model_standard="real-standard",
        openai_model_strong="real-strong",
    )
    env = config.load_env(isolated_env["home"])
    runner = CliRunner()

    result = runner.invoke(app, ["use", "cheap"])
    assert result.exit_code == 0
    assert config.resolve_model_alias("cg-active", isolated_env["home"]) == "cg-cheap"
    assert config.model_for_client("cg-active", "cline", env, isolated_env["home"]) == "real-cheap"

    result = runner.invoke(app, ["use", "standard"])
    assert result.exit_code == 0
    assert config.resolve_model_alias("cg-active", isolated_env["home"]) == "cg-standard"
    assert config.model_for_client("cg-active", "cline", env, isolated_env["home"]) == "real-standard"

    result = runner.invoke(app, ["use", "strong"])
    assert result.exit_code == 0
    assert config.resolve_model_alias("cg-active", isolated_env["home"]) == "cg-strong"
    assert config.model_for_client("cg-active", "cline", env, isolated_env["home"]) == "real-strong"


def test_proxy_resolves_cg_active_and_keeps_fixed_alias(isolated_env, monkeypatch):
    setup_costguard(
        tool="cline",
        non_interactive=True,
        openai_upstream_base_url="http://upstream.example/v1",
        openai_model_cheap="real-cheap",
        openai_model_standard="real-standard",
    )
    monkeypatch.setenv("OPENAI_UPSTREAM_API_KEY", "test-key")
    config.set_active_model("cheap", isolated_env["home"])

    dynamic = _proxy_request(
        isolated_env["home"],
        {"model": "cg-active", "messages": [{"role": "user", "content": "hello"}]},
        monkeypatch,
    )
    fixed = _proxy_request(
        isolated_env["home"],
        {"model": "cg-standard", "messages": [{"role": "user", "content": "hello"}]},
        monkeypatch,
    )

    assert dynamic["json"]["model"] == "real-cheap"
    assert fixed["json"]["model"] == "real-standard"
