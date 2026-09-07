#!/usr/bin/env bash
# Sync the environment, lint, and type-check. Exit non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
uv sync --quiet
# macOS flags dot-directories under ~/Documents hidden and Python 3.13 skips hidden .pth
# files, which makes the editable install vanish. Clear the flag; a no-op elsewhere.
chflags -R nohidden .venv 2>/dev/null || true
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
