from __future__ import annotations

import http.client
import json
import sys
import threading
import types
from http.server import ThreadingHTTPServer
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from costguard import headroom, proxy, usage as usage_mod
from costguard.cli import app
from costguard.install import setup_costguard


def _install_fake_headroom(monkeypatch: pytest.MonkeyPatch, fn_name: str = "compress_payload") -> types.ModuleType:
    module = types.ModuleType("headroom")

    def compress_payload(payload: dict[str, Any], client: str | None = None, home: str | None = None) -> dict[str, Any]:
        payload["messages"][0]["content"] = "short context"
        payload["headroom_meta"] = {"client": client, "home_seen": bool(home)}
        return payload

    setattr(module, fn_name, compress_payload)
    monkeypatch.setitem(sys.modules, "headroom", module)
    return module


def _install_fake_headroom_compress(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("headroom")

    class CompressResult:
        def __init__(self, messages: list[dict[str, Any]]) -> None:
            self.messages = messages
            self.tokens_before = 100
            self.tokens_after = 20
            self.tokens_saved = 80
            self.compression_ratio = 0.8

    def compress(messages: list[dict[str, Any]], model: str) -> CompressResult:
        assert model == "real-model"
        module.calls.append({"messages": messages, "model": model})  # type: ignore[attr-defined]
        compressed = [dict(message) for message in messages]
        compressed[0]["content"] = "short context"
        return CompressResult(compressed)

    module.calls = []  # type: ignore[attr-defined]
    module.compress = compress  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "headroom", module)
    return module


def _install_no_change_headroom_compress(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("headroom")

    class CompressResult:
        def __init__(self, messages: list[dict[str, Any]]) -> None:
            self.messages = messages

    def compress(messages: list[dict[str, Any]], model: str) -> CompressResult:
        module.calls.append({"messages": messages, "model": model})  # type: ignore[attr-defined]
        return CompressResult([dict(message) for message in messages])

    module.calls = []  # type: ignore[attr-defined]
    module.compress = compress  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "headroom", module)
    return module


def _install_shape_aware_headroom_compress(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("headroom")

    def compress(value: Any, model: str) -> Any:
        module.calls.append({"value": value, "model": model})  # type: ignore[attr-defined]
        if isinstance(value, dict):
            payload = json.loads(json.dumps(value))
            payload["messages"][0]["content"] = "short context"
            return {"payload": payload, "tokens_saved": 80}
        if isinstance(value, list):
            messages = json.loads(json.dumps(value))
            messages[0]["content"] = "short context"
            return {"compressed_messages": messages, "tokens_saved": 80}
        if isinstance(value, str):
            return {"compressed_text": "short context", "tokens_saved": 80}
        return {"tokens_saved": 0}

    module.calls = []  # type: ignore[attr-defined]
    module.compress = compress  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "headroom", module)
    return module


def _install_metadata_only_headroom_compress(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("headroom")

    def compress(value: Any, model: str) -> dict[str, Any]:
        module.calls.append({"value": value, "model": model})  # type: ignore[attr-defined]
        return {"changed": False, "tokens_saved": 0}

    module.calls = []  # type: ignore[attr-defined]
    module.compress = compress  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "headroom", module)
    return module


def _install_introspective_headroom_compress(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("headroom")

    class CompressResult:
        def __init__(self, messages: Any) -> None:
            self.messages = messages
            self.tokens_before = 500
            self.tokens_after = 300
            self.tokens_saved = 200
            self.compression_ratio = 0.4
            self.transforms_applied = ["smart_crusher", "kompress"]
            self.compressed = True
            self.noop_reason = ""
            self.metadata = {"safe_metric": 1}

    def compress(messages: Any, model: str, **kwargs: Any) -> CompressResult:
        module.calls.append({"messages": messages, "model": model, "kwargs": kwargs})  # type: ignore[attr-defined]
        if not isinstance(messages, list):
            return CompressResult(messages)
        compressed = json.loads(json.dumps(messages))
        compressed[0]["content"] = "short context"
        return CompressResult(compressed)

    module.calls = []  # type: ignore[attr-defined]
    module.compress = compress  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "headroom", module)
    return module


def test_headroom_enable_and_transform_payload(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True)
    _install_fake_headroom(monkeypatch)

    status = headroom.enable(isolated_env["home"])
    result = headroom.transform_payload(
        {"model": "cg-standard", "messages": [{"role": "user", "content": "very long context"}]},
        "cline",
        isolated_env["home"],
    )

    assert status["active"] is True
    assert status["adapter"] == "compress_payload"
    assert status["install_hint"] == "n/a"
    assert result.applied is True
    assert result.adapter == "compress_payload"
    assert result.payload["messages"][0]["content"] == "short context"
    assert result.payload["headroom_meta"]["client"] == "cline"


