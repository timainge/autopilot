# Contributing

See [CONTRIBUTING.md](https://github.com/timainge/autopilot/blob/main/CONTRIBUTING.md) in the repository for full contribution guidelines.

## Quick Start

```bash
git clone https://github.com/timainge/autopilot.git
cd autopilot
uv pip install -e ".[dev]"
```

## Running Tests

```bash
make test
```

## Running Linter

```bash
make lint
```

## Submitting PRs

- Fork the repo and create a feature branch
- Make your changes with tests
- Run `make ci` to verify lint and tests pass
- Open a pull request against `main`
