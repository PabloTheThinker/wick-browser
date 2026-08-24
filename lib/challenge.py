"""Detect human challenges (CAPTCHA / bot walls).

Cloud / headless: halt interact + secrets. Desktop computer-use (Hermes,
Grokbot, headed Chromium) may click/type the puzzle like a person. Vault
login, secret refs, and passkeys stay blocked until the challenge is gone.

Wick will not send puzzles to a third-party service.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})

HINT = (
    "A human must complete this challenge. Wick will not solve CAPTCHAs "
    "or click through bot walls."
)
HINT_COMPUTER_USE = (
    "Human challenge on the page. A desktop computer-use agent may complete "
    "it with wick act cu / click_xy / type. Vault login, secret fills, and "
    "passkeys stay blocked until it is gone. Wick will not send this puzzle "
    "to a third-party service."
)

SECRET_ACTIONS = frozenset(
    {"login", "passkey", "passkey_register", "eval", "download"}
)
INTERACT_ACTIONS = frozenset(
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

# Host / path / markup markers. Order matters: more specific kinds first.
_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("turnstile", ("cf-turnstile", "challenges.cloudflare.com", "turnstile")),
    ("hcaptcha", ("hcaptcha.com", "hcaptcha", "h-captcha")),
    ("recaptcha", ("google.com/recaptcha", "recaptcha/api", "g-recaptcha", "recaptcha")),
    ("funcaptcha", ("funcaptcha", "arkoselabs", "arkose")),
    ("geetest", ("geetest_holder", "geetest.com", "geetest")),
    ("friendlycaptcha", ("frc-captcha", "friendlycaptcha.com", "friendly-captcha")),
    ("aws_waf", ("token.awswaf.com", "awswaf.com/challenge", "aws-waf")),
    ("datadome", ("captcha-delivery.com", "datadome.co", "datadome")),
    ("perimeterx", ("px-captcha", "perimeterx")),
    ("cloudflare", ("just a moment", "cdn-cgi/challenge", "cf-browser-check", "cf-challenge")),
    ("captcha", ("captcha",)),
)

_BANNED_HINT_WORDS = ("2captcha", "anticaptcha", "solver", "bypass", "auto-submit")


def _norm_bool(raw: str | None) -> bool | None:
    if raw is None or not str(raw).strip():
        return None
    v = str(raw).strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


def halt_on_challenge() -> bool:
    """Default on. Env wins; policy file can pin it when env is unset."""
    env = _norm_bool(os.environ.get("WICK_HALT_ON_CHALLENGE"))
    if env is not None:
        return env
    try:
        import policy

        flag = policy.effective().get("halt_on_challenge")
        if isinstance(flag, bool):
            return flag
    except Exception:
        pass
    return True


def desktop_session() -> bool:
    """True on a real user seat or headed Chromium — not DISPLAY= plus Xvfb."""
    if _norm_bool(os.environ.get("WICK_HEADED")):
        return True
    if _norm_bool(os.environ.get("WICK_HEADLESS")) is False:
        return True
    if (os.environ.get("WAYLAND_DISPLAY") or "").strip():
        return True
    session = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    desktop = (
        os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("DESKTOP_SESSION")
        or ""
    ).strip()
    return session in ("wayland", "x11") and bool(desktop)


def computer_use_allowed() -> bool:
    """Desktop / Hermes / Grokbot may interact with a challenge widget."""
    env = _norm_bool(os.environ.get("WICK_CHALLENGE_COMPUTER_USE"))
    if env is not None:
        return env
    try:
        import policy

        if policy.effective().get("challenge_computer_use"):
            return True
    except Exception:
        pass
    return desktop_session()


def _blob(*parts: Any) -> str:
    chunks: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple)):
            for item in part:
                if isinstance(item, dict):
                    chunks.append(str(item.get("name") or ""))
                    chunks.append(str(item.get("href") or ""))
                    chunks.append(str(item.get("hint") or ""))
                else:
                    chunks.append(str(item))
        else:
            chunks.append(str(part))
    return " ".join(chunks).lower()


def detect(
    *,
    url: str | None = None,
    title: str | None = None,
    html: str | None = None,
    excerpt: str | None = None,
    elements: list[Any] | None = None,
) -> dict[str, Any]:
    """Return {found, kind, evidence, halt, computer_use, hint}. No solver advice."""
    host = ""
    path = ""
    if url:
        parsed = urlsplit(url if "://" in url else "https://" + url)
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "").lower()
    text = _blob(url, title, html, excerpt, elements, host, path)
    kind = None
    evidence = None
    for name, needles in _MARKERS:
        for needle in needles:
            if needle in text:
                kind = name
                evidence = needle
                break
        if kind:
            break
    found = kind is not None
    if kind == "captcha":
        title_l = (title or "").lower()
        widget = bool(
            re.search(
                r"""(?:type|name|id|class)\s*=\s*["']?[^"'>\s]*captcha""",
                text,
            )
        )
        if not widget and "captcha" not in title_l and "captcha" not in path:
            found = False
            kind = None
            evidence = None
    cu = computer_use_allowed()
    halt = bool(found) and halt_on_challenge()
    hint = None
    if found:
        hint = HINT_COMPUTER_USE if cu else HINT
    out: dict[str, Any] = {
        "found": found,
        "kind": kind if found else None,
        "evidence": evidence if found else None,
        "halt": halt,
        "computer_use": bool(found and cu),
        "error": "human_challenge" if halt else None,
        "hint": hint,
        "solves": False,
    }
    blob = " ".join(str(v) for v in out.values()).lower()
    for banned in _BANNED_HINT_WORDS:
        if banned in blob:
            out["hint"] = HINT_COMPUTER_USE if cu else HINT
    return out


