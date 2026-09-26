"""The daily slot (`scripts/slot.sh`) runs Claude Code unattended with Bash and a push to main,
so it must never read the open web: a fetched page or a search result can carry instructions,
and nobody is there to refuse them (BEDIP-146). The web tools are neither allowed nor left to
whatever ~/.claude/settings.json allows; they are denied, and a deny wins."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

SLOT = (Path(__file__).resolve().parents[1] / "scripts/slot.sh").read_text(encoding="utf-8")
WEB = {"WebFetch", "WebSearch"}


def _tools(flag: str) -> set[str]:
    # The claude call is one command continued over lines; shlex reads its quoted lists whole.
    call = next(c for c in re.split(r"(?<!\\)\n", SLOT) if c.lstrip().startswith("claude -p"))
    words = shlex.split(call.replace("\\\n", " "))
    values = [words[i + 1] for i, w in enumerate(words) if w == flag]
    assert len(values) == 1, f"slot.sh passes {flag} {len(values)} times"
    return {t.strip() for t in re.split(r"[,\s]+", values[0]) if t.strip()}


def test_the_unattended_slot_never_reads_the_open_web() -> None:
    allowed = _tools("--allowedTools")
    assert "Bash" in allowed, "the slot builds and pushes; if that changes, so does this test"
    assert not allowed & WEB, f"slot.sh allows {sorted(allowed & WEB)} beside Bash"
    denied = _tools("--disallowedTools")
    assert denied >= WEB, "slot.sh must deny the web tools, not only leave them out"
