"""Static HTTP observe — title, markdown, links, tree. No Chromium, no JS.

Used when Playwright is missing (or WICK_OBSERVE=http) so the search → snap
loop stays headless. SPAs that only render in the browser need Chromium.
"""
from __future__ import annotations

import html as htmlmod
import os
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

try:
    import origins as wick_origins
except Exception:
    wick_origins = None  # type: ignore
try:
    import capability as wick_capability
except Exception:
    wick_capability = None  # type: ignore
try:
    import search as wick_search
except Exception:
    wick_search = None  # type: ignore
try:
    import chrome_observe as wick_chrome_observe
except Exception:
    wick_chrome_observe = None  # type: ignore

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_A_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_HREF_RE = re.compile(r"""\bhref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_BUTTON_RE = re.compile(r"<button\b([^>]*)>(.*?)</button>", re.IGNORECASE | re.DOTALL)
_INPUT_RE = re.compile(r"<input\b([^>]*)/?>", re.IGNORECASE)
_TEXTAREA_RE = re.compile(r"<textarea\b([^>]*)>(.*?)</textarea>", re.IGNORECASE | re.DOTALL)
_TYPE_ATTR_RE = re.compile(r"""\btype\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_VALUE_ATTR_RE = re.compile(r"""\bvalue\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_ATTR_KEYS = ("aria-label", "title", "placeholder", "alt", "name")
_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_text(raw: str) -> str:
    text = htmlmod.unescape(_TAG_RE.sub(" ", raw or ""))
    return _WS_RE.sub(" ", text).strip()


def _usable_href(href: str, base: str) -> str | None:
    raw = htmlmod.unescape((href or "").strip())
    if not raw:
        return None
    dest = urljoin(base, raw)
    if wick_origins is not None:
        if wick_origins.is_dangerous_url(dest):
            return None
        try:
            dest = wick_origins.normalize_agent_url(dest)
        except ValueError:
            return None
        if wick_origins.is_private_url(dest) and not wick_origins.allow_private_override():
            return None
    else:
        scheme = (urlsplit(dest).scheme or "").lower()
        if scheme in {"javascript", "data", "file", "blob", "vbscript"}:
            return None
        if not dest.startswith("http://") and not dest.startswith("https://"):
            return None
    if wick_capability is not None and wick_capability.deny_host(dest):
        return None
    return dest


def parse_title(html: str) -> str:
    m = _TITLE_RE.search(html or "")
    return _strip_text(m.group(1))[:200] if m else ""


def parse_links(html: str, base: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _A_RE.finditer(html or ""):
        attrs, inner = m.group(1), m.group(2)
        hm = _HREF_RE.search(attrs or "")
        if not hm:
            continue
        dest = _usable_href(hm.group(1), base)
        if not dest or dest in seen:
            continue
        seen.add(dest)
        text = _strip_text(inner)[:160]
        out.append({"text": text or dest, "href": dest})
        if len(out) >= 200:
            break
    return out


def _attr_name(attrs: str, inner: str = "") -> str:
    blob = attrs or ""
    for key in _ATTR_KEYS:
        m = re.search(rf"""\b{re.escape(key)}\s*=\s*["']([^"']+)["']""", blob, re.IGNORECASE)
        if m:
            return _strip_text(m.group(1))[:80]
    inner_t = _strip_text(inner)
    if inner_t:
        return inner_t[:80]
    vm = _VALUE_ATTR_RE.search(blob)
    return _strip_text(vm.group(1))[:80] if vm else ""


def parse_controls(html: str) -> list[dict[str, str]]:
    """Buttons and fields from static markup (no computed styles)."""
    out: list[dict[str, str]] = []
    for m in _BUTTON_RE.finditer(html or ""):
        name = _attr_name(m.group(1), m.group(2))
        out.append({"role": "button", "name": name})
    for m in _INPUT_RE.finditer(html or ""):
        attrs = m.group(1) or ""
        typ = (_TYPE_ATTR_RE.search(attrs).group(1).lower() if _TYPE_ATTR_RE.search(attrs) else "text")
        name = _attr_name(attrs)
        if typ in {"submit", "button", "image"}:
            out.append({"role": "button", "name": name or typ})
        elif typ in {"checkbox"}:
            out.append({"role": "checkbox", "name": name})
        elif typ in {"radio"}:
            out.append({"role": "radio", "name": name})
        elif typ in {"hidden", "file"}:
            continue
        else:
            role = "searchbox" if typ == "search" else "textbox"
            out.append({"role": role, "name": name})
    for m in _TEXTAREA_RE.finditer(html or ""):
        out.append({"role": "textbox", "name": _attr_name(m.group(1), m.group(2))})
    return out[:80]


def body_text(html: str) -> str:
    cleaned = _STYLE_RE.sub(" ", _SCRIPT_RE.sub(" ", html or ""))
    return _strip_text(cleaned)


def build_tree_text(title: str, links: list[dict[str, str]], controls: list[dict[str, str]]) -> str:
    lines = [f"1 document '{(title or 'document')[:120]}'"]
    nid = 2
    for link in links[:40]:
        name = (link.get("text") or "").replace("'", " ")[:80]
        if not name:
            continue
        lines.append(f"{nid} [i] link '{name}'")
        nid += 1
    for el in controls:
        name = (el.get("name") or "").replace("'", " ")[:80]
        role = el.get("role") or "generic"
        if name:
            lines.append(f"{nid} [i] {role} '{name}'")
        else:
            lines.append(f"{nid} [i] {role}")
        nid += 1
    return "\n".join(lines)


def pack_http_observe(
    *,
    url: str,
    dump: str,
    title: str,
    text: str,
    html: str,
    links: list[dict[str, str]],
    tree_text: str,
    http_status: int | None,
    max_chars: int,
    ms: int,
) -> dict[str, Any]:
    if wick_chrome_observe is not None:
        body = wick_chrome_observe.pack_observe(
            url=url,
            dump=dump,
            title=title,
            text=text,
            html=html,
            links=links,
            tree_text=tree_text,
            http_status=http_status,
            max_chars=max_chars,
            ms=ms,
            wait_until="http",
            wait_ms=0,
        )
    else:
        if dump == "semantic_tree_text" or dump == "semantic_tree":
            content = tree_text
        elif dump == "html":
            content = html or text
        else:
            parts = []
            if title:
                parts.append(f"# {title}\n")
            if text:
                parts.append(text)
            for link in links:
                parts.append(f"[{link.get('text') or link['href']}]({link['href']})")
            content = "\n".join(parts)
        status_i = int(http_status) if http_status is not None else None
        body = {
            "ok": True,
            "product": "wick",
            "url": url,
            "http_status": status_i,
            "http_ok": status_i is None or 200 <= status_i < 400,
            "dump": dump,
            "chars": len(content or ""),
            "content": (content or "")[:max_chars],
            "truncated": len(content or "") > max_chars,
            "ms": ms,
            "title": title,
        }
    body["engine"] = "http"
    body["via"] = "http"
    body["headless"] = True
    body["pixels"] = False
    body["js"] = False
    return body


def observe_html(
    html: str,
    *,
    url: str,
    dump: str = "markdown",
    max_chars: int = 12000,
    http_status: int | None = 200,
    ms: int = 0,
) -> dict[str, Any]:
    title = parse_title(html)
    links = parse_links(html, url)
    controls = parse_controls(html)
    text = body_text(html)
    tree = build_tree_text(title, links, controls)
    return pack_http_observe(
        url=url,
        dump=dump,
        title=title,
        text=text,
        html=html,
        links=links,
        tree_text=tree,
        http_status=http_status,
        max_chars=max_chars,
        ms=ms,
    )


def http_fetch(
    url: str,
    *,
    dump: str = "markdown",
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Guarded HTTP GET + static parse. Same URL shields as search."""
    if wick_search is None:
        return {"ok": False, "product": "wick", "error": "search_module_missing"}
    fetched = wick_search.light_fetch(url)
    if not fetched.get("ok"):
        return fetched
    html = str(fetched.get("html") or "")
    return observe_html(
        html,
        url=str(fetched.get("url") or url),
        dump=dump,
        max_chars=max_chars,
        http_status=fetched.get("http_status"),
        ms=int(fetched.get("ms") or 0),
    )


def prefer_http() -> bool:
    return (os.environ.get("WICK_OBSERVE") or "").strip().lower() in {"http", "light", "static"}
