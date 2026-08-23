"""Post-action expectation guards for Chromium act.

Agents pass --expect-url-fragment and/or --expect-element after an action.
A click that "succeeds" but does not reach the next page is expect_failed.
"""
from __future__ import annotations

from typing import Any, Callable


def split_flags(args: list[str] | None) -> tuple[list[str], dict[str, str | None]]:
    raw = list(args or [])
    clean: list[str] = []
    url_fragment: str | None = None
    element: str | None = None
    i = 0
    while i < len(raw):
        tok = raw[i]
        if tok == "--expect-url-fragment" and i + 1 < len(raw):
            url_fragment = raw[i + 1]
            i += 2
            continue
        if tok == "--expect-element" and i + 1 < len(raw):
            element = raw[i + 1]
            i += 2
            continue
        clean.append(tok)
        i += 1
    return clean, {"url_fragment": url_fragment, "element": element}


def check(
    page: Any,
    expect: dict[str, str | None] | None,
    *,
    resolve_locator: Callable | None = None,
) -> dict[str, Any] | None:
    """Return an error payload if an expectation is unmet. None means ok."""
    exp = expect or {}
    frag = exp.get("url_fragment")
    url = getattr(page, "url", "") or ""
    if frag and frag not in url:
        return {
            "ok": False,
            "error": "expect_failed",
            "expect": "url_fragment",
            "wanted": frag,
            "url": url,
            "retryable": True,
            "hint": "Action ran but URL did not contain the expected fragment.",
        }
    sel = exp.get("element")
    if sel:
        try:
            loc = resolve_locator(page, sel) if resolve_locator is not None else page.locator(sel)
            first = loc.first if hasattr(loc, "first") else loc
            if hasattr(first, "is_visible"):
                first.is_visible(timeout=4000)
            elif hasattr(first, "wait_for"):
                first.wait_for(state="visible", timeout=4000)
            else:
                raise RuntimeError("no_visible_check")
        except Exception as e:
            return {
                "ok": False,
                "error": "expect_failed",
                "expect": "element",
                "wanted": sel,
                "detail": str(e)[:200],
                "url": url,
                "retryable": True,
                "hint": "Action ran but the expected element was not visible.",
            }
    return None
