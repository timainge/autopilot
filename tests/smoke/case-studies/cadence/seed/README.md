# Cadence

Time-tracking API. A user tracks time against activities, projects, and
clients. This repo is a case-study subject for autopilot real-agent
smokes.

## Run

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Visit http://127.0.0.1:8000/ — should return `{"ok": true}`.

## Test

```bash
uv run pytest
```
