"""realized_vol の健全性テスト（ネットワーク不要）。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.compute import realized_vol as rv


def _synthetic(n: int = 300, sigma_daily: float = 0.01, seed: int = 0) -> pd.DataFrame:
    """既知の日次ボラで対数正規パスを生成し OHLC を作る。"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, sigma_daily, n)
    close = 30000 * np.exp(np.cumsum(rets))
    open_ = close / np.exp(rets)  # 前日終値≒当日始値の近似
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.003, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.003, n))
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def test_all_estimators_positive_and_reasonable():
    df = _synthetic()
    out = rv.all_latest(df, window=20, annualization=245)
    for name, val in out.items():
        assert np.isfinite(val), f"{name} が非有限"
        assert 0 < val < 200, f"{name} が非現実的: {val}"  # 年率% 表示


def test_close_to_close_recovers_input_vol():
    # 日次1% → 年率 ≒ 1% * sqrt(245) ≒ 15.6% 前後
    df = _synthetic(n=500, sigma_daily=0.01, seed=1)
    s = rv.close_to_close(df, window=250, annualization=245)
    ann = s.iloc[-1] * 100
    assert 12 < ann < 20, f"回収した年率ボラが範囲外: {ann}"
