"""夜間バッチのエントリーポイント（ローカル手動・GitHub Actions 共通）。

パイプライン:
    1. fetch: 日経225 OHLC / 日経VI 当日値を取得し history CSV に upsert
    2. compute: HV各推定量, IV Rank/Percentile, VRP, レジームを算出
    3. report: docs/index.html を生成
    4. (CI側で) 変更を commit & push → GitHub Pages 更新

Claude Code はこの雛形の TODO を埋めて完成させる。失敗時は前回データで縮退運転し、
ダッシュボードに「更新失敗・前回値表示」を出すこと（夜間無人運用のため）。
"""
from __future__ import annotations

import sys

from src import config
from src.compute import iv_metrics, realized_vol, regime


def main() -> int:
    # 1. FETCH -------------------------------------------------------------
    # TODO(Claude Code): fetch_ohlc / fetch_vi_latest を呼び history を更新
    #   from src.fetch.nikkei_ohlc import fetch_ohlc, upsert_history
    #   from src.fetch.nikkei_vi import fetch_vi_latest, load_vi_history, append_vi

    # 2. COMPUTE -----------------------------------------------------------
    # TODO(Claude Code):
    #   ohlc = load history -> pd.DataFrame(open/high/low/close)
    #   hv = realized_vol.all_latest(ohlc, config.HV_WINDOW, config.ANNUALIZATION)
    #   vi_series = load_vi_history()
    #   ivp = iv_metrics.iv_percentile(vi_series, config.IV_HISTORY_WINDOW)
    #   ivr = iv_metrics.iv_rank(vi_series, config.IV_HISTORY_WINDOW)
    #   vrp = iv_metrics.vrp_proxy(vi_series.iloc[-1], hv[config.HV_PRIMARY])
    #   ma = regime.vi_moving_average(vi_series, config.VI_MA_WINDOW)
    #   slope = regime.vi_slope(vi_series, config.VI_SLOPE_LOOKBACK)
    #   flag = regime.regime_flag(vi_series.iloc[-1], ma.iloc[-1], slope)

    # 3. REPORT ------------------------------------------------------------
    # TODO(Claude Code): build_html.build(metrics, series)

    print("run_local: 雛形。Claude Code が TODO を実装します。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
