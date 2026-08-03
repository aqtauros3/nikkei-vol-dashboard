"""夜間バッチのエントリーポイント（ローカル手動・GitHub Actions 共通）。

パイプライン:
    1. fetch: 日経225 OHLC / 日経VI 当日値を取得し history CSV に upsert
    2. compute: HV各推定量, IV Rank/Percentile, VRP, レジームを算出
    3. report: docs/index.html を生成
    4. (CI側で) 変更を commit & push → GitHub Pages 更新

失敗時は前回データで縮退運転し、ダッシュボードに「更新失敗・前回値表示」を出す。
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import pandas as pd

from src import config
from src.compute import iv_metrics, realized_vol, regime
from src.compute import option_metrics
from src.fetch.jpx_derivatives import (
    fetch_derivatives,
    load_derivatives_latest,
    upsert_derivatives,
)
from src.fetch.nikkei_ohlc import fetch_ohlc, upsert_history as upsert_ohlc
from src.fetch.nikkei_vi import append_vi, fetch_vi_latest, load_vi_history

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# チャート用に渡す最大日数（VI Rank 窓と合わせる）
_CHART_WINDOW = config.IV_HISTORY_WINDOW

# OHLC 取得カレンダー日数：営業日→カレンダー日換算(×7/5) + HV 窓バッファ
# 例: 252 * 7/5 + 20 + 30 ≈ 403 日 → 約285営業日を確保
_OHLC_LOOKBACK = int(_CHART_WINDOW * 7 / 5) + config.HV_WINDOW + 30


def _read_ohlc_csv() -> pd.DataFrame:
    path = config.OHLC_CSV
    if not path.exists():
        raise FileNotFoundError(f"OHLC CSV が見つかりません: {path}")
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index).normalize()
    df.index.name = "date"
    df.columns = df.columns.str.lower()
    return df.sort_index()


def main() -> int:
    fetch_errors: list[str] = []

    # ------------------------------------------------------------------
    # 1. FETCH
    # ------------------------------------------------------------------
    logger.info("=== FETCH ===")

    try:
        ohlc_new = fetch_ohlc(lookback_days=_OHLC_LOOKBACK)
        upsert_ohlc(ohlc_new)
    except Exception as exc:
        msg = f"OHLC 取得失敗: {exc}"
        fetch_errors.append(msg)
        logger.warning("%s → 前回 CSV で縮退運転", msg)

    try:
        vi_date, vi_value = fetch_vi_latest()
        append_vi(vi_date, vi_value)
        logger.info("VI 取得: %s → %.2f", vi_date.date(), vi_value)
    except Exception as exc:
        msg = f"VI 取得失敗: {exc}"
        fetch_errors.append(msg)
        logger.warning("%s → 前回 CSV で縮退運転", msg)

    # JPX 清算値段 CSV（オプション IV・先物清算値）
    jpx_fetch_errors: list[str] = []
    try:
        deriv_df = fetch_derivatives()
        upsert_derivatives(deriv_df)
        logger.info("JPX derivatives 取得: %d 行", len(deriv_df))
    except Exception as exc:
        msg = f"JPX derivatives 取得失敗: {exc}"
        jpx_fetch_errors.append(msg)
        logger.warning("%s → 前回 CSV で縮退運転", msg)

    # ------------------------------------------------------------------
    # 2. COMPUTE
    # ------------------------------------------------------------------
    logger.info("=== COMPUTE ===")

    try:
        ohlc_df = _read_ohlc_csv()
    except FileNotFoundError as exc:
        logger.error("OHLC CSV が存在しないため計算を中止: %s", exc)
        return 1

    vi_series = load_vi_history()
    if vi_series.empty:
        logger.error("VI history が空です。scripts/seed_vi_history.py を実行してください。")
        return 1

    # HV: 全推定量の最新値（%）
    hv_dict: dict[str, float] = realized_vol.all_latest(
        ohlc_df, config.HV_WINDOW, config.ANNUALIZATION
    )
    hv_primary = hv_dict.get(config.HV_PRIMARY, float("nan"))

    # IV Rank / Percentile
    ivr = iv_metrics.iv_rank(vi_series, config.IV_HISTORY_WINDOW)
    ivp = iv_metrics.iv_percentile(vi_series, config.IV_HISTORY_WINDOW)

    # VRP（最新値）
    vi_latest = float(vi_series.iloc[-1])
    vrp = iv_metrics.vrp_proxy(vi_latest, hv_primary)

    # JPX オプション指標
    deriv_latest = load_derivatives_latest()
    option_data_ok = not deriv_latest.empty          # 蓄積データの有無のみで判定
    option_fetched_today = not jpx_fetch_errors      # 当日取得成否は別フラグ
    if option_data_ok:
        try:
            front_exp = option_metrics.nearest_expiry(deriv_latest)
            atm_iv_val = option_metrics.atm_iv(deriv_latest, front_exp)
            skew_df = option_metrics.iv_skew_series(deriv_latest, front_exp)
            iv_term_s = option_metrics.iv_term_structure(deriv_latest)
            fut_term_s = option_metrics.futures_term_structure(deriv_latest)
            fut_underlying = option_metrics.futures_underlying_price(deriv_latest)
            option_data_date = str(deriv_latest["date"].iloc[0])
            iv_slope = option_metrics.iv_term_slope(deriv_latest)
            # 月次限月で先物なし（現物フォールバック）の限月セット（チャート視覚化用）
            iv_term_fallback_expiries = option_metrics.get_fallback_expiries(deriv_latest)
            # ATM IV の判定基準（先物 or 現物フォールバック）
            atm_basis = "spot" if front_exp in iv_term_fallback_expiries else "futures"
            # 期近限月の先物清算値（スキューチャート横軸基準）
            # フォールバック限月では現物終値を使用
            _front_futs = option_metrics.filter_futures(deriv_latest, expiry=front_exp)
            _front_settle = _front_futs["settlement"].dropna()
            skew_futures_price = (
                float(_front_settle.iloc[0]) if not _front_settle.empty else fut_underlying
            )
            # Weekly−Monthly ATM IV スプレッド（pt）
            wm_spread = option_metrics.weekly_monthly_atm_spread(deriv_latest)
        except Exception as exc:
            logger.warning("option_metrics 計算エラー: %s", exc)
            option_data_ok = False
    if not option_data_ok:
        atm_iv_val = float("nan")
        skew_df = iv_term_s = fut_term_s = None
        fut_underlying = float("nan")
        front_exp = ""
        option_data_date = "N/A"
        iv_slope = {
            "slope": float("nan"), "front_iv": float("nan"),
            "far_iv": float("nan"), "front_expiry": "", "far_expiry": "",
        }
        skew_futures_price = float("nan")
        iv_term_fallback_expiries: set[str] = set()
        atm_basis = "futures"
        wm_spread: dict = {
            "spread": float("nan"), "weekly_expiry": "",
            "weekly_iv": float("nan"), "monthly_expiry": "", "monthly_iv": float("nan"),
        }

    # レジーム
    vi_ma_series = regime.vi_moving_average(vi_series, config.VI_MA_WINDOW)
    slope = regime.vi_slope(vi_series, config.VI_SLOPE_LOOKBACK)
    vi_ma_latest = (
        float(vi_ma_series.dropna().iloc[-1])
        if not vi_ma_series.dropna().empty
        else float("nan")
    )
    flag = regime.regime_flag(vi_latest, vi_ma_latest, slope)

    vrp_option = iv_metrics.vrp_proxy(atm_iv_val, hv_primary)

    metrics: dict[str, Any] = {
        "date": vi_series.index[-1].strftime("%Y-%m-%d"),
        "vi": vi_latest,
        "iv_percentile": ivp,
        "iv_rank": ivr,
        "hv": hv_dict,
        "vrp": vrp,
        "regime": flag,
        "fetch_ok": len(fetch_errors) == 0,
        "fetch_errors": fetch_errors,
        # JPX オプション由来指標
        "atm_iv": atm_iv_val,
        "atm_basis": atm_basis,        # "futures" or "spot" (フォールバック)
        "vrp_option": vrp_option,
        "option_data_ok": option_data_ok,
        "option_fetched_today": option_fetched_today,
        "option_data_date": option_data_date,
        "option_fetch_errors": jpx_fetch_errors,
        "iv_term_slope": iv_slope,
        "wm_spread": wm_spread,        # Weekly−Monthly ATM IV スプレッド
    }
    logger.info(
        "VI=%.2f IVP=%.1f%% IVR=%.1f%% HV_YZ=%.1f%% VRP=%.2f レジーム=%s",
        vi_latest, ivp, ivr, hv_primary, vrp, flag,
    )

    # チャート用 rolling series（直近 _CHART_WINDOW 日分）
    # HV 全推定量（%）
    hv_rolling: dict[str, pd.Series] = {
        name: fn(ohlc_df, config.HV_WINDOW, config.ANNUALIZATION) * 100.0
        for name, fn in realized_vol.ESTIMATORS.items()
    }
    hv_yz_series = hv_rolling.get("yang_zhang", pd.Series(dtype=float))

    # VI と HV_YZ を日付で内部結合して VRP series を作る
    vi_aligned, hv_aligned = vi_series.align(hv_yz_series, join="inner")
    vrp_series = vi_aligned - hv_aligned

    # 直近ピークからの距離（rolling）
    vi_rolling_peak = vi_series.rolling(config.VI_PEAK_LOOKBACK).max()
    vi_drawdown_series = vi_series / vi_rolling_peak - 1.0

    series: dict[str, Any] = {
        "vi": vi_series.tail(_CHART_WINDOW),
        "vi_ma": vi_ma_series.tail(_CHART_WINDOW),
        "hv_yz": hv_yz_series.tail(_CHART_WINDOW),
        "hv_all": {k: v.tail(_CHART_WINDOW) for k, v in hv_rolling.items()},
        "vrp": vrp_series.tail(_CHART_WINDOW),
        "vi_drawdown": vi_drawdown_series.tail(_CHART_WINDOW),
        # JPX オプション由来チャート用データ
        "iv_skew": skew_df,
        "iv_skew_expiry": front_exp,
        "iv_term": iv_term_s,
        "futures_term": fut_term_s,
        "futures_underlying": fut_underlying,          # 現物終値（先物期間構造チャートの参照線）
        "skew_futures_price": skew_futures_price,     # スキューチャート横軸基準（期近先物清算値）
        "iv_term_fallback_expiries": iv_term_fallback_expiries,  # 先物なし→現物フォールバック限月
    }

    # ------------------------------------------------------------------
    # 3. REPORT
    # ------------------------------------------------------------------
    logger.info("=== REPORT ===")
    try:
        from src.report.build_html import build
        build(metrics, series)
        logger.info("HTML 生成完了: %s", config.DOCS / "index.html")
    except NotImplementedError:
        logger.warning("build_html 未実装。サマリーのみ表示（2-4 フェーズで実装）。")
        _print_summary(metrics)
    except Exception as exc:
        logger.error("HTML 生成エラー: %s", exc)
        _print_summary(metrics)
        return 1

    return 0


def _print_summary(metrics: dict[str, Any]) -> None:
    """HTML 生成前の動作確認用テキストサマリー。"""
    regime_label = {
        "STRESS": "STRESS [新規売り回避]",
        "CALM": "CALM [売り検討]",
        "NEUTRAL": "NEUTRAL",
        "UNKNOWN": "UNKNOWN (データ不足)",
    }.get(metrics["regime"], metrics["regime"])

    hv_yz = metrics["hv"].get("yang_zhang", float("nan"))
    print()
    print("=" * 52)
    print("  日経225 ボラティリティ ダッシュボード")
    print("=" * 52)
    print(f"  基準日       : {metrics['date']}")
    print(f"  日経VI       : {metrics['vi']:.2f}")
    print(f"  IV Percentile: {metrics['iv_percentile']:.1f}%")
    print(f"  IV Rank      : {metrics['iv_rank']:.1f}%")
    print(f"  HV20(YZ)     : {hv_yz:.1f}%")
    print(f"  VRP          : {metrics['vrp']:.2f} pt")
    print(f"  レジーム     : {regime_label}")
    if not metrics["fetch_ok"]:
        print()
        print("  [警告] 当日フェッチ失敗 → 前回 CSV で縮退運転")
        for err in metrics["fetch_errors"]:
            print(f"    {err}")
    print("=" * 52)


if __name__ == "__main__":
    raise SystemExit(main())
