.PHONY: up down logs test-backend test-frontend

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

test-backend:
	cd backend && uv run pytest -v

test-frontend:
	cd frontend && npm test -- --run --passWithNoTests
