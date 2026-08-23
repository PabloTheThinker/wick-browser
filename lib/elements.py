"""Parse Lightpanda semantic_tree_text into agent-actionable elements."""
from __future__ import annotations

import re
from typing import Any

# Lines like:  12 [i] link 'Plan'   or  5 heading 'Title'  or  11 [i] button 'Go'
LINE_RE = re.compile(
    r"^\s*(\d+)\s+"
    r"(?:\[([^\]]*)\]\s+)?"
    r"([a-zA-Z][\w-]*)"
    r"(?:\s+'([^']*)')?"
    r"(?:\s+\"([^\"]*)\")?"
)


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


def parse_tree_text(tree: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in (tree or "").splitlines():
        m = LINE_RE.match(line.strip()) if line.strip() else None
        if not m:
            continue
        node_id, flags, role, name1, name2 = m.groups()
        name = name1 or name2 or ""
        role_l = (role or "").lower()
        interactive = role_l in INTERACTIVE or (flags or "").find("i") >= 0
        out.append({
            "id": int(node_id),
            "role": role_l,
            "name": name,
            "flags": flags or "",
            "interactive": interactive,
            # Best-effort selector hints for Chromium path
            "hint": _hint(role_l, name),
        })
    return out


def _hint(role: str, name: str) -> str | None:
    if not name:
        return None
    # Playwright-friendly get_by_role / text selectors
    if role == "link":
        return f'role=link[name="{name}"]'
    if role == "button":
        return f'role=button[name="{name}"]'
    if role in ("textbox", "searchbox"):
        return f'role=textbox[name="{name}"]'
    if role:
        return f'role={role}[name="{name}"]'
    return f'text={name}'


def interactive_only(elements: list[dict[str, Any]], limit: int = 50) -> list[dict[str, Any]]:
    hit = [e for e in elements if e.get("interactive")]
    return hit[:limit]


def query_words(query: str) -> list[str]:
    """Split query into lowercase tokens for fuzzy matching (no external LLM)."""
    return [w for w in re.split(r"[^\w]+", (query or "").lower()) if len(w) >= 2]


def fuzzy_score(text: str, words: list[str]) -> int:
    """Count query words found as substrings in text (case-insensitive)."""
    if not words:
        return 0
    hay = (text or "").lower()
    return sum(1 for w in words if w in hay)


def fuzzy_match_fields(fields: dict[str, str], query: str, *, min_score: int = 1) -> int:
    """Return match score across named fields, or 0 if below min_score."""
    words = query_words(query)
    if not words:
        return 0
    score = sum(fuzzy_score(v, words) for v in fields.values() if v)
    return score if score >= min_score else 0


def filter_links(links: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    words = query_words(query)
    if not words:
        return links
    scored: list[tuple[int, dict[str, Any]]] = []
    for link in links:
        s = fuzzy_score(link.get("text") or "", words) + fuzzy_score(link.get("href") or "", words)
        if s > 0:
            scored.append((s, link))
    scored.sort(key=lambda x: (-x[0], x[1].get("text") or ""))
    return [link for _, link in scored]


def filter_elements(elements: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    words = query_words(query)
    if not words:
        return elements
    scored: list[tuple[int, dict[str, Any]]] = []
    for el in elements:
        s = (
            fuzzy_score(el.get("name") or "", words)
            + fuzzy_score(el.get("role") or "", words)
            + fuzzy_score(el.get("hint") or "", words)
        )
        if s > 0:
            scored.append((s, el))
    scored.sort(key=lambda x: (-x[0], x[1].get("name") or ""))
    return [el for _, el in scored]


def plan_suggestions(
    *,
    url: str,
    title: str | None,
    excerpt: str,
    links: list[dict[str, Any]],
    elements: list[dict[str, Any]],
    click_limit: int = 3,
) -> list[dict[str, Any]]:
    """Goal-agnostic next-step hints for agents (built from snap data)."""
    out: list[dict[str, Any]] = []
    try:
        import login_form as _login_form
    except Exception:
        _login_form = None  # type: ignore
    login = _login_form.detect_login_fields(elements) if _login_form is not None else None
    if login and login.get("is_login"):
        out.append({
            "action": "login",
            "cmd": f"wick act login {url!r}",
            "why": (
                "password field detected — origin-bound vault autofill "
                f"(also: wick vault suggest --url {url!r})"
            ),
        })
    out.append({
        "action": "open",
        "cmd": f"wick open {url!r} --max 8000",
        "why": "read full markdown body",
    })
    if excerpt and len(excerpt) < 400:
        out.append({
            "action": "open",
            "cmd": f"wick open {url!r}",
            "why": "excerpt is short; full page may add context",
        })
    if links:
        first = links[0]
        out.append({
            "action": "links",
            "cmd": f"wick links {url!r}",
            "why": f"page has {len(links)} links; sample: {first.get('text') or first.get('href')}",
        })
    for el in elements[: max(0, click_limit)]:
        hint = el.get("hint")
        if not hint:
            continue
        out.append({
            "action": "click",
            "cmd": f"wick act click {hint!r}",
            "hint": hint,
            "element": {"id": el.get("id"), "role": el.get("role"), "name": el.get("name")},
            "why": f"interactive {el.get('role')}: {el.get('name') or '(unnamed)'}",
        })
    if elements:
        out.append({
            "action": "elements",
            "cmd": f"wick elements {url!r}",
            "why": f"{len(elements)} interactive targets available",
        })
    out.append({
        "action": "screenshot",
        "cmd": "wick act goto <url> && wick act screenshot",
        "why": "visual snapshot via Chromium when observe is not enough",
    })
    out.append({
        "action": "pdf",
        "cmd": f"wick pdf --url {url!r}",
        "why": "archive page as PDF",
    })
    if title:
        out.append({
            "action": "ask",
            "cmd": f"wick ask {url!r} --q {title!r}",
            "why": "filter links/elements matching title keywords",
        })
    return out
