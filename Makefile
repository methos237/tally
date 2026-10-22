.PHONY: up down dev migrate test lint

up:
	docker compose up -d --wait

down:
	docker compose down

migrate:
	uv run python manage.py migrate

dev: up migrate
	uv run python manage.py runserver 8001 & \
	uv run celery -A tally worker -l info & \
	uv run celery -A tally beat -l info & \
	wait

test:
	uv run pytest -m "not live"

lint:
	uv run ruff format --check . && uv run ruff check . && uv run mypy tally && uv run lint-imports
