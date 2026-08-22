#!/usr/bin/env python3
import json, os, re, sys
from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("WICK_CHROME_PORT", "9222"))
maxn = int(sys.argv[1]) if len(sys.argv) > 1 else 8000

with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    text = page.inner_text("body")
    text = re.sub(r"\s+", " ", text).strip()
    print(json.dumps({"ok": True, "url": page.url, "title": page.title(), "text": text[:maxn], "chars": len(text)}))
