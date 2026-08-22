#!/usr/bin/env python3
"""Tests for CLI edge cases in bin/wick."""
from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path


def _load_wick_module():
    wick_path = Path(__file__).resolve().parents[1] / "bin" / "wick"
    loader = SourceFileLoader("wick_cli", str(wick_path))
    spec = importlib.util.spec_from_loader("wick_cli", loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wick = _load_wick_module()


def test_lp_fetch_rejects_blank_url():
    result = wick.lp_fetch("   ")
    assert result["ok"] is False
    assert result["error"] == "no_url"
    assert result["product"] == "wick"


def test_lp_fetch_reports_missing_lightpanda(monkeypatch):
    monkeypatch.setattr(wick, "find_lightpanda", lambda: None)
    result = wick.lp_fetch("https://example.com/")
    assert result["ok"] is False
    assert result["error"] == "lightpanda_not_found"
    assert result["product"] == "wick"
