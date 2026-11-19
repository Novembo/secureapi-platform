.PHONY: install up down migrate lint typecheck test check seed demo

install: ; uv sync --frozen
up: ; docker compose up -d --build
down: ; docker compose down
migrate: ; docker compose run --rm migrate
lint: ; ruff check . && ruff format --check .
typecheck: ; mypy
test: ; pytest --cov --cov-report=term-missing --cov-report=xml --cov-report=html
check: lint typecheck test
seed: ; docker compose run --rm api python scripts/seed_demo.py
demo: ; bash scripts/demo_scenario.sh
