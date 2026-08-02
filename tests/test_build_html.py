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

    # IV スキュー・期間構造の合成データ
    strikes = [36000, 37000, 38000, 39000, 40000]
    underlying = 38000.0
    skew_df = pd.DataFrame({
        "moneyness": [s / underlying for s in strikes],
        "iv_put": [28.0, 25.0, 22.0, 20.0, 19.0],
        "iv_call": [20.0, 21.0, 22.0, 23.0, 24.0],
        "outlier_put": [False] * 5,
        "outlier_call": [False] * 5,
    })
    iv_term = pd.Series({"202609": 22.0, "202612": 24.0, "202703": 25.5}, name="atm_iv")
    futures_term = pd.Series({"202609": 38300.0, "202612": 38600.0, "202703": 38850.0}, name="settlement")

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
        "atm_iv": 22.0,
        "vrp_option": 3.0,
        "option_data_ok": True,
        "option_fetched_today": True,
        "option_data_date": "2024-08-01",
        "option_fetch_errors": [],
        "iv_term_slope": {
            "slope": -2.0,
            "front_iv": 22.0,
            "far_iv": 24.0,
            "front_expiry": "202609",
            "far_expiry": "202612",
        },
    }
    series = {
        "vi": vi,
        "vi_ma": vi_ma,
        "hv_yz": hv_yz,
        "hv_all": hv_all,
        "vrp": vrp,
        "vi_drawdown": dd,
        "iv_skew": skew_df,
        "iv_skew_expiry": "202609",
        "iv_term": iv_term,
        "futures_term": futures_term,
        "futures_underlying": underlying,
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


def test_build_contains_nine_charts(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DOCS", tmp_path)
    metrics, series = _build_inputs()
    build(metrics, series)

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    # 4(VI/HV/VRP/drawdown) + 3(skew/iv_term/futures_term) + 2(iv_term_zoom/futures_term_zoom)
    assert html.count("Plotly.newPlot") >= 9
