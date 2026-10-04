from __future__ import annotations

import json

from fastapi.testclient import TestClient

import app as nanobot_app


def written_config(tmp_path) -> dict:
    return json.loads((tmp_path / "nanobot-home" / "config.json").read_text())


def preset(config: dict) -> dict:
    return config["modelPresets"]["lmStudio"]


def test_writes_config_into_nanobot_home(tmp_path) -> None:
    nanobot_app.configure_nanobot()
    assert (tmp_path / "nanobot-home" / "config.json").is_file()


def test_context_and_output_tokens_come_from_env(tmp_path, monkeypatch) -> None:
    # Regression: nanobot defaults to a 200k window, which silently overflowed the
    # model actually loaded in LM Studio and forced every call onto the ddgs fallback.
    monkeypatch.setenv("NANOBOT_CONTEXT_TOKENS", "16384")
    monkeypatch.setenv("NANOBOT_MAX_OUTPUT_TOKENS", "512")
    nanobot_app.configure_nanobot()
    assert preset(written_config(tmp_path))["contextWindowTokens"] == 16384
    assert preset(written_config(tmp_path))["maxTokens"] == 512


def test_token_defaults_are_never_nanobots_200k(tmp_path) -> None:
    nanobot_app.configure_nanobot()
    model = preset(written_config(tmp_path))
    assert 0 < model["contextWindowTokens"] < 200_000
    assert 0 < model["maxTokens"] < model["contextWindowTokens"]


def test_lm_studio_endpoint_and_model_come_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://example.test:1234/v1")
    monkeypatch.setenv("LM_STUDIO_MODEL", "some-model")
    nanobot_app.configure_nanobot()
    config = written_config(tmp_path)
    assert config["providers"]["lm_studio"]["apiBase"] == "http://example.test:1234/v1"
    assert preset(config)["model"] == "some-model"


def test_lm_studio_defaults(tmp_path) -> None:
    nanobot_app.configure_nanobot()
    config = written_config(tmp_path)
    assert config["providers"]["lm_studio"]["apiBase"] == "http://host.docker.internal:1234/v1"
    assert preset(config)["model"] == "qwen2.5-7b-instruct"


def test_default_agent_uses_the_lm_studio_preset(tmp_path) -> None:
    nanobot_app.configure_nanobot()
    config = written_config(tmp_path)
    assert config["agents"]["defaults"]["modelPreset"] == "lmStudio"
    assert config["providers"]["lm_studio"] is not None
    assert preset(config)["provider"] == "lm_studio"


def test_sandbox_settings_stay_locked_down(tmp_path) -> None:
    nanobot_app.configure_nanobot()
    tools = written_config(tmp_path)["tools"]
    assert tools["restrictToWorkspace"] is True
    assert tools["exec"]["sandbox"] == "bwrap"
    assert tools["web"]["fetch"]["useJinaReader"] is False


def test_rewriting_config_is_idempotent(tmp_path) -> None:
    nanobot_app.configure_nanobot()
    first = (tmp_path / "nanobot-home" / "config.json").read_text()
    nanobot_app.configure_nanobot()
    assert (tmp_path / "nanobot-home" / "config.json").read_text() == first


def test_startup_event_writes_config_and_health_reports_mode(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APP_MODE", "local")
    with TestClient(nanobot_app.app) as client:
        assert (tmp_path / "nanobot-home" / "config.json").is_file()
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "local"}


def test_health_mode_defaults_to_fake() -> None:
    assert TestClient(nanobot_app.app).get("/health").json()["mode"] == "fake"
