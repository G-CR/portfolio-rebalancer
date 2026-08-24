from collections.abc import Mapping

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


EXPECTED_TEST_DATABASE = "portfolio_test"
EXPECTED_TEST_COMPOSE_IDENTITIES = {
    "COMPOSE_PROJECT_NAME": "portfolio-rebalancer-test",
    "PYTEST_POSTGRES_VOLUME": "portfolio-rebalancer-test_postgres_data",
    "PYTEST_SECRET_VOLUME": "portfolio-rebalancer-test_secret_data",
    "PYTEST_BACKUP_VOLUME": "portfolio-rebalancer-test_backup_data",
}


def require_safe_test_environment(environment: Mapping[str, str]) -> None:
    if any(
        environment.get(key) != expected
        for key, expected in EXPECTED_TEST_COMPOSE_IDENTITIES.items()
    ):
        raise RuntimeError(
            "Refusing pytest database reset: test Compose isolation identity mismatch. "
            "Run `make test-backend`."
        )


def require_safe_test_database(
    database_url: str | None,
    reset_token: str | None,
) -> str:
    database_name = "unset"
    has_database_override = False
    if database_url is not None:
        try:
            parsed_url = make_url(database_url)
            database_name = parsed_url.database or "unset"
            has_database_override = any(
                key.casefold() in {"database", "dbname"} for key in parsed_url.query
            )
        except ArgumentError:
            database_name = "invalid"

    if (
        database_url is None
        or database_name != EXPECTED_TEST_DATABASE
        or has_database_override
        or reset_token != EXPECTED_TEST_DATABASE
    ):
        raise RuntimeError(
            "Refusing pytest database reset: "
            f"database={database_name!r}. "
            "Business databases must never be reset by pytest. "
            "Run `make test-backend`."
        )

    return database_url