def test_headroom_supports_real_compress_api(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True)
    _install_fake_headroom_compress(monkeypatch)

    status = headroom.enable(isolated_env["home"])
    result = headroom.transform_payload(
        {"model": "real-model", "messages": [{"role": "user", "content": "very long context"}]},
        "cline",
        isolated_env["home"],
    )

    assert status["active"] is True
    assert status["adapter"] == "compress"
    assert result.applied is True
    assert result.adapter == "compress"
    assert result.payload["messages"][0]["content"] == "short context"


def test_headroom_enable_rejects_incompatible_module(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True)
    monkeypatch.setitem(sys.modules, "headroom", types.ModuleType("headroom"))

    with pytest.raises(RuntimeError, match="incompatible"):
        headroom.enable(isolated_env["home"])


def test_setup_headroom_requires_compatible_module(isolated_env, monkeypatch):
    monkeypatch.setitem(sys.modules, "headroom", types.ModuleType("headroom"))

    with pytest.raises(RuntimeError, match="Headroom was requested"):
        setup_costguard(tool="cline", non_interactive=True, headroom_enabled=True)


def test_proxy_applies_headroom_before_forwarding(isolated_env, monkeypatch):
    setup_costguard(
        tool="cline",
        non_interactive=True,
        openai_upstream_base_url="http://upstream.example/v1",
        openai_model_standard="real-model",
    )
    monkeypatch.setenv("OPENAI_UPSTREAM_API_KEY", "test-key")
    _install_fake_headroom(monkeypatch)
    headroom.enable(isolated_env["home"])

    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: int) -> httpx.Response:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        captured["timeout"] = timeout
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(proxy.httpx, "post", fake_post)
    server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.CostGuardHandler)
    server.costguard_home = isolated_env["home"]  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        marker = "PRIVATE_CONTEXT_SHOULD_NOT_BE_STORED"
        body = json.dumps({"model": "cg-standard", "messages": [{"role": "user", "content": marker * 20}]})
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={"authorization": "Bearer sk-costguard-local", "content-type": "application/json"},
        )
        response = connection.getresponse()
        response_body = response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert json.loads(response_body) == {"ok": True}
    assert captured["json"]["model"] == "real-model"
    assert captured["json"]["messages"][0]["content"] == "short context"
    assert captured["json"]["headroom_meta"]["client"] == "cline"
    summary = usage_mod.summary("today", isolated_env["home"])
    assert summary["headroom_applied_count"] == 1
    assert summary["headroom_input_chars_before"] > summary["headroom_input_chars_after"]
    assert summary["headroom_input_tokens_before"] >= summary["headroom_input_tokens_after"]
    assert summary["headroom_tokens_saved"] > 0
    assert summary["headroom_reduction_ratio"] > 0
    assert summary["outputs_reduced"] == 0
    assert marker.encode("utf-8") not in (isolated_env["home"] / "costguard.db").read_bytes()


