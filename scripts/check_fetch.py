"""取得疎通確認スクリプト（開発・デバッグ用）。

実行方法:
    python scripts/check_fetch.py

ネットワーク接続が必要。取得成功後 data/history/ CSV が更新される。
"""
from __future__ import annotations

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)

from src.fetch.nikkei_ohlc import fetch_ohlc, upsert_history
from src.fetch.nikkei_vi import append_vi, fetch_vi_latest, load_vi_history


def main() -> int:
    ok = True

    # ---- OHLC ----
    print("=" * 50)
    print("OHLC 取得テスト（直近30営業日分）")
    print("=" * 50)
    try:
        df = fetch_ohlc(lookback_days=30)
        print(df.tail(3).to_string())
        print(f"\n→ {len(df)} 行取得成功")

        combined = upsert_history(df)
        print(f"→ CSV 合計 {len(combined)} 行（data/history/nikkei_ohlc.csv）")
    except Exception as exc:
        print(f"[失敗] {exc}", file=sys.stderr)
        ok = False

    # ---- VI ----
    print("\n" + "=" * 50)
    print("日経VI 取得テスト")
    print("=" * 50)
    try:
        date, vi = fetch_vi_latest()
        print(f"→ {date.date()} : 日経VI = {vi:.2f}")

        append_vi(date, vi)
        s = load_vi_history()
        print(f"→ VI history {len(s)} 行（data/history/nikkei_vi.csv）")
        print(s.tail(3).to_string())
    except Exception as exc:
        print(f"[失敗] {exc}", file=sys.stderr)
        ok = False

    print("\n" + ("全ステップ成功" if ok else "一部失敗（上記ログを確認）"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
