"""日経225 現物 OHLC 取得（無料）。

契約（Claude Code はこの契約を満たす実装をすること）:
    fetch_ohlc(lookback_days: int) -> pd.DataFrame
        - index: 日付(昇順, tz-naive, 日次)
        - columns: open, high, low, close（float）
    - 一次候補: yfinance の config.NIKKEI_YAHOO_TICKER (^N225)
    - フォールバック: Stooq の config.NIKKEI_STOOQ_SYMBOL (^nkx) を requests でCSV取得
    - 取得成功後 data/history/nikkei_ohlc.csv に upsert（重複日付は最新で上書き）

注意:
    - 祝日・半日立会に注意。欠損日は詰めない（rolling が壊れないよう連続営業日で）。
    - ネットワーク失敗時は明示的に例外を投げ、run_local 側で前回値を使う設計。
"""
from __future__ import annotations

import pandas as pd


def fetch_ohlc(lookback_days: int = 400) -> pd.DataFrame:  # noqa: D401
    raise NotImplementedError("Claude Code が yfinance/Stooq で実装する")


def upsert_history(df: pd.DataFrame) -> pd.DataFrame:
    raise NotImplementedError("history CSV への追記・重複排除を実装する")
