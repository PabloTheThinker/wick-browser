"""Lightpanda fetch + metrics parse for Wick shields proof."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable


def parse_metrics(text: str) -> dict[str, int | None]:
    async_req = re.findall(r'http_requests_total\{mode="async"\}\s+(\d+)', text)
    sync_req = re.findall(r'http_requests_total\{mode="sync"\}\s+(\d+)', text)
    ok2 = re.findall(r'http_status_total\{category="2xx"\}\s+(\d+)', text)
    return {
        "http_requests_async": int(async_req[-1]) if async_req else None,
        "http_requests_sync": int(sync_req[-1]) if sync_req else None,
        "http_2xx": int(ok2[-1]) if ok2 else None,
    }


def metrics_pass(
    lp_bin: str | Path,
    url: str,
    *,
    build_shield_cmd: Callable[[list[str]], None] | None = None,
    wait_ms: int = 3500,
    wait_until: str = "load",
) -> dict[str, Any]:
    cmd = [
        str(lp_bin),
        "fetch",
        url,
        "--json",
        "--metrics",
        "--dump",
        "markdown",
        "--wait-ms",
        str(wait_ms),
        "--wait-until",
        wait_until,
        "--block-private-networks",
    ]
    if build_shield_cmd:
        build_shield_cmd(cmd)
    proc = subprocess.run(cmd, capture_output=True, timeout=90)
    text = proc.stdout.decode(errors="replace") + "\n" + proc.stderr.decode(errors="replace")
    return parse_metrics(text)