def test_proxy_invokes_compress_adapter_for_openai_chat_request(isolated_env, monkeypatch):
    setup_costguard(
        tool="cline",
        non_interactive=True,
        openai_upstream_base_url="http://upstream.example/v1",
        openai_model_cheap="real-model",
    )
    monkeypatch.setenv("OPENAI_UPSTREAM_API_KEY", "test-key")
    fake_headroom = _install_fake_headroom_compress(monkeypatch)
    headroom.enable(isolated_env["home"])

    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: int) -> httpx.Response:
        captured["json"] = json
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(proxy.httpx, "post", fake_post)
    server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.CostGuardHandler)
    server.costguard_home = isolated_env["home"]  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        long_text = "repeatable context " * 400
        body = json.dumps({"model": "cg-cheap", "messages": [{"role": "user", "content": long_text}]})
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={"authorization": "Bearer sk-costguard-local", "content-type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert fake_headroom.calls == [{"messages": [{"role": "user", "content": long_text}], "model": "real-model"}]
    assert captured["json"]["messages"][0]["content"] == "short context"
    summary = usage_mod.summary("today", isolated_env["home"])
    assert summary["headroom_applied_count"] == 1
    assert summary["headroom_skipped_count"] == 0
    assert summary["headroom_input_chars_before"] > summary["headroom_input_chars_after"]
    assert summary["headroom_tokens_saved"] > 0
    assert summary["headroom_last_skip_reason"] == "n/a"


def test_proxy_records_headroom_skip_reason_for_tools_request(isolated_env, monkeypatch):
    setup_costguard(
        tool="cline",
        non_interactive=True,
        openai_upstream_base_url="http://upstream.example/v1",
        openai_model_standard="real-model",
    )
    monkeypatch.setenv("OPENAI_UPSTREAM_API_KEY", "test-key")
    fake_headroom = _install_fake_headroom_compress(monkeypatch)
    headroom.enable(isolated_env["home"])

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: int) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(proxy.httpx, "post", fake_post)
    server = ThreadingHTTPServer(("127.0.0.1", 0), proxy.CostGuardHandler)
    server.costguard_home = isolated_env["home"]  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "model": "cg-standard",
                "messages": [{"role": "user", "content": "safe context"}],
                "tools": [{"type": "function", "function": {"name": "do_work"}}],
            }
        )
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={"authorization": "Bearer sk-costguard-local", "content-type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert response.status == 200
    assert fake_headroom.calls == []
    summary = usage_mod.summary("today", isolated_env["home"])
    assert summary["headroom_applied_count"] == 0
    assert summary["headroom_skipped_count"] == 1
    assert summary["headroom_last_skip_reason"] == "skipped_tools"
    assert summary["headroom_input_chars_before"] > 0


def test_headroom_diagnostic_reports_metrics_without_content(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True, openai_model_standard="real-model")
    _install_fake_headroom_compress(monkeypatch)
    headroom.enable(isolated_env["home"])

    result = headroom.diagnostic(
        sample="repeated",
        client="cline",
        model="cg-standard",
        home=isolated_env["home"],
    )

    assert result["changed"] is True
    assert result["adapter"] == "compress"
    assert result["adapter_input_shape"] == "messages_list"
    assert result["adapter_result_attributes"] == "compression_ratio,messages,tokens_after,tokens_before,tokens_saved"
    assert result["adapter_result_message_count"] == 1
    assert result["adapter_result_tokens_before"] == 100
    assert result["adapter_result_tokens_after"] == 20
    assert result["adapter_result_tokens_saved"] == 80
    assert result["adapter_result_compression_ratio"] == 0.8
    assert result["input_message_count"] == 1
    assert result["input_chars_before"] > result["input_chars_after"]
    assert result["tokens_saved"] > 0
    assert result["skip_reason"] == "n/a"
    assert result["content_printed"] is False
    assert "Cost Guard validates" not in json.dumps(result)


def test_headroom_diagnostic_passes_compress_options(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True, openai_model_standard="real-model")
    fake_headroom = _install_introspective_headroom_compress(monkeypatch)
    headroom.enable(isolated_env["home"])

    result = headroom.diagnostic(
        sample="repeated",
        client="cline",
        model="cg-standard",
        home=isolated_env["home"],
        compress_user_messages=True,
        protect_recent=0,
        target_ratio=0.5,
        min_tokens_to_compress=10,
    )

    assert result["changed"] is True
    assert result["headroom_compress_user_messages"] is True
    assert result["headroom_protect_recent"] == 0
    assert result["headroom_target_ratio"] == 0.5
    assert result["headroom_min_tokens_to_compress"] == 10
    assert fake_headroom.calls[-1]["kwargs"] == {  # type: ignore[attr-defined]
        "compress_user_messages": True,
        "protect_recent": 0,
        "min_tokens_to_compress": 10,
        "target_ratio": 0.5,
    }


def test_headroom_diagnostic_reports_incompatible_raw_text_result(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True, openai_model_standard="real-model")
    _install_introspective_headroom_compress(monkeypatch)
    headroom.enable(isolated_env["home"])

    result = headroom.diagnostic(
        sample="repeated",
        client="cline",
        model="cg-standard",
        home=isolated_env["home"],
        input_shape="raw-text",
    )

    assert result["changed"] is False
    assert result["skip_reason"] == "skipped_adapter_error"
    assert result["adapter_result_type"] == "CompressResult"
    assert result["normalized_result_shape"] == "CompressResult"
    assert result["payload_reconstruction_status"] == "unsupported"
    assert result["error_type"] == "invalid_result"
    assert result["adapter_result_message_count"] == "n/a"
    assert "Cost Guard validates" not in json.dumps(result)


@pytest.mark.parametrize("sample", ["multi-turn", "tool-output", "long-code", "markdown", "logs", "test-failure"])
def test_headroom_diagnostic_supports_realistic_samples_without_content(isolated_env, monkeypatch, sample):
    setup_costguard(tool="cline", non_interactive=True, openai_model_standard="real-model")
    _install_no_change_headroom_compress(monkeypatch)
    headroom.enable(isolated_env["home"])

    result = headroom.diagnostic(
        sample=sample,
        client="cline",
        model="cg-standard",
        home=isolated_env["home"],
    )

    assert result["sample"] == sample
    assert result["input_message_count"] >= 1
    assert result["content_printed"] is False
    rendered = json.dumps(result)
    assert "safe repeated validation event" not in rendered
    assert "def transform_record" not in rendered
    assert "FAILED tests" not in rendered


@pytest.mark.parametrize(
    ("input_shape", "expected_input_type", "expected_result_keys", "expected_normalized_shape", "expected_status"),
    [
        ("messages-list", list, "compressed_messages,tokens_saved", "dict_compressed_messages", "messages_reconstructed"),
        ("openai-payload", dict, "payload,tokens_saved", "dict_payload_messages", "payload_reconstructed"),
        ("raw-text", str, "compressed_text,tokens_saved", "dict_compressed_text", "text_reconstructed"),
        (
            "concatenated-messages-text",
            str,
            "compressed_text,tokens_saved",
            "dict_compressed_text",
            "text_reconstructed",
        ),
    ],
)
def test_headroom_diagnostic_input_shapes_reconstruct_payload(
    isolated_env,
    monkeypatch,
    input_shape,
    expected_input_type,
    expected_result_keys,
    expected_normalized_shape,
    expected_status,
):
    setup_costguard(tool="cline", non_interactive=True, openai_model_standard="real-model")
    fake_headroom = _install_shape_aware_headroom_compress(monkeypatch)
    headroom.enable(isolated_env["home"])

    result = headroom.diagnostic(
        sample="repeated",
        client="cline",
        model="cg-standard",
        home=isolated_env["home"],
        input_shape=input_shape,
    )

    assert result["changed"] is True
    assert result["requested_input_shape"] == input_shape
    assert result["adapter_input_shape"] == input_shape.replace("-", "_")
    assert result["adapter_result_type"] == "dict"
    assert result["adapter_result_keys"] == expected_result_keys
    assert result["normalized_result_shape"] == expected_normalized_shape
    assert result["payload_reconstruction_status"] == expected_status
    assert result["input_chars_before"] > result["input_chars_after"]
    assert result["tokens_saved"] > 0
    assert isinstance(fake_headroom.calls[-1]["value"], expected_input_type)  # type: ignore[attr-defined]
    assert fake_headroom.calls[-1]["model"] == "real-model"  # type: ignore[attr-defined]
    assert "Cost Guard validates" not in json.dumps(result)


def test_headroom_diagnostic_accepts_underscore_input_shape_alias(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True, openai_model_standard="real-model")
    _install_shape_aware_headroom_compress(monkeypatch)
    headroom.enable(isolated_env["home"])

    result = headroom.diagnostic(
        sample="repeated",
        client="cline",
        model="cg-standard",
        home=isolated_env["home"],
        input_shape="raw_text",
    )

    assert result["requested_input_shape"] == "raw-text"
    assert result["adapter_input_shape"] == "raw_text"
    assert result["changed"] is True


def test_headroom_diagnostic_reports_metadata_only_dict(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True, openai_model_standard="real-model")
    _install_metadata_only_headroom_compress(monkeypatch)
    headroom.enable(isolated_env["home"])

    result = headroom.diagnostic(
        sample="repeated",
        client="cline",
        model="cg-standard",
        home=isolated_env["home"],
    )

    assert result["changed"] is False
    assert result["skip_reason"] == "skipped_no_change"
    assert result["adapter_result_keys"] == "changed,tokens_saved"
    assert result["adapter_result_attributes"] == "n/a"
    assert result["normalized_result_shape"] == "dict_metadata_only"
    assert result["payload_reconstruction_status"] == "metadata_only"
    assert result["tokens_saved"] == 0
    assert "Cost Guard validates" not in json.dumps(result)


def test_headroom_diagnostic_reports_no_change(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True, openai_model_standard="real-model")
    fake_headroom = _install_no_change_headroom_compress(monkeypatch)
    headroom.enable(isolated_env["home"])

    result = headroom.diagnostic(
        sample="repeated",
        client="cline",
        model="cg-standard",
        home=isolated_env["home"],
    )

    assert fake_headroom.calls != []
    assert result["changed"] is False
    assert result["adapter"] == "compress"
    assert result["skip_reason"] == "skipped_no_change"
    assert result["tokens_saved"] == 0
    assert result["input_chars_before"] == result["input_chars_after"]


def test_cli_headroom_test_does_not_print_sample_content(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True, openai_model_standard="real-model")
    _install_shape_aware_headroom_compress(monkeypatch)
    headroom.enable(isolated_env["home"])
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "headroom",
            "test",
            "--sample",
            "repeated",
            "--model",
            "cg-standard",
            "--input-shape",
            "raw-text",
        ],
    )

    assert result.exit_code == 0
    assert "changed" in result.output
    assert "True" in result.output
    assert "raw-text" in result.output
    assert "Cost Guard validates" not in result.output
