"""Detect human challenges (CAPTCHA / bot walls) and halt. Never solve them.

Wick will not click through, auto-submit, or send puzzles to a solver.
A harness that needs past a challenge must get a human — `wick approve`
or a headed session — not a bypass.
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlsplit

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})

HINT = (
    "A human must complete this challenge. Wick will not solve CAPTCHAs "
    "or click through bot walls."
)

# Host / path / markup markers. Order matters: more specific kinds first.
_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("turnstile", ("cf-turnstile", "challenges.cloudflare.com", "turnstile")),
    ("hcaptcha", ("hcaptcha.com", "hcaptcha", "h-captcha")),
    ("recaptcha", ("google.com/recaptcha", "recaptcha/api", "g-recaptcha", "recaptcha")),
    ("funcaptcha", ("funcaptcha", "arkoselabs", "arkose")),
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
    """Return {found, kind, evidence, halt, hint}. Never includes solver advice."""
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
    # A lone "captcha" word on a docs page is weak; require markup-ish context
    # unless it is a known vendor marker (already matched above).
    found = kind is not None
    # A lone "captcha" word on a docs / privacy page is not a widget.
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
    halt = bool(found) and halt_on_challenge()
    out: dict[str, Any] = {
        "found": found,
        "kind": kind if found else None,
        "evidence": evidence if found else None,
        "halt": halt,
        "error": "human_challenge" if halt else None,
        "hint": HINT if found else None,
        "solves": False,
    }
    blob = " ".join(str(v) for v in out.values()).lower()
    for banned in _BANNED_HINT_WORDS:
        if banned in blob:
            out["hint"] = HINT
    return out


def page_challenge(page) -> dict[str, Any]:
    """Inspect a live Chromium page. Best-effort; never throws into the caller."""
    url = title = html = ""
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
    return detect(url=url, title=title, html=html)


def deny_if_halted(hit: dict[str, Any] | None) -> dict[str, Any] | None:
    """Error object for chrome_actions when a challenge must stop the loop."""
    if not hit or not hit.get("halt"):
        return None
    return {
        "ok": False,
        "error": "human_challenge",
        "kind": hit.get("kind"),
        "evidence": hit.get("evidence"),
        "hint": HINT,
        "solves": False,
    }
