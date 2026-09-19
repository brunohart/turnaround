#!/usr/bin/env bash
# The board (Day 12): a static page that draws a grid in the browser. This writes the two
# things the board takes from the package — the sheet's stylesheet, cut from the template's
# style macro so the two cannot drift (tests/test_board.py holds them together), and the
# Regent's brief and grid as the page's one example — then, asked, serves or previews it.
#   scripts/board.sh            write board/sheet.css and board/examples/
#   scripts/board.sh --serve    and serve it on http://localhost:8712
#   scripts/board.sh --preview  and deploy a Vercel preview (bruno-gated: needs `vercel login`)
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
chflags -R nohidden .venv 2>/dev/null || true
uv run python -c "from turnaround.render import board_css; print(board_css(), end='')" > board/sheet.css
mkdir -p board/examples
cp examples/regent.json board/examples/regent.json
cp docs/grids/regent.json board/examples/regent.grid.json
echo "board/sheet.css and board/examples/ written"
case "${1:-}" in
  --serve) exec python3 -m http.server 8712 --directory board ;;
  --preview) exec npx --yes vercel deploy board ;;
esac
