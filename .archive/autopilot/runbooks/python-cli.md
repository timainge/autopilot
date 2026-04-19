# Runbook: python-cli

Python CLI tool archetype using Typer, uv, Ruff, and pytest.

## Project Structure

- `src/{name}/` — source package
- `src/{name}/cli.py` — Typer app entry point
- `tests/` — pytest test suite
- `pyproject.toml` — build config, dependencies, tool config
- `.github/workflows/ci.yml` — CI workflow (lint + test + build)

## Tooling

- **Package manager**: uv (`uv add`, `uv run`)
- **Linter/formatter**: Ruff (`uv run ruff check .`, `uv run ruff format .`)
- **Test runner**: pytest (`uv run pytest`)
- **Build**: `uv build`

## Conventions

- Entry point in `pyproject.toml` `[project.scripts]`: `name = "package.cli:app"`
- Typer app in `cli.py`: `app = typer.Typer()` with `@app.command()`
- Tests mirror source structure: `tests/test_cli.py`, `tests/test_core.py`
- Commit style: `type: brief description` (feat, fix, chore, docs, test, refactor)

## Validation Commands

- `uv run pytest`
- `uv run ruff check .`
- `uv build`

## Common Pitfalls

- Don't import from `__main__` in tests — import from the package directly
- `uv build` requires `[build-system]` table in `pyproject.toml`
- Ruff `I` rules enforce import order — run `ruff format` to fix automatically
- Entry point name in `pyproject.toml` must match the installed CLI command name
