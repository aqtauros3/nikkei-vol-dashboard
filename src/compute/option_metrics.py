"""オプション・先物デリバティブデータからの指標算出（副作用なしの純関数群）。

入力: jpx_derivatives.csv から読み込んだ DataFrame（1日分）
出力: チャート用 Series/DataFrame、サマリー用スカラー

単位の約束:
    iv は年率%表記（例: 24.1）で受け取り、そのまま返す。×100 や /100 は不要。

put_call の値:
    "PUT" / "CAL"（JPX CSV のまま）。NaN の行が先物。
"""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from src import config

logger = logging.getLogger(__name__)


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

def nearest_expiry(
    df: pd.DataFrame,
    monthly_only: bool | None = None,
    min_dte: int | None = None,
) -> str:
    """残日数が最短（かつ >= min_dte）の限月を返す。

    monthly_only=True（デフォルト）: 6桁 YYYYMM の月次限月のみ対象。Weekly（8桁）を除外。
    min_dte: DTE がこれ未満の限月は除外（直前 SQ 週の急騰 IV を避ける）。
    該当なしの場合は月次限月（monthly_only=True 時）または全限月の辞書順最小で代替。
    """
    if monthly_only is None:
        monthly_only = config.NEAREST_EXPIRY_MONTHLY_ONLY
    if min_dte is None:
        min_dte = config.NEAREST_EXPIRY_MIN_DTE

    opts = filter_options(df)
    if monthly_only:
        opts = opts[opts["expiry"].astype(str).str.len() == 6]

    valid = opts[opts["days_to_expiry"].fillna(0) >= min_dte]
    if valid.empty:
        # フォールバック: 辞書順最小の限月
        all_expiries = opts["expiry"].dropna().unique()
        if len(all_expiries) == 0:
            raise ValueError("オプション行が存在しません")
        return sorted(all_expiries)[0]
    min_dte_val = valid["days_to_expiry"].min()
    return valid[valid["days_to_expiry"] == min_dte_val]["expiry"].iloc[0]


def nearest_weekly_expiry(df: pd.DataFrame, min_dte: int = 1) -> str | None:
    """残日数が最短（かつ >= min_dte）の Weekly（8桁 YYYYMMDD）限月を返す。

    Weekly限月が存在しない場合は None。
    """
    opts = filter_options(df)
    weekly = opts[opts["expiry"].astype(str).str.len() == 8]
    valid = weekly[weekly["days_to_expiry"].fillna(0) >= min_dte]
    if valid.empty:
        return None
    min_dte_val = valid["days_to_expiry"].min()
    return valid[valid["days_to_expiry"] == min_dte_val]["expiry"].iloc[0]


def weekly_monthly_atm_spread(df: pd.DataFrame) -> dict:
    """期近 Weekly ATM IV と月次 front ATM IV のスプレッド（pt）を返す。

    spread = weekly_atm_iv - monthly_atm_iv
    正値は Weekly プレミアム（期近緊張）、負値は逆転（通常は稀）。
    Weekly 限月が存在しない場合は spread=NaN。
    """
    monthly_exp = nearest_expiry(df)
    weekly_exp = nearest_weekly_expiry(df)

    monthly_iv = atm_iv(df, monthly_exp)
    if weekly_exp is None:
        return {
            "spread": float("nan"),
            "weekly_expiry": "",
            "weekly_iv": float("nan"),
            "monthly_expiry": monthly_exp,
            "monthly_iv": monthly_iv,
        }

    weekly_iv = atm_iv(df, weekly_exp)
    spread = (
        weekly_iv - monthly_iv
        if math.isfinite(weekly_iv) and math.isfinite(monthly_iv)
        else float("nan")
    )
    return {
        "spread": spread,
        "weekly_expiry": weekly_exp,
        "weekly_iv": weekly_iv,
        "monthly_expiry": monthly_exp,
        "monthly_iv": monthly_iv,
    }


# ---------------------------------------------------------------------------
# 先物価格ルックアップ（ATM 判定基準）
# ---------------------------------------------------------------------------

def _futures_price_for_expiry(df: pd.DataFrame, expiry: str) -> float | None:
    """指定限月に対応する先物清算値を返す。先物行が存在しない場合は None。

    ATM 判定の基準価格として使用する。SPEC §0 に従い、日経225オプションの
    原資産として先物清算値が現物終値より理論的に正確（配当・金利の推定誤差を回避）。
    """
    futs = filter_futures(df, expiry=expiry)
    valid = futs["settlement"].dropna()
    if valid.empty:
        return None
    return float(valid.iloc[0])


def get_fallback_expiries(df: pd.DataFrame) -> set[str]:
    """月次限月のうち対応先物が存在せず現物終値フォールバックとなる限月セットを返す。

    JPX CSV に先物行がない限月（例: 2027年の四半期外月）を特定する。
    build_html.py でフォールバック限月を視覚的に区別（淡色表示）するために使用する。
    """
    opts = filter_options(df)
    monthly_expiries = {
        str(e) for e in opts["expiry"].dropna().unique() if len(str(e)) == 6
    }
    return {exp for exp in monthly_expiries if _futures_price_for_expiry(df, exp) is None}


# ---------------------------------------------------------------------------
# ATM IV
# ---------------------------------------------------------------------------

