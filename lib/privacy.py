"""Privacy leak guards for Wick's Chromium path — not fingerprint stealth.

What this module does:
  - Stop WebRTC from handing LAN/CGNAT IPs to the page (Chromium IP handling)
  - Reduce User-Agent Client Hints entropy (fewer identifying headers)
  - *Report* known fingerprinting scripts/hosts so a harness can decide

What this module will not do:
  - Canvas / WebGL / audio farbling (needs a patched engine; we do not fake it)
  - User-Agent spoofing or navigator.webdriver theater beyond existing flags
  - Claim Camoufox / Brave-class anti-detect
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})

_FP_HOSTS = (
    "fingerprint.com",
    "fpjs.io",
    "api.fpjs.io",
    "cdn.fingerprint.com",
    "fingerprintjs.com",
)
_FP_WORDS = (
    "fingerprintjs",
    "fingerprint.js",
    "canvas fingerprint",
    "webgl fingerprint",
    "audio fingerprint",
)


def _env_on(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    v = str(raw).strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return default


def webrtc_ip_guard() -> bool:
    return _env_on("WICK_WEBRTC_IP_GUARD", True)


def reduce_client_hints() -> bool:
    return _env_on("WICK_REDUCE_CLIENT_HINTS", True)


def webrtc_args() -> list[str]:
    """Official Chromium IP-handling policy. No ICE host candidates on the LAN."""
    if not webrtc_ip_guard():
        return []
    return [
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    ]


def chrome_privacy_args() -> list[str]:
    """Privacy flags only. Never a forged User-Agent string."""
    args = list(webrtc_args())
    if reduce_client_hints():
        args.append("--disable-features=UserAgentClientHint,CriticalClientHint")
    return args


def merge_chrome_args(base: list[str], extra: list[str]) -> list[str]:
    """Fold extra flags into base. Multiple --disable-features= become one."""
    feats: list[str] = []
    out: list[str] = []

    def take(flag: str) -> None:
        if flag.startswith("--disable-features="):
            for part in flag.split("=", 1)[1].split(","):
                name = part.strip()
                if name and name not in feats:
                    feats.append(name)
            return
        if flag not in out:
            out.append(flag)

    for flag in list(base or []) + list(extra or []):
        take(flag)
    if feats:
        out.append("--disable-features=" + ",".join(feats))
    return out


def fingerprint_probes(
    *,
    url: str | None = None,
    excerpt: str | None = None,
    links: list[Any] | None = None,
    elements: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Deterministic report of known fingerprinting vendors / phrases."""
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(kind: str, evidence: str) -> None:
        key = kind + "|" + evidence
        if key in seen:
            return
        seen.add(key)
        hits.append({"kind": kind, "evidence": evidence[:160]})

    hrefs: list[str] = []
    if url:
        hrefs.append(url)
    for link in links or []:
        if isinstance(link, dict):
            hrefs.append(str(link.get("href") or ""))
        else:
            hrefs.append(str(link))
    for href in hrefs:
        host = (urlsplit(href if "://" in href else "https://" + href).hostname or "").lower()
        for needle in _FP_HOSTS:
            if needle in host or needle in href.lower():
                add("fingerprintjs" if "fpjs" in needle or "fingerprint" in needle else needle, host or href)
    text = " ".join(
        [
            str(excerpt or ""),
            " ".join(str((e or {}).get("name") or "") for e in (elements or []) if isinstance(e, dict)),
        ]
    ).lower()
    for word in _FP_WORDS:
        if word in text:
            add("fingerprintjs" if "fingerprint" in word else word, word)
    return hits


def status() -> dict[str, Any]:
    return {
        "webrtc_ip_guard": webrtc_ip_guard(),
        "reduce_client_hints": reduce_client_hints(),
        "fingerprint_farbling": False,
        "stealth": False,
        "not_claimed": "Brave canvas/WebGL/audio farbling and Camoufox-class stealth are not claimed",
    }


def annotate(out: dict[str, Any]) -> dict[str, Any]:
    """Attach privacy + probe metadata to an observe payload."""
    probes = fingerprint_probes(
        url=str(out.get("url") or ""),
        excerpt=str(out.get("excerpt") or out.get("content") or ""),
        links=list(out.get("links") or []),
        elements=list(out.get("elements") or []),
    )
    sec = dict(out.get("security") or {})
    sec["fingerprint_farbling"] = False
    sec["webrtc_ip_guard"] = webrtc_ip_guard()
    if probes:
        sec["fingerprint_probes"] = probes
    out["security"] = sec
    out["privacy"] = status()
    return out
