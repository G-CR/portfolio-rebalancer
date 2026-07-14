.PHONY: up down logs test-backend test-frontend backup restore

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

test-backend:
	docker compose run --rm api uv run pytest -v

test-frontend:
	cd frontend && npm test -- --run --passWithNoTests

backup:
	./scripts/backup.sh

restore:
	@test -n "$(FILE)" || (echo "Usage: make restore FILE=backups/file.dump" && exit 1)
	./scripts/restore.sh "$(FILE)"
