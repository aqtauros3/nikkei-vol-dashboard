"""日経平均VI（日経VI）取得（無料）。

契約:
    fetch_vi_latest() -> tuple[pd.Timestamp, float]
        当日の日経VI終値（％表記, 例 41.29）と日付を返す。
    load_vi_history() -> pd.Series   # index=date, value=vi(％)
    append_vi(date, value) -> None   # data/history/nikkei_vi.csv に追記(重複排除)

実装メモ:
    - 無料の公開ページから当日値をスクレイプ（複数ソースをフォールバック）。
      候補: 日経の指数ページ / investing.com。HTML構造変更に備え try/except で多重化。
    - IV Rank/Percentile には過去252営業日が要る。初回は投資サイトの履歴CSVを
      data/history/nikkei_vi.csv に手動シードし、以後は当日値を append して積み上げる。
    - 無料web配信は約20分遅延の場合あり（レジーム判定はこの遅延前提で設計）。
"""
from __future__ import annotations

import pandas as pd


def fetch_vi_latest() -> tuple[pd.Timestamp, float]:
    raise NotImplementedError("Claude Code が公開ソースのスクレイプで実装する")


def load_vi_history() -> pd.Series:
    raise NotImplementedError("history CSV を読み込む")


def append_vi(date: pd.Timestamp, value: float) -> None:
    raise NotImplementedError("history CSV に追記（重複排除）")
