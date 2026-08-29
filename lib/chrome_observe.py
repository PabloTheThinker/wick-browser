"""Chromium observe fallback — same JSON shape as Lightpanda fetch.

When Lightpanda is absent, snap/plan/ask/open/tree/links still work for
agents by driving headless Chromium. Tree text is Lightpanda-shaped so
lib/elements.py can parse role= hints for wick act click.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Keep in sync with lib/elements.py INTERACTIVE
INTERACTIVE = {
    "link",
    "button",
    "textbox",
    "searchbox",
    "checkbox",
    "radio",
    "combobox",
    "listbox",
    "menuitem",
    "tab",
    "switch",
    "slider",
    "spinbutton",
    "option",
}

ROLE_MAP = {
    "webarea": "document",
    "text": "text",
    "textbox": "textbox",
    "searchbox": "searchbox",
    "combobox": "combobox",
}

PW_WAIT = {
    "load": "load",
    "domcontentloaded": "domcontentloaded",
    "networkidle": "networkidle",
    "networkalmostidle": "networkidle",
    "done": "load",
    "none": "commit",
}

LINKS_JS = """() => {
  const out = [];
  const seen = new Set();
  for (const a of Array.from(document.querySelectorAll('a[href]'))) {
    const href = (a.href || '').trim();
    if (!href || seen.has(href)) continue;
    if (href.startsWith('javascript:') || href.startsWith('data:')) continue;
    seen.add(href);
    const text = (a.innerText || a.getAttribute('aria-label') || a.title || '')
      .replace(/\\s+/g, ' ').trim().slice(0, 160);
    out.push({text, href});
    if (out.length >= 200) break;
  }
  return out;
}"""

A11Y_JS = """() => {
  const sel = 'a, button, input, select, textarea, summary, [role], [onclick], [tabindex]:not([tabindex="-1"])';
  const nodes = Array.from(document.querySelectorAll(sel));
  const seen = new Set();
  const elements = [];
  for (const el of nodes) {
    if (seen.has(el)) continue;
    seen.add(el);
    const cs = window.getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const role = (el.getAttribute('role') || el.tagName || '').toLowerCase();
    const name = (
      el.getAttribute('aria-label')
      || el.getAttribute('title')
      || el.getAttribute('placeholder')
      || (el.innerText || el.value || '')
    ).replace(/\\s+/g, ' ').trim().slice(0, 80);
    elements.push({
      role,
      name,
      tag: (el.tagName || '').toLowerCase(),
    });
    if (elements.length >= 80) break;
  }
  return elements;
}"""


def map_role(role: str | None) -> str:
    raw = (role or "generic").strip()
    key = raw.lower()
    if key in ROLE_MAP:
        return ROLE_MAP[key]
    if key in INTERACTIVE:
        return key
    if not raw:
        return "generic"
    return key.replace(" ", "-")


def _quote_name(name: str) -> str:
    cleaned = (name or "").replace("'", " ").replace("\n", " ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120]


def flatten_a11y(node: dict[str, Any] | None, *, start_id: int = 1) -> str:
    """Turn a Playwright accessibility snapshot into Lightpanda tree text."""
    lines: list[str] = []
    nid = start_id

    def walk(item: dict[str, Any] | None) -> None:
        nonlocal nid
        if not item or not isinstance(item, dict):
            return
        role = map_role(item.get("role"))
        name = _quote_name(str(item.get("name") or ""))
        interactive = role in INTERACTIVE
        flag = "[i] " if interactive else ""
        if name:
            lines.append(f"{nid} {flag}{role} '{name}'")
        else:
            lines.append(f"{nid} {flag}{role}")
        nid += 1
        for child in item.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(node)
    return "\n".join(lines)


def tree_from_elements(
    elements: list[dict[str, Any]] | None,
    *,
    title: str = "",
    start_id: int = 1,
) -> str:
    """Build tree text from DOM/a11y element dicts (role + name)."""
    lines: list[str] = []
    nid = start_id
    if title:
        lines.append(f"{nid} document '{_quote_name(title)}'")
        nid += 1
    for el in elements or []:
        role = map_role(el.get("role") or el.get("tag"))
        name = _quote_name(str(el.get("name") or ""))
        interactive = role in INTERACTIVE or str(el.get("tag") or "").lower() in {
            "a",
            "button",
            "input",
            "select",
            "textarea",
        }
        if role in {"a", "anchor"}:
            role = "link"
            interactive = True
        if role in {"input"}:
            itype = str(el.get("type") or "").lower()
            role = "textbox" if itype not in {"checkbox", "radio", "submit", "button"} else (
                "checkbox" if itype == "checkbox" else ("radio" if itype == "radio" else "button")
            )
            interactive = True
        flag = "[i] " if interactive else ""
        if name:
            lines.append(f"{nid} {flag}{role} '{name}'")
        else:
            lines.append(f"{nid} {flag}{role}")
        nid += 1
    return "\n".join(lines)


def merge_tree(a11y_text: str, elements: list[dict[str, Any]] | None, title: str) -> str:
    """Prefer accessibility snapshot; fill in interactive nodes if the snapshot is thin."""
    base = (a11y_text or "").strip()
    extra = tree_from_elements(elements, title="" if base else title, start_id=1)
    if not base:
        return extra
    if not extra:
        return base
    existing = set()
    for line in base.splitlines():
        existing.add(re.sub(r"^\s*\d+\s+", "", line.strip()))
    extra_lines = []
    next_id = 0
    for line in base.splitlines():
        m = re.match(r"^\s*(\d+)\s+", line)
        if m:
            next_id = max(next_id, int(m.group(1)))
    for line in extra.splitlines():
        key = re.sub(r"^\s*\d+\s+", "", line.strip())
        if key and key not in existing:
            next_id += 1
            extra_lines.append(re.sub(r"^\s*\d+\s+", f"{next_id} ", line.strip(), count=1))
            existing.add(key)
    if not extra_lines:
        return base
    return base + "\n" + "\n".join(extra_lines)


def build_markdown(title: str, text: str, links: list[dict[str, str]] | None) -> str:
    """Agent-cheap markdown: heading, body excerpt, then markdown links."""
    parts: list[str] = []
    t = (title or "").strip()
    if t:
        parts.append(f"# {t}")
        parts.append("")
    body = re.sub(r"\s+", " ", text or "").strip()
    if body:
        parts.append(body)
        parts.append("")
    for link in links or []:
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        label = str(link.get("text") or href).strip() or href
        label = label.replace("]", " ").replace("[", " ")
        parts.append(f"[{label}]({href})")
    return "\n".join(parts).strip() + ("\n" if parts else "")


def playwright_wait(wait_until: str | None) -> str:
    return PW_WAIT.get((wait_until or "load").lower(), "load")


def pack_observe(
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
    wait_until: str,
    wait_ms: int,
) -> dict[str, Any]:
    """Match lp_fetch pack_one so snap/plan/ask stay engine-agnostic."""
    if dump == "semantic_tree_text":
        content = tree_text
    elif dump == "semantic_tree":
        content = tree_text
    elif dump == "html":
        content = html or text
    else:
        content = build_markdown(title, text, links)
    status_i = int(http_status) if http_status is not None else None
    http_ok = status_i is not None and 200 <= status_i < 400
    body: dict[str, Any] = {
        "ok": True,
        "product": "wick",
        "engine": "chromium",
        "url": url,
        "http_status": status_i if status_i is not None else http_status,
        "http_ok": http_ok if status_i is not None else True,
        "dump": dump,
        "chars": len(content or ""),
        "content": (content or "")[:max_chars],
        "truncated": len(content or "") > max_chars,
        "ms": ms,
        "wait_until": wait_until,
        "wait_ms": wait_ms,
        "title": title,
        "fallback": "chromium",
    }
    if dump == "semantic_tree":
        body["tree"] = {"text": tree_text, "links": links}
    if status_i and status_i >= 400 and not (content or "").strip():
        body["empty_error_body"] = True
    return body


def collect_from_page(
    page: Any,
    url: str,
    *,
    dump: str = "markdown",
    max_chars: int = 12000,
    wait_until: str = "load",
    wait_ms: int = 2000,
) -> dict[str, Any]:
    """Drive an existing Playwright page. page is duck-typed for tests."""
    import time

    t0 = time.time()
    wu = playwright_wait(wait_until)
    resp = page.goto(url, wait_until=wu, timeout=max(60000, int(wait_ms) + 30000))
    extra = max(0, int(wait_ms))
    if extra:
        try:
            page.wait_for_timeout(extra)
        except Exception:
            pass
    status = None
    if resp is not None:
        try:
            status = int(resp.status)
        except Exception:
            status = None
    title = ""
    try:
        title = page.title() or ""
    except Exception:
        title = ""
    text = ""
    try:
        text = page.inner_text("body") or ""
    except Exception:
        text = ""
    html = ""
    if dump == "html":
        try:
            html = page.content() or ""
        except Exception:
            html = ""
    links: list[dict[str, str]] = []
    try:
        raw_links = page.evaluate(LINKS_JS) or []
        if isinstance(raw_links, list):
            links = [
                {"text": str(x.get("text") or ""), "href": str(x.get("href") or "")}
                for x in raw_links
                if isinstance(x, dict)
            ]
    except Exception:
        links = []
    a11y_text = ""
    try:
        snap = page.accessibility.snapshot() if getattr(page, "accessibility", None) else None
        if isinstance(snap, dict):
            a11y_text = flatten_a11y(snap)
    except Exception:
        a11y_text = ""
    dom_els: list[dict[str, Any]] = []
    try:
        raw_els = page.evaluate(A11Y_JS) or []
        if isinstance(raw_els, list):
            dom_els = [x for x in raw_els if isinstance(x, dict)]
    except Exception:
        dom_els = []
    tree_text = merge_tree(a11y_text, dom_els, title)
    final_url = url
    try:
        final_url = page.url or url
    except Exception:
        final_url = url
    ms = int((time.time() - t0) * 1000)
    return pack_observe(
        url=final_url,
        dump=dump,
        title=title,
        text=text,
        html=html,
        links=links,
        tree_text=tree_text,
        http_status=status,
        max_chars=max_chars,
        ms=ms,
        wait_until=wait_until,
        wait_ms=wait_ms,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: python chrome_observe.py URL DUMP MAX WAIT_UNTIL WAIT_MS"""
    import os
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(json.dumps({"ok": False, "error": "no_url", "product": "wick"}))
        return 2
    url = args[0]
    dump = args[1] if len(args) > 1 else "markdown"
    max_chars = int(args[2]) if len(args) > 2 else 12000
    wait_until = args[3] if len(args) > 3 else "load"
    wait_ms = int(args[4]) if len(args) > 4 else 2000
    port = int(os.environ.get("WICK_CHROME_PORT", "9222"))
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            json.dumps(
                {
                    "ok": False,
                    "product": "wick",
                    "error": "playwright_missing",
                    "hint": "make install  # creates .venv + Playwright Chromium",
                }
            )
        )
        return 1
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        out = collect_from_page(
            page,
            url,
            dump=dump,
            max_chars=max_chars,
            wait_until=wait_until,
            wait_ms=wait_ms,
        )
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
