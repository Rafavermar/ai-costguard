from __future__ import annotations

import httpx
import pytest
from typer.testing import CliRunner

from costguard.cli import app
from costguard import budget, paths, pricing
from costguard.install import setup_costguard
from costguard.utils import write_yaml


def test_parse_catalog_supports_generic_model_prices():
    payload = [
        {
            "provider": "provider",
            "name": "provider.model-large",
            "systemName": "region.provider.model-large",
            "inputPrice": 3.3,
            "outputPrice": 16.5,
            "cachedTokenReadPrice": 0.33,
            "cachedTokenCreationPrice": 4.125,
        }
    ]

    parsed = pricing.parse_catalog(payload)

    assert parsed["region.provider.model-large"]["input_per_million"] == 3.3
    assert parsed["region.provider.model-large"]["output_per_million"] == 16.5
    assert parsed["region.provider.model-large"]["cached_read_per_million"] == 0.33
    assert parsed["provider.model-large"]["input_per_million"] == 3.3


def test_budget_uses_pricing_catalog_for_configured_upstream_model(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)
    home = isolated_env["home"]
    env_file = paths.env_path(home)
    env_file.write_text(
        env_file.read_text(encoding="utf-8") + "OPENAI_MODEL_STANDARD=region.provider.model-large\n",
        encoding="utf-8",
    )
    write_yaml(
        paths.pricing_path(home),
        {
            "models": {
                "region.provider.model-large": {
                    "input_per_million": 3.3,
                    "output_per_million": 16.5,
                }
            }
        },
    )

    assert budget.estimate_cost("cg-standard", 1000, home, output_tokens=2000) == pytest.approx(0.0363)


def test_budget_falls_back_to_local_estimate_without_pricing_catalog(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)

    assert budget.estimate_cost("cg-standard", 1000, isolated_env["home"]) == 0.001


def test_pricing_status_without_configured_endpoint(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)

    status = pricing.status(isolated_env["home"])

    assert status["configured"] is False
    assert status["models"] == 0
    assert status["fallback"] == "settings.yaml pricing estimates"


def test_pricing_refresh_uses_endpoint_api_key_env_and_writes_cache(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True)
    monkeypatch.setenv("PRICING_API_KEY", "test-pricing-key")
    captured: dict[str, object] = {}
    payload = [
        {
            "provider": "provider",
            "name": "provider.model-large",
            "systemName": "region.provider.model-large",
            "inputPrice": 3.3,
            "outputPrice": 16.5,
        }
    ]

    def fake_get(url: str, headers: dict[str, str], timeout: float) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(pricing.httpx, "get", fake_get)

    result = pricing.refresh(
        isolated_env["home"],
        endpoint="https://models.example.test/v1/models",
        api_key_env="PRICING_API_KEY",
        auth_header="x-api-key",
        timeout=12,
    )

    assert result["written"] is True
    assert result["models"] == 2
    assert captured["url"] == "https://models.example.test/v1/models"
    assert captured["headers"] == {"accept": "application/json", "x-api-key": "test-pricing-key"}
    assert captured["timeout"] == 12
    assert paths.models_cache_path(isolated_env["home"]).exists()
    assert paths.pricing_path(isolated_env["home"]).exists()
    assert "test-pricing-key" not in paths.models_cache_path(isolated_env["home"]).read_text(encoding="utf-8")
    assert "test-pricing-key" not in paths.pricing_path(isolated_env["home"]).read_text(encoding="utf-8")
    assert pricing.model_pricing("region.provider.model-large", isolated_env["home"])["input_per_million"] == 3.3


def test_pricing_refresh_can_reuse_local_env_key_reference(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True)
    home = isolated_env["home"]
    env_file = paths.env_path(home)
    env_file.write_text(
        env_file.read_text(encoding="utf-8")
        + "\n"
        + "OPENAI_UPSTREAM_API_KEY=shared-local-key\n"
        + "COSTGUARD_PRICING_URL=https://models.example.test/v1/models\n"
        + "COSTGUARD_PRICING_API_KEY_ENV=OPENAI_UPSTREAM_API_KEY\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}
    payload = [{"name": "provider.model-large", "inputPrice": 3.3, "outputPrice": 16.5}]

    def fake_get(url: str, headers: dict[str, str], timeout: float) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = headers
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(pricing.httpx, "get", fake_get)

    result = pricing.refresh(home, dry_run=True)

    assert result["models"] == 1
    assert captured["url"] == "https://models.example.test/v1/models"
    assert captured["headers"] == {"accept": "application/json", "x-api-key": "shared-local-key"}


def test_pricing_refresh_dry_run_does_not_write_cache(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True)
    payload = [{"name": "model-a", "inputPrice": 1, "outputPrice": 2}]

    def fake_get(url: str, headers: dict[str, str], timeout: float) -> httpx.Response:
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(pricing.httpx, "get", fake_get)

    result = pricing.refresh(isolated_env["home"], endpoint="https://models.example.test/v1/models", dry_run=True)

    assert result["dry_run"] is True
    assert result["written"] is False
    assert result["models"] == 1
    assert not paths.models_cache_path(isolated_env["home"]).exists()
    assert not paths.pricing_path(isolated_env["home"]).exists()


def test_cli_pricing_refresh_help_lists_operational_options(isolated_env):
    runner = CliRunner()

    result = runner.invoke(app, ["pricing", "refresh", "--help"])

    assert result.exit_code == 0
    assert "--endpoint" in result.output
    assert "--api-key-env" in result.output
    assert "--auth-header" in result.output
    assert "--dry-run" in result.output
    assert "--timeout" in result.output


def test_pricing_configure_writes_local_env_without_api_key(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)

    result = pricing.configure(
        isolated_env["home"],
        endpoint="https://models.example.test/v1/models",
        api_key_env="PRICING_API_KEY",
        auth_header="x-api-key",
    )
    env_text = paths.env_path(isolated_env["home"]).read_text(encoding="utf-8")

    assert result["endpoint"] == "configured"
    assert result["api_key"] == "not stored"
    assert "COSTGUARD_PRICING_URL=https://models.example.test/v1/models" in env_text
    assert "COSTGUARD_PRICING_API_KEY_ENV=PRICING_API_KEY" in env_text
    assert "COSTGUARD_PRICING_API_KEY=\n" in env_text
    assert "test-pricing-key" not in env_text


def test_cli_pricing_configure_does_not_print_endpoint_or_key(isolated_env):
    setup_costguard(tool="cline", non_interactive=True)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "pricing",
            "configure",
            "--endpoint",
            "https://models.example.test/v1/models",
            "--api-key-env",
            "PRICING_API_KEY",
            "--auth-header",
            "x-api-key",
        ],
    )

    assert result.exit_code == 0
    assert "https://models.example.test/v1/models" not in result.output
    assert "test-pricing-key" not in result.output
    assert "configured" in result.output


def test_cli_pricing_refresh_does_not_print_api_key(isolated_env, monkeypatch):
    setup_costguard(tool="cline", non_interactive=True)
    monkeypatch.setenv("PRICING_API_KEY", "test-pricing-key")
    payload = [{"name": "model-a", "inputPrice": 1, "outputPrice": 2}]

    def fake_get(url: str, headers: dict[str, str], timeout: float) -> httpx.Response:
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(pricing.httpx, "get", fake_get)
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "pricing",
            "refresh",
            "--endpoint",
            "https://models.example.test/v1/models",
            "--api-key-env",
            "PRICING_API_KEY",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "test-pricing-key" not in result.output
    assert "PRICING_API_KEY" not in result.output
