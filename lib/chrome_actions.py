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
try:
    import computer_use as wick_cu
except Exception:
    wick_cu = None  # type: ignore

try:
    import act_expect as wick_expect
except Exception:
    wick_expect = None  # type: ignore
try:
    import approval as wick_approval
except Exception:
    wick_approval = None  # type: ignore
try:
    import passkey as wick_passkey
except Exception:
    wick_passkey = None  # type: ignore
try:
    import challenge as wick_challenge
except Exception:
    wick_challenge = None  # type: ignore
try:
    import elements as wick_elements
except Exception:
    wick_elements = None  # type: ignore
try:
    import page_read as wick_page_read
except Exception:
    wick_page_read = None  # type: ignore

_OBSERVE_JS = """() => {
  const skipName = (s) => {
    const t = (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    return !t || /^(skip\\b|main content|keyboard shortcuts)$/.test(t);
  };
  const isVisible = (el) => {
    if (!el) return false;
    if (el.closest('[aria-hidden="true"]')) return false;
    const st = window.getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };
  const inChrome = (el) => !!(el && el.closest('nav, header, footer, [role=navigation], [role=banner], [role=contentinfo]'));
  const pickMain = () => {
    const scored = [];
    const add = (el, bonus) => {
      if (!el) return;
      const t = ((el.innerText || '') + '').trim();
      if (t.length < 20) return;
      scored.push({el, score: t.length + bonus});
    };
    add(document.querySelector('#dp'), 8000);
    const article = document.querySelector('article');
    if (article && ((article.innerText || '').trim().length >= 400)) add(article, 6000);
    add(document.querySelector('[itemprop="articleBody"]'), 6000);
    add(document.querySelector('#mw-content-text'), 5000);
    add(document.querySelector('[role="main"]'), 4000);
    add(document.querySelector('main'), 4000);
    const search = document.querySelector('#search');
    if (search && search.querySelectorAll('a[href]').length >= 3) add(search, 7000);
    add(document.querySelector('#content, #main-content'), 2000);
    scored.sort((a, b) => b.score - a.score);
    return (scored[0] && scored[0].el) || document.body;
  };
  const main = pickMain();
  const text = ((main && main.innerText) || (document.body && document.body.innerText) || '').slice(0, 20000);
  const headings = [];
  const paragraphs = [];
  const sections = [];
  const paraRoot = main || document.body;
  let current = null;
  const startSection = (level, heading) => {
    current = {heading, level, paragraphs: []};
    sections.push(current);
    headings.push({level, text: heading.slice(0, 160)});
  };
  const addPara = (t) => {
    const slice = t.slice(0, 500);
    if (current && current.paragraphs.length < 8) current.paragraphs.push(slice);
    if (paragraphs.length < 24) paragraphs.push(slice);
  };
  for (const el of paraRoot.querySelectorAll('h1, h2, h3, p, li')) {
    if (!isVisible(el) || inChrome(el)) continue;
    const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!t) continue;
    if (/^H[123]$/.test(el.tagName)) {
      if (skipName(t) || headings.length >= 24) continue;
      startSection(parseInt(el.tagName[1], 10), t);
      continue;
    }
    if (t.length < 40) continue;
    addPara(t);
  }
  if (paragraphs.length < 3) {
    for (const card of paraRoot.querySelectorAll('article, [data-asin], .s-result-item')) {
      if (!isVisible(card) || inChrome(card)) continue;
      const t = (card.innerText || '').replace(/\\s+/g, ' ').trim();
      if (t.length < 16) continue;
      addPara(t.slice(0, 500));
      if (paragraphs.length >= 12) break;
    }
  }
  const title = document.title || '';
  const links = [];
  const seenHref = new Set();
  const addLink = (a) => {
    const href = a.href || '';
    if (!href || seenHref.has(href)) return;
    if (href.indexOf('javascript:') === 0) return;
    const t = (a.innerText || a.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim().slice(0, 120);
    if (skipName(t)) return;
    try {
      const u = new URL(href, location.href);
      if (u.pathname === location.pathname && u.search === location.search && u.hash) return;
    } catch (e) {}
    seenHref.add(href);
    links.push({ text: t, href });
  };
  const collectLinks = (root) => {
    if (!root) return;
    for (const a of root.querySelectorAll('a[href]')) {
      if (links.length >= 40) break;
      if (!isVisible(a)) continue;
      addLink(a);
    }
  };
  collectLinks(main);
  if (links.length < 12) collectLinks(document);
  const roleOf = (el) => {
    const r = (el.getAttribute('role') || '').toLowerCase();
    if (r) return r;
    const t = el.tagName.toLowerCase();
    if (t === 'a') return 'link';
    if (t === 'button') return 'button';
    if (t === 'textarea') return 'textbox';
    if (t === 'select') return 'combobox';
    if (t === 'input') {
      const ty = (el.getAttribute('type') || 'text').toLowerCase();
      if (ty === 'submit' || ty === 'button' || ty === 'reset') return 'button';
      if (ty === 'checkbox') return 'checkbox';
      if (ty === 'radio') return 'radio';
      if (ty === 'search') return 'searchbox';
      return 'textbox';
    }
    return t;
  };
  const nameOf = (el) => {
    const al = el.getAttribute('aria-label');
    if (al) return al.trim();
    if (el.labels && el.labels[0]) return (el.labels[0].innerText || '').trim();
    const ph = el.getAttribute('placeholder');
    if (ph) return ph.trim();
    return (el.innerText || el.value || el.getAttribute('name') || '').replace(/\\s+/g, ' ').trim();
  };
  const elements = [];
  const seenEl = new Set();
  const pushEl = (el) => {
    if (!el || seenEl.has(el) || elements.length >= 40) return;
    const role = roleOf(el);
    const name = nameOf(el).slice(0, 80);
    const keepHiddenSearch = role === 'searchbox' || (el.getAttribute && el.getAttribute('type') === 'search');
    if (!keepHiddenSearch && !isVisible(el)) return;
    if (role === 'link' && skipName(name)) return;
    seenEl.add(el);
    let hint = null;
    if (name) hint = 'role=' + role + '[name="' + name.replace(/"/g, '') + '"]';
    else if (el.id) hint = 'css=#' + el.id;
    elements.push({role, name, interactive: true, hint});
  };
  document.querySelectorAll(
    'input[type=search], [role=searchbox], input[name=field-keywords], #twotabsearchtextbox'
  ).forEach(pushEl);
  const sel = 'a[href], button, input, textarea, select, [role=button], [role=link], [role=textbox], [role=searchbox]';
  if (main) main.querySelectorAll(sel).forEach(pushEl);
  document.querySelectorAll(sel).forEach(pushEl);
  return {title, text, links, elements, headings, paragraphs, sections};
}"""


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


