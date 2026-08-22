#!/usr/bin/env python3
"""Connect over CDP and navigate."""
import json, os, sys
from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("WICK_CHROME_PORT", "9222"))
url = sys.argv[1]

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    print(json.dumps({"ok": True, "url": page.url, "title": page.title()}))
