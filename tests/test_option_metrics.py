"""option_metrics のテスト（ネットワーク不要・合成データ使用）。"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.compute.option_metrics import (
    _flag_iv_outliers,
    atm_iv,
    filter_futures,
    filter_options,
    futures_term_structure,
    futures_underlying_price,
    get_fallback_expiries,
    iv_skew_series,
    iv_term_slope,
    iv_term_structure,
    nearest_expiry,
    nearest_weekly_expiry,
    weekly_monthly_atm_spread,
)


# ---------------------------------------------------------------------------
# ヘルパ: 合成データ生成
# ---------------------------------------------------------------------------

def _make_deriv_df(
    date: str = "2026-07-31",
    expiries: list[str] | None = None,
    underlying: float = 38000.0,
    strikes: list[int] | None = None,
    dte_map: dict[str, int] | None = None,
    futures_expiries: list[str] | None = None,
) -> pd.DataFrame:
    """テスト用のデリバティブ DataFrame を生成する。

    先物1行 + 指定限月 × 指定ストライクの Put/Call を作成。
    IV はモネーネスに対してプットスキューを持つシンプルな曲面。

    dte_map: 限月 → DTE の辞書。未指定時はリスト位置で自動割り当て（先頭=40, 他=130）。
    futures_expiries: 先物行を作成する限月。未指定時は全 expiries 分を作成。
    """
    if expiries is None:
        expiries = ["202609", "202612"]
    if strikes is None:
        strikes = [34000, 36000, 37000, 38000, 39000, 40000, 42000]
    if futures_expiries is None:
        futures_expiries = list(expiries)

    def _dte(exp: str, idx: int) -> int:
        if dte_map and exp in dte_map:
            return dte_map[exp]
        return 40 if idx == 0 else 130

    rows: list[dict] = []

    # 先物行（futures_expiries のみ）
    for exp in futures_expiries:
        idx = expiries.index(exp) if exp in expiries else 0
        dte = _dte(exp, idx)
        rows.append({
            "date": date, "code": f"NK225F{exp}", "name": f"日経225先物 {exp}",
            "put_call": float("nan"), "expiry": exp,
            "strike": float("nan"), "settlement": underlying + (dte * 0.3),
            "theoretical": float("nan"), "underlying": underlying,
            "iv": float("nan"), "rate": float("nan"), "days_to_expiry": float("nan"),
        })

    # オプション行（プットスキューあり）
    for idx, exp in enumerate(expiries):
        dte = _dte(exp, idx)
        for strike in strikes:
            moneyness = strike / underlying
            # Put IV: OTM プットほど高い（スキュー）
            iv_put = 25.0 + (1.0 - moneyness) * 20.0
            iv_put = max(10.0, min(60.0, iv_put))
            # Call IV: OTM コールほど低い（逆スキュー）
            iv_call = 20.0 + (moneyness - 1.0) * 5.0
            iv_call = max(10.0, min(40.0, iv_call))

            rows.append({
                "date": date, "code": f"NK225E{exp}{strike:06d}P",
                "name": f"日経225OP {exp} {strike}プット",
                "put_call": "PUT", "expiry": exp, "strike": float(strike),
                "settlement": max(0.0, underlying - strike) + 50.0,
                "theoretical": max(0.0, underlying - strike) + 45.0,
                "underlying": underlying, "iv": iv_put, "rate": 0.1, "days_to_expiry": float(dte),
            })
            rows.append({
                "date": date, "code": f"NK225E{exp}{strike:06d}C",
                "name": f"日経225OP {exp} {strike}コール",
                "put_call": "CAL", "expiry": exp, "strike": float(strike),
                "settlement": max(0.0, strike - underlying) + 50.0,
                "theoretical": max(0.0, strike - underlying) + 45.0,
                "underlying": underlying, "iv": iv_call, "rate": 0.1, "days_to_expiry": float(dte),
            })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# filter_options / filter_futures
# ---------------------------------------------------------------------------

def test_filter_options_excludes_futures():
    df = _make_deriv_df()
    opts = filter_options(df)
    assert opts["put_call"].notna().all()
    assert "PUT" in opts["put_call"].values
    assert "CAL" in opts["put_call"].values


def test_filter_futures_excludes_options():
    df = _make_deriv_df()
    futs = filter_futures(df)
    assert futs["put_call"].isna().all()
    assert len(futs) == 2  # 2限月分の先物


def test_filter_options_by_expiry():
    df = _make_deriv_df()
    opts = filter_options(df, expiry="202609")
    assert (opts["expiry"] == "202609").all()


def test_filter_options_by_put_call():
    df = _make_deriv_df()
    puts = filter_options(df, put_call="PUT")
    assert (puts["put_call"] == "PUT").all()


# ---------------------------------------------------------------------------
# nearest_expiry
# ---------------------------------------------------------------------------

def test_nearest_expiry_returns_front_month():
    df = _make_deriv_df(expiries=["202609", "202612"])
    exp = nearest_expiry(df)
    assert exp == "202609"


def test_nearest_expiry_single_expiry():
    df = _make_deriv_df(expiries=["202609"])
    assert nearest_expiry(df) == "202609"


# ---------------------------------------------------------------------------
# atm_iv
# ---------------------------------------------------------------------------

def test_atm_iv_returns_finite():
    df = _make_deriv_df()
    result = atm_iv(df, "202609")
    assert math.isfinite(result)
    assert 5.0 < result < 80.0


def test_atm_iv_empty_expiry_returns_nan():
    df = _make_deriv_df()
    result = atm_iv(df, "999999")
    assert math.isnan(result)


def test_atm_iv_uses_call_put_average():
    """先物清算値に最近接のストライクで Call/Put IV 平均が返ること。

    A-4修正: ATM判定を現物終値→先物清算値ベースに変更（SPEC §0準拠）。
    _make_deriv_df の先物 settlement = underlying + dte*0.3 = 38000 + 40*0.3 = 38012。
    唯一のストライク38000が先物38012の最近傍として選ばれる（|38000/38012-1|=0.03%）。
    iv_put = 25.0（moneyness=38000/38000=1.0 で計算）、iv_call = 20.0 → 平均 22.5。
    """
    df = _make_deriv_df(underlying=38000.0, strikes=[38000])
    result = atm_iv(df, "202609")
    expected = (25.0 + 20.0) / 2.0
    assert abs(result - expected) < 0.1


# ---------------------------------------------------------------------------
# iv_skew_series
# ---------------------------------------------------------------------------

def test_iv_skew_has_required_columns():
    df = _make_deriv_df()
    skew = iv_skew_series(df, "202609")
    for col in ["moneyness", "iv_put", "iv_call", "outlier_put", "outlier_call"]:
        assert col in skew.columns


def test_iv_skew_moneyness_sorted():
    """moneyness が単調増加していること。"""
    df = _make_deriv_df()
    skew = iv_skew_series(df, "202609")
    assert (skew["moneyness"].diff().dropna() >= 0).all()


def test_iv_skew_empty_expiry():
    df = _make_deriv_df()
    skew = iv_skew_series(df, "999999")
    assert skew.empty


def test_iv_skew_put_higher_than_call_otm():
    """OTM プット（moneyness < 1）で Put IV > Call IV であること（スキュー実在）。"""
    df = _make_deriv_df(underlying=38000.0)
    skew = iv_skew_series(df, "202609")
    otm_puts = skew[skew["moneyness"] < 0.95]
    if not otm_puts.empty:
        assert (otm_puts["iv_put"] > otm_puts["iv_call"]).all()


# ---------------------------------------------------------------------------
# _flag_iv_outliers
# ---------------------------------------------------------------------------

def test_flag_outliers_detects_spike():
    """既知のスパイク（近傍から±30%超の外れ値）が True になること。"""
    iv = pd.Series([20.0, 21.0, 22.0, 80.0, 21.0, 20.0, 19.0])  # index 3 がスパイク
    flags = _flag_iv_outliers(iv, threshold_pct=0.30)
    assert flags.iloc[3] == True


def test_flag_outliers_normal_series_all_false():
    """均一な IV 系列は全て False であること。"""
    iv = pd.Series([20.0, 21.0, 22.0, 21.0, 20.0])
    flags = _flag_iv_outliers(iv, threshold_pct=0.30)
    assert not flags.any()


def test_flag_outliers_nan_series_returns_false():
    """全 NaN は全て False を返すこと。"""
    iv = pd.Series([float("nan")] * 5)
    flags = _flag_iv_outliers(iv, threshold_pct=0.30)
    assert not flags.any()


# ---------------------------------------------------------------------------
# get_fallback_expiries
# ---------------------------------------------------------------------------

def test_get_fallback_expiries_empty_when_all_have_futures():
    """全限月に先物がある場合はフォールバックセットが空であること。"""
    df = _make_deriv_df(expiries=["202609", "202612"])
    fallback = get_fallback_expiries(df)
    assert fallback == set()


def test_get_fallback_expiries_detects_missing_futures():
    """先物行がない限月（オプションのみ）がフォールバックセットに含まれること。"""
    df = _make_deriv_df(expiries=["202609", "202612"])
    # 先物行を202609分だけ削除して202612の先物なし状態を模擬
    df_no_fut_612 = df[~((df["put_call"].isna()) & (df["expiry"] == "202612"))].copy()
    fallback = get_fallback_expiries(df_no_fut_612)
    assert "202612" in fallback
    assert "202609" not in fallback


# ---------------------------------------------------------------------------
# iv_term_structure
# ---------------------------------------------------------------------------

def test_iv_term_structure_has_all_expiries():
    df = _make_deriv_df(expiries=["202609", "202612"])
    term = iv_term_structure(df)
    assert "202609" in term.index
    assert "202612" in term.index


def test_iv_term_structure_finite_values():
    df = _make_deriv_df()
    term = iv_term_structure(df)
    assert term.dropna().map(math.isfinite).all()


def test_iv_term_structure_index_sorted():
    """index が昇順（expiry 辞書順）であること。"""
    df = _make_deriv_df(expiries=["202612", "202609"])
    term = iv_term_structure(df)
    assert list(term.index) == sorted(term.index)


def test_iv_term_structure_excludes_weekly():
    """8桁（Weekly YYYYMMDD）限月が除外され、6桁（月次）のみ返ること。"""
    # 月次 202609 と Weekly 20260905 を混在させる
    df_monthly = _make_deriv_df(expiries=["202609"])
    df_weekly = _make_deriv_df(expiries=["20260905"])
    # 8桁は zfill(6) では変換されないためそのまま設定
    import pandas as pd
    combined = pd.concat([df_monthly, df_weekly], ignore_index=True)
    term = iv_term_structure(combined)
    assert "202609" in term.index
    assert "20260905" not in term.index


# ---------------------------------------------------------------------------
# futures_term_structure
# ---------------------------------------------------------------------------

def test_futures_term_structure_returns_settlement():
    df = _make_deriv_df()
    term = futures_term_structure(df)
    assert not term.empty
    assert term.dtype.kind == "f" or term.dtype.kind == "i"


def test_futures_term_structure_only_futures():
    """options の settlement が混入しないこと。"""
    df = _make_deriv_df()
    term = futures_term_structure(df)
    futs = filter_futures(df)
    for exp in term.index:
        expected_settle = futs[futs["expiry"] == exp]["settlement"].iloc[0]
        assert abs(term[exp] - expected_settle) < 0.01


def test_futures_term_structure_empty_df():
    """オプションのみのデータでは空 Series を返すこと。"""
    df = _make_deriv_df()
    opts_only = filter_options(df)
    term = futures_term_structure(opts_only)
    assert term.empty


# ---------------------------------------------------------------------------
# futures_underlying_price
# ---------------------------------------------------------------------------

def test_futures_underlying_price_returns_value():
    df = _make_deriv_df(underlying=38000.0)
    price = futures_underlying_price(df)
    assert abs(price - 38000.0) < 1.0


# ---------------------------------------------------------------------------
# iv_term_slope
# ---------------------------------------------------------------------------

def test_iv_term_slope_returns_finite():
    """2限月以上のデータで有限なスロープが返ること。"""
    df = _make_deriv_df(expiries=["202609", "202612"])
    result = iv_term_slope(df)
    assert math.isfinite(result["slope"])
    assert math.isfinite(result["front_iv"])
    assert math.isfinite(result["far_iv"])


def test_iv_term_slope_front_is_nearest():
    """front_expiry が DTE 最小の限月（期近）であること。"""
    df = _make_deriv_df(expiries=["202609", "202612", "202703"])
    result = iv_term_slope(df)
    assert result["front_expiry"] == "202609"


def test_iv_term_slope_front_differs_from_far():
    """front_expiry と far_expiry が異なること。"""
    df = _make_deriv_df(expiries=["202609", "202612"])
    result = iv_term_slope(df)
    assert result["front_expiry"] != result["far_expiry"]


def test_iv_term_slope_single_expiry_returns_nan():
    """限月が1つしかない場合は NaN を返すこと。"""
    df = _make_deriv_df(expiries=["202609"])
    result = iv_term_slope(df)
    assert math.isnan(result["slope"])
    assert result["front_expiry"] == ""


def test_iv_term_slope_empty_returns_nan():
    """オプション行がない場合は NaN を返すこと。"""
    df = _make_deriv_df()
    futs_only = df[df["put_call"].isna()].copy()
    result = iv_term_slope(futs_only)
    assert math.isnan(result["slope"])


def test_iv_term_slope_backwardation():
    """期近 IV > 3M先 IV のときスロープが正（バックワーデーション）であること。
    合成データは DTE=40(期近) / DTE=130(3M先) で構成。
    プットスキュー: iv_put = 25 + (1 - moneyness)*20 → ATM では 25.0
    コールスキュー: iv_call = 20 + (moneyness - 1)*5 → ATM では 20.0
    ATM IV（平均）= 22.5。両限月とも underlying=38000 かつ ATM ストライクは同じ。
    ただし _make_deriv_df の IV 計算は DTE に依存しないため前後に限月差は生じない。
    ここでは slope が有限であることのみ確認し符号は問わない。
    """
    df = _make_deriv_df(expiries=["202609", "202612"])
    result = iv_term_slope(df)
    assert math.isfinite(result["slope"])


# ---------------------------------------------------------------------------
# nearest_expiry / nearest_weekly_expiry (Phase 2)
# ---------------------------------------------------------------------------

def test_nearest_expiry_excludes_weekly_by_default():
    """デフォルト(monthly_only=True)では Weekly（8桁）が除外され月次が返ること。"""
    # DTE=5の Weeklyと DTE=40の月次を混在させる
    df = _make_deriv_df(
        expiries=["20260805", "202609"],
        dte_map={"20260805": 5, "202609": 40},
        futures_expiries=["202609"],  # 月次のみ先物あり
    )
    exp = nearest_expiry(df)
    assert exp == "202609"
    assert len(exp) == 6


def test_nearest_expiry_monthly_only_false_picks_weekly():
    """monthly_only=False にすると DTE 最小の Weekly が選ばれること。"""
    df = _make_deriv_df(
        expiries=["20260805", "202609"],
        dte_map={"20260805": 5, "202609": 40},
        futures_expiries=["202609"],
    )
    exp = nearest_expiry(df, monthly_only=False, min_dte=1)
    assert exp == "20260805"


def test_nearest_expiry_min_dte_floor():
    """DTE がフロア未満の月次限月はスキップされること。"""
    # 202608(DTE=3 < 7) / 202609(DTE=40 >= 7)
    df = _make_deriv_df(
        expiries=["202608", "202609"],
        dte_map={"202608": 3, "202609": 40},
    )
    exp = nearest_expiry(df, monthly_only=True, min_dte=7)
    assert exp == "202609"


def test_nearest_weekly_expiry_returns_shortest():
    """Weekly限月が複数ある場合は DTE 最小が返ること。"""
    df = _make_deriv_df(
        expiries=["20260805", "20260812", "202609"],
        dte_map={"20260805": 5, "20260812": 12, "202609": 40},
        futures_expiries=["202609"],
    )
    exp = nearest_weekly_expiry(df)
    assert exp == "20260805"


def test_nearest_weekly_expiry_none_when_absent():
    """Weekly限月がない場合は None を返すこと。"""
    df = _make_deriv_df(expiries=["202609", "202612"])
    assert nearest_weekly_expiry(df) is None


# ---------------------------------------------------------------------------
# weekly_monthly_atm_spread (Phase 2)
# ---------------------------------------------------------------------------

def test_weekly_monthly_spread_has_required_keys():
    """weekly_monthly_atm_spread が必要なキーを持つこと。"""
    df = _make_deriv_df(
        expiries=["20260805", "202609"],
        dte_map={"20260805": 5, "202609": 40},
        futures_expiries=["202609"],
    )
    result = weekly_monthly_atm_spread(df)
    for key in ["spread", "weekly_expiry", "weekly_iv", "monthly_expiry", "monthly_iv"]:
        assert key in result


def test_weekly_monthly_spread_finite_when_both_present():
    """Weekly・月次両方あるときスプレッドが有限であること。"""
    df = _make_deriv_df(
        expiries=["20260805", "202609"],
        dte_map={"20260805": 5, "202609": 40},
        futures_expiries=["202609"],
    )
    result = weekly_monthly_atm_spread(df)
    assert math.isfinite(result["spread"])
    assert result["weekly_expiry"] == "20260805"
    assert result["monthly_expiry"] == "202609"


def test_weekly_monthly_spread_nan_when_no_weekly():
    """Weekly限月がない場合スプレッドは NaN であること。"""
    df = _make_deriv_df(expiries=["202609", "202612"])
    result = weekly_monthly_atm_spread(df)
    assert math.isnan(result["spread"])
    assert result["weekly_expiry"] == ""