def parse_login_args(args: list[str]) -> dict:
    """Split login flags. `--after-challenge [ms]` waits for a widget to clear."""
    submit = True
    after = False
    timeout_ms = 15000
    rest: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--no-submit":
            submit = False
        elif tok == "--after-challenge":
            after = True
            if i + 1 < len(args) and str(args[i + 1]).isdigit():
                timeout_ms = max(1, int(args[i + 1]))
                i += 1
        else:
            rest.append(tok)
        i += 1
    return {
        "rest": rest,
        "submit": submit,
        "after_challenge": after,
        "timeout_ms": timeout_ms,
    }


def _wait_login_surface(page, timeout: int = 10000) -> None:
    try:
        page.wait_for_selector(
            'input[type="password"], input[type="email"], input[autocomplete="username"], '
            "#use, #use-passkey, #create-passkey, [data-wick-passkey]",
            timeout=timeout,
        )
    except Exception:
        pass


def _cdp_session(page):
    return page.context.new_cdp_session(page)


def _playwright_credentials(page):
    try:
        return page.context.credentials
    except Exception:
        return None


def _install_virtual_authenticator(page) -> tuple[object, str]:
    api = _playwright_credentials(page)
    if api is not None:
        try:
            api.install()
        except Exception:
            pass
        page.context._wick_authenticator_id = "playwright"
        return api, "playwright"
    session = _cdp_session(page)
    session.send("WebAuthn.enable")
    cached = getattr(page.context, "_wick_authenticator_id", None)
    if cached and cached != "playwright":
        return session, str(cached)
    res = session.send(
        "WebAuthn.addVirtualAuthenticator",
        {
            "options": {
                "protocol": "ctap2",
                "transport": "internal",
                "hasResidentKey": True,
                "hasUserVerification": True,
                "isUserVerified": True,
                "automaticPresenceSimulation": True,
            }
        },
    )
    aid = str((res or {}).get("authenticatorId") or "")
    if not aid:
        raise RuntimeError("virtual_authenticator_failed")
    page.context._wick_authenticator_id = aid
    return session, aid


def _add_vault_credential(page, cdp_cred: dict) -> None:
    api = _playwright_credentials(page)
    pub = str(cdp_cred.get("publicKey") or "")
    if api is not None and pub and wick_passkey is not None:
        pw = wick_passkey.to_playwright(
            {
                "rp_id": cdp_cred.get("rpId"),
                "credential_id": cdp_cred.get("credentialId"),
                "user_handle": cdp_cred.get("userHandle"),
                "private_key": cdp_cred.get("privateKey"),
                "public_key": pub,
            }
        )
        try:
            api.install()
        except Exception:
            pass
        if pw["id"] and pw["private_key"] and pw["public_key"]:
            api.create(
                pw["rp_id"],
                id=pw["id"],
                user_handle=pw["user_handle"],
                private_key=pw["private_key"],
                public_key=pw["public_key"],
            )
            return
    session, aid = _install_virtual_authenticator(page)
    if aid == "playwright":
        raise RuntimeError("virtual_authenticator_failed")
    payload = {k: v for k, v in cdp_cred.items() if k != "publicKey"}
    session.send(
        "WebAuthn.addCredential",
        {"authenticatorId": aid, "credential": payload},
    )


def _click_passkey_button(page, *, register: bool = False) -> bool:
    if register:
        patterns = (
            r"create (a )?passkey",
            r"register (a )?passkey",
            r"set up (a )?passkey",
            r"add (a )?passkey",
            r"create",
        )
        css = ("#create", "#create-passkey", "#reg", "[data-wick-passkey-register]")
    else:
        patterns = (
            r"use (a |saved )?passkey",
            r"sign in with (a )?passkey",
            r"continue with (a )?passkey",
            r"passkey",
            r"use security key",
        )
        css = ("#use", "#use-passkey", "[data-wick-passkey]")
    for pat in patterns:
        try:
            page.get_by_role("button", name=re.compile(pat, re.I)).first.click(timeout=2500)
            return True
        except Exception:
            continue
    for sel in css:
        try:
            page.locator(sel).first.click(timeout=1500)
            return True
        except Exception:
            continue
    return False


