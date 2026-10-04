from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep configure_nanobot() out of the real home directory and start from clean env."""
    monkeypatch.setenv("NANOBOT_HOME", str(tmp_path / "nanobot-home"))
    for name in (
        "NANOBOT_CONTEXT_TOKENS", "NANOBOT_MAX_OUTPUT_TOKENS",
        "LM_STUDIO_BASE_URL", "LM_STUDIO_MODEL", "APP_MODE",
    ):
        monkeypatch.delenv(name, raising=False)
