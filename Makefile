.PHONY: help install lint format typecheck test eval eval-full eval-ci clean docker-up docker-down docker-logs

DOCKER_CTX ?= docker-vm
COMPOSE    := DOCKER_CONTEXT=$(DOCKER_CTX) docker compose -f deploy/docker-compose/dev.yml

help:
	@echo "LV_DCP dev targets:"
	@echo "  install      - uv sync (install deps)"
	@echo "  lint         - ruff check + ruff format --check"
	@echo "  format       - ruff format"
	@echo "  typecheck    - mypy strict"
	@echo "  test         - pytest (excluding eval)"
	@echo "  eval         - retrieval eval harness (IR metrics)"
	@echo "  eval-full    - full eval + RAGAS LLM-judge (needs ANTHROPIC_API_KEY)"
	@echo "  eval-ci      - promptfoo CI gate (local sanity)"
	@echo "  docker-up    - docker compose up on remote context ($(DOCKER_CTX))"
	@echo "  docker-down  - docker compose down"
	@echo "  docker-logs  - tail remote compose logs"
	@echo "  clean        - remove caches"

install:
	uv sync --extra dev

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy .

test:
	uv run pytest -q -m "not eval and not llm"

eval:
	uv run pytest -q -m eval

eval-full:
	uv run ctx eval run --full --output eval-results/$(shell date +%Y-%m-%d)-$(shell git rev-parse --short HEAD).json

eval-ci:
	npx -y promptfoo@latest eval -c tests/eval/promptfoo.config.yaml

docker-up:
	$(COMPOSE) up -d

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f --tail=100

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov dist build
	find . -type d -name __pycache__ -exec rm -rf {} +
