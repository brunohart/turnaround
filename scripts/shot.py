# /// script
# requires-python = ">=3.13"
# dependencies = ["websocket-client>=1.8"]
# ///
"""Screenshot a sheet at a real device width.

Headless Chrome will not lay a window out narrower than about 500 px, so
`--window-size=390,…` silently crops a wider page. This drives Chrome over the
DevTools protocol instead and emulates the device, which is the only way to see
the phone view the way a phone sees it.

    uv run scripts/shot.py docs/grids/booth.html day-6-sheet.png --width 1280 --height 1100
    uv run scripts/shot.py docs/grids/booth.html day-6-phone.png --width 390 --mobile --full
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from websocket import create_connection

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _wait_for_devtools(port: int, seconds: float = 15.0) -> list[dict[str, Any]]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as r:
                targets: list[dict[str, Any]] = json.load(r)
                if targets:
                    return targets
        except OSError:
            pass
        time.sleep(0.2)
    raise SystemExit("Chrome did not open its DevTools port")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("html", type=Path)
    ap.add_argument("png", type=Path)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=1100, help="viewport height")
    ap.add_argument("--scale", type=float, default=1.0, help="device scale factor")
    ap.add_argument("--mobile", action="store_true", help="emulate a touch device")
    ap.add_argument("--full", action="store_true", help="capture the whole page, not the viewport")
    ap.add_argument("--port", type=int, default=9333)
    args = ap.parse_args()

    url = args.html.resolve().as_uri()
    with tempfile.TemporaryDirectory() as profile:
        chrome = subprocess.Popen(
            [
                CHROME,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--remote-debugging-port={args.port}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            page = next(t for t in _wait_for_devtools(args.port) if t.get("type") == "page")
            ws = create_connection(page["webSocketDebuggerUrl"], suppress_origin=True)
            seq = 0

            def call(method: str, **params: Any) -> dict[str, Any]:
                nonlocal seq
                seq += 1
                ws.send(json.dumps({"id": seq, "method": method, "params": params}))
                while True:
                    msg = json.loads(ws.recv())
                    if msg.get("id") == seq:
                        if "error" in msg:
                            raise SystemExit(f"{method}: {msg['error']}")
                        result: dict[str, Any] = msg.get("result", {})
                        return result

            call("Page.enable")
            call(
                "Emulation.setDeviceMetricsOverride",
                width=args.width,
                height=args.height,
                deviceScaleFactor=args.scale,
                mobile=args.mobile,
            )
            if args.mobile:
                call("Emulation.setTouchEmulationEnabled", enabled=True)
            call("Page.navigate", url=url)
            # wait for the load event, then a beat for fonts and layout
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                msg = json.loads(ws.recv())
                if msg.get("method") == "Page.loadEventFired":
                    break
            time.sleep(0.6)
            shot: dict[str, Any] = {"format": "png"}
            if args.full:
                metrics = call("Page.getLayoutMetrics")
                size = metrics["cssContentSize"]
                shot["clip"] = {
                    "x": 0,
                    "y": 0,
                    "width": args.width,
                    "height": int(size["height"]),
                    "scale": 1,
                }
                shot["captureBeyondViewport"] = True
            data = call("Page.captureScreenshot", **shot)["data"]
            args.png.write_bytes(base64.b64decode(data))
            ws.close()
        finally:
            chrome.terminate()
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome.kill()
    how = f"{args.width}×{args.height}"
    how += (" mobile" if args.mobile else "") + (" full" if args.full else "")
    print(f"{args.png} ← {args.html} @ {how}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
