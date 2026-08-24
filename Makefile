.PHONY: up down logs test-backend test-frontend backup restore

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

PYTEST_ARGS ?= -v

test-backend:
	@set -eu; \
		export COMPOSE_PROJECT_NAME=portfolio-rebalancer-test; \
		export POSTGRES_DB=portfolio_test; \
		export DATABASE_URL=postgresql+asyncpg://portfolio:portfolio@db:5432/portfolio_test; \
		export PYTEST_DATABASE_RESET_TOKEN=portfolio_test; \
		export PYTEST_POSTGRES_VOLUME=$${COMPOSE_PROJECT_NAME}_postgres_data; \
		export PYTEST_SECRET_VOLUME=$${COMPOSE_PROJECT_NAME}_secret_data; \
		export PYTEST_BACKUP_VOLUME=$${COMPOSE_PROJECT_NAME}_backup_data; \
		export PORTFOLIO_PORT=0; \
		cleanup() { docker compose down -v --remove-orphans >/dev/null 2>&1 || true; }; \
		trap cleanup EXIT; \
		cleanup; \
		docker compose up -d db; \
		docker compose build api; \
		docker compose run --rm -e DATABASE_URL api uv run alembic upgrade head; \
		docker compose run --rm \
			-e DATABASE_URL \
			-e PYTEST_DATABASE_RESET_TOKEN \
			-e COMPOSE_PROJECT_NAME \
			-e PYTEST_POSTGRES_VOLUME \
			-e PYTEST_SECRET_VOLUME \
			-e PYTEST_BACKUP_VOLUME \
			api uv run pytest $(PYTEST_ARGS)

test-frontend:
	cd frontend && npm test -- --run --passWithNoTests

backup:
	./scripts/backup.sh

restore:
	@test -n "$(FILE)" || (echo "Usage: make restore FILE=backups/file.dump" && exit 1)
	./scripts/restore.sh "$(FILE)"