def _cred_obj_to_dict(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    return {
        "id": getattr(raw, "id", None),
        "rpId": getattr(raw, "rp_id", None) or getattr(raw, "rpId", None),
        "userHandle": getattr(raw, "user_handle", None) or getattr(raw, "userHandle", None),
        "privateKey": getattr(raw, "private_key", None) or getattr(raw, "privateKey", None),
        "publicKey": getattr(raw, "public_key", None) or getattr(raw, "publicKey", None),
    }


def _scrub_passkey_export(exported: dict) -> dict:
    """Drop privateKey before any JSON that might reach an agent."""
    out = {k: v for k, v in exported.items() if k != "credential"}
    return out


def _locator_visible(locator) -> bool:
    try:
        return bool(locator.count() > 0 and locator.first.is_visible())
    except Exception:
        return False


def _fill_visible(locator, value: str, timeout: int = 15000) -> None:
    """Wait visible, focus, fill; retry once on timeout/detached."""
    last: Exception | None = None
    for _attempt in range(2):
        try:
            target = locator.first
            target.wait_for(state="visible", timeout=timeout)
            try:
                target.focus()
            except Exception:
                pass
            target.fill(value, timeout=timeout)
            return
        except Exception as e:
            last = e
    if last is not None:
        raise last


def _click_login_step(page) -> bool:
    """Advance a two-step login (Continue / Next) so the password field appears."""
    names = getattr(wick_login_form, "STEP_BUTTON_NAMES", ("Continue", "Next")) if wick_login_form else ("Continue", "Next")
    for name in names:
        try:
            page.get_by_role("button", name=re.compile(rf"^{name}$", re.I)).first.click(timeout=2500)
            return True
        except Exception:
            continue
    for sel in ("#continue", "#next", "button[name=continue]", "button[name=next]"):
        try:
            page.locator(sel).first.click(timeout=1500)
            return True
        except Exception:
            continue
    return False


def _wait_after_submit(page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=8000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass


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
    raw = (sel or "").strip()
    m = ROLE_SEL_RE.match(raw)
    if m:
        role, name1, name2 = m.groups()
        name = name1 if name1 is not None else name2
        kwargs = {"name": name} if name else {}
        loc = page.get_by_role(role, **kwargs)
        # HTML type=search is ARIA searchbox. Older snaps emitted textbox.
        if role == "textbox":
            loc = loc.or_(page.get_by_role("searchbox", **kwargs))
        elif role == "searchbox":
            loc = loc.or_(page.get_by_role("textbox", **kwargs))
        return loc
    if raw.startswith("css="):
        return page.locator(raw[4:])
    if raw.startswith("text="):
        return page.get_by_text(raw[5:])
    return page.locator(raw)


# Secret injection always halts on a challenge. Click/type may proceed when
# a desktop computer-use agent (Hermes / Grokbot) is allowed to complete it.
_CHALLENGE_SECRET = frozenset({"eval", "download"})
_CHALLENGE_INTERACT = frozenset(
    {
        "click",
        "click_n",
        "click_xy",
        "dblclick",
        "doubleclick",
        "rightclick",
        "contextclick",
        "type",
        "type_n",
        "fill",
        "select",
        "check",
        "press",
        "key",
        "drag",
        "move",
        "hover",
        "scroll_xy",
    }
)


def _secret_text_for_action(action: str, args: list[str]) -> str:
    if action in ("fill", "select") and len(args) > 1:
        return args[1]
    if action == "type_n" and len(args) > 1:
        return args[1]
    if action == "type" and args:
        return args[0]
    return ""


def _challenge_halt(page, action: str, *, secret: bool = False) -> dict | None:
    if wick_challenge is None:
        return None
    return wick_challenge.deny_if_halted(
        wick_challenge.page_challenge(page), action=action, secret=secret
    )


def _dispatch(page, ctx, action: str, args: list[str]) -> tuple[int, dict]:
    if action in _CHALLENGE_SECRET or action in _CHALLENGE_INTERACT:
        secret = action in _CHALLENGE_SECRET
        text = _secret_text_for_action(action, args)
        if (
            not secret
            and text
            and wick_vault is not None
            and wick_vault.is_secret_ref(text)
        ):
            secret = True
        blocked = _challenge_halt(page, action, secret=secret)
        if blocked:
            return 1, blocked
    if action == "goto":
        url, err = _guard_nav_url(args[0])
        if err:
            return 1, err
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        out: dict = {"ok": True, "url": page.url, "title": page.title()}
        if wick_challenge is not None:
            hit = wick_challenge.page_challenge(page)
            if hit.get("found"):
                out["challenge"] = hit
        return 0, out

    elif action == "click" and wick_cu is not None and wick_cu.looks_like_xy(args):
        x, y = wick_cu.parse_xy(args)
        page.mouse.click(x, y)
        return 0, {"ok": True, "clicked": "xy", "x": x, "y": y, "url": page.url}

    elif action in ("click", "click_n") and wick_cu is not None and wick_cu.parse_n(args) is not None and (
        action == "click_n"
        or str(args[0]).startswith(("n=", "#"))
        or wick_cu.resolve_n(wick_cu.parse_n(args), wick_cu.load_last_state()) is not None
    ):
        n = wick_cu.parse_n(args)
        if n is None:
            return 2, {"ok": False, "error": "need_n", "hint": "wick act click_n 3"}
        state = wick_cu.load_last_state()
        el = wick_cu.resolve_n(n, state)
        if not el or el.get("cx") is None or el.get("cy") is None:
            return 1, {
                "ok": False,
                "error": "unknown_n",
                "n": n,
                "hint": "Run wick act cu first, then wick act click_n N",
            }
        x, y = float(el["cx"]), float(el["cy"])
        page.mouse.click(x, y)
        stale = bool(state and state.get("url") and state.get("url") != page.url)
        return 0, {
            "ok": True,
            "clicked": "n",
            "n": n,
            "x": x,
            "y": y,
            "name": el.get("name"),
            "role": el.get("role"),
            "stale": stale,
            "url": page.url,
        }

    elif action == "click":
        sel = args[0]
        resolve_locator(page, sel).click(timeout=15000)
        return 0, {"ok": True, "clicked": sel, "url": page.url}

    elif action == "click_xy":
        if wick_cu is None or not wick_cu.looks_like_xy(args):
            return 2, {"ok": False, "error": "need_x_y", "hint": "wick act click_xy 120 340"}
        x, y = wick_cu.parse_xy(args)
        page.mouse.click(x, y)
        return 0, {"ok": True, "clicked": "xy", "x": x, "y": y, "url": page.url}

    elif action in ("dblclick", "doubleclick"):
        if wick_cu is not None and wick_cu.looks_like_xy(args):
            x, y = wick_cu.parse_xy(args)
            page.mouse.dblclick(x, y)
            return 0, {"ok": True, "dblclicked": "xy", "x": x, "y": y, "url": page.url}
        else:
            resolve_locator(page, args[0]).dblclick(timeout=15000)
            return 0, {"ok": True, "dblclicked": args[0], "url": page.url}

    elif action in ("rightclick", "contextclick"):
        if wick_cu is not None and wick_cu.looks_like_xy(args):
            x, y = wick_cu.parse_xy(args)
            page.mouse.click(x, y, button="right")
            return 0, {"ok": True, "rightclicked": "xy", "x": x, "y": y, "url": page.url}
        else:
            resolve_locator(page, args[0]).click(timeout=15000, button="right")
            return 0, {"ok": True, "rightclicked": args[0], "url": page.url}

    elif action == "move":
        if wick_cu is None or not wick_cu.looks_like_xy(args):
            return 2, {"ok": False, "error": "need_x_y"}
        x, y = wick_cu.parse_xy(args)
        page.mouse.move(x, y)
        return 0, {"ok": True, "moved": [x, y], "url": page.url}

    elif action == "drag":
        if wick_cu is None or len(args) < 4:
            return 2, {"ok": False, "error": "need_x1_y1_x2_y2"}
        x1, y1 = float(args[0]), float(args[1])
        x2, y2 = float(args[2]), float(args[3])
        page.mouse.move(x1, y1)
        page.mouse.down()
        page.mouse.move(x2, y2, steps=8)
        page.mouse.up()
        return 0, {"ok": True, "dragged": [x1, y1, x2, y2], "url": page.url}

    elif action == "type":
        text = args[0] if args else ""
        if wick_vault is not None and wick_vault.is_secret_ref(text):
            text, vmeta, verr = _fill_secret(page, "", text)
            if verr:
                return 1, verr
        else:
            vmeta = None
        page.keyboard.type(text, delay=15)
        out = {"ok": True, "typed": True, "n": len(text), "url": page.url}
        if vmeta and vmeta.get("resolved"):
            out["vault"] = {k: vmeta[k] for k in ("ref", "backend", "chars", "origin_ok") if k in vmeta}
        return 0, out

    elif action == "type_n":
        if wick_cu is None:
            return 1, {"ok": False, "error": "computer_use_missing"}
        n = wick_cu.parse_n(args)
        if n is None:
            return 2, {"ok": False, "error": "need_n", "hint": "wick act type_n 3 hello"}
        state = wick_cu.load_last_state()
        el = wick_cu.resolve_n(n, state)
        if not el or el.get("cx") is None or el.get("cy") is None:
            return 1, {
                "ok": False,
                "error": "unknown_n",
                "n": n,
                "hint": "Run wick act cu first, then wick act type_n N TEXT",
            }
        text = args[1] if len(args) > 1 else ""
        if wick_vault is not None and wick_vault.is_secret_ref(text):
            text, vmeta, verr = _fill_secret(page, "", text)
            if verr:
                return 1, verr
        else:
            vmeta = None
        x, y = float(el["cx"]), float(el["cy"])
        page.mouse.click(x, y)
        page.keyboard.type(text, delay=15)
        out = {
            "ok": True,
            "typed": True,
            "target_n": n,
            "chars": len(text),
            "x": x,
            "y": y,
            "url": page.url,
        }
        if vmeta and vmeta.get("resolved"):
            out["vault"] = {k: vmeta[k] for k in ("ref", "backend", "chars", "origin_ok") if k in vmeta}
        return 0, out

    elif action == "wait_text":
        text = args[0]
        timeout = int(args[1]) if len(args) > 1 else 15000
        page.get_by_text(text).first.wait_for(state="visible", timeout=timeout)
        return 0, {"ok": True, "waited_text": text, "url": page.url}

    elif action == "wait_visible":
        sel = args[0]
        timeout = int(args[1]) if len(args) > 1 else 15000
        resolve_locator(page, sel).wait_for(state="visible", timeout=timeout)
        return 0, {"ok": True, "waited": sel, "url": page.url}

    elif action == "dialog":
        mode = (args[0] if args else "accept").lower()
        prompt = args[1] if len(args) > 1 else ""

        def _on_dialog(d):
            if mode in ("dismiss", "cancel"):
                d.dismiss()
            else:
                d.accept(prompt)

        page.once("dialog", _on_dialog)
        return 0, {"ok": True, "dialog": mode, "armed": True, "hint": "Next alert/confirm/prompt will be handled."}

    elif action in ("cu", "computer", "a11y"):
        raw: dict = {}
        if wick_cu is not None:
            try:
                raw = page.evaluate(wick_cu.A11Y_JS) or {}
            except Exception:
                raw = {}
        if not isinstance(raw, dict):
            raw = {}
        numbered = wick_cu.number_targets(list(raw.get("elements") or [])) if wick_cu else []
        shot = None
        annotated = None
        if action != "a11y":
            dest = Path(
                args[0]
                if args
                else str(Path(os.environ.get("WICK_HOME") or Path.home() / ".wick") / "shots" / "cu.png")
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(dest), full_page=False)
            shot = str(dest)
            if wick_cu is not None and numbered:
                ann = dest.with_name(f"{dest.stem}-boxes{dest.suffix}")
                try:
                    page.evaluate(wick_cu.OVERLAY_INSTALL_JS, numbered)
                    page.screenshot(path=str(ann), full_page=False)
                    annotated = str(ann)
                except Exception:
                    annotated = None
                finally:
                    try:
                        page.evaluate(wick_cu.OVERLAY_REMOVE_JS)
                    except Exception:
                        pass
        if wick_cu is None:
            return 0, {"ok": True, "url": page.url, "title": page.title(), "screenshot": shot, "elements": []}
        else:
            payload = wick_cu.build_cu_payload(
                url=page.url,
                title=page.title(),
                screenshot=shot,
                raw=raw,
                annotated=annotated,
            )
            wick_cu.save_last_state(payload)
            return 0, payload

    elif action == "fill":
        sel, text = args[0], args[1]
        text, vmeta, verr = _fill_secret(page, sel, text)
        if verr:
            return 1, verr
        _fill_visible(resolve_locator(page, sel), text)
        out = {"ok": True, "filled": sel, "n": len(text)}
        if vmeta and vmeta.get("resolved"):
            out["vault"] = {
                k: vmeta[k]
                for k in ("ref", "backend", "chars", "origin_ok", "origin_reason")
                if k in vmeta
            }
        return 0, out

    elif action == "select":
        sel, value = args[0], args[1]
        value, vmeta, verr = _fill_secret(page, sel, value)
        if verr:
            return 1, verr
        page.select_option(sel, value, timeout=15000)
        out = {"ok": True, "selected": sel}
        if vmeta and vmeta.get("resolved"):
            out["vault"] = {
                k: vmeta[k]
                for k in ("ref", "backend", "chars", "origin_ok")
                if k in vmeta
            }
        return 0, out

    elif action == "login":
        flags = parse_login_args(args)
        rest = flags["rest"]
        submit = flags["submit"]
        start_url = rest[0] if rest else None
        if start_url:
            start_url, err = _guard_nav_url(start_url)
            if err:
                return 1, err
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
        _wait_login_surface(page)
        if flags["after_challenge"] and wick_challenge is not None:
            still = wick_challenge.wait_cleared(page, timeout_ms=flags["timeout_ms"])
            if still and still.get("found"):
                blocked = wick_challenge.deny_if_halted(still, action="login", secret=True)
                if blocked:
                    blocked = dict(blocked)
                    blocked["after_challenge"] = True
                    blocked["waited_ms"] = flags["timeout_ms"]
                    return 1, blocked
        blocked = _challenge_halt(page, "login", secret=True)
        if blocked:
            return 1, blocked
        if wick_vault is None:
            return 1, {"ok": False, "error": "vault_module_missing"}
        matched = wick_vault.match_url(page.url)
        hits = matched.get("matches") or []
        if not hits:
            return 1, {
                "ok": False,
                "error": "no_vault_match",
                "url": page.url,
                "hint": "Save an entry with --url matching this origin: wick vault set NAME --url URL --username …",
            }
        m = hits[0]
        if m.get("has_passkey"):
            exported = wick_vault.export_passkey_for_cdp(m["name"], page.url)
            if exported.get("ok") and exported.get("credential"):
                try:
                    _add_vault_credential(page, exported["credential"])
                    if _click_passkey_button(page):
                        return 0, {
                            "ok": True,
                            "action": "login",
                            "via": "passkey",
                            "url": page.url,
                            "title": page.title(),
                            "entry": m.get("name"),
                            "origin_reason": m.get("reason"),
                            "filled": [],
                            "refs": [m.get("passkey_ref") or f"vault://{m.get('name')}/passkey"],
                            "submitted": True,
                            "after_challenge": bool(flags["after_challenge"]),
                            "vault": {"revealed": False, "chars": None},
                        }
                except Exception:
                    pass
        filled: list[str] = []
        refs: list[str] = []
        pw_css = wick_login_form.PASSWORD_CSS if wick_login_form else 'input[type="password"]'
        user_css = wick_login_form.USERNAME_CSS if wick_login_form else 'input[type="email"], input[type="text"]'
        otp_css = wick_login_form.OTP_CSS if wick_login_form else 'input[autocomplete="one-time-code"]'
        if m.get("username_ref"):
            loc = page.locator(user_css)
            val, meta = wick_vault.resolve_for_fill(
                m["username_ref"], reason="act_login", page_url=page.url
            )
            _fill_visible(loc, val)
            filled.append("username")
            refs.append(meta.get("ref") or m["username_ref"])
        pw_loc = page.locator(pw_css)
        need_step = wick_login_form.needs_password_step(
            username_filled="username" in filled,
            password_visible=_locator_visible(pw_loc),
        ) if wick_login_form is not None else (
            "username" in filled and not _locator_visible(pw_loc)
        )
        if m.get("password_ref") and need_step:
            if _click_login_step(page):
                try:
                    pw_loc.first.wait_for(state="visible", timeout=8000)
                except Exception:
                    pass
        if m.get("password_ref"):
            val, meta = wick_vault.resolve_for_fill(
                m["password_ref"], reason="act_login", page_url=page.url
            )
            _fill_visible(pw_loc, val)
            filled.append("password")
            refs.append(meta.get("ref") or m["password_ref"])
        if m.get("otp_ref"):
            loc = page.locator(otp_css)
            if loc.count() > 0:
                val, meta = wick_vault.resolve_for_fill(
                    m["otp_ref"], reason="act_login", page_url=page.url
                )
                _fill_visible(loc, val)
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
            if submitted:
                _wait_after_submit(page)
        return 0, {
            "ok": True,
            "action": "login",
            "url": page.url,
            "title": page.title(),
            "filled": filled,
            "refs": refs,
            "entry": m.get("name"),
            "origin_reason": m.get("reason"),
            "submitted": submitted,
            "after_challenge": bool(flags["after_challenge"]),
            "vault": {"revealed": False, "chars": None},
        }

    elif action == "check":
        page.check(args[0], timeout=15000)
        return 0, {"ok": True, "checked": args[0]}

    elif action in ("press", "key"):
        raw_key = args[0] if args else "Enter"
        key = wick_cu.normalize_key(raw_key) if wick_cu is not None else raw_key
        page.keyboard.press(key)
        return 0, {"ok": True, "pressed": key, "url": page.url}

    elif action == "scroll_xy":
        if wick_cu is None or not wick_cu.looks_like_xy(args):
            return 2, {"ok": False, "error": "need_x_y", "hint": "wick act scroll_xy 120 340 400"}
        x, y = wick_cu.parse_xy(args)
        dy = int(float(args[2])) if len(args) > 2 else 400
        page.mouse.move(x, y)
        page.mouse.wheel(0, dy)
        return 0, {"ok": True, "scrolled_xy": [x, y], "amount": dy, "url": page.url}

    elif action == "wait":
        page.wait_for_selector(args[0], timeout=30000)
        return 0, {"ok": True, "waited": args[0]}

    elif action == "wait_url":
        fragment = args[0]
        timeout = int(args[1]) if len(args) > 1 else 30000
        page.wait_for_function(
            "(f) => window.location.href.includes(f)",
            arg=fragment,
            timeout=timeout,
        )
        return 0, {"ok": True, "url": page.url, "matched": fragment}

    elif action == "eval":
        val = page.evaluate(args[0])
        return 0, {"ok": True, "result": val}

    elif action == "observe":
        start_url = args[0] if args else None
        dump = (args[1] if len(args) > 1 else "markdown") or "markdown"
        max_chars = int(args[2]) if len(args) > 2 else 12000
        wait_ms = int(args[3]) if len(args) > 3 else 1200
        if wick_origins is not None:
            here = wick_origins.is_here_url(start_url)
        else:
            here = (not start_url) or str(start_url).strip() in {".", "here", "--here"}
        reused = False
        if here:
            live = page.url or ""
            blank = (not live) or live.startswith("about:") or "chrome://new" in live.lower()
            if blank:
                return 1, {
                    "ok": False,
                    "error": "no_current_page",
                    "url": live,
                    "hint": "wick act goto URL first, then wick snap",
                }
            reused = True
        elif start_url:
            start_url, err = _guard_nav_url(start_url)
            if err:
                return 1, err
            live = page.url or ""
            if wick_origins is not None and wick_origins.same_observe_target(live, start_url):
                reused = True
            else:
                page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
                try:
                    page.wait_for_timeout(max(0, min(wait_ms, 4000)))
                except Exception:
                    pass
        data: dict = {}
        try:
            data = page.evaluate(_OBSERVE_JS) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        title = str(data.get("title") or page.title() or "")
        text = str(data.get("text") or "")
        links = data.get("links") if isinstance(data.get("links"), list) else []
        raw_els = data.get("elements") if isinstance(data.get("elements"), list) else []
        elements: list[dict] = []
        for i, el in enumerate(raw_els[:40], start=1):
            if not isinstance(el, dict):
                continue
            role = str(el.get("role") or "generic")
            name = str(el.get("name") or "")
            hint = el.get("hint")
            if not hint and wick_elements is not None:
                hint = wick_elements._hint(role, name)
            elif not hint and name:
                hint = f'role={role}[name="{name}"]'
            item = {
                "id": i,
                "role": role,
                "name": name,
                "interactive": True,
                "hint": hint,
            }
            elements.append(item)
        if wick_elements is not None:
            tree = wick_elements.tree_from_elements(title, elements)
            md = wick_elements.markdown_from_observe(title, text, links)
        else:
            tree = f"1 document '{title.replace(chr(39), '')}'"
            md = (f"# {title}\n\n" if title else "") + text
        html = ""
        if dump == "html":
            try:
                html = page.content()
            except Exception:
                html = ""
        if dump == "semantic_tree_text":
            content = tree[:max_chars]
        elif dump == "html":
            content = html[:max_chars]
        else:
            content = md[:max_chars]
        raw_headings = data.get("headings") if isinstance(data.get("headings"), list) else []
        raw_paras = data.get("paragraphs") if isinstance(data.get("paragraphs"), list) else []
        raw_sections = data.get("sections") if isinstance(data.get("sections"), list) else []
        payload = {
            "ok": True,
            "url": page.url,
            "title": title,
            "http_ok": True,
            "http_status": 200,
            "dump": dump,
            "chars": len(content),
            "content": content,
            "text": text,
            "excerpt": re.sub(r"\s+", " ", text).strip()[:600],
            "links": links[:25],
            "elements": elements,
            "headings": raw_headings[:24],
            "paragraphs": raw_paras[:24],
            "sections": raw_sections[:16],
            "engine": "chromium",
            "reused": reused,
        }
        if wick_page_read is not None:
            shaped = wick_page_read.shape_observe(payload, excerpt_len=600)
            if shaped.get("excerpt"):
                payload["excerpt"] = shaped["excerpt"]
            payload["kind"] = shaped.get("kind")
            payload["headings"] = shaped.get("headings") or payload["headings"]
            payload["paragraphs"] = shaped.get("paragraphs") or payload["paragraphs"]
            payload["sections"] = shaped.get("sections") or payload["sections"]
        return 0, payload

    elif action == "content":
        text = page.inner_text("body")
        lim = int(args[0]) if args else 12000
        return 0, {
            "ok": True, "url": page.url, "title": page.title(),
            "chars": len(text), "content": text[:lim],
        }

    elif action == "title":
        return 0, {"ok": True, "url": page.url, "title": page.title()}

    elif action == "back":
        page.go_back(timeout=30000)
        return 0, {"ok": True, "url": page.url, "title": page.title()}

    elif action == "forward":
        page.go_forward(timeout=30000)
        return 0, {"ok": True, "url": page.url, "title": page.title()}

    elif action == "reload":
        page.reload(wait_until="domcontentloaded", timeout=60000)
        return 0, {"ok": True, "url": page.url, "title": page.title()}

    elif action == "tab_new":
        url = args[0] if args else "about:blank"
        p2 = ctx.new_page()
        if url and url != "about:blank":
            p2.goto(url, wait_until="domcontentloaded", timeout=60000)
        return 0, {"ok": True, "tabs": pages_info(ctx), "active": len(ctx.pages) - 1}

    elif action == "tab_list":
        return 0, {"ok": True, "tabs": pages_info(ctx)}

    elif action == "tab_switch":
        idx = int(args[0])
        if idx < 0 or idx >= len(ctx.pages):
            return 1, {"ok": False, "error": "bad_index", "tabs": pages_info(ctx)}
        p2 = ctx.pages[idx]
        p2.bring_to_front()
        return 0, {"ok": True, "index": idx, "url": p2.url, "title": p2.title()}

    elif action == "tab_close":
        idx = int(args[0]) if args else len(ctx.pages) - 1
        if idx < 0 or idx >= len(ctx.pages):
            return 1, {"ok": False, "error": "bad_index"}
        if len(ctx.pages) <= 1:
            return 1, {"ok": False, "error": "cannot_close_last_tab"}
        ctx.pages[idx].close()
        return 0, {"ok": True, "tabs": pages_info(ctx)}

    elif action == "pdf":
        out = Path(args[0] if args else str(Path.home() / ".wick" / "downloads" / "page.pdf"))
        out.parent.mkdir(parents=True, exist_ok=True)
        page.pdf(path=str(out), format="A4", print_background=True)
        return 0, {"ok": True, "path": str(out), "bytes": out.stat().st_size}

    elif action == "screenshot":
        out = Path(args[0] if args else str(Path.home() / ".wick" / "shots" / "page.png"))
        out.parent.mkdir(parents=True, exist_ok=True)
        full = (args[1] == "full") if len(args) > 1 else False
        page.screenshot(path=str(out), full_page=full)
        return 0, {"ok": True, "path": str(out), "bytes": out.stat().st_size}

    elif action == "download":
        url, err = _guard_nav_url(args[0])
        if err:
            return 1, err
        url = url or args[0]
        out_dir = Path(args[1] if len(args) > 1 else os.environ.get("WICK_DOWNLOADS") or str(Path.home() / ".wick" / "downloads"))
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            with page.expect_download(timeout=15000) as di:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            dl = di.value
            dest = out_dir / (dl.suggested_filename or "download.bin")
            dl.save_as(str(dest))
            return 0, {"ok": True, "path": str(dest), "filename": dest.name}
        except Exception:
            resp = page.request.get(url)
            body = resp.body()
            name = url.rstrip("/").split("/")[-1].split("?")[0] or "download.bin"
            dest = out_dir / name
            dest.write_bytes(body)
            return 0, {"ok": True, "path": str(dest), "bytes": len(body), "via": "request"}

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
        return 0, {"ok": True, "scrolled": direction, "amount": amount, "url": page.url}

    elif action == "hover":
        resolve_locator(page, args[0]).hover(timeout=15000)
        return 0, {"ok": True, "hovered": args[0]}

    elif action == "cookies":
        return 0, {"ok": True, "cookies": ctx.cookies()}

    elif action == "passkey":
        rest = list(args)
        start_url = rest[0] if rest else None
        name = rest[1] if len(rest) > 1 else None
        if start_url:
            start_url, err = _guard_nav_url(start_url)
            if err:
                return 1, err
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
        _wait_login_surface(page)
        blocked = _challenge_halt(page, "passkey", secret=True)
        if blocked:
            return 1, blocked
        if wick_vault is None:
            return 1, {"ok": False, "error": "vault_module_missing"}
        if not name:
            matched = wick_vault.match_url(page.url)
            hits = [h for h in (matched.get("matches") or []) if h.get("has_passkey")]
            if not hits:
                return 1, {
                    "ok": False,
                    "error": "no_vault_match",
                    "url": page.url,
                    "hint": "wick vault passkey-new NAME --url URL",
                }
            name = hits[0]["name"]
        exported = wick_vault.export_passkey_for_cdp(name, page.url)
        if not exported.get("ok"):
            return 1, _scrub_passkey_export(exported)
        cred = exported.get("credential")
        if not cred:
            return 1, {"ok": False, "error": "no_passkey", "name": name}
        try:
            _add_vault_credential(page, cred)
        except Exception as e:
            return 1, {"ok": False, "error": "virtual_authenticator_failed", "detail": str(e)[:160]}
        clicked = _click_passkey_button(page)
        return 0, {
            "ok": True,
            "action": "passkey",
            "url": page.url,
            "title": page.title(),
            "entry": name,
            "clicked": clicked,
            "used_virtual_authenticator": True,
            "vault": {"revealed": False, "chars": None},
        }

    elif action == "passkey_register":
        rest = list(args)
        start_url = rest[0] if rest else None
        name = rest[1] if len(rest) > 1 else None
        if start_url:
            start_url, err = _guard_nav_url(start_url)
            if err:
                return 1, err
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
        _wait_login_surface(page)
        blocked = _challenge_halt(page, "passkey_register", secret=True)
        if blocked:
            return 1, blocked
        if wick_vault is None:
            return 1, {"ok": False, "error": "vault_module_missing"}
        try:
            session, aid = _install_virtual_authenticator(page)
        except Exception as e:
            return 1, {"ok": False, "error": "virtual_authenticator_failed", "detail": str(e)[:160]}
        clicked = _click_passkey_button(page, register=True)
        creds: list = []
        try:
            page.wait_for_timeout(800)
            if aid == "playwright":
                got = session.get()
                creds = [_cred_obj_to_dict(c) for c in (got or [])]
            else:
                raw = session.send("WebAuthn.getCredentials", {"authenticatorId": aid}) or {}
                creds = list(raw.get("credentials") or [])
        except Exception:
            creds = []
        if not creds:
            return 1, {
                "ok": False,
                "error": "no_credential_created",
                "clicked": clicked,
                "hint": "Page must call navigator.credentials.create after the Create click",
            }
        raw_cred = creds[-1]
        if not isinstance(raw_cred, dict):
            return 1, {"ok": False, "error": "no_credential_created"}
        if not name:
            host = ""
            if wick_passkey is not None:
                host = wick_passkey.rp_id_from_url(page.url) or ""
            name = f"passkey-{host or 'site'}"
        saved = wick_vault.save_passkey_from_cdp(name, page.url, raw_cred)
        return (0 if saved.get("ok") else 1), {
            **{k: v for k, v in saved.items() if k != "credential"},
            "action": "passkey_register",
            "url": page.url,
            "clicked": clicked,
            "revealed": False,
        }

    else:
        return 2, {"ok": False, "error": f"unknown_action {action}"}


def run_on_page(page, ctx, action: str, raw_args: list[str] | None = None) -> tuple[int, dict]:
    """Dispatch one Chromium action against an existing page (tests + CLI)."""
    if wick_approval is not None:
        denied = wick_approval.check(action)
        if denied:
            return 1, denied
    raw = list(raw_args or [])
    if wick_expect is not None:
        args, expect = wick_expect.split_flags(raw)
    else:
        args, expect = raw, {"url_fragment": None, "element": None}
    try:
        rc, out = _dispatch(page, ctx, action, args)
    except Exception as e:
        url = ""
        try:
            url = page.url
        except Exception:
            pass
        if wick_cu is not None:
            return 1, wick_cu.fail_payload(action, e, url=url)
        return 1, {"ok": False, "error": "action_failed", "action": action, "detail": str(e)[:300]}
    if not isinstance(out, dict):
        out = {"ok": True, "result": out}
    if rc == 0 and out.get("ok") and wick_expect is not None:
        err = wick_expect.check(page, expect, resolve_locator=resolve_locator)
        if err:
            return 1, err
        flagged = {k: v for k, v in expect.items() if v}
        if flagged:
            out = dict(out)
            out["expect"] = flagged
    return rc, out


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
        rc, out = run_on_page(page, ctx, action, args)
        print(json.dumps(out, default=str))
        return rc
    finally:
        try:
            pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
