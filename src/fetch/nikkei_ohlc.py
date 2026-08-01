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

import io
import logging

import pandas as pd
import requests
import yfinance as yf

from src import config

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; Python/3.12)"}


def fetch_ohlc(lookback_days: int = 400) -> pd.DataFrame:
    """日経225 OHLC を取得。Primary: yfinance, Fallback: Stooq。"""
    try:
        df = _fetch_yfinance(lookback_days)
        logger.info("yfinance から %d 行取得", len(df))
        return df
    except Exception as exc:
        logger.warning("yfinance 失敗 (%s)。Stooq にフォールバック", exc)

    df = _fetch_stooq(lookback_days)
    logger.info("Stooq から %d 行取得", len(df))
    return df


def _fetch_yfinance(lookback_days: int) -> pd.DataFrame:
    start = (pd.Timestamp.today() - pd.Timedelta(days=lookback_days + 30)).strftime("%Y-%m-%d")
    ticker = yf.Ticker(config.NIKKEI_YAHOO_TICKER)
    raw = ticker.history(start=start, auto_adjust=False)

    if raw.empty:
        raise ValueError("yfinance: 空データが返りました")

    # MultiIndex になる yfinance バージョンに対応
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    raw.columns = raw.columns.str.lower()
    df = raw[["open", "high", "low", "close"]].copy()

    # tz-aware インデックスをカレンダー日付（tz-naive）に変換
    df.index = pd.to_datetime([ts.date() for ts in df.index])
    df.index.name = "date"
    df = df.sort_index().dropna(subset=["open", "high", "low", "close"])

    if df.empty:
        raise ValueError("yfinance: 有効データがありません")
    return df


def _fetch_stooq(lookback_days: int) -> pd.DataFrame:
    end = pd.Timestamp.today()
    start = end - pd.Timedelta(days=lookback_days + 60)
    url = (
        f"https://stooq.com/q/d/l/"
        f"?s={config.NIKKEI_STOOQ_SYMBOL}"
        f"&d1={start.strftime('%Y%m%d')}"
        f"&d2={end.strftime('%Y%m%d')}"
        f"&i=d"
    )
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()

    text = resp.text.strip()
    if not text or text.startswith("No data"):
        raise ValueError(f"Stooq: 空レスポンス ({text[:80]})")

    df = pd.read_csv(io.StringIO(text))
    df.columns = df.columns.str.lower().str.strip()
    df = df.rename(columns={"date": "date"}).set_index("date")
    df.index = pd.to_datetime(df.index).normalize()
    df.index.name = "date"
    df = df[["open", "high", "low", "close"]].sort_index()
    df = df.dropna(subset=["open", "high", "low", "close"])

    if df.empty:
        raise ValueError("Stooq: 有効データがありません")
    return df


def upsert_history(df: pd.DataFrame) -> pd.DataFrame:
    """data/history/nikkei_ohlc.csv に upsert（重複日付は最新で上書き）。"""
    config.HISTORY.mkdir(parents=True, exist_ok=True)
    path = config.OHLC_CSV

    if path.exists():
        existing = pd.read_csv(path, index_col=0, parse_dates=True)
        existing.index = pd.to_datetime(existing.index).normalize()
        existing.index.name = "date"
        combined = pd.concat([existing, df])
    else:
        combined = df.copy()

    combined.index.name = "date"
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined.to_csv(path, date_format="%Y-%m-%d")
    logger.info("OHLC CSV 更新: 新規 %d 行 → 合計 %d 行", len(df), len(combined))
    return combined
