#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("WICK_CHROME_PORT", "9222"))
out = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "viewport"
Path(out).parent.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.screenshot(path=out, full_page=(mode == "full"))
    print(json.dumps({"ok": True, "path": out, "url": page.url}))
