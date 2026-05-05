.PHONY: help install lint format typecheck test eval eval-resume eval-resume-update clean docker-up docker-down docker-logs

DOCKER_CTX ?= docker-vm
COMPOSE    := DOCKER_CONTEXT=$(DOCKER_CTX) docker compose -f deploy/docker-compose/dev.yml

help:
	@echo "LV_DCP dev targets:"
	@echo "  install      - uv sync (install deps)"
	@echo "  lint         - ruff check + ruff format --check"
	@echo "  format       - ruff format"
	@echo "  typecheck    - mypy strict"
	@echo "  test         - pytest (excluding eval)"
	@echo "  eval         - retrieval eval harness"
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

docker-up:
	$(COMPOSE) up -d

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f --tail=100

eval-resume:
	uv run pytest -q -m eval tests/eval/resume

eval-resume-update:
	@echo "Re-record baseline.json after intentional improvement (manual step)"
	@echo "Edit tests/eval/resume/baseline.json and commit with rationale"

clean:
	rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov dist build
	find . -type d -name __pycache__ -exec rm -rf {} +
