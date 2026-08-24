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
    if role == "searchbox":
        # Playwright's textbox role does not match <input type="search">.
        return f'role=searchbox[name="{name}"]'
    if role == "textbox":
        return f'role=textbox[name="{name}"]'
    if role:
        return f'role={role}[name="{name}"]'
    return f'text={name}'


def tree_from_elements(title: str, elements: list[dict[str, Any]]) -> str:
    """Lightpanda-shaped semantic_tree_text so snap/plan/ask share one parser."""
    safe_title = (title or "").replace("'", "")
    lines = [f"1 document '{safe_title}'"]
    for i, el in enumerate(elements or [], start=2):
        role = re.sub(r"[^a-zA-Z0-9_-]", "", str(el.get("role") or "generic")) or "generic"
        name = (el.get("name") or "").replace("'", "")
        if name:
            lines.append(f"{i} [i] {role} '{name}'")
        else:
            lines.append(f"{i} [i] {role}")
    return "\n".join(lines)


def markdown_from_observe(
    title: str,
    text: str,
    links: list[dict[str, Any]] | None = None,
) -> str:
    """Cheap markdown so extract_md_links / ask still work on the Chromium path."""
    parts: list[str] = []
    if title:
        parts.append(f"# {title.strip()}")
        parts.append("")
    for link in links or []:
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        label = (link.get("text") or href).replace("]", " ").replace("\n", " ").strip() or href
        parts.append(f"[{label}]({href})")
    body = (text or "").strip()
    if body:
        if parts:
            parts.append("")
        parts.append(body)
    return "\n".join(parts)


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
    kind: str | None = None,
    headings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Goal-agnostic next-step hints for agents (built from snap data)."""
    out: list[dict[str, Any]] = []
    try:
        import login_form as _login_form
    except Exception:
        _login_form = None  # type: ignore
    login = _login_form.detect_login_fields(elements) if _login_form is not None else None
    chal = None
    try:
        import challenge as _challenge

        chal = _challenge.detect(url=url, title=title, excerpt=excerpt, elements=elements)
    except Exception:
        chal = None
    if chal and chal.get("found"):
        if chal.get("computer_use"):
            out.append({
                "action": "cu",
                "cmd": "wick act cu",
                "why": (
                    "human challenge — computer-use (screenshot + click_xy / type) "
                    "like Hermes / Grokbot; vault login stays blocked"
                ),
            })
        else:
            out.append({
                "action": "cu",
                "cmd": "wick act cu",
                "why": (
                    "human challenge — vault login/click halted here; "
                    "headed desktop or WICK_CHALLENGE_COMPUTER_USE=1 allows computer-use"
                ),
            })
    elif login and login.get("is_login"):
        out.append({
            "action": "login",
            "cmd": f"wick act login {url!r}",
            "why": (
                "password field detected — origin-bound vault autofill "
                f"(also: wick vault suggest --url {url!r})"
            ),
        })
    read_cmd = "wick read" if not url else f"wick read {url!r}"
    if (kind or "") == "article" or (headings and excerpt):
        out.append({
            "action": "read",
            "cmd": read_cmd,
            "why": "structured page read (kind, headings, paragraphs) — prefer this over a markdown dump",
        })
        section = next(
            (h.get("text") for h in (headings or []) if int(h.get("level") or 2) >= 2 and h.get("text")),
            None,
        )
        if section:
            out.append({
                "action": "read",
                "cmd": f"{read_cmd} --section {section!r}",
                "why": f"focused read of the {section!r} section only",
            })
    out.append({
        "action": "open",
        "cmd": f"wick open {url!r} --max 8000",
        "why": "full markdown dump when the structured read is not enough",
    })
    if excerpt and len(excerpt) < 400 and (kind or "") != "article":
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
    search = next(
        (
            el
            for el in elements
            if (el.get("role") or "") in {"searchbox", "textbox"}
            and "search" in (el.get("name") or "").lower()
            and el.get("hint")
        ),
        None,
    )
    if search:
        hint = search["hint"]
        out.append({
            "action": "fill",
            "cmd": f"wick act fill {hint!r} 'query' && wick act press Enter",
            "hint": hint,
            "element": {
                "id": search.get("id"),
                "role": search.get("role"),
                "name": search.get("name"),
            },
            "why": f"search field: {search.get('name')}",
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
        "action": "cu",
        "cmd": "wick act cu",
        "why": "computer-use loop: screenshot + numbered on-screen targets (click_n / click_xy)",
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
