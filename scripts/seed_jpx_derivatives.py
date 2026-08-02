"""JPX 清算値段データの初回バックフィル（ワンショット実行）。

JPX は約2ヶ月分の過去ファイルを保持する。このスクリプトは初回のみ実行し、
data/history/jpx_derivatives.csv に過去データを upsert する。

以降の日次追記は run_local.py が行う。

使い方:
    python scripts/seed_jpx_derivatives.py [--lookback DAYS] [--dry-run]

    --lookback DAYS  : 遡る営業日数（デフォルト: config.SEED_LOOKBACK_BDAYS = 60）
    --dry-run        : CSV 書き込みをせず取得内容のみ表示
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import pandas as pd

# プロジェクトルートを sys.path に追加（スクリプト直接実行用）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.fetch.jpx_derivatives import (
    _USER_AGENT,
    _fetch_with_retry,
    _parse_rb_csv,
    _resolve_base_url,
    upsert_derivatives,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def seed_range(lookback_days: int, dry_run: bool) -> None:
    """past `lookback_days` 営業日分の rb*.csv を取得して upsert する。"""
    headers = {"User-Agent": _USER_AGENT}

    # index.html からベース URL を解決（ハッシュディレクトリを動的に取得）
    logger.info("index.html からベース URL を解決中...")
    base_url = _resolve_base_url(config.JPX_SETTLEMENT_INDEX_URL, headers)

    # 遡り日付リスト（日本株営業日近似。祝日は 404 で自動スキップ）
    end_date = pd.Timestamp.now(tz=config.TIMEZONE).normalize().tz_localize(None)
    start_date = end_date - pd.offsets.BDay(lookback_days)
    bdays = pd.bdate_range(start=start_date, end=end_date)

    logger.info(
        "対象期間: %s ～ %s (%d 営業日)",
        bdays[0].date(), bdays[-1].date(), len(bdays),
    )

    ok_count = 0
    skip_count = 0
    error_count = 0
    frames: list[pd.DataFrame] = []

    for ts in bdays:
        date_str = ts.strftime("%Y-%m-%d")
        yyyymmdd = ts.strftime("%Y%m%d")
        file_url = f"{base_url}/rb{yyyymmdd}.csv"

        try:
            resp = _fetch_with_retry(file_url, headers, max_retries=2)
            df = _parse_rb_csv(resp.content, date_str)
            frames.append(df)
            ok_count += 1
            logger.info("  ✓ %s: %d 行", date_str, len(df))
        except FileNotFoundError:
            # 404 = 休場日 or ファイルなし → 正常スキップ
            skip_count += 1
            logger.debug("  - %s: 404 スキップ（休場日等）", date_str)
        except Exception as exc:
            error_count += 1
            logger.warning("  ✗ %s: 取得失敗 → %s", date_str, exc)

        # JPX への過負荷防止（1 リクエスト/秒）
        time.sleep(1.0)

    logger.info(
        "取得完了: 成功=%d / スキップ=%d / 失敗=%d",
        ok_count, skip_count, error_count,
    )

    if not frames:
        logger.warning("取得できたファイルが 0 件。CSV は更新されません。")
        return

    combined = pd.concat(frames, ignore_index=True)
    logger.info("合計 %d 行をマージ", len(combined))

    if dry_run:
        print(combined.to_string(max_rows=20))
        print(f"\n[dry-run] 書き込みをスキップしました（{len(combined)} 行）")
        return

    upsert_derivatives(combined)
    logger.info("完了: %s に保存しました", config.JPX_DERIVATIVES_CSV)


def main() -> int:
    parser = argparse.ArgumentParser(description="JPX 清算値段データの初回バックフィル")
    parser.add_argument(
        "--lookback", type=int, default=config.SEED_LOOKBACK_BDAYS,
        help=f"遡る営業日数（デフォルト: {config.SEED_LOOKBACK_BDAYS}）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="CSV を書き込まず内容を確認するだけ",
    )
    args = parser.parse_args()

    seed_range(lookback_days=args.lookback, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
