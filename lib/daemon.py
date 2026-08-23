#!/usr/bin/env python3
"""Persistent Playwright Chromium daemon exposing CDP for agents."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HOME = Path(os.environ.get("WICK_HOME", Path.home() / ".wick"))
STATE = HOME / "state"
LOGS = HOME / "logs"
USER_DATA = Path(os.environ.get("WICK_CHROME_PROFILE") or (HOME / "profile"))
CDP_PORT = int(os.environ.get("WICK_CHROME_PORT", "9222"))
HEADLESS = os.environ.get("WICK_HEADLESS", "1") != "0"
USE_XVFB = os.environ.get("WICK_XVFB", "0") == "1"
PID_FILE = STATE / "browser.pid"
META_FILE = STATE / "meta.json"

_xvfb_proc = None
_pw = None
_context = None


def start_xvfb() -> str | None:
    global _xvfb_proc
    if not USE_XVFB:
        return None
    LOGS.mkdir(parents=True, exist_ok=True)
    for n in range(90, 110):
        display = f":{n}"
        lock = Path(f"/tmp/.X{n}-lock")
        if lock.exists():
            continue
        log = open(LOGS / "xvfb.log", "a", encoding="utf-8")
        _xvfb_proc = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", "1440x900x24", "-ac"],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        time.sleep(0.4)
        if _xvfb_proc.poll() is None:
            os.environ["DISPLAY"] = display
            return display
    return None


def _cleanup() -> None:
    global _xvfb_proc, _pw, _context
    try:
        if _context is not None:
            _context.close()
    except Exception:
        pass
    _context = None
    try:
        if _pw is not None:
            _pw.stop()
    except Exception:
        pass
    _pw = None
    if _xvfb_proc is not None and _xvfb_proc.poll() is None:
        try:
            _xvfb_proc.terminate()
            try:
                _xvfb_proc.wait(timeout=2)
            except Exception:
                _xvfb_proc.kill()
        except Exception:
            pass
    _xvfb_proc = None
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def main() -> int:
    global _pw, _context
    # Create dirs before Xvfb / Chromium so open() never races a missing path.
    for d in (HOME, STATE, LOGS, USER_DATA, HOME / "shots"):
        d.mkdir(parents=True, exist_ok=True)
    try:
        HOME.chmod(0o700)
    except OSError:
        pass

    display = start_xvfb()
    # When Xvfb is on, run headed chromium against virtual display (less bot-like).
    headless = HEADLESS and not display

    exit_code = 0
    stop = {"flag": False}

    def _stop(*_a):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    try:
        _pw = sync_playwright().start()
        launch_args = [
            f"--remote-debugging-port={CDP_PORT}",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-features=Translate,BackForwardCache",
            "--disable-sync",
            "--metrics-recording-only",
            "--password-store=basic",
            "--use-mock-keychain",
            "--disable-blink-features=AutomationControlled",
            "--no-pings",
            "--disable-client-side-phishing-detection",
            "--disable-component-update",
            "--disable-breakpad",
        ]
        try:
            import privacy as wick_privacy

            for flag in wick_privacy.chrome_privacy_args():
                if flag not in launch_args:
                    launch_args.append(flag)
        except Exception:
            pass
        extra_headers = {}
        if os.environ.get("WICK_PRIVACY_HEADERS", "1") != "0":
            extra_headers = {
                "DNT": "1",
                "Sec-GPC": "1",
                "Upgrade-Insecure-Requests": "1",
            }
        launch_kwargs = dict(
            user_data_dir=str(USER_DATA),
            headless=headless,
            args=launch_args,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
            ignore_https_errors=False,
            accept_downloads=True,
            extra_http_headers=extra_headers,
            downloads_path=str(Path(os.environ.get("WICK_DOWNLOADS") or (HOME / "downloads"))),
        )
        try:
            _context = _pw.chromium.launch_persistent_context(
                channel="chromium",
                **launch_kwargs,
            )
        except Exception:
            launch_kwargs.pop("extra_http_headers", None)
            try:
                _context = _pw.chromium.launch_persistent_context(
                    channel="chromium",
                    **launch_kwargs,
                )
            except Exception:
                _context = _pw.chromium.launch_persistent_context(**launch_kwargs)

        page = _context.pages[0] if _context.pages else _context.new_page()
        try:
            _context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                "window.chrome=window.chrome||{runtime:{}};"
            )
        except Exception:
            pass
        page.goto("about:blank")

        meta = {
            "pid": os.getpid(),
            "cdp": f"http://127.0.0.1:{CDP_PORT}",
            "headless": headless,
            "display": display,
            "user_data": str(USER_DATA),
            "started": time.time(),
            "home": str(HOME),
        }
        META_FILE.write_text(json.dumps(meta, indent=2) + "\n")
        PID_FILE.write_text(str(os.getpid()))
        print(json.dumps({"daemon": "up", **meta}), flush=True)

        while not stop["flag"]:
            time.sleep(1.0)
            if not _context.pages:
                _context.new_page()

    except Exception as e:
        print(json.dumps({"daemon": "error", "error": str(e)}), flush=True)
        exit_code = 1
    finally:
        _cleanup()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
