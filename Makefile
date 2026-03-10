.PHONY: test lint ci

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check src/
	uv run ruff format --check src/

ci: lint test
