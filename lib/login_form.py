"""Detect login-form targets from semantic-tree elements (no DOM required).

Used by vault suggest / plan so agents get the same autofill targeting a
human password manager would: username, password, optional OTP, submit.
"""
from __future__ import annotations

import re
from typing import Any

USER_RE = re.compile(
    r"(user(name)?|e-?mail|login|phone|account|\bid\b|identifier)",
    re.IGNORECASE,
)
PASS_RE = re.compile(r"(pass(word|wd|phrase)?|\bpwd\b|secret)", re.IGNORECASE)
OTP_RE = re.compile(
    r"(otp|totp|2fa|mfa|one[-\s]?time|verif(y|ication)|authenticator|\bcode\b)",
    re.IGNORECASE,
)
SUBMIT_RE = re.compile(
    r"(log\s*in|sign\s*in|sign\s*on|signin|submit|continue|next|enter|authenticate)",
    re.IGNORECASE,
)

# Playwright CSS used on the Chromium login path (human-browser autofill).
PASSWORD_CSS = 'input[type="password"]:not([disabled])'
USERNAME_CSS = (
    'input[type="email"]:not([disabled]), '
    'input[autocomplete="username"]:not([disabled]), '
    'input[autocomplete="email"]:not([disabled]), '
    'input[name*="user" i]:not([type="password"]), '
    'input[name*="email" i]:not([type="password"]), '
    'input[id*="user" i]:not([type="password"]), '
    'input[id*="email" i]:not([type="password"]), '
    'input[type="text"]:not([disabled])'
)
OTP_CSS = (
    'input[autocomplete="one-time-code"], '
    'input[name*="otp" i], input[id*="otp" i], '
    'input[name*="totp" i], input[name*="2fa" i]'
)
SUBMIT_CSS = 'button[type="submit"], input[type="submit"], button:not([type]), [role="button"]'


def _copy_el(el: dict[str, Any] | None) -> dict[str, Any] | None:
    if not el:
        return None
    return {
        "id": el.get("id"),
        "role": el.get("role"),
        "name": el.get("name"),
        "hint": el.get("hint"),
        "interactive": el.get("interactive"),
    }


def detect_login_fields(elements: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Pick username/password/otp/submit from snap/elements output."""
    password = None
    username = None
    otp = None
    submit = None
    boxes: list[dict[str, Any]] = []
    for el in elements or []:
        role = (el.get("role") or "").lower()
        name = el.get("name") or ""
        if role in {"textbox", "searchbox", "combobox"}:
            boxes.append(el)
            if password is None and PASS_RE.search(name):
                password = el
            elif otp is None and OTP_RE.search(name) and not PASS_RE.search(name):
                otp = el
            elif username is None and USER_RE.search(name) and not PASS_RE.search(name):
                username = el
        if role == "button" and submit is None and SUBMIT_RE.search(name):
            submit = el
    if password and not username:
        for el in boxes:
            if el is password or el is otp:
                continue
            username = el
            break
    return {
        "is_login": password is not None,
        "username": _copy_el(username),
        "password": _copy_el(password),
        "otp": _copy_el(otp),
        "submit": _copy_el(submit),
    }


def is_login_form(elements: list[dict[str, Any]] | None) -> bool:
    return bool(detect_login_fields(elements).get("is_login"))
