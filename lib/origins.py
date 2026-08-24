"""Chrome/Brave-style origin matching and URL guards for agent browsing.

Substring URL matching is a phishing bug. Agents fill passwords only when
scheme+host(+port) match the saved credential, with a narrow www alias and
optional subdomain grant. HTTPS-saved logins never fill on HTTP pages.

Private-network fetches stay blocked unless WICK_ALLOW_PRIVATE=1 or a policy
file opts in (see lib/policy.py); env wins when it is set.
"""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit


def _sibling_module(name: str) -> Any:
    """Import a lib/ sibling whether or not lib/ is on sys.path."""
    try:
        return __import__(name)
    except Exception:
        pass
    try:
        import importlib.util
        from importlib.machinery import SourceFileLoader

        path = Path(__file__).resolve().parent / f"{name}.py"
        if not path.is_file():
            return None
        loader = SourceFileLoader(name, str(path))
        spec = importlib.util.spec_from_loader(name, loader)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


wick_policy = _sibling_module("policy")

DANGEROUS_SCHEMES = frozenset(
    {
        "javascript",
        "data",
        "file",
        "blob",
        "vbscript",
        "about",
        "chrome",
        "chrome-extension",
        "chrome-untrusted",
        "edge",
        "devtools",
        "view-source",
    }
)
HTTP_SCHEMES = frozenset({"http", "https"})


def is_dangerous_url(url: str | None) -> bool:
    s = (url or "").strip()
    if not s:
        return False
    scheme = s.split(":", 1)[0].lower()
    if scheme in DANGEROUS_SCHEMES:
        return True
    if s.lower().startswith("javascript:") or s.lower().startswith("data:"):
        return True
    return False


def parse_origin(url: str | None) -> dict[str, Any] | None:
    """Return {scheme, host, port, origin, path} or None if not an http(s) URL."""
    s = (url or "").strip()
    if not s or is_dangerous_url(s):
        return None
    if "://" not in s:
        return None
    parts = urlsplit(s)
    scheme = (parts.scheme or "").lower()
    if scheme not in HTTP_SCHEMES:
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        origin = f"{scheme}://{host}"
    else:
        origin = f"{scheme}://{host}:{port}"
    return {
        "scheme": scheme,
        "host": host,
        "port": int(port),
        "origin": origin,
        "path": parts.path or "/",
    }


def normalize_agent_url(url: str | None) -> str:
    """HTTPS-first normalize. Bare hosts become https://host. Raises ValueError."""
    s = (url or "").strip()
    if not s:
        raise ValueError("empty_url")
    if is_dangerous_url(s):
        raise ValueError("dangerous_url")
    if s.startswith("//"):
        s = "https:" + s
    elif "://" not in s:
        s = "https://" + s.lstrip("/")
    parts = urlsplit(s)
    if (parts.scheme or "").lower() not in HTTP_SCHEMES:
        raise ValueError("dangerous_url")
    if not (parts.hostname or "").strip():
        raise ValueError("empty_host")
    return s


def is_private_host(host: str | None) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return False
    if h in {"localhost", "localhost.localdomain", "0.0.0.0", "::1", "ip6-localhost"}:
        return True
    if h.endswith(".localhost") or h.endswith(".local") or h.endswith(".internal"):
        return True
    if h.endswith(".home.arpa") or h.endswith(".lan"):
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_private_url(url: str | None) -> bool:
    s = (url or "").strip()
    if not s or is_dangerous_url(s):
        return False
    try:
        if "://" not in s:
            s = normalize_agent_url(s)
    except ValueError:
        return False
    o = parse_origin(s)
    if not o:
        return False
    return is_private_host(o["host"])


def _www_alias(a: str, b: str) -> bool:
    return a == f"www.{b}" or b == f"www.{a}"


def _is_subdomain(page_host: str, saved_host: str) -> bool:
    return bool(saved_host) and page_host.endswith("." + saved_host)


def origins_compatible(
    saved_url: str | None,
    page_url: str | None,
    *,
    allow_subdomains: bool = False,
) -> tuple[bool, str, int]:
    """Return (ok, reason, score). Score 0 means no fill."""
    saved = parse_origin(saved_url)
    page = parse_origin(page_url)
    if not saved or not page:
        return False, "unparseable", 0
    if saved["scheme"] == "https" and page["scheme"] == "http":
        return False, "https_required", 0

    host_ok = saved["host"] == page["host"]
    reason = "exact_host"
    score = 100
    if not host_ok and _www_alias(saved["host"], page["host"]):
        host_ok = True
        reason = "www_alias"
        score = 70
    elif (
        not host_ok
        and allow_subdomains
        and _is_subdomain(page["host"], saved["host"])
    ):
        host_ok = True
        reason = "subdomain"
        score = 60
    if not host_ok:
        return False, "host_mismatch", 0

    if saved["port"] != page["port"]:
        # default-port www alias already normalized; treat explicit mismatch as fail
        if not (
            {saved["port"], page["port"]} <= {80, 443}
            and saved["scheme"] != page["scheme"]
        ):
            return False, "port_mismatch", 0

    if saved["scheme"] == "http" and page["scheme"] == "https":
        return True, "https_upgrade", min(score, 85)
    if saved["scheme"] != page["scheme"]:
        return False, "scheme_mismatch", 0
    return True, reason, score


def same_observe_target(current: str | None, target: str | None) -> bool:
    """True when Chromium is already on the page an agent wants to snap.

    Extra tracking query on the live URL is OK. Every key in the target query
    must match. Fragments are ignored.
    """
    cur = (current or "").strip()
    tgt = (target or "").strip()
    if not cur or not tgt:
        return False
    if tgt in {".", "here", "--here"}:
        return True
    try:
        c, t = urlsplit(cur), urlsplit(tgt)
    except Exception:
        return False
    if (c.scheme or "https").lower() != (t.scheme or "https").lower():
        return False
    if (c.hostname or "").lower() != (t.hostname or "").lower():
        return False
    c_path = c.path.rstrip("/") or "/"
    t_path = t.path.rstrip("/") or "/"
    if c_path != t_path:
        return False
    if not t.query:
        return True
    have = dict(parse_qsl(c.query, keep_blank_values=True))
    want = dict(parse_qsl(t.query, keep_blank_values=True))
    return all(have.get(k) == v for k, v in want.items())


def is_here_url(url: str | None) -> bool:
    s = (url or "").strip()
    return s == "" or s in {".", "here", "--here"}


def allow_private_override() -> bool:
    """WICK_ALLOW_PRIVATE wins when set; a policy file can opt in otherwise."""
    if wick_policy is not None:
        try:
            return bool(wick_policy.effective().get("allow_private"))
        except Exception:
            pass
    return os.environ.get("WICK_ALLOW_PRIVATE", "0") == "1"


def guard_fetch_url(url: str | None) -> dict[str, Any] | None:
    """Return an error dict if the URL must not be fetched; else None."""
    s = (url or "").strip()
    if not s:
        return {"ok": False, "product": "wick", "error": "no_url"}
    if is_dangerous_url(s):
        return {"ok": False, "product": "wick", "error": "dangerous_url", "url": s[:120]}
    try:
        normalized = normalize_agent_url(s) if "://" not in s else s
    except ValueError as e:
        return {"ok": False, "product": "wick", "error": str(e), "url": s[:120]}
    if is_private_url(normalized) and not allow_private_override():
        return {"ok": False, "product": "wick", "error": "private_url", "url": normalized[:120]}
    return None
