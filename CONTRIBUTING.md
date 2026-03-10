# Contributing to autopilot

## Setup

```bash
git clone https://github.com/timainge/autopilot
cd autopilot
uv pip install -e ".[dev]"
```

## Adding a New Agent Role

1. Create `src/autopilot/agents/<role>.md` with YAML frontmatter:
   ```markdown
   ---
   name: role-name
   description: What this agent does
   allowed_tools:
     - Read
     - Write
     - Bash
   max_turns: 20
   max_budget_usd: 1.00
   permission_mode: default
   ---

   You are an expert...
   ```
2. Add a `build_<role>_prompt()` function in `prompts.py`
3. Add a `<role>_project()` function in `orchestrator.py`
4. Wire up the CLI flag in `cli.py`

## Running Linter

```bash
make lint
```

## Running Tests

```bash
make test
```

## Submitting PRs

- Keep changes focused; one feature per PR
- Run `make ci` before opening a PR
- Update `README.md` if you add CLI flags or agent roles
