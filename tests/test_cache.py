from __future__ import annotations

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

from costguard import cache as cache_mod, paths, proxy
from costguard.install import setup_costguard
from costguard.sqlite_store import usage_summary


def _post_to_proxy(home: Path, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.CostGuardHandler)
    server.costguard_home = home  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=json.dumps(payload),
            headers={"authorization": "Bearer sk-costguard-local", "content-type": "application/json"},
        )
        response = connection.getresponse()
        body = response.read()
        return response.status, json.loads(body)
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _install_with_cache(home: Path, monkeypatch, *, mode: str = "basic", store_content: bool = True) -> None:
    setup_costguard(
        tool="cline",
        non_interactive=True,
        openai_upstream_base_url="http://upstream.example/v1",
        openai_model_standard="real-standard",
    )
    monkeypatch.setenv("OPENAI_UPSTREAM_API_KEY", "test-upstream-key")
    monkeypatch.setenv("COSTGUARD_CACHE_STORE_CONTENT", str(store_content).lower())
    cache_mod.enable(mode, home)


def _fake_upstream(monkeypatch) -> dict[str, int]:
    calls = {"count": 0}

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: int) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200,
            json={
                "id": f"call-{calls['count']}",
                "model": json["model"],
                "choices": [{"message": {"role": "assistant", "content": "cached answer"}}],
            },
        )

    monkeypatch.setattr(proxy.httpx, "post", fake_post)
    return calls


def _chat_payload(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "model": "cg-standard",
        "messages": [{"role": "user", "content": "Say ok in one short sentence."}],
        "temperature": 0,
        "max_tokens": 20,
    }
    if extra:
        payload.update(extra)
    return payload


def test_basic_response_cache_reuses_identical_request(isolated_env, monkeypatch):
    home = isolated_env["home"]
    _install_with_cache(home, monkeypatch, store_content=True)
    calls = _fake_upstream(monkeypatch)

    first_status, first_body = _post_to_proxy(home, _chat_payload())
    second_status, second_body = _post_to_proxy(home, _chat_payload())

    assert first_status == 200
    assert second_status == 200
    assert first_body == second_body
    assert calls["count"] == 1
    summary = usage_summary("today", paths.db_path(home))
    assert summary["cache_misses"] == 1
    assert summary["cache_hits"] == 1
    assert summary["cache_hit_ratio"] == 0.5
    assert summary["cache_tokens_saved"] > 0
    assert summary["cache_cost_saved"] > 0
    cached_files = list(paths.response_cache_dir(home).glob("*.json"))
    assert len(cached_files) == 1
    cache_file_text = cached_files[0].read_text(encoding="utf-8")
    assert "test-upstream-key" not in cache_file_text
    assert "authorization" not in cache_file_text.lower()


def test_disabled_cache_does_not_reuse_response(isolated_env, monkeypatch):
    home = isolated_env["home"]
    setup_costguard(
        tool="cline",
        non_interactive=True,
        openai_upstream_base_url="http://upstream.example/v1",
        openai_model_standard="real-standard",
    )
    monkeypatch.setenv("OPENAI_UPSTREAM_API_KEY", "test-upstream-key")
    monkeypatch.setenv("COSTGUARD_CACHE_STORE_CONTENT", "true")
    calls = _fake_upstream(monkeypatch)

    _post_to_proxy(home, _chat_payload())
    _post_to_proxy(home, _chat_payload())

    assert calls["count"] == 2
    summary = usage_summary("today", paths.db_path(home))
    assert summary["cache_misses"] == 0
    assert summary["cache_hits"] == 0


def test_basic_cache_requires_explicit_content_storage(isolated_env, monkeypatch):
    home = isolated_env["home"]
    _install_with_cache(home, monkeypatch, store_content=False)
    calls = _fake_upstream(monkeypatch)

    _post_to_proxy(home, _chat_payload())
    _post_to_proxy(home, _chat_payload())

    assert calls["count"] == 2
    assert not list(paths.response_cache_dir(home).glob("*.json"))
    status = cache_mod.status(home)
    assert status["mode"] == "basic"
    assert status["functional"] is False


def test_streaming_requests_are_not_cached(isolated_env, monkeypatch):
    home = isolated_env["home"]
    _install_with_cache(home, monkeypatch, store_content=True)
    calls = _fake_upstream(monkeypatch)

    _post_to_proxy(home, _chat_payload({"stream": True}))
    _post_to_proxy(home, _chat_payload({"stream": True}))

    assert calls["count"] == 2
    summary = usage_summary("today", paths.db_path(home))
    assert summary["cache_misses"] == 0
    assert summary["cache_hits"] == 0


def test_cache_clear_can_preserve_pricing_cache(isolated_env):
    home = isolated_env["home"]
    paths.response_cache_dir(home).mkdir(parents=True)
    paths.vector_cache_dir(home).mkdir(parents=True)
    paths.models_cache_path(home).parent.mkdir(parents=True, exist_ok=True)
    (paths.response_cache_dir(home) / "entry.json").write_text("{}", encoding="utf-8")
    (paths.vector_cache_dir(home) / "index.json").write_text("{}", encoding="utf-8")
    paths.models_cache_path(home).write_text("[]", encoding="utf-8")

    cache_mod.clear(home, responses_only=True)

    assert not list(paths.response_cache_dir(home).glob("*.json"))
    assert (paths.vector_cache_dir(home) / "index.json").exists()
    assert paths.models_cache_path(home).exists()


def test_semantic_cache_status_is_experimental(isolated_env):
    home = isolated_env["home"]
    setup_costguard(tool="cline", non_interactive=True)

    status = cache_mod.enable("semantic", home)

    assert status["mode"] == "semantic"
    assert status["functional"] is False
    assert "experimental" in str(status["note"])
