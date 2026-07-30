"""実現ボラティリティ推定量（年率化）。

入力: pandas.DataFrame（列: open, high, low, close, 昇順の日付インデックス）
出力: いずれも「年率化した標準偏差」の rolling Series（小数。例 0.22 = 22%）

日経は夜間ギャップが大きいため、既定の推奨は yang_zhang。
年率化係数 ANNUALIZATION は config.py で設定（日本株の営業日 ≒ 245）。

数式の出典: Parkinson(1980), Garman-Klass(1980), Rogers-Satchell(1991),
Yang-Zhang(2000)。詳細は リポジトリ直下の SPEC.md を参照。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _require_cols(df: pd.DataFrame) -> None:
    need = {"open", "high", "low", "close"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame に列が不足しています: {sorted(missing)}")


def close_to_close(df: pd.DataFrame, window: int, annualization: float) -> pd.Series:
    """標準的な終値ベース推定量。σ² = Var(ln(C_t/C_{t-1}))（標本分散）。"""
    _require_cols(df)
    r = np.log(df["close"] / df["close"].shift(1))
    var = r.rolling(window).var(ddof=1)
    return np.sqrt(var * annualization)


def parkinson(df: pd.DataFrame, window: int, annualization: float) -> pd.Series:
    """高安幅推定量。σ² = 1/(4 ln2) · mean(ln(H/L)²)。ギャップは無視。"""
    _require_cols(df)
    hl = np.log(df["high"] / df["low"]) ** 2
    var = (1.0 / (4.0 * np.log(2.0))) * hl.rolling(window).mean()
    return np.sqrt(var * annualization)


def garman_klass(df: pd.DataFrame, window: int, annualization: float) -> pd.Series:
    """OHLC 推定量。σ² = mean(0.5·ln(H/L)² − (2ln2−1)·ln(C/O)²)。"""
    _require_cols(df)
    hl = np.log(df["high"] / df["low"]) ** 2
    co = np.log(df["close"] / df["open"]) ** 2
    term = 0.5 * hl - (2.0 * np.log(2.0) - 1.0) * co
    var = term.rolling(window).mean()
    return np.sqrt(var * annualization)


def rogers_satchell(df: pd.DataFrame, window: int, annualization: float) -> pd.Series:
    """ドリフト非依存の OHLC 推定量。
    σ² = mean(ln(H/C)·ln(H/O) + ln(L/C)·ln(L/O))。
    """
    _require_cols(df)
    ho = np.log(df["high"] / df["open"])
    hc = np.log(df["high"] / df["close"])
    lo = np.log(df["low"] / df["open"])
    lc = np.log(df["low"] / df["close"])
    rs = hc * ho + lc * lo
    var = rs.rolling(window).mean()
    return np.sqrt(var * annualization)


def yang_zhang(df: pd.DataFrame, window: int, annualization: float) -> pd.Series:
    """Yang-Zhang 推定量（オーバーナイト＋ドリフト対応・最も効率的）。
    σ²_YZ = σ²_overnight + k·σ²_open2close + (1−k)·σ²_RS
    k = 0.34 / (1.34 + (n+1)/(n−1))
    日経のように夜間ギャップが大きい系列に推奨。
    """
    _require_cols(df)
    o = np.log(df["open"] / df["close"].shift(1))   # overnight return
    c = np.log(df["close"] / df["open"])            # open-to-close return
    o_var = o.rolling(window).var(ddof=1)
    c_var = c.rolling(window).var(ddof=1)

    ho = np.log(df["high"] / df["open"])
    hc = np.log(df["high"] / df["close"])
    lo = np.log(df["low"] / df["open"])
    lc = np.log(df["low"] / df["close"])
    rs = hc * ho + lc * lo
    rs_var = rs.rolling(window).mean()

    k = 0.34 / (1.34 + (window + 1) / (window - 1))
    var = o_var + k * c_var + (1.0 - k) * rs_var
    return np.sqrt(var * annualization)


ESTIMATORS = {
    "close_to_close": close_to_close,
    "parkinson": parkinson,
    "garman_klass": garman_klass,
    "rogers_satchell": rogers_satchell,
    "yang_zhang": yang_zhang,
}


def all_latest(df: pd.DataFrame, window: int, annualization: float) -> dict[str, float]:
    """全推定量の「最新値（年率, %表記）」を dict で返す。表示・比較用。"""
    out: dict[str, float] = {}
    for name, fn in ESTIMATORS.items():
        s = fn(df, window, annualization)
        val = s.iloc[-1] if len(s) else np.nan
        out[name] = float(val * 100.0) if pd.notna(val) else float("nan")
    return out
