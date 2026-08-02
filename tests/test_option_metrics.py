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
    iv_skew_series,
    iv_term_structure,
    nearest_expiry,
)


# ---------------------------------------------------------------------------
# ヘルパ: 合成データ生成
# ---------------------------------------------------------------------------

def _make_deriv_df(
    date: str = "2026-07-31",
    expiries: list[str] | None = None,
    underlying: float = 38000.0,
    strikes: list[int] | None = None,
) -> pd.DataFrame:
    """テスト用のデリバティブ DataFrame を生成する。

    先物1行 + 指定限月 × 指定ストライクの Put/Call を作成。
    IV はモネーネスに対してプットスキューを持つシンプルな曲面。
    """
    if expiries is None:
        expiries = ["202609", "202612"]
    if strikes is None:
        strikes = [34000, 36000, 37000, 38000, 39000, 40000, 42000]

    rows: list[dict] = []

    # 先物行
    for exp in expiries:
        dte = 40 if exp == expiries[0] else 130
        rows.append({
            "date": date, "code": f"NK225F{exp}", "name": f"日経225先物 {exp}",
            "put_call": float("nan"), "expiry": exp,
            "strike": float("nan"), "settlement": underlying + (dte * 0.3),
            "theoretical": float("nan"), "underlying": underlying,
            "iv": float("nan"), "rate": float("nan"), "days_to_expiry": float("nan"),
        })

    # オプション行（プットスキューあり）
    for exp in expiries:
        dte = 40 if exp == expiries[0] else 130
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
    """ATM ストライク（38000 = underlying）で Call と Put の IV の平均になること。"""
    df = _make_deriv_df(underlying=38000.0, strikes=[38000])
    result = atm_iv(df, "202609")
    # strike==underlying のとき moneyness==1.0 → iv_put=25.0, iv_call=20.0
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