def atm_iv(df: pd.DataFrame, expiry: str) -> float:
    """指定限月の ATM IV（%）を返す。

    ATM 定義: 同一限月の先物清算値（先物なし限月は現物終値にフォールバック）に
    最も近い strike を ATM とし、そのストライクの CAL と PUT の IV の平均を返す。

    先物ベースの理由: SPEC §0 参照。日経225オプションは Black-76 が実務標準。
    先物が存在しない限月（JPX CSV に先物行がない場合）は警告ログを出して現物で代替。
    Put-Call パリティの理論上は同値だが実際には需給乖離がある。
    平均を取ることで単側の歪みを中和し、安定した ATM IV を得る。
    """
    opts = filter_options(df, expiry=expiry)
    if opts.empty or opts["underlying"].dropna().empty:
        return float("nan")

    spot = float(opts["underlying"].dropna().iloc[0])
    ref_price = _futures_price_for_expiry(df, expiry)
    if ref_price is None:
        # 対応する先物行が存在しない限月（例: 2027年四半期外月）は現物終値で代替
        logger.warning("限月 %s: 先物清算値なし → 現物終値 %.0f でATM判定（フォールバック）", expiry, spot)
        ref_price = spot

    opts = opts.copy()
    opts["moneyness_dist"] = (opts["strike"] / ref_price - 1.0).abs()
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
        - moneyness = strike / 先物清算値（先物なし限月は現物終値にフォールバック）
        - iv_put: PUT の IV（%）、iv_call: CAL の IV（%）
        - outlier_put/call: True = 異常値フラグ（淡色表示の対象）

    軸基準の注記: moneyness の基準価格は対応限月の先物清算値（SPEC §0準拠）。
    将来、複数限月を1チャートに重ね描きする場合は限月ごとに異なる基準価格が
    使われるため、共通モネーネス軸での直接比較は不整合が生じる点に注意が必要。
    """
    opts = filter_options(df, expiry=expiry)
    if opts.empty or opts["underlying"].dropna().empty:
        return pd.DataFrame(
            columns=["moneyness", "iv_put", "iv_call", "outlier_put", "outlier_call"]
        )

    spot = float(opts["underlying"].dropna().iloc[0])
    ref_price = _futures_price_for_expiry(df, expiry)
    if ref_price is None:
        logger.warning(
            "限月 %s: 先物清算値なし → 現物終値 %.0f でモネーネス計算（フォールバック）", expiry, spot
        )
        ref_price = spot
    opts = opts.copy()
    opts["moneyness"] = opts["strike"] / ref_price

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
    """限月ごとの ATM IV（%）を返す Series（index=expiry, 昇順）。

    月次スタンダード限月（6桁 YYYYMM）のみを対象とする。
    Weekly オプション（8桁 YYYYMMDD）は残存が短く満期効果で IV が不安定なため除外。
    ATM 判定は限月別先物清算値ベース（先物なし限月は現物終値フォールバック）。
    フォールバック限月の識別には get_fallback_expiries() を使用すること。
    """
    opts = filter_options(df)
    expiries = sorted(
        e for e in opts["expiry"].dropna().unique() if len(str(e)) == 6
    )
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


def iv_term_slope(df: pd.DataFrame) -> dict:
    """期近 ATM IV と 3か月先 ATM IV のスロープ（期近 − 3M先, pt）を返す。

    3か月先の選択根拠: 残存日数（暦日）が 90 日に最も近い限月（期近を除く）。
    90暦日 ≈ 3暦月。ATM判定は限月別先物清算値ベース（SPEC §0準拠）。

    Returns:
        dict with keys:
            slope        : float  正=バックワーデーション(目先緊張), 負=コンタンゴ(平時型)
            front_iv     : float
            far_iv       : float
            front_expiry : str  ("YYYYMM" or "" if unavailable)
            far_expiry   : str
    """
    _NAN: dict = {
        "ts_near_minus_far": float("nan"),
        "front_iv": float("nan"),
        "far_iv": float("nan"),
        "front_expiry": "",
        "far_expiry": "",
    }

    opts = filter_options(df)
    valid = opts[opts["days_to_expiry"].fillna(0) > 0]
    if valid.empty:
        return _NAN

    # 月次スタンダード限月のみ（6桁 YYYYMM）。Weekly等（8桁）はスロープ計算のノイズになるため除外
    valid = valid[valid["expiry"].astype(str).str.len() == 6]
    if valid.empty:
        return _NAN

    # 限月ごとの代表 DTE（中央値）を昇順で取得
    dte_by_expiry = (
        valid.groupby("expiry")["days_to_expiry"]
        .median()
        .sort_values()
    )
    if len(dte_by_expiry) < 2:
        return _NAN

    front_expiry = dte_by_expiry.index[0]

    # 3か月先: 期近を除いた中で DTE が 90 日（暦日）に最も近い限月
    dte_ex_front = dte_by_expiry.drop(front_expiry)
    far_expiry = (dte_ex_front - 90.0).abs().idxmin()

    front_iv_val = atm_iv(df, front_expiry)
    far_iv_val = atm_iv(df, far_expiry)

    if not (math.isfinite(front_iv_val) and math.isfinite(far_iv_val)):
        return _NAN

    return {
        "ts_near_minus_far": front_iv_val - far_iv_val,
        "front_iv": front_iv_val,
        "far_iv": far_iv_val,
        "front_expiry": front_expiry,
        "far_expiry": far_expiry,
    }


def futures_underlying_price(df: pd.DataFrame) -> float:
    """先物行の原資産価格（現物終値）を返す。データなしは NaN。"""
    futs = filter_futures(df)
    vals = futs["underlying"].dropna()
    if vals.empty:
        # オプション行から取得を試みる
        opts = filter_options(df)
        vals = opts["underlying"].dropna()
    return float(vals.iloc[0]) if not vals.empty else float("nan")
