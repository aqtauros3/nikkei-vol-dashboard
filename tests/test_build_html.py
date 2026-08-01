"""build_html のテスト（ネットワーク不要）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import src.config as cfg
from src.report.build_html import build, _fmt


# ---------- ヘルパ ----------

def _make_vi(n: int = 300) -> pd.Series:
    rng = np.random.default_rng(0)
    vals = 25.0 + rng.normal(0, 3, n).cumsum() * 0.1
    vals = np.clip(vals, 10.0, 80.0)
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.Series(vals, index=idx, name="vi")


def _build_inputs(regime: str = "CALM") -> tuple[dict, dict]:
    vi = _make_vi(300)
    vi_ma = vi.rolling(20).mean()
    hv_yz = vi * 0.8
    vrp = vi - hv_yz
    dd = vi / vi.rolling(20).max() - 1.0

    hv_all = {
        "yang_zhang": hv_yz,
        "close_to_close": hv_yz * 0.95,
        "parkinson": hv_yz * 1.05,
        "garman_klass": hv_yz * 1.02,
        "rogers_satchell": hv_yz * 0.98,
    }

    metrics = {
        "date": "2024-08-01",
        "vi": float(vi.iloc[-1]),
        "iv_percentile": 60.0,
        "iv_rank": 55.0,
        "hv": {k: float(s.iloc[-1]) for k, s in hv_all.items()},
        "vrp": float(vrp.iloc[-1]),
        "regime": regime,
        "fetch_ok": True,
        "fetch_errors": [],
    }
    series = {
        "vi": vi,
        "vi_ma": vi_ma,
        "hv_yz": hv_yz,
        "hv_all": hv_all,
        "vrp": vrp,
        "vi_drawdown": dd,
    }
    return metrics, series


# ---------- _fmt フィルタ ----------

def test_fmt_normal():
    assert _fmt(25.678, ".2f") == "25.68"


def test_fmt_nan():
    assert _fmt(float("nan")) == "N/A"


def test_fmt_none():
    assert _fmt(None) == "N/A"


# ---------- build() ----------

def test_build_creates_index_html(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DOCS", tmp_path)
    metrics, series = _build_inputs()
    build(metrics, series)

    out = tmp_path / "index.html"
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert "日経225" in html
    assert "2024-08-01" in html
    assert "plotly" in html.lower()


def test_build_shows_regime_calm(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DOCS", tmp_path)
    metrics, series = _build_inputs(regime="CALM")
    build(metrics, series)

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "CALM" in html
    assert "regime-calm" in html
    # STRESS バナーは出ないこと
    assert "banner stress" not in html


def test_build_stress_shows_banner(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DOCS", tmp_path)
    metrics, series = _build_inputs(regime="STRESS")
    build(metrics, series)

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "banner stress" in html
    assert "新規売り回避" in html


def test_build_fetch_failure_shows_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DOCS", tmp_path)
    metrics, series = _build_inputs()
    metrics["fetch_ok"] = False
    metrics["fetch_errors"] = ["VI 取得失敗: timeout"]
    build(metrics, series)

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "更新失敗" in html
    assert "timeout" in html


def test_build_contains_four_charts(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DOCS", tmp_path)
    metrics, series = _build_inputs()
    build(metrics, series)

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    # Plotly は各チャートに Plotly.newPlot を生成する
    assert html.count("Plotly.newPlot") >= 4
