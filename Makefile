.PHONY: up down logs test-backend test-frontend backup restore

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

test-backend:
	@set -eu; \
		export COMPOSE_PROJECT_NAME=portfolio-rebalancer-test; \
		export PORTFOLIO_PORT=0; \
		cleanup() { docker compose down -v --remove-orphans >/dev/null 2>&1 || true; }; \
		trap cleanup EXIT; \
		cleanup; \
		docker compose up -d db; \
		docker compose run --rm api uv run alembic upgrade head; \
		docker compose run --rm api uv run pytest -v

test-frontend:
	cd frontend && npm test -- --run --passWithNoTests

backup:
	./scripts/backup.sh

restore:
	@test -n "$(FILE)" || (echo "Usage: make restore FILE=backups/file.dump" && exit 1)
	./scripts/restore.sh "$(FILE)"
