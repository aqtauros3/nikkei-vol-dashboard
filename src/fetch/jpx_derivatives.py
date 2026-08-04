"""JPX 清算値段CSV（rbYYYYMMDD.csv）の取得・正規化・蓄積。

データ源: https://www.jpx.co.jp/markets/derivatives/settlement-price/index.html
  - 先物行（PUT/CAL 空欄）とオプション行（PUT/CAL が "PUT"/"CAL"）を同一 CSV に収録
  - IV・金利・残日数・理論価格を JPX が計算済みで提供 → BS 逆算不要
  - 対象絞込: 原資産名称 == "日経225"（TOPIX・GOLD 等は除外）

URL 解決:
  index.html を取得し、href が rb + 8桁 + .csv に一致するリンクを抽出。
  ハッシュディレクトリ（tvdivq00000014l6-att 等）が変わっても追従できる。

列マッピング（実ファイル確認済み）:
  銘柄コード → code
  銘柄名称   → name
  PUT/CAL    → put_call  ("PUT"/"CAL" or NaN for futures)
  限月       → expiry    (YYYYMM 文字列)
  権利行使価格 → strike  (float, NaN for futures)
  清算価格   → settlement
  理論価格   → theoretical (NaN for futures)
  原資産価格 → underlying
  ボラティリティ → iv   (年率%, NaN for futures)
  金利       → rate      (NaN for futures)
  残日数     → days_to_expiry (NaN for futures)
  原資産名称 → (フィルタ後に drop)
"""
from __future__ import annotations

import io
import logging
import re
import time
from pathlib import Path

import jpholiday
import pandas as pd
import requests
from bs4 import BeautifulSoup

from src import config

logger = logging.getLogger(__name__)

_USER_AGENT = "nikkei-vol-dashboard/1.0 (GitHub Actions; contact via repo)"

_COL_MAP = {
    "銘柄コード":   "code",
    "銘柄名称":     "name",
    "PUT/CAL":      "put_call",
    "限月":         "expiry",
    "権利行使価格": "strike",
    "清算価格":     "settlement",
    "理論価格":     "theoretical",
    "原資産価格":   "underlying",
    "ボラティリティ": "iv",
    "金利":         "rate",
    "残日数":       "days_to_expiry",
    "原資産名称":   "underlying_name",
}

_SCHEMA_COLS = [
    "date", "code", "name", "put_call", "expiry", "strike",
    "settlement", "theoretical", "underlying", "iv", "rate", "days_to_expiry",
]

_NUMERIC_COLS = ["strike", "settlement", "theoretical", "underlying", "iv", "rate", "days_to_expiry"]


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------

def fetch_derivatives(trade_date: pd.Timestamp | None = None) -> pd.DataFrame:
    """JPX 清算値段 CSV を取得して正規化した DataFrame を返す。

    trade_date が None なら当日（JST 基準の date を使用）。
    失敗時は RuntimeError を raise する（呼び出し元で except して縮退運転）。
    """
    if trade_date is None:
        trade_date = pd.Timestamp.now(tz=config.TIMEZONE).normalize().tz_localize(None)

    # 土日・祝日は JPX 休場 → 直近営業日にロールバック
    trade_date = _prev_jbday_if_needed(trade_date)

    date_str = trade_date.strftime("%Y-%m-%d")
    yyyymmdd = trade_date.strftime("%Y%m%d")

    headers = {"User-Agent": _USER_AGENT}
    base_url = _resolve_base_url(config.JPX_SETTLEMENT_INDEX_URL, headers)
    file_url = f"{base_url}/rb{yyyymmdd}.csv"

    logger.info("JPX derivatives: %s を取得中 → %s", date_str, file_url)
    resp = _fetch_with_retry(file_url, headers)

    # ファイル名日付の一致検証（リダイレクト等で別日付のファイルを掴まないための保護）
    actual_url = resp.url
    if f"rb{yyyymmdd}" not in actual_url:
        raise RuntimeError(
            f"JPX CSV ファイル名の日付が一致しません。"
            f"要求={yyyymmdd}, 取得URL={actual_url}"
        )

    df = _parse_rb_csv(resp.content, date_str)
    logger.info("JPX derivatives: %d 行（日経225フィルタ後）", len(df))
    return df


