from __future__ import annotations

import http.client
import json
import time
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


def test_secret_like_payload_is_not_cached(isolated_env, monkeypatch):
    home = isolated_env["home"]
    _install_with_cache(home, monkeypatch, store_content=True)
    calls = _fake_upstream(monkeypatch)

    status, body = _post_to_proxy(
        home,
        _chat_payload({"messages": [{"role": "user", "content": "api_key=abcdefghijklmnop"}]}),
    )

    assert status == 400
    assert "payload blocked by secret filter" in body["error"]
    assert calls["count"] == 0
    assert not list(paths.response_cache_dir(home).glob("*.json"))


def test_expired_cache_entry_generates_miss(isolated_env, monkeypatch):
    home = isolated_env["home"]
    _install_with_cache(home, monkeypatch, store_content=True)
    monkeypatch.setenv("COSTGUARD_CACHE_TTL_SECONDS", "1")
    calls = _fake_upstream(monkeypatch)

    _post_to_proxy(home, _chat_payload())
    cached_file = next(paths.response_cache_dir(home).glob("*.json"))
    cached_entry = json.loads(cached_file.read_text(encoding="utf-8"))
    cached_entry["created_at"] = time.time() - 10
    cached_entry["accessed_at"] = time.time() - 10
    cached_file.write_text(json.dumps(cached_entry), encoding="utf-8")
    _post_to_proxy(home, _chat_payload())

    assert calls["count"] == 2
    summary = usage_summary("today", paths.db_path(home))
    assert summary["cache_hits"] == 0
    assert summary["cache_misses"] == 2


def test_cache_clear_expired_removes_only_expired_responses(isolated_env, monkeypatch):
    home = isolated_env["home"]
    monkeypatch.setenv("COSTGUARD_CACHE_STORE_CONTENT", "true")
    monkeypatch.setenv("COSTGUARD_CACHE_TTL_SECONDS", "1")
    fresh = cache_mod.store_response(
        key="fresh",
        body=b"fresh",
        status_code=200,
        content_type="application/json",
        output_chars=5,
        estimated_tokens=1,
        estimated_cost=0.1,
        client="cline",
        path="/v1/chat/completions",
        model_alias="cg-standard",
        upstream_model="real-standard",
        home=home,
    )
    expired = cache_mod.store_response(
        key="expired",
        body=b"expired",
        status_code=200,
        content_type="application/json",
        output_chars=7,
        estimated_tokens=2,
        estimated_cost=0.2,
        client="cline",
        path="/v1/chat/completions",
        model_alias="cg-standard",
        upstream_model="real-standard",
        home=home,
    )
    assert fresh is not None
    assert expired is not None
    expired_entry = json.loads(expired.read_text(encoding="utf-8"))
    expired_entry["created_at"] = time.time() - 10
    expired_entry["accessed_at"] = time.time() - 10
    expired.write_text(json.dumps(expired_entry), encoding="utf-8")

    status = cache_mod.clear(home, expired_only=True)

    assert status["expired_entries"] == 1
    assert fresh.exists()
    assert not expired.exists()


def test_max_entries_evicts_lru_response_entries(isolated_env, monkeypatch):
    home = isolated_env["home"]
    monkeypatch.setenv("COSTGUARD_CACHE_STORE_CONTENT", "true")
    monkeypatch.setenv("COSTGUARD_CACHE_MAX_ENTRIES", "1")
    cache_mod.store_response(
        key="old",
        body=b"old",
        status_code=200,
        content_type="application/json",
        output_chars=3,
        estimated_tokens=1,
        estimated_cost=0.1,
        client="cline",
        path="/v1/chat/completions",
        model_alias="cg-standard",
        upstream_model="real-standard",
        home=home,
    )
    time.sleep(0.01)
    cache_mod.store_response(
        key="new",
        body=b"new",
        status_code=200,
        content_type="application/json",
        output_chars=3,
        estimated_tokens=1,
        estimated_cost=0.1,
        client="cline",
        path="/v1/chat/completions",
        model_alias="cg-standard",
        upstream_model="real-standard",
        home=home,
    )

    cached_names = {path.stem for path in paths.response_cache_dir(home).glob("*.json")}
    assert cached_names == {"new"}
    status = cache_mod.status(home)
    assert status["max_entries"] == 1
    assert status["eviction_policy"] == "lru"


def test_max_size_evicts_response_entries(isolated_env, monkeypatch):
    home = isolated_env["home"]
    monkeypatch.setenv("COSTGUARD_CACHE_STORE_CONTENT", "true")
    monkeypatch.setenv("COSTGUARD_CACHE_MAX_SIZE_MB", "0.003")
    for index in range(3):
        cache_mod.store_response(
            key=f"entry-{index}",
            body=b"x" * 2048,
            status_code=200,
            content_type="application/json",
            output_chars=2048,
            estimated_tokens=512,
            estimated_cost=0.1,
            client="cline",
            path="/v1/chat/completions",
            model_alias="cg-standard",
            upstream_model="real-standard",
            home=home,
        )

    status = cache_mod.status(home)
    assert status["response_size_bytes"] <= status["max_size_bytes"]
    assert status["response_entries"] < 3


def test_cache_status_shows_limits_and_policy(isolated_env, monkeypatch):
    home = isolated_env["home"]
    monkeypatch.setenv("COSTGUARD_CACHE_MAX_ENTRIES", "25")
    monkeypatch.setenv("COSTGUARD_CACHE_MAX_SIZE_MB", "5")
    monkeypatch.setenv("COSTGUARD_CACHE_EVICTION_POLICY", "fifo")

    status = cache_mod.status(home)

    assert status["max_entries"] == 25
    assert status["max_size_mb"] == 5.0
    assert status["max_size_bytes"] == 5 * 1024 * 1024
    assert status["eviction_policy"] == "fifo"
    assert "expired_entries" in status
    assert "evicted_entries" in status


def test_semantic_cache_status_is_experimental(isolated_env):
    home = isolated_env["home"]
    setup_costguard(tool="cline", non_interactive=True)

    status = cache_mod.enable("semantic", home)

    assert status["mode"] == "semantic"
    assert status["functional"] is False
    assert "experimental" in str(status["note"])
