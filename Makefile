.PHONY: up down dev migrate test test-live lint

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

test-live:  # Stripe test mode; needs STRIPE_TEST_SECRET_KEY in .env
	set -a; . ./.env; set +a; STRIPE_API_BASE= uv run pytest -m live -rs

lint:
	uv run ruff format --check . && uv run ruff check . && uv run mypy tally && uv run lint-imports
