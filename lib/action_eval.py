#!/usr/bin/env python3
import json, os, sys
from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("WICK_CHROME_PORT", "9222"))
expr = sys.argv[1]

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    val = page.evaluate(expr)
    print(json.dumps({"ok": True, "result": val}, default=str))
