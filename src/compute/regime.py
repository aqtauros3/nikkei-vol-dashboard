"""レジーム判定。VIの水準・傾き・ピークからの位置で「売り環境か回避か」を分類。

重要な設計思想（SPEC.md の§11・戦略章と一致）:
「VIが高い＝売り」ではない。急落中でVIが上昇継続＝実現ボラがIVを上回りやすく
VRPが負になりうる → 新規売りは回避。VIがピークアウトして低下＝平常回帰＝売り検討。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import config


def vi_moving_average(vi_series: pd.Series, window: int = 20) -> pd.Series:
    return vi_series.rolling(window).mean()


def vi_slope(vi_series: pd.Series, lookback: int = 5) -> float:
    """直近 lookback 日の平均変化（正=上昇, 負=低下）。"""
    d = vi_series.diff().dropna().tail(lookback)
    return float(d.mean()) if len(d) else float("nan")


def vi_peak_drawdown(vi_series: pd.Series, lookback: int = 20) -> float:
    """直近ピークからの位置。0=ピーク近傍, 負に大きい=ピークアウト進行。"""
    s = vi_series.dropna().tail(lookback)
    if len(s) < 2:
        return float("nan")
    peak, cur = s.max(), s.iloc[-1]
    return float(cur / peak - 1.0) if peak > 0 else float("nan")


def regime_flag(
    vi_value: float,
    vi_ma: float,
    slope: float,
    dead_band_pct: float | None = None,
) -> str:
    """'STRESS'（売り回避） / 'CALM'（売り検討） / 'NEUTRAL'。

    dead_band_pct: |VI-MA|/MA がこれ未満なら NEUTRAL に強制（誤検知抑制）。
    デフォルトは config.REGIME_DEAD_BAND_PCT（2%）。
    例: VI=25.5, MA=25.0 → 乖離率=2%で不感帯内 → NEUTRAL。
    """
    if any(pd.isna(x) for x in (vi_value, vi_ma, slope)):
        return "UNKNOWN"
    if dead_band_pct is None:
        dead_band_pct = config.REGIME_DEAD_BAND_PCT
    if vi_ma > 0 and abs(vi_value - vi_ma) / vi_ma < dead_band_pct:
        return "NEUTRAL"  # 不感帯: MA との乖離が微小 → 方向判定を保留
    if vi_value > vi_ma and slope > 0:
        return "STRESS"   # 高止まり＋上昇 → 新規売り回避
    if vi_value < vi_ma and slope < 0:
        return "CALM"     # 平常回帰 → 売り検討
    return "NEUTRAL"


def iv_absolute_level(iv_percentile: float, high_threshold: float | None = None) -> str:
    """IV Percentile の絶対水準を 'HIGH' / 'NORMAL' / 'LOW' で返す。

    high_threshold: 以上で HIGH（デフォルト: config.REGIME_HIGH_IV_THRESHOLD=70%）。
    30% 未満で LOW。
    """
    if pd.isna(iv_percentile):
        return "UNKNOWN"
    if high_threshold is None:
        high_threshold = config.REGIME_HIGH_IV_THRESHOLD
    if iv_percentile >= high_threshold:
        return "HIGH"
    if iv_percentile < 30.0:
        return "LOW"
    return "NORMAL"
