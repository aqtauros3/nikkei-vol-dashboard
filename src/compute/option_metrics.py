"""オプション・先物デリバティブデータからの指標算出（副作用なしの純関数群）。

入力: jpx_derivatives.csv から読み込んだ DataFrame（1日分）
出力: チャート用 Series/DataFrame、サマリー用スカラー

単位の約束:
    iv は年率%表記（例: 24.1）で受け取り、そのまま返す。×100 や /100 は不要。

put_call の値:
    "PUT" / "CAL"（JPX CSV のまま）。NaN の行が先物。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import config


# ---------------------------------------------------------------------------
# 基本フィルタ
# ---------------------------------------------------------------------------

def filter_options(
    df: pd.DataFrame,
    expiry: str | None = None,
    put_call: str | None = None,
) -> pd.DataFrame:
    """オプション行だけを返す。expiry・put_call で絞り込み可能。"""
    mask = df["put_call"].notna()
    if expiry is not None:
        mask &= df["expiry"] == expiry
    if put_call is not None:
        mask &= df["put_call"] == put_call
    return df[mask].copy()


def filter_futures(df: pd.DataFrame, expiry: str | None = None) -> pd.DataFrame:
    """先物行だけを返す（put_call が NaN の行）。"""
    mask = df["put_call"].isna()
    if expiry is not None:
        mask &= df["expiry"] == expiry
    return df[mask].copy()


# ---------------------------------------------------------------------------
# 限月選択
# ---------------------------------------------------------------------------

def nearest_expiry(df: pd.DataFrame) -> str:
    """残日数が最短（かつ正）の限月を返す。

    days_to_expiry > 0 のオプション行を対象にする。
    全行 NaN または該当なしの場合は expiry の最小値（辞書順）で代替。
    """
    opts = filter_options(df)
    valid = opts[opts["days_to_expiry"].fillna(0) > 0]
    if valid.empty:
        # フォールバック: 辞書順最小の限月
        all_expiries = opts["expiry"].dropna().unique()
        if len(all_expiries) == 0:
            raise ValueError("オプション行が存在しません")
        return sorted(all_expiries)[0]
    min_dte = valid["days_to_expiry"].min()
    return valid[valid["days_to_expiry"] == min_dte]["expiry"].iloc[0]


# ---------------------------------------------------------------------------
# ATM IV
# ---------------------------------------------------------------------------

def atm_iv(df: pd.DataFrame, expiry: str) -> float:
    """指定限月の ATM IV（%）を返す。

    ATM 定義: |strike / underlying - 1| が最小の strike を ATM とし、
    そのストライクの CAL と PUT の IV の平均を返す。
    片方しかなければその値を使う。

    理由: Put-Call パリティの理論上は同値だが実際には需給乖離がある。
    平均を取ることで単側の歪みを中和し、安定した ATM IV を得る。
    """
    opts = filter_options(df, expiry=expiry)
    if opts.empty or opts["underlying"].dropna().empty:
        return float("nan")

    underlying = float(opts["underlying"].dropna().iloc[0])
    opts = opts.copy()
    opts["moneyness_dist"] = (opts["strike"] / underlying - 1.0).abs()
    min_dist = opts["moneyness_dist"].min()
    atm_rows = opts[opts["moneyness_dist"] == min_dist]

    iv_vals = atm_rows["iv"].dropna()
    return float(iv_vals.mean()) if len(iv_vals) > 0 else float("nan")


# ---------------------------------------------------------------------------
# IV スキュー
# ---------------------------------------------------------------------------

def iv_skew_series(df: pd.DataFrame, expiry: str) -> pd.DataFrame:
    """指定限月の IV スキューデータを返す。

    戻り値: DataFrame の列は [moneyness, iv_put, iv_call, outlier_put, outlier_call]
        - moneyness = strike / underlying（1.0 が ATM）
        - iv_put: PUT の IV（%）、iv_call: CAL の IV（%）
        - outlier_put/call: True = 異常値フラグ（淡色表示の対象）
    """
    opts = filter_options(df, expiry=expiry)
    if opts.empty or opts["underlying"].dropna().empty:
        return pd.DataFrame(
            columns=["moneyness", "iv_put", "iv_call", "outlier_put", "outlier_call"]
        )

    underlying = float(opts["underlying"].dropna().iloc[0])
    opts = opts.copy()
    opts["moneyness"] = opts["strike"] / underlying

    puts = (
        opts[opts["put_call"] == "PUT"][["moneyness", "iv"]]
        .rename(columns={"iv": "iv_put"})
        .set_index("moneyness")
    )
    calls = (
        opts[opts["put_call"] == "CAL"][["moneyness", "iv"]]
        .rename(columns={"iv": "iv_call"})
        .set_index("moneyness")
    )

    result = puts.join(calls, how="outer").reset_index().sort_values("moneyness")

    result["outlier_put"] = _flag_iv_outliers(result["iv_put"])
    result["outlier_call"] = _flag_iv_outliers(result["iv_call"])

    return result.reset_index(drop=True)


def _flag_iv_outliers(
    iv_series: pd.Series,
    threshold_pct: float | None = None,
) -> pd.Series:
    """ローリング近傍中央値から threshold_pct 以上乖離した点を True でフラグ。

    window=5（前後 2 strike を「近傍」と定義）、center=True。
    閾値は config.IV_OUTLIER_PCT_THRESH（デフォルト 0.30 = ±30%）。
    """
    if threshold_pct is None:
        threshold_pct = config.IV_OUTLIER_PCT_THRESH

    s = iv_series.copy().reset_index(drop=True)
    if s.dropna().empty:
        return pd.Series(False, index=s.index)

    rolling_med = s.rolling(window=5, center=True, min_periods=2).median()
    rolling_med = rolling_med.fillna(s.median())  # 端点を全体中央値で補完

    denom = rolling_med.clip(lower=1e-9)
    flag = ((s - rolling_med).abs() / denom > threshold_pct).fillna(False)
    return flag


# ---------------------------------------------------------------------------
# 期間構造
# ---------------------------------------------------------------------------

def iv_term_structure(df: pd.DataFrame) -> pd.Series:
    """限月ごとの ATM IV（%）を返す Series（index=expiry, 昇順）。"""
    opts = filter_options(df)
    expiries = sorted(opts["expiry"].dropna().unique())
    return pd.Series(
        {exp: atm_iv(df, exp) for exp in expiries},
        name="atm_iv",
    )


def futures_term_structure(df: pd.DataFrame) -> pd.Series:
    """先物の限月別清算価格を返す Series（index=expiry, 昇順）。"""
    futs = filter_futures(df)
    if futs.empty:
        return pd.Series(dtype=float, name="settlement")
    # 同一限月に複数行が存在した場合は最初の値を使用
    return (
        futs.groupby("expiry")["settlement"]
        .first()
        .sort_index()
        .rename("settlement")
    )


def futures_underlying_price(df: pd.DataFrame) -> float:
    """先物行の原資産価格（現物終値）を返す。データなしは NaN。"""
    futs = filter_futures(df)
    vals = futs["underlying"].dropna()
    if vals.empty:
        # オプション行から取得を試みる
        opts = filter_options(df)
        vals = opts["underlying"].dropna()
    return float(vals.iloc[0]) if not vals.empty else float("nan")
