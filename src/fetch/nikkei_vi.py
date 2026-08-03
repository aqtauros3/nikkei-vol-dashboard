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

import datetime
import logging
import re

import jpholiday
import pandas as pd
import requests
from bs4 import BeautifulSoup

from src import config

logger = logging.getLogger(__name__)

# 日経VI の現実的な値域（サニティチェック用）
_VI_MIN = 5.0
_VI_MAX = 200.0

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_vi_latest() -> tuple[pd.Timestamp, float]:
    """当日の日経VI終値（%表記）を複数ソースから取得。全ソース失敗時は例外を投げる。"""
    errors: list[str] = []

    for fn, name in [
        (_fetch_vi_nikkei, "nikkei.com"),
        (_fetch_vi_investing, "investing.com"),
    ]:
        try:
            date, value = fn()
            logger.info("%s から VI 取得: %s → %.2f", name, date.date(), value)
            return date, value
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            logger.warning("%s 失敗: %s", name, exc)

    raise RuntimeError(
        "日経VI 取得失敗（全ソース試行済み）:\n" + "\n".join(errors)
    )


def _today_jst() -> pd.Timestamp:
    return pd.Timestamp.now(tz=config.TIMEZONE).normalize().tz_localize(None)


def is_jbday(ts: pd.Timestamp) -> bool:
    """日本の営業日（祝日除く平日）かどうかを返す。"""
    d: datetime.date = ts.date() if isinstance(ts, pd.Timestamp) else ts
    return d.weekday() < 5 and not jpholiday.is_holiday(d)


def _parse_vi_float(text: str) -> float:
    """カンマ・全角数字を除去して float 変換。範囲外は ValueError。"""
    cleaned = (
        text.strip()
        .replace(",", "")
        .replace("，", "")
        .replace(" ", "")
        .translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
    )
    val = float(cleaned)
    if not (_VI_MIN < val < _VI_MAX):
        raise ValueError(f"VI 値が現実的な範囲外: {val}")
    return val


def _extract_first_valid_number(text: str) -> float | None:
    """テキスト中の数値候補を左から順に試し、VI として妥当な最初の値を返す。"""
    for m in re.finditer(r"\d{1,3}(?:[,，]\d{3})*(?:\.\d+)?", text):
        try:
            return _parse_vi_float(m.group())
        except ValueError:
            continue
    return None


def _fetch_vi_nikkei() -> tuple[pd.Timestamp, float]:
    """nikkei.com 公式ページから日経VI を取得（JSON API → HTML フォールバック）。"""
    # JSON エンドポイントを先に試す
    json_url = (
        "https://indexes.nikkei.co.jp/nkave/index/result"
        "?elapsedTime=0&index=nk225vi&type=json"
    )
    try:
        resp = requests.get(json_url, headers=_HEADERS, timeout=20)
        if resp.ok:
            data = resp.json()
            for key in ("closePrice", "currentPrice", "price", "val", "close", "value"):
                raw = data.get(key)
                if raw is not None:
                    val = _parse_vi_float(str(raw))
                    return _today_jst(), val
    except Exception:
        pass  # HTML にフォールバック

    # HTML スクレイプ
    url = "https://indexes.nikkei.co.jp/nkave/index?id=nk225vi"
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # class 名にclose/current/val/price を含む要素を候補に
    pattern = re.compile(r"(close|current|high|val|price)", re.I)
    for tag in ("span", "td", "div", "p"):
        for el in soup.find_all(tag, class_=pattern):
            val = _extract_first_valid_number(el.get_text(strip=True))
            if val is not None:
                return _today_jst(), val

    raise ValueError(
        "nikkei.com: VI 値を抽出できませんでした（ページ構造が変わった可能性）"
    )


def _fetch_vi_investing() -> tuple[pd.Timestamp, float]:
    """investing.com から日経VI を取得。"""
    url = "https://www.investing.com/indices/nikkei-volatility-index"
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    # investing.com の典型的なセレクタ（複数バージョンに対応）
    candidates = [
        soup.find(attrs={"data-test": "instrument-price-last"}),
        soup.find("span", id=re.compile(r"last")),
        soup.find("div", attrs={"data-test": "instrument-price-last"}),
        soup.find("span", class_=re.compile(r"(last|price|current)", re.I)),
    ]

    for el in candidates:
        if el is None:
            continue
        val = _extract_first_valid_number(el.get_text(strip=True))
        if val is not None:
            return _today_jst(), val

    raise ValueError(
        "investing.com: VI 値を抽出できませんでした（ページ構造が変わった可能性）"
    )


def load_vi_history() -> pd.Series:
    """data/history/nikkei_vi.csv を読み込み Series（index=date, values=vi%）を返す。"""
    path = config.VI_CSV
    if not path.exists():
        logger.warning("VI history CSV が存在しません: %s", path)
        return pd.Series(dtype=float, name="vi")

    df = pd.read_csv(path, index_col="date", parse_dates=True)
    df.index = pd.to_datetime(df.index).normalize()
    s = df["vi"].sort_index()
    s.name = "vi"
    return s


def append_vi(date: pd.Timestamp, value: float) -> None:
    """data/history/nikkei_vi.csv に 1 行追記（同日は最新値で上書き）。

    非営業日（土日・祝日）は保存をスキップしてログ警告を出す。
    手動実行時に週末・祝日の汚染行が混入するのを防ぐ。
    """
    config.HISTORY.mkdir(parents=True, exist_ok=True)
    path = config.VI_CSV

    date = date.normalize()
    if not is_jbday(date):
        logger.warning(
            "append_vi: %s は非営業日のため保存をスキップ（土日・祝日）", date.date()
        )
        return

    new = pd.Series({date: value}, name="vi")
    new.index.name = "date"

    if path.exists():
        existing = load_vi_history()
        combined = pd.concat([existing, new])
    else:
        combined = new.copy()

    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined.name = "vi"
    combined.to_csv(path, header=True, date_format="%Y-%m-%d")
    logger.info("VI CSV 更新: %s → %.2f", date.date(), value)
