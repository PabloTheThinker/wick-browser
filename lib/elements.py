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
