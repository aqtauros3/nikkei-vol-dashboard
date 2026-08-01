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
        ohlc_new = fetch_ohlc(lookback_days=_CHART_WINDOW + 60)
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

    # レジーム
    vi_ma_series = regime.vi_moving_average(vi_series, config.VI_MA_WINDOW)
    slope = regime.vi_slope(vi_series, config.VI_SLOPE_LOOKBACK)
    vi_ma_latest = (
        float(vi_ma_series.dropna().iloc[-1])
        if not vi_ma_series.dropna().empty
        else float("nan")
    )
    flag = regime.regime_flag(vi_latest, vi_ma_latest, slope)

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
    }
    logger.info(
        "VI=%.2f IVP=%.1f%% IVR=%.1f%% HV_YZ=%.1f%% VRP=%.2f レジーム=%s",
        vi_latest, ivp, ivr, hv_primary, vrp, flag,
    )

    # チャート用 rolling series（直近 _CHART_WINDOW 日分）
    hv_yz_series = (
        realized_vol.yang_zhang(ohlc_df, config.HV_WINDOW, config.ANNUALIZATION) * 100.0
    )
    # VI と HV を日付で内部結合して VRP series を作る
    vi_aligned, hv_aligned = vi_series.align(hv_yz_series, join="inner")
    vrp_series = vi_aligned - hv_aligned

    # 直近ピークからの距離（rolling）
    vi_rolling_peak = vi_series.rolling(config.VI_PEAK_LOOKBACK).max()
    vi_drawdown_series = vi_series / vi_rolling_peak - 1.0

    series: dict[str, pd.Series] = {
        "vi": vi_series.tail(_CHART_WINDOW),
        "vi_ma": vi_ma_series.tail(_CHART_WINDOW),
        "hv_yz": hv_yz_series.tail(_CHART_WINDOW),
        "vrp": vrp_series.tail(_CHART_WINDOW),
        "vi_drawdown": vi_drawdown_series.tail(_CHART_WINDOW),
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