def upsert_derivatives(df: pd.DataFrame) -> None:
    """jpx_derivatives.csv に last-write-wins で upsert する。"""
    if df.empty:
        logger.warning("upsert_derivatives: 空 DataFrame。スキップ。")
        return

    path = config.JPX_DERIVATIVES_CSV

    if path.exists():
        existing = pd.read_csv(path, dtype={"expiry": str, "code": str})
        combined = pd.concat([existing, df], ignore_index=True)
    else:
        combined = df.copy()

    combined = (
        combined
        .drop_duplicates(subset=["date", "code"], keep="last")
        .sort_values(["date", "expiry", "strike", "put_call"])
        .reset_index(drop=True)
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    logger.info("upsert_derivatives: %d 行を保存 → %s", len(combined), path)


def load_derivatives_latest(path: Path | None = None) -> pd.DataFrame:
    """CSV の最終日付の行を返す。ファイル不在・空は空 DataFrame を返す。"""
    p = path or config.JPX_DERIVATIVES_CSV
    if not p.exists():
        return pd.DataFrame(columns=_SCHEMA_COLS)
    df = pd.read_csv(p, dtype={"expiry": str, "code": str})
    if df.empty:
        return df
    latest = df["date"].max()
    return df[df["date"] == latest].reset_index(drop=True)


# ---------------------------------------------------------------------------
# 内部実装
# ---------------------------------------------------------------------------

def _is_jbday(ts: pd.Timestamp) -> bool:
    """日本の営業日（祝日除く平日）かどうかを返す。"""
    import datetime
    d: datetime.date = ts.date()
    return d.weekday() < 5 and not jpholiday.is_holiday(d)


def _prev_jbday_if_needed(ts: pd.Timestamp) -> pd.Timestamp:
    """ts が非営業日なら直前の営業日を返す。営業日ならそのまま返す。"""
    t = ts
    while not _is_jbday(t):
        t -= pd.Timedelta(days=1)
    if t != ts:
        logger.info("非営業日のため直近営業日を使用: %s → %s", ts.date(), t.date())
    return t


def _resolve_base_url(index_url: str, headers: dict) -> str:
    """index.html から rb*.csv のベースディレクトリ URL を抽出する。"""
    resp = _fetch_with_retry(index_url, headers)
    soup = BeautifulSoup(resp.content, "lxml")
    pattern = re.compile(r"rb\d{8}\.csv", re.IGNORECASE)

    for tag in soup.find_all("a", href=True):
        href: str = tag["href"]
        if pattern.search(href):
            if href.startswith("http"):
                full_url = href
            else:
                from urllib.parse import urljoin
                full_url = urljoin(index_url, href)
            base = full_url.rsplit("/", 1)[0]
            logger.info("JPX ベースURL 確定: %s", base)
            return base

    raise RuntimeError(f"rb*.csv リンクが見つかりません: {index_url}")


def _parse_rb_csv(content: bytes, date_str: str) -> pd.DataFrame:
    """CP932 バイト列をパースして正規化 DataFrame を返す。

    先頭の ＊ 注記行をスキップし、"銘柄コード" で始まる行をヘッダとして検出。
    原資産名称 == config.JPX_TARGET_UNDERLYING でフィルタ。
    """
    text = content.decode("cp932", errors="replace")
    lines = text.splitlines()

    # ヘッダ行を検出（"銘柄コード" で始まる行）
    header_idx: int | None = None
    for i, line in enumerate(lines):
        if line.strip().startswith("銘柄コード"):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError("ヘッダ行（銘柄コード）が見つかりません")

    csv_text = "\n".join(lines[header_idx:])
    df = pd.read_csv(io.StringIO(csv_text), dtype=str)

    # 列名を英語にリネーム（存在する列のみ）
    rename_map = {k: v for k, v in _COL_MAP.items() if k in df.columns}
    df = df.rename(columns=rename_map)

    # 原資産フィルタ
    if "underlying_name" in df.columns:
        df = df[df["underlying_name"].str.strip() == config.JPX_TARGET_UNDERLYING].copy()
        df = df.drop(columns=["underlying_name"])

    # 数値変換（strip → to_numeric、変換不能は NaN）
    for col in _NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.strip(), errors="coerce")

    # put_call: 空文字 / 空白 → NaN
    if "put_call" in df.columns:
        df["put_call"] = df["put_call"].str.strip().replace("", float("nan"))
        df.loc[df["put_call"].isna() | (df["put_call"] == "nan"), "put_call"] = float("nan")

    # expiry を 6桁文字列に統一
    if "expiry" in df.columns:
        df["expiry"] = df["expiry"].astype(str).str.strip().str.zfill(6)

    # date 列を先頭に挿入
    df.insert(0, "date", date_str)

    # スキーマ列のみを保持（余分な列は捨てる）
    existing_schema = [c for c in _SCHEMA_COLS if c in df.columns]
    df = df[existing_schema].reset_index(drop=True)

    return df


def _fetch_with_retry(url: str, headers: dict, max_retries: int = 3) -> requests.Response:
    """HTTP GET。4xx は即失敗、5xx / 接続エラーは指数バックオフでリトライ。"""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            if resp.status_code == 404:
                raise FileNotFoundError(f"404: {url}")
            if 400 <= resp.status_code < 500:
                resp.raise_for_status()
            if resp.status_code >= 500:
                raise RuntimeError(f"サーバーエラー {resp.status_code}: {url}")
            return resp
        except FileNotFoundError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                logger.warning("取得失敗（attempt %d）: %s → %d秒後リトライ", attempt + 1, exc, wait)
                time.sleep(wait)
    raise RuntimeError(f"取得失敗（最大リトライ超過）: {url}") from last_exc
