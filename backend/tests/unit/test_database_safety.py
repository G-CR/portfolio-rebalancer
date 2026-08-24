import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.database_safety import require_safe_test_database, require_safe_test_environment


SAFE_URL = "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio_test"
SAFE_COMPOSE_ENVIRONMENT = {
    "COMPOSE_PROJECT_NAME": "portfolio-rebalancer-test",
    "PYTEST_POSTGRES_VOLUME": "portfolio-rebalancer-test_postgres_data",
    "PYTEST_SECRET_VOLUME": "portfolio-rebalancer-test_secret_data",
    "PYTEST_BACKUP_VOLUME": "portfolio-rebalancer-test_backup_data",
}


def test_accepts_only_exact_test_compose_and_volume_identities() -> None:
    assert require_safe_test_environment(SAFE_COMPOSE_ENVIRONMENT) is None


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("COMPOSE_PROJECT_NAME", None),
        ("COMPOSE_PROJECT_NAME", "portfolio-rebalancer"),
        ("PYTEST_POSTGRES_VOLUME", "portfolio-rebalancer_postgres_data"),
        ("PYTEST_SECRET_VOLUME", "portfolio-rebalancer_secret_data"),
        ("PYTEST_BACKUP_VOLUME", "portfolio-rebalancer_backup_data"),
    ],
)
def test_rejects_missing_or_non_test_compose_volume_identity(
    key: str, value: str | None
) -> None:
    environment = dict(SAFE_COMPOSE_ENVIRONMENT)
    if value is None:
        environment.pop(key)
    else:
        environment[key] = value

    with pytest.raises(RuntimeError, match="test Compose isolation"):
        require_safe_test_environment(environment)


BACKEND_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("database_url", "reset_token", "rejected_database"),
    [
        (None, "portfolio_test", "unset"),
        (
            "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio",
            "portfolio_test",
            "portfolio",
        ),
        (SAFE_URL, None, "portfolio_test"),
        (SAFE_URL, "wrong-token", "portfolio_test"),
    ],
)
def test_rejects_unsafe_database_identity(
    database_url: str | None,
    reset_token: str | None,
    rejected_database: str,
) -> None:
    with pytest.raises(RuntimeError) as exc_info:
        require_safe_test_database(database_url, reset_token)

    message = str(exc_info.value)
    assert rejected_database in message
    assert "Business databases must never be reset by pytest" in message
    assert "make test-backend" in message


@pytest.mark.parametrize(
    "database_url",
    [
        SAFE_URL,
        f"{SAFE_URL}?ssl=disable",
    ],
)
def test_accepts_only_explicit_test_database_and_token(database_url: str) -> None:
    assert require_safe_test_database(database_url, "portfolio_test") == database_url


@pytest.mark.parametrize(
    "database_url",
    [
        f"{SAFE_URL}?database=portfolio",
        f"{SAFE_URL}?%64atabase=portfolio",
        f"{SAFE_URL}?database=portfolio&database=portfolio_test",
        f"{SAFE_URL}?dbname=portfolio",
    ],
)
def test_rejects_query_database_identity_overrides(database_url: str) -> None:
    with pytest.raises(RuntimeError) as exc_info:
        require_safe_test_database(database_url, "portfolio_test")

    message = str(exc_info.value)
    assert "Business databases must never be reset by pytest" in message
    assert "make test-backend" in message
    assert "portfolio:portfolio" not in message


def test_conftest_rejects_business_database_before_test_collection() -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = (
        "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio"
    )
    environment["PYTEST_DATABASE_RESET_TOKEN"] = "portfolio_test"

    result = subprocess.run(
        [sys.executable, "-c", "import tests.conftest"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "database='portfolio'" in result.stderr
    assert "make test-backend" in result.stderr


def test_conftest_rejects_query_database_override_before_test_collection() -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"{SAFE_URL}?database=portfolio"
    environment["PYTEST_DATABASE_RESET_TOKEN"] = "portfolio_test"

    result = subprocess.run(
        [sys.executable, "-c", "import tests.conftest"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Business databases must never be reset by pytest" in result.stderr
    assert "make test-backend" in result.stderr
    assert "portfolio:portfolio" not in result.stderr


def test_conftest_rejects_non_test_volume_identity_before_collection() -> None:
    environment = os.environ.copy()
    environment.update(SAFE_COMPOSE_ENVIRONMENT)
    environment["DATABASE_URL"] = SAFE_URL
    environment["PYTEST_DATABASE_RESET_TOKEN"] = "portfolio_test"
    environment["PYTEST_SECRET_VOLUME"] = "portfolio-rebalancer_secret_data"

    result = subprocess.run(
        [sys.executable, "-c", "import tests.conftest"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "test Compose isolation identity mismatch" in result.stderr
    assert "make test-backend" in result.stderr
