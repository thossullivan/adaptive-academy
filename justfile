set dotenv-load := true

install:
	uv sync

seed:
	uv run aa seed

api:
	uv run uvicorn adaptive_academy.api.app:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	uv run pytest -q

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f
