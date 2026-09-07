#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
chflags -R nohidden .venv 2>/dev/null || true  # see build.sh
uv run pytest -q "$@"
