#!/usr/bin/env python3
"""Chromium interactive actions for Wick — tabs, PDF, navigation, forms."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from shields import CHROME_HARDENING_ARGS  # noqa: F401
except Exception:
    CHROME_HARDENING_ARGS = []

PORT = int(os.environ.get("WICK_CHROME_PORT", "9222"))


def connect():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{PORT}")
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return pw, browser, ctx, page


def pages_info(ctx):
    out = []
    for i, p in enumerate(ctx.pages):
        try:
            out.append({"index": i, "url": p.url, "title": p.title()})
        except Exception:
            out.append({"index": i, "url": "?", "title": "?"})
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: action <name> ..."}))
        return 2
    action = sys.argv[1]
    args = sys.argv[2:]
    try:
        pw, browser, ctx, page = connect()
    except Exception as e:
        print(json.dumps({"ok": False, "error": "cdp_connect_failed", "detail": str(e)[:200]}))
        return 1

    try:
        if action == "goto":
            url = args[0]
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            print(json.dumps({"ok": True, "url": page.url, "title": page.title()}))

        elif action == "click":
            sel = args[0]
            page.click(sel, timeout=15000)
            print(json.dumps({"ok": True, "clicked": sel, "url": page.url}))

        elif action == "fill":
            sel, text = args[0], args[1]
            page.fill(sel, text, timeout=15000)
            print(json.dumps({"ok": True, "filled": sel, "n": len(text)}))

        elif action == "select":
            sel, value = args[0], args[1]
            page.select_option(sel, value, timeout=15000)
            print(json.dumps({"ok": True, "selected": sel, "value": value}))

        elif action == "check":
            page.check(args[0], timeout=15000)
            print(json.dumps({"ok": True, "checked": args[0]}))

        elif action == "press":
            page.keyboard.press(args[0])
            print(json.dumps({"ok": True, "pressed": args[0]}))

        elif action == "wait":
            page.wait_for_selector(args[0], timeout=30000)
            print(json.dumps({"ok": True, "waited": args[0]}))

        elif action == "eval":
            val = page.evaluate(args[0])
            print(json.dumps({"ok": True, "result": val}, default=str))

        elif action == "content":
            text = page.inner_text("body")
            lim = int(args[0]) if args else 12000
            print(json.dumps({
                "ok": True, "url": page.url, "title": page.title(),
                "chars": len(text), "content": text[:lim],
            }))

        elif action == "title":
            print(json.dumps({"ok": True, "url": page.url, "title": page.title()}))

        elif action == "back":
            page.go_back(timeout=30000)
            print(json.dumps({"ok": True, "url": page.url, "title": page.title()}))

        elif action == "forward":
            page.go_forward(timeout=30000)
            print(json.dumps({"ok": True, "url": page.url, "title": page.title()}))

        elif action == "reload":
            page.reload(wait_until="domcontentloaded", timeout=60000)
            print(json.dumps({"ok": True, "url": page.url, "title": page.title()}))

        elif action == "tab_new":
            url = args[0] if args else "about:blank"
            p2 = ctx.new_page()
            if url and url != "about:blank":
                p2.goto(url, wait_until="domcontentloaded", timeout=60000)
            print(json.dumps({"ok": True, "tabs": pages_info(ctx), "active": len(ctx.pages) - 1}))

        elif action == "tab_list":
            print(json.dumps({"ok": True, "tabs": pages_info(ctx)}))

        elif action == "tab_switch":
            idx = int(args[0])
            if idx < 0 or idx >= len(ctx.pages):
                print(json.dumps({"ok": False, "error": "bad_index", "tabs": pages_info(ctx)}))
                return 1
            p2 = ctx.pages[idx]
            p2.bring_to_front()
            print(json.dumps({"ok": True, "index": idx, "url": p2.url, "title": p2.title()}))

        elif action == "tab_close":
            idx = int(args[0]) if args else len(ctx.pages) - 1
            if idx < 0 or idx >= len(ctx.pages):
                print(json.dumps({"ok": False, "error": "bad_index"}))
                return 1
            if len(ctx.pages) <= 1:
                print(json.dumps({"ok": False, "error": "cannot_close_last_tab"}))
                return 1
            ctx.pages[idx].close()
            print(json.dumps({"ok": True, "tabs": pages_info(ctx)}))

        elif action == "pdf":
            out = Path(args[0] if args else str(Path.home() / ".wick" / "downloads" / "page.pdf"))
            out.parent.mkdir(parents=True, exist_ok=True)
            page.pdf(path=str(out), format="A4", print_background=True)
            print(json.dumps({"ok": True, "path": str(out), "bytes": out.stat().st_size}))

        elif action == "screenshot":
            out = Path(args[0] if args else str(Path.home() / ".wick" / "shots" / "page.png"))
            out.parent.mkdir(parents=True, exist_ok=True)
            full = (args[1] == "full") if len(args) > 1 else False
            page.screenshot(path=str(out), full_page=full)
            print(json.dumps({"ok": True, "path": str(out), "bytes": out.stat().st_size}))

        elif action == "download":
            url = args[0]
            out_dir = Path(args[1] if len(args) > 1 else os.environ.get("WICK_DOWNLOADS") or str(Path.home() / ".wick" / "downloads"))
            out_dir.mkdir(parents=True, exist_ok=True)
            try:
                with page.expect_download(timeout=15000) as di:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                dl = di.value
                dest = out_dir / (dl.suggested_filename or "download.bin")
                dl.save_as(str(dest))
                print(json.dumps({"ok": True, "path": str(dest), "filename": dest.name}))
            except Exception:
                resp = page.request.get(url)
                body = resp.body()
                name = url.rstrip("/").split("/")[-1].split("?")[0] or "download.bin"
                dest = out_dir / name
                dest.write_bytes(body)
                print(json.dumps({"ok": True, "path": str(dest), "bytes": len(body), "via": "request"}))

        elif action == "scroll":
            direction = (args[0] if args else "down").lower()
            amount = int(args[1]) if len(args) > 1 else 800
            dy = amount if direction in ("down", "d") else -amount
            if direction in ("left", "l"):
                page.mouse.wheel(-amount, 0)
            elif direction in ("right", "r"):
                page.mouse.wheel(amount, 0)
            else:
                page.mouse.wheel(0, dy)
            print(json.dumps({"ok": True, "scrolled": direction, "amount": amount, "url": page.url}))

        elif action == "hover":
            page.hover(args[0], timeout=15000)
            print(json.dumps({"ok": True, "hovered": args[0]}))

        elif action == "cookies":
            print(json.dumps({"ok": True, "cookies": ctx.cookies()}, default=str))

        else:
            print(json.dumps({"ok": False, "error": f"unknown_action {action}"}))
            return 2
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": "action_failed", "action": action, "detail": str(e)[:300]}))
        return 1
    finally:
        try:
            pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
