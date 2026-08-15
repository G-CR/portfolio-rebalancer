from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


EXPECTED_TEST_DATABASE = "portfolio_test"


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
