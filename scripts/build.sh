#!/usr/bin/env bash
# Sync the environment, lint, and type-check. Exit non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
uv sync --quiet
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
