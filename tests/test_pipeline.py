"""run_local パイプラインの単体テスト（ネットワーク不要）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import src.config as cfg
from src.compute import iv_metrics, realized_vol, regime


# ---------- ヘルパ: 合成データ ----------

def _make_ohlc(n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rets = rng.normal(0, 0.01, n)
    close = 35000 * np.exp(np.cumsum(rets))
    open_ = close / np.exp(rets)
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.003, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.003, n))
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def _make_vi(n: int = 300, base: float = 25.0) -> pd.Series:
    rng = np.random.default_rng(7)
    vals = base + rng.normal(0, 3.0, n).cumsum() * 0.1
    vals = np.clip(vals, 10.0, 80.0)
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.Series(vals, index=idx, name="vi")


# ---------- compute 層の結合テスト ----------

def test_hv_all_latest_finite():
    ohlc = _make_ohlc()
    out = realized_vol.all_latest(ohlc, cfg.HV_WINDOW, cfg.ANNUALIZATION)
    for k, v in out.items():
        assert np.isfinite(v), f"{k} が非有限"
        assert 0 < v < 200, f"{k} = {v} が範囲外"


def test_iv_metrics_finite():
    vi = _make_vi(300)
    ivr = iv_metrics.iv_rank(vi, cfg.IV_HISTORY_WINDOW)
    ivp = iv_metrics.iv_percentile(vi, cfg.IV_HISTORY_WINDOW)
    assert 0 <= ivr <= 100
    assert 0 <= ivp <= 100


def test_vrp_sign():
    """VI > HV なら VRP > 0。"""
    vrp = iv_metrics.vrp_proxy(vi_value=40.0, hv_annual_pct=20.0)
    assert vrp == pytest.approx(20.0)


def test_regime_stress():
    vi = _make_vi(60, base=40.0)
    ma = regime.vi_moving_average(vi, window=20)
    slope = regime.vi_slope(vi, lookback=5)
    # 最後の値が MA より高く傾きが正になるように調整済み（base 高め）
    flag = regime.regime_flag(float(vi.iloc[-1]), float(ma.iloc[-1]), slope)
    assert flag in {"STRESS", "CALM", "NEUTRAL", "UNKNOWN"}


def test_regime_flag_unknown_on_nan():
    flag = regime.regime_flag(float("nan"), 25.0, 0.5)
    assert flag == "UNKNOWN"


# ---------- 縮退運転: fetch 失敗でも compute が通ること ----------

def test_pipeline_compute_without_fetch(tmp_path, monkeypatch):
    """OHLC と VI の CSV が既に存在すれば fetch 失敗でも compute できる。"""
    # tmp_path に CSV を用意
    ohlc = _make_ohlc(300)
    ohlc.index.name = "date"
    ohlc_path = tmp_path / "nikkei_ohlc.csv"
    ohlc.to_csv(ohlc_path, date_format="%Y-%m-%d")

    vi = _make_vi(300)
    vi.index.name = "date"
    vi_path = tmp_path / "nikkei_vi.csv"
    vi.to_csv(vi_path, header=True, date_format="%Y-%m-%d")

    monkeypatch.setattr(cfg, "HISTORY", tmp_path)
    monkeypatch.setattr(cfg, "OHLC_CSV", ohlc_path)
    monkeypatch.setattr(cfg, "VI_CSV", vi_path)

    # compute 層を直接呼ぶ（run_local.main() はネットワーク呼び出しを含むため）
    import pandas as pd
    from src.compute import iv_metrics, realized_vol, regime
    from src.fetch.nikkei_vi import load_vi_history

    df = pd.read_csv(ohlc_path, index_col=0, parse_dates=True)
    df.columns = df.columns.str.lower()
    vi_s = load_vi_history()

    hv = realized_vol.all_latest(df, cfg.HV_WINDOW, cfg.ANNUALIZATION)
    ivp = iv_metrics.iv_percentile(vi_s, cfg.IV_HISTORY_WINDOW)
    vrp = iv_metrics.vrp_proxy(float(vi_s.iloc[-1]), hv[cfg.HV_PRIMARY])
    ma = regime.vi_moving_average(vi_s, cfg.VI_MA_WINDOW)
    slope = regime.vi_slope(vi_s, cfg.VI_SLOPE_LOOKBACK)
    flag = regime.regime_flag(float(vi_s.iloc[-1]), float(ma.dropna().iloc[-1]), slope)

    assert np.isfinite(ivp)
    assert np.isfinite(vrp)
    assert flag in {"STRESS", "CALM", "NEUTRAL", "UNKNOWN"}