def page_challenge(page) -> dict[str, Any]:
    """Inspect a live Chromium page, including iframe URLs (late-loaded widgets)."""
    url = title = html = ""
    frames: list[str] = []
    try:
        url = page.url
    except Exception:
        pass
    try:
        title = page.title()
    except Exception:
        pass
    try:
        html = page.content()[:40000]
    except Exception:
        html = ""
    try:
        for fr in getattr(page, "frames", []) or []:
            frames.append(str(getattr(fr, "url", "") or ""))
    except Exception:
        pass
    extra = " ".join(frames)
    return detect(url=url, title=title, html=(html + " " + extra).strip())


def probe(
    url: str,
    *,
    html: str | None = None,
    title: str | None = None,
    excerpt: str | None = None,
) -> dict[str, Any]:
    """Observe-only challenge detect. Never logs in. Never solves.

    Pass ``html`` for fixtures. Without it, GET the public URL (no cookies,
    no credentials). Private-network targets are refused.
    """
    base: dict[str, Any] = {
        "product": "wick",
        "mode": "observe",
        "login": False,
        "solves": False,
        "url": (url or "")[:240],
    }
    try:
        import origins as wick_origins

        if wick_origins.is_dangerous_url(url):
            return {**base, "ok": False, "error": "dangerous_url"}
        if wick_origins.is_private_url(url) and not wick_origins.allow_private_override():
            if html is None:
                return {**base, "ok": False, "error": "private_url"}
    except Exception:
        pass

    fetched = False
    page_html = html
    page_title = title
    if page_html is None:
        try:
            fetched_html, fetched_title = _fetch_public(url)
        except Exception as e:
            return {**base, "ok": False, "error": "fetch_failed", "detail": str(e)[:120]}
        page_html = fetched_html
        page_title = page_title or fetched_title
        fetched = True

    hit = detect(url=url, title=page_title, html=page_html, excerpt=excerpt)
    return {
        **base,
        **hit,
        "ok": True,
        "login": False,
        "solves": False,
        "mode": "observe",
        "fetched": fetched,
    }


def _fetch_public(url: str) -> tuple[str, str]:
    """GET public HTML. No cookie jar. No credentials. Timeout 12s."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Wick-observe/0.9 (+https://github.com/PabloTheThinker/wick-browser)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read(120000)
            final = str(getattr(resp, "url", "") or url)
    except urllib.error.HTTPError as e:
        raw = e.read(120000) if e.fp else b""
        final = url
        if e.code >= 500 and not raw:
            raise
    except Exception:
        raise
    try:
        import origins as wick_origins

        if wick_origins.is_private_url(final) and not wick_origins.allow_private_override():
            raise ValueError("private_url")
    except ImportError:
        pass
    text = raw.decode("utf-8", errors="replace")
    title = ""
    low = text.lower()
    i = low.find("<title")
    if i >= 0:
        j = low.find(">", i)
        k = low.find("</title>", j)
        if j >= 0 and k > j:
            title = re.sub(r"\s+", " ", text[j + 1 : k]).strip()[:160]
    return text, title


def wait_cleared(page, timeout_ms: int = 15000, interval_ms: int = 250) -> dict[str, Any] | None:
    """Poll until no challenge widget is visible. None = cleared. Last hit if not."""
    last = page_challenge(page)
    if not last.get("found"):
        return None
    deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000.0
    pause = max(0.005, int(interval_ms) / 1000.0)
    while time.monotonic() < deadline:
        time.sleep(pause)
        last = page_challenge(page)
        if not last.get("found"):
            return None
    return last


def deny_if_halted(
    hit: dict[str, Any] | None,
    action: str | None = None,
    *,
    secret: bool = False,
) -> dict[str, Any] | None:
    """Stop secret injection always; allow computer-use clicks when permitted."""
    if not hit or not hit.get("found") or not halt_on_challenge():
        return None
    act = (action or "").strip().lower()
    is_secret = secret or act in SECRET_ACTIONS
    if not is_secret and computer_use_allowed() and (not act or act in INTERACT_ACTIONS):
        return None
    if not is_secret and act and act not in INTERACT_ACTIONS and act not in SECRET_ACTIONS:
        return None
    return {
        "ok": False,
        "error": "human_challenge",
        "kind": hit.get("kind"),
        "evidence": hit.get("evidence"),
        "hint": HINT_COMPUTER_USE if computer_use_allowed() else HINT,
        "computer_use": computer_use_allowed(),
        "solves": False,
    }
