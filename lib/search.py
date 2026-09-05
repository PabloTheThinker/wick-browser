"""Headless web search for agents — structured SERP, no pixels.

Default engine is DuckDuckGo HTML (`html.duckduckgo.com`). A plain HTTP GET
with a Chromium User-Agent is enough; DDG otherwise serves a bot interstitial.
This is not fingerprint stealth. Chromium observe is an optional fallback.

Wikipedia OpenSearch is a second engine when you only need encyclopedia hits.
"""
from __future__ import annotations

import html as htmlmod
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    import origins as wick_origins
except Exception:
    wick_origins = None  # type: ignore
try:
    import capability as wick_capability
except Exception:
    wick_capability = None  # type: ignore
try:
    import observe_security as wick_observe_security
except Exception:
    wick_observe_security = None  # type: ignore

ENGINES = ("ddg", "ddg_lite", "wiki")
DEFAULT_ENGINE = "ddg"
DEFAULT_LIMIT = 8
SEARCH_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)
WICK_UA = "Wick/0.9 (headless agent browser; +https://github.com/PabloTheThinker/wick-browser)"

_A_RE = re.compile(
    r"""<a\b[^>]*class=["'][^"']*(?:result__a|result-link)[^"']*["'][^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)
# href may come before class
_A_RE_ALT = re.compile(
    r"""<a\b[^>]*href=["']([^"']+)["'][^>]*class=["'][^"']*(?:result__a|result-link)[^"']*["'][^>]*>(.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)
_SNIP_RE = re.compile(
    r"""class=["'][^"']*(?:result__snippet|result-snippet)[^"']*["'][^>]*>(.*?)</(?:a|td|span|div)>""",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_CHALLENGE_MARKERS = (
    "anomaly.js",
    "anomaly-modal",
    "pardon our interruption",
    "unusual traffic",
    "enable javascript and cookies",
)


def normalize_query(q: str | list[str] | None) -> str:
    if isinstance(q, (list, tuple)):
        q = " ".join(str(x) for x in q)
    return " ".join(str(q or "").split()).strip()


def engine_name(raw: str | None = None) -> str:
    name = (raw or os.environ.get("WICK_SEARCH_ENGINE") or DEFAULT_ENGINE).strip().lower()
    if name in {"duckduckgo", "html"}:
        return "ddg"
    if name in {"lite", "ddg-lite"}:
        return "ddg_lite"
    if name in {"wikipedia", "opensearch"}:
        return "wiki"
    return name if name in ENGINES else DEFAULT_ENGINE


def search_url(q: str, engine: str | None = None) -> str:
    query = normalize_query(q)
    enc = urllib.parse.quote_plus(query)
    eng = engine_name(engine)
    if eng == "ddg_lite":
        return f"https://lite.duckduckgo.com/lite/?q={enc}"
    if eng == "wiki":
        return (
            "https://en.wikipedia.org/w/api.php?action=opensearch&format=json"
            f"&formatversion=2&namespace=0&limit=10&search={enc}"
        )
    return f"https://html.duckduckgo.com/html/?q={enc}"


def _strip_text(raw: str) -> str:
    text = htmlmod.unescape(_TAG_RE.sub(" ", raw or ""))
    return _WS_RE.sub(" ", text).strip()


def unwrap_result_url(href: str | None) -> str:
    """Turn a DDG redirect / protocol-relative href into an https URL."""
    s = htmlmod.unescape((href or "").strip())
    if not s:
        return ""
    if s.startswith("//"):
        s = "https:" + s
    elif s.startswith("/l/?") or s.startswith("/l?"):
        s = "https://duckduckgo.com" + s
    try:
        parts = urllib.parse.urlsplit(s)
        qs = urllib.parse.parse_qs(parts.query)
        if qs.get("uddg"):
            s = urllib.parse.unquote(qs["uddg"][0])
    except Exception:
        pass
    if s.startswith("//"):
        s = "https:" + s
    return s


def _usable_result_url(url: str) -> str | None:
    if wick_origins is not None:
        if wick_origins.is_dangerous_url(url):
            return None
        try:
            url = wick_origins.normalize_agent_url(url)
        except ValueError:
            return None
        if wick_origins.is_private_url(url) and not wick_origins.allow_private_override():
            return None
    else:
        if not url.startswith("http://") and not url.startswith("https://"):
            return None
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host.endswith("duckduckgo.com") or host in {"duckduckgo.com", "www.duckduckgo.com"}:
        return None
    if wick_capability is not None:
        if wick_capability.deny_host(url):
            return None
    return url


def parse_serp_html(html: str) -> list[dict[str, str]]:
    """Parse DDG html or lite markup into {title, url, snippet}."""
    if not html:
        return []
    anchors = list(_A_RE.finditer(html)) + list(_A_RE_ALT.finditer(html))
    snippets = [_strip_text(m.group(1)) for m in _SNIP_RE.finditer(html)]
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for i, m in enumerate(anchors):
        title = _strip_text(m.group(2))
        dest = _usable_result_url(unwrap_result_url(m.group(1)))
        if not dest or dest in seen or not title:
            continue
        seen.add(dest)
        out.append(
            {
                "title": title[:200],
                "url": dest,
                "snippet": snippets[i][:280] if i < len(snippets) else "",
            }
        )
    return out


def parse_wiki_opensearch(payload: Any) -> list[dict[str, str]]:
    if not isinstance(payload, list) or len(payload) < 4:
        return []
    titles, descs, urls = payload[1], payload[2], payload[3]
    if not isinstance(titles, list):
        return []
    out: list[dict[str, str]] = []
    for i, title in enumerate(titles):
        dest = _usable_result_url(str(urls[i] if i < len(urls) else ""))
        if not dest:
            continue
        out.append(
            {
                "title": str(title)[:200],
                "url": dest,
                "snippet": str(descs[i] if i < len(descs) else "")[:280],
            }
        )
    return out


def looks_like_challenge(html: str) -> bool:
    blob = (html or "").lower()
    return any(m in blob for m in _CHALLENGE_MARKERS)


def pack_results(
    *,
    q: str,
    engine: str,
    results: list[dict[str, str]],
    url: str,
    via: str,
    http_status: int | None,
    ms: int,
    limit: int,
    challenge: bool = False,
) -> dict[str, Any]:
    trimmed = results[: max(1, min(int(limit), 25))]
    items = []
    for i, row in enumerate(trimmed, start=1):
        dest = row["url"]
        items.append(
            {
                "n": i,
                "title": row.get("title") or dest,
                "url": dest,
                "snippet": row.get("snippet") or "",
                "cmd": f"wick snap {dest} --profile micro",
            }
        )
    suggestions = []
    if items:
        first = items[0]["url"]
        suggestions.append(
            {
                "action": "snap",
                "cmd": f"wick snap {first} --profile micro",
                "why": f"read first result: {items[0]['title']}",
            }
        )
        if len(items) >= 2:
            top = " ".join(r["url"] for r in items[:3])
            suggestions.append(
                {
                    "action": "snap_many",
                    "cmd": f"wick snap-many {top}",
                    "why": "brief the top results in parallel (micro)",
                }
            )
        suggestions.append(
            {
                "action": "open",
                "cmd": f"wick open {first} --fast",
                "why": "full markdown of the first result",
            }
        )
    out: dict[str, Any] = {
        "ok": True,
        "product": "wick",
        "mode": "agent_search",
        "engine": engine,
        "q": q,
        "url": url,
        "via": via,
        "headless": True,
        "pixels": False,
        "http_status": http_status,
        "http_ok": http_status is None or 200 <= int(http_status) < 400,
        "count": len(items),
        "results": items,
        "suggestions": suggestions,
        "ms": ms,
    }
    if challenge:
        out["challenge"] = True
        out["hint"] = "Search engine served an interstitial. Retry, use --engine wiki, or --chromium."
    if wick_observe_security is not None:
        try:
            wick_observe_security.annotate_observe(out)
        except Exception:
            out["untrusted_content"] = True
    else:
        out["untrusted_content"] = True
    return out


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if newurl is None:
            return None
        joined = urllib.parse.urljoin(req.full_url, newurl)
        if wick_origins is not None:
            err = wick_origins.guard_fetch_url(joined, resolve=False)
            if err:
                raise urllib.error.HTTPError(joined, 403, err.get("error") or "blocked", headers, None)
        if wick_capability is not None:
            herr = wick_capability.deny_host(joined)
            if herr:
                raise urllib.error.HTTPError(joined, 403, "host_not_allowed", headers, None)
        return super().redirect_request(req, fp, code, msg, headers, joined)


def light_fetch(url: str, *, timeout: int = 20) -> dict[str, Any]:
    """Plain HTTP GET. No Chromium. Redirects stay under the same URL guards."""
    if wick_origins is not None:
        err = wick_origins.guard_fetch_url(url)
        if err:
            return err
    if wick_capability is not None:
        herr = wick_capability.deny_host(url)
        if herr:
            return herr
    t0 = time.time()
    opener = urllib.request.build_opener(_GuardedRedirect)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": SEARCH_UA,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
            final = str(getattr(resp, "url", url) or url)
            ctype = str(resp.headers.get("Content-Type") or "")
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "product": "wick",
            "error": "search_http_error",
            "http_status": int(e.code),
            "url": url,
            "detail": str(e.reason)[:160],
        }
    except Exception as e:
        return {
            "ok": False,
            "product": "wick",
            "error": "search_fetch_failed",
            "url": url,
            "detail": str(e)[:200],
        }
    if wick_origins is not None:
        err = wick_origins.guard_fetch_url(final)
        if err:
            err["landed"] = True
            return err
    text = raw.decode("utf-8", errors="replace")
    return {
        "ok": True,
        "url": final,
        "http_status": status,
        "content_type": ctype,
        "html": text,
        "ms": int((time.time() - t0) * 1000),
    }


def run_search(
    q: str | list[str],
    *,
    engine: str | None = None,
    limit: int = DEFAULT_LIMIT,
    html: str | None = None,
    wiki_json: Any | None = None,
    via: str = "http",
    url: str | None = None,
    http_status: int | None = None,
    ms: int = 0,
) -> dict[str, Any]:
    """Parse already-fetched SERP bytes, or fetch via light HTTP when html is None."""
    query = normalize_query(q)
    if not query:
        return {"ok": False, "product": "wick", "error": "missing_query", "hint": "wick search example domain"}
    eng = engine_name(engine)
    if eng not in ENGINES:
        return {"ok": False, "product": "wick", "error": "unknown_engine", "engine": eng, "hint": "ddg | ddg_lite | wiki"}
    dest = url or search_url(query, eng)
    challenge = False
    if html is None and wiki_json is None:
        fetched = light_fetch(dest)
        if not fetched.get("ok"):
            return fetched
        dest = str(fetched.get("url") or dest)
        http_status = fetched.get("http_status")
        ms = int(fetched.get("ms") or 0)
        if eng == "wiki":
            try:
                wiki_json = json.loads(fetched.get("html") or "[]")
            except ValueError:
                return {"ok": False, "product": "wick", "error": "bad_wiki_json", "url": dest}
        else:
            html = str(fetched.get("html") or "")
            challenge = looks_like_challenge(html)
            via = "http"
    if eng == "wiki":
        rows = parse_wiki_opensearch(wiki_json)
    else:
        rows = parse_serp_html(html or "")
        challenge = challenge or looks_like_challenge(html or "")
    return pack_results(
        q=query,
        engine=eng,
        results=rows,
        url=dest,
        via=via,
        http_status=http_status,
        ms=ms,
        limit=limit,
        challenge=challenge and not rows,
    )
