"""Chromium request + file guards for agent safety.

Composes origins (SSRF / dangerous URL) with a small built-in tracker
substring list and optional ~/.wick/shields/wick-block-urls.txt.

EasyList files are still download-only. This module applies only:
  - private / metadata / dangerous schemes
  - resolved-private hosts (when WICK_RESOLVE_CHECK is on)
  - tracker URL substrings when WICK_SHIELDS is on
  - host allow/deny on *navigations* only (not every CDN subresource)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    import origins as wick_origins
except Exception:
    wick_origins = None  # type: ignore
try:
    import capability as wick_capability
except Exception:
    wick_capability = None  # type: ignore
try:
    import shields as wick_shields
except Exception:
    wick_shields = None  # type: ignore

# Small built-in list so shields do something without Lightpanda / EasyList.
BUILTIN_TRACKER_NEEDLES = (
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "googleadservices.com",
    "facebook.com/tr",
    "connect.facebook.net",
    "hotjar.com",
    "segment.io",
    "api.segment.io",
    "fingerprint.com",
    "cdn.fingerprint.com",
    "fpjs.io",
    "api.fpjs.io",
)

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def shields_on() -> bool:
    raw = (os.environ.get("WICK_SHIELDS") or "1").strip().lower()
    return raw not in _FALSE


def _tracker_needles() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for n in BUILTIN_TRACKER_NEEDLES:
        if n not in seen:
            out.append(n)
            seen.add(n)
    if wick_shields is not None:
        try:
            for n in wick_shields.block_url_patterns():
                s = (n or "").strip().lower()
                if s and s not in seen:
                    out.append(s)
                    seen.add(s)
        except Exception:
            pass
    return out


def is_tracker_url(url: str | None) -> bool:
    s = (url or "").strip().lower()
    if not s:
        return False
    return any(n in s for n in _tracker_needles())


def block_reason(
    url: str | None,
    *,
    navigation: bool = False,
    resolve: bool | None = None,
) -> str | None:
    """Why this URL must not be fetched. None means allow."""
    if wick_origins is None:
        return None
    s = (url or "").strip()
    if not s:
        return "no_url"
    if wick_origins.is_parking_url(s):
        return None
    if wick_origins.is_dangerous_url(s):
        return "dangerous_url"
    err = wick_origins.guard_fetch_url(s, resolve=resolve if navigation else False)
    if err:
        return str(err.get("error") or "blocked")
    if navigation and wick_capability is not None:
        herr = wick_capability.deny_host(s)
        if herr:
            return "host_not_allowed"
    if shields_on() and is_tracker_url(s):
        return "tracker_url"
    return None


def filter_agent_links(links: list[Any] | None) -> tuple[list[dict[str, str]], int]:
    """Drop javascript:/data:/file: hrefs from observe link lists."""
    kept: list[dict[str, str]] = []
    dropped = 0
    if wick_origins is None:
        for item in links or []:
            if isinstance(item, dict):
                kept.append(
                    {"text": str(item.get("text") or ""), "href": str(item.get("href") or "")}
                )
        return kept, 0
    for item in links or []:
        if not isinstance(item, dict):
            dropped += 1
            continue
        href = str(item.get("href") or "").strip()
        if not href or wick_origins.is_dangerous_url(href):
            dropped += 1
            continue
        scheme = (urlsplit(href).scheme or "").lower()
        if scheme and scheme not in wick_origins.HTTP_SCHEMES:
            dropped += 1
            continue
        kept.append({"text": str(item.get("text") or ""), "href": href})
    return kept, dropped


def confine_path(dest: Path, *roots: Path) -> Path | None:
    """Resolve dest and require it to sit under one of roots. None = reject."""
    if not roots:
        return None
    try:
        target = Path(dest).expanduser().resolve()
    except OSError:
        return None
    for root in roots:
        try:
            base = Path(root).expanduser().resolve()
            target.relative_to(base)
            return target
        except (OSError, ValueError):
            continue
    return None


def allowed_write_roots() -> list[Path]:
    home = Path(os.environ.get("WICK_HOME") or (Path.home() / ".wick"))
    roots = [home]
    extra = os.environ.get("WICK_DOWNLOADS")
    if extra:
        roots.append(Path(extra))
    shots = os.environ.get("WICK_SHOTS")
    if shots:
        roots.append(Path(shots))
    return roots


def confine_agent_file(dest: Path) -> Path | None:
    """Downloads/PDF/screenshots stay under WICK_HOME unless unconfined."""
    raw = (os.environ.get("WICK_ALLOW_UNCONFINED_FILES") or "0").strip().lower()
    if raw in _TRUE:
        try:
            return Path(dest).expanduser().resolve()
        except OSError:
            return None
    return confine_path(dest, *allowed_write_roots())


def install_playwright_routes(context: Any) -> bool:
    """Abort private/dangerous/tracker requests on a Playwright context."""
    if context is None or getattr(context, "_wick_request_guard", False):
        return False

    def on_route(route: Any) -> None:
        try:
            req = route.request
            url = str(getattr(req, "url", "") or "")
            navigation = bool(getattr(req, "is_navigation_request", lambda: False)())
            reason = block_reason(url, navigation=navigation)
            if reason in {
                "private_url",
                "dangerous_url",
                "resolved_private",
                "tracker_url",
            }:
                route.abort()
                return
            if reason == "host_not_allowed" and navigation:
                route.abort()
                return
            route.continue_()
        except Exception:
            try:
                route.continue_()
            except Exception:
                pass

    try:
        context.route("**/*", on_route)
        context._wick_request_guard = True
        return True
    except Exception:
        return False
