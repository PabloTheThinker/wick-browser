#!/usr/bin/env python3
"""Chromium interactive actions for Wick — tabs, PDF, navigation, forms."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from shields import CHROME_HARDENING_ARGS  # noqa: F401
except Exception:
    CHROME_HARDENING_ARGS = []

PORT = int(os.environ.get("WICK_CHROME_PORT", "9222"))
ROLE_SEL_RE = re.compile(
    r'^role=([a-zA-Z][\w-]*)(?:\[name=(?:"([^"]*)"|\'([^\']*)\')\])?$'
)

try:
    import origins as wick_origins
except Exception:
    wick_origins = None  # type: ignore
try:
    import vault as wick_vault
except Exception:
    wick_vault = None  # type: ignore
try:
    import login_form as wick_login_form
except Exception:
    wick_login_form = None  # type: ignore
try:
    import capability as wick_capability
except Exception:
    wick_capability = None  # type: ignore


def _guard_nav_url(url: str) -> tuple[str | None, dict | None]:
    """Normalize and reject dangerous / private targets (SSRF on Chromium path)."""
    if wick_origins is None:
        return url, None
    if wick_origins.is_dangerous_url(url):
        return None, {"ok": False, "error": "dangerous_url", "url": (url or "")[:120]}
    try:
        normalized = wick_origins.normalize_agent_url(url)
    except ValueError as e:
        return None, {"ok": False, "error": str(e), "url": (url or "")[:120]}
    if wick_origins.is_private_url(normalized) and not wick_origins.allow_private_override():
        return None, {"ok": False, "error": "private_url", "url": normalized[:120]}
    if wick_capability is not None:
        herr = wick_capability.deny_host(normalized)
        if herr:
            return None, herr
    return normalized, None


def _fill_secret(page, sel: str, text: str) -> tuple[str, dict | None, dict | None]:
    """Resolve vault refs against the live page origin. Never return the secret in err."""
    meta = None
    if wick_vault is not None and wick_vault.is_secret_ref(text):
        try:
            text, meta = wick_vault.resolve_for_fill(
                text, reason="act_fill", page_url=page.url
            )
        except ValueError as e:
            return "", None, {
                "ok": False,
                "error": "vault_resolve_failed",
                "detail": str(e)[:160],
                "ref": wick_vault._redact_ref(text),
            }
    return text, meta, None


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


def resolve_locator(page, sel: str):
    """Translate role=link[name=\"...\"] hints to Playwright get_by_role."""
    m = ROLE_SEL_RE.match((sel or "").strip())
    if m:
        role, name1, name2 = m.groups()
        name = name1 if name1 is not None else name2
        if name:
            return page.get_by_role(role, name=name)
        return page.get_by_role(role)
    return page.locator(sel)


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
            url, err = _guard_nav_url(args[0])
            if err:
                print(json.dumps(err))
                return 1
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            print(json.dumps({"ok": True, "url": page.url, "title": page.title()}))

        elif action == "click":
            sel = args[0]
            resolve_locator(page, sel).click(timeout=15000)
            print(json.dumps({"ok": True, "clicked": sel, "url": page.url}))

        elif action == "fill":
            sel, text = args[0], args[1]
            text, vmeta, verr = _fill_secret(page, sel, text)
            if verr:
                print(json.dumps(verr))
                return 1
            resolve_locator(page, sel).fill(text, timeout=15000)
            out = {"ok": True, "filled": sel, "n": len(text)}
            if vmeta and vmeta.get("resolved"):
                out["vault"] = {
                    k: vmeta[k]
                    for k in ("ref", "backend", "chars", "origin_ok", "origin_reason")
                    if k in vmeta
                }
            print(json.dumps(out))

        elif action == "select":
            sel, value = args[0], args[1]
            value, vmeta, verr = _fill_secret(page, sel, value)
            if verr:
                print(json.dumps(verr))
                return 1
            page.select_option(sel, value, timeout=15000)
            out = {"ok": True, "selected": sel}
            if vmeta and vmeta.get("resolved"):
                out["vault"] = {
                    k: vmeta[k]
                    for k in ("ref", "backend", "chars", "origin_ok")
                    if k in vmeta
                }
            print(json.dumps(out))

        elif action == "login":
            rest = [a for a in args if a != "--no-submit"]
            submit = "--no-submit" not in args
            start_url = rest[0] if rest else None
            if start_url:
                start_url, err = _guard_nav_url(start_url)
                if err:
                    print(json.dumps(err))
                    return 1
                page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
            if wick_vault is None:
                print(json.dumps({"ok": False, "error": "vault_module_missing"}))
                return 1
            matched = wick_vault.match_url(page.url)
            hits = matched.get("matches") or []
            if not hits:
                print(json.dumps({
                    "ok": False,
                    "error": "no_vault_match",
                    "url": page.url,
                    "hint": "Save an entry with --url matching this origin: wick vault set NAME --url URL --username …",
                }))
                return 1
            m = hits[0]
            filled: list[str] = []
            refs: list[str] = []
            pw_css = wick_login_form.PASSWORD_CSS if wick_login_form else 'input[type="password"]'
            user_css = wick_login_form.USERNAME_CSS if wick_login_form else 'input[type="email"], input[type="text"]'
            otp_css = wick_login_form.OTP_CSS if wick_login_form else 'input[autocomplete="one-time-code"]'
            if m.get("username_ref"):
                loc = page.locator(user_css).first
                val, meta = wick_vault.resolve_for_fill(
                    m["username_ref"], reason="act_login", page_url=page.url
                )
                loc.fill(val, timeout=15000)
                filled.append("username")
                refs.append(meta.get("ref") or m["username_ref"])
            if m.get("password_ref"):
                loc = page.locator(pw_css).first
                val, meta = wick_vault.resolve_for_fill(
                    m["password_ref"], reason="act_login", page_url=page.url
                )
                loc.fill(val, timeout=15000)
                filled.append("password")
                refs.append(meta.get("ref") or m["password_ref"])
            if m.get("otp_ref"):
                loc = page.locator(otp_css)
                if loc.count() > 0:
                    val, meta = wick_vault.resolve_for_fill(
                        m["otp_ref"], reason="act_login", page_url=page.url
                    )
                    loc.first.fill(val, timeout=15000)
                    filled.append("otp")
                    refs.append(meta.get("ref") or m["otp_ref"])
            submitted = False
            if submit:
                try:
                    page.locator('button[type="submit"], input[type="submit"]').first.click(timeout=4000)
                    submitted = True
                except Exception:
                    try:
                        page.get_by_role("button", name=re.compile(r"log\s*in|sign\s*in|submit|continue", re.I)).first.click(timeout=4000)
                        submitted = True
                    except Exception:
                        submitted = False
            print(json.dumps({
                "ok": True,
                "action": "login",
                "url": page.url,
                "title": page.title(),
                "filled": filled,
                "refs": refs,
                "entry": m.get("name"),
                "origin_reason": m.get("reason"),
                "submitted": submitted,
                "vault": {"revealed": False, "chars": None},
            }))

        elif action == "check":
            page.check(args[0], timeout=15000)
            print(json.dumps({"ok": True, "checked": args[0]}))

        elif action == "press":
            page.keyboard.press(args[0])
            print(json.dumps({"ok": True, "pressed": args[0]}))

        elif action == "wait":
            page.wait_for_selector(args[0], timeout=30000)
            print(json.dumps({"ok": True, "waited": args[0]}))

        elif action == "wait_url":
            fragment = args[0]
            timeout = int(args[1]) if len(args) > 1 else 30000
            page.wait_for_function(
                "(f) => window.location.href.includes(f)",
                arg=fragment,
                timeout=timeout,
            )
            print(json.dumps({"ok": True, "url": page.url, "matched": fragment}))

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
            resolve_locator(page, args[0]).hover(timeout=15000)
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
