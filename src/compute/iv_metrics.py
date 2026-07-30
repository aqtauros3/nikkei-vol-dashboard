"""IV 水準系の指標。日経VI（または ATM IV）の時系列から算出。

単位の約束:
- vi_series / vi_value は「％表記」（例 41.29）
- hv_annual_pct も「年率％」（realized_vol は小数を返すので ×100 して渡す）
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def iv_rank(vi_series: pd.Series, window: int = 252) -> float:
    """IV Rank = (現在 − 期間最小) / (期間最大 − 期間最小) × 100。"""
    s = vi_series.dropna().tail(window)
    if len(s) < 2:
        return float("nan")
    lo, hi, cur = s.min(), s.max(), s.iloc[-1]
    return float((cur - lo) / (hi - lo) * 100.0) if hi > lo else float("nan")


def iv_percentile(vi_series: pd.Series, window: int = 252) -> float:
    """IV Percentile = 期間中に現在値を下回った日数の割合 × 100。
    スパイクに引っ張られにくく、エントリー判定に推奨。
    """
    s = vi_series.dropna().tail(window)
    if len(s) < 2:
        return float("nan")
    cur = s.iloc[-1]
    return float((s < cur).sum() / len(s) * 100.0)


def vrp_proxy(vi_value: float, hv_annual_pct: float) -> float:
    """簡易 VRP（ボラポイント）= 日経VI − HV。正で大きいほど売り妙味。
    厳密には分散ベース（IV² − E[RV²]）だが、ダッシュボード表示は本簡易版で足りる。
    """
    return float(vi_value - hv_annual_pct)
