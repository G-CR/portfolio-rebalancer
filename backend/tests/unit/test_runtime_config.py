from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import get_settings


def test_lifespan_disposes_engine_on_shutdown(monkeypatch) -> None:
    dispose = AsyncMock()
    monkeypatch.setattr(main_module, "engine", SimpleNamespace(dispose=dispose))

    with TestClient(main_module.app):
        pass

    dispose.assert_awaited_once()


def test_compose_secret_mount_matches_settings() -> None:
    compose_path = Path(__file__).resolve().parents[3] / "compose.yaml"
    if not compose_path.exists():
        pytest.skip("compose.yaml is not available in the backend test image")

    compose = yaml.safe_load(compose_path.read_text())
    expected_mount = "secret_data:/run/portfolio-secrets"

    assert get_settings().secret_key_path == "/run/portfolio-secrets/fernet.key"
    assert expected_mount in compose["services"]["api"]["volumes"]
    assert expected_mount in compose["services"]["worker"]["volumes"]


def test_startup_commands_exec_uvicorn_after_migration() -> None:
    expected_fragment = "uv run alembic upgrade head && exec uv run --no-sync uvicorn"
    dockerfile_path = Path(__file__).resolve().parents[2] / "Dockerfile"

    if dockerfile_path.exists():
        assert expected_fragment in dockerfile_path.read_text()

    compose_path = Path(__file__).resolve().parents[3] / "compose.yaml"
    if compose_path.exists():
        compose = yaml.safe_load(compose_path.read_text())
        assert expected_fragment in compose["services"]["api"]["command"]
