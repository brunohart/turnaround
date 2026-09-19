# /// script
# requires-python = ">=3.13"
# dependencies = ["playwright>=1.47"]
# ///
"""The Playwright pass on the board (Day 12): serve `board/`, give it files the way a
person would, and hold it to what it promises at a desk width and a phone's.

    uv run scripts/board_pass.py            # asserts, and writes docs/grids/day-12-*.png

It drives the Chrome already on the machine (`channel="chrome"`), so there is no browser
download. Every request the page makes is recorded; one that leaves the board's own
origin fails the pass.
"""

from __future__ import annotations

import functools
import json
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "docs/grids"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def serve() -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(Quiet, directory=str(ROOT / "board"))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def give(page: Page, *files: str) -> None:
    page.set_input_files("#files", [str(ROOT / f) for f in files])


def main() -> int:
    httpd, origin = serve()
    regent = json.loads((ROOT / "docs/grids/regent.json").read_text())["sessions"]
    voyages = sum(1 for s in regent if s["film"] == "odyssey")
    seen: list[str] = []
    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        # the desk
        ctx = browser.new_context(viewport={"width": 1280, "height": 1100})
        page = ctx.new_page()
        page.on("request", lambda r: seen.append(r.url))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(origin + "/")
        page.screenshot(path=SHOTS / "day-12-board-empty.png")

        give(page, "docs/grids/regent.json", "examples/regent.json")
        page.wait_for_selector("#out .block")
        assert page.locator("#out .grid").is_visible(), "the grid shows at a desk width"
        assert not page.locator("#out .strips").is_visible(), "the strips are the phone's"
        assert page.locator("#out .block").count() == len(regent), "every session is a block"
        assert page.locator("#out .block .t", has_text="The Long Voyage").count() == voyages
        assert page.locator("#out .feat.forced, #out .feat.wanted").count() > 0, "the why marks"
        assert "?" not in page.url and "#" not in page.url, "the URL carries nothing"
        # a block sits where the package's sheet puts it, to a hundredth of a percent
        want = [
            (e.get_attribute("style") or "").split(";")[0]
            for e in _package_blocks(browser, "docs/grids/regent.html")
        ]
        got = [
            (e.get_attribute("style") or "").split(";")[0]
            for e in page.locator("#out .lane > .block").all()
        ]
        assert [_pct(s) for s in got] == [_pct(s) for s in want], "block positions match"
        page.screenshot(path=SHOTS / "day-12-board.png")

        # a grid alone is drawn by id and says so
        page.click("#again")
        give(page, "docs/grids/regent.json")
        page.wait_for_selector("#out .block")
        assert "no brief" in page.locator("#bar-what").inner_text().lower()
        assert page.locator("#out .block .t", has_text="odyssey").count() == voyages
        # a brief alone is refused in a sentence; so is something that is neither
        page.click("#again")
        give(page, "examples/regent.json")
        page.locator("#error").wait_for(state="visible")
        assert "drop its grid" in page.locator("#error").inner_text().lower()
        page.reload()
        give(page, "pyproject.toml")
        page.locator("#error").wait_for(state="visible")
        assert "not json" in page.locator("#error").inner_text().lower()
        # a week draws day by day; the festival's venues are its rows
        page.reload()
        give(page, "docs/grids/regent-week.json", "examples/regent-week.json")
        page.wait_for_selector("#out .day-page")
        assert page.locator("#out .day-page").count() == 7
        page.reload()
        give(page, "docs/grids/festival.json", "examples/festival.json")
        page.wait_for_selector("#out .day-page")
        assert page.locator("#out .day-page").count() == 10
        page.screenshot(path=SHOTS / "day-12-board-festival.png")
        # the example button reads the board's own folder
        page.reload()
        page.click("#example")
        page.wait_for_selector("#out .block")
        ctx.close()

        # the phone: the grid is replaced by the booth strips
        phone = browser.new_context(**pw.devices["iPhone 13"])
        page = phone.new_page()
        page.on("request", lambda r: seen.append(r.url))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(origin + "/")
        page.screenshot(path=SHOTS / "day-12-board-phone-empty.png")
        give(page, "docs/grids/regent.json", "examples/regent.json")
        page.wait_for_selector("#out .vblock")
        assert not page.locator("#out .grid").is_visible(), "no shrunken grid on a phone"
        assert page.locator("#out .vblock").count() == len(regent)
        wide = page.evaluate("document.documentElement.scrollWidth > innerWidth")
        assert not wide, "nothing scrolls the page sideways on a phone"
        page.screenshot(path=SHOTS / "day-12-board-phone.png", full_page=False)
        phone.close()
        browser.close()
    httpd.shutdown()
    away = [u for u in seen if not u.startswith(origin)]
    assert not away, f"the board asked for something that is not its own: {away}"
    assert not errors, f"the page threw: {errors}"
    print(f"board pass: ok · {len(seen)} requests, all to the board · 5 screenshots in docs/grids/")
    return 0


def _pct(style: str) -> float:
    return round(float(style.split(":")[1].strip().rstrip("%")), 2)


def _package_blocks(browser, html: str):  # type: ignore[no-untyped-def]
    page = browser.new_page()
    page.goto((ROOT / html).as_uri())
    return page.locator(".lane > .block").all()


if __name__ == "__main__":
    sys.exit(main())
