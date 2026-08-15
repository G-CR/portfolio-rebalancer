import pytest

from tests.database_safety import require_safe_test_database


SAFE_URL = "postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio_test"


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
