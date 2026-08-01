"""日経VI 履歴の初回シードスクリプト（ワンショット）。

【手順】
    1. 下記サイトのどちらかから日経VIの過去1〜2年分の履歴CSVをダウンロード
    2. CSVファイルを任意の場所に置く（例: data/raw/vi_raw.csv）
    3. python scripts/seed_vi_history.py <CSVファイルのパス>
    4. 成功すると data/history/nikkei_vi.csv が生成される

-----------------------------------------------------------------------
【対応する入力CSVフォーマット】

■ A) シンプル形式（推奨）
    自分で日付とVI値の2列に整形したもの。
    日付形式: YYYY-MM-DD

    date,vi
    2023-08-01,22.15
    2023-08-02,21.89
    ...

■ B) investing.com 形式（英語版）
    https://www.investing.com/indices/nikkei-volatility-index-historical-data
    画面右上の「ダウンロード」から取得。ヘッダ行に "Price" を含む。

    Date,Price,Open,High,Low,Vol.,Change %
    "Aug 01, 2024","25.34","24.80","25.90","24.50","","0.21%"
    ...

■ B') investing.com 形式（日本語版）★ダウンロードしたファイルはこれ
    同サイトの日本語ページからダウンロードした場合。列名が日本語。

    "日付","終値","始値","高値","安値","出来高","変化率 %"
    "2024-01-04","22.15","21.90","22.80","21.80","","0.00%"
    ...

■ C) stooq 形式
    https://stooq.com/q/d/?s=^vxj (存在する場合)
    ヘッダ行に "Close" または "close" を含む。

    Date,Open,High,Low,Close,Volume
    2024-08-01,24.80,25.90,24.50,25.34,
    ...

-----------------------------------------------------------------------
出力: data/history/nikkei_vi.csv
    date,vi
    2023-08-01,22.15
    2023-08-02,21.89
    ...
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.fetch.nikkei_vi import load_vi_history

_VI_MIN = 5.0
_VI_MAX = 200.0


def _detect_format(df_raw: pd.DataFrame) -> str:
    """入力 CSV のフォーマットを列名から自動判定。"""
    cols_raw = [c.strip() for c in df_raw.columns]
    cols = {c.lower() for c in cols_raw}

    # 日本語版 investing.com: 「日付」「終値」「変化率 %」
    if "日付" in cols_raw and "終値" in cols_raw:
        return "investing_ja"
    # 英語版 investing.com: "price" + "change %"
    if "price" in cols and "change %" in cols:
        return "investing"
    # stooq / OHLC 形式
    if "close" in cols and "open" in cols:
        return "stooq"
    # シンプル date,vi
    if "vi" in cols and "date" in cols:
        return "simple"
    if "date" in cols and len(df_raw.columns) == 2:
        return "simple"
    return "unknown"


def _clean_num(series: pd.Series) -> pd.Series:
    """クォート・カンマを除去して numeric に変換。"""
    return pd.to_numeric(
        series.astype(str).str.replace('"', "").str.replace(",", "").str.strip(),
        errors="coerce",
    )


def _load_investing(df_raw: pd.DataFrame) -> pd.Series:
    """investing.com 英語版を正規化。日付は "Aug 01, 2024" 形式。"""
    df = df_raw.copy()
    df.columns = df.columns.str.strip().str.lower()
    dates = pd.to_datetime(df["date"].str.strip().str.replace('"', ""), format="mixed")
    s = pd.Series(_clean_num(df["price"]).values, index=dates, name="vi")
    return s


def _load_investing_ja(df_raw: pd.DataFrame) -> pd.Series:
    """investing.com 日本語版を正規化。列名: 日付, 終値。日付は YYYY-MM-DD 形式。"""
    df = df_raw.copy()
    dates = pd.to_datetime(
        df["日付"].astype(str).str.strip().str.replace('"', ""), format="mixed"
    )
    s = pd.Series(_clean_num(df["終値"]).values, index=dates, name="vi")
    return s


def _load_stooq(df_raw: pd.DataFrame) -> pd.Series:
    """stooq 形式を正規化。"""
    df = df_raw.copy()
    df.columns = df.columns.str.strip().str.lower()
    dates = pd.to_datetime(df["date"])
    s = pd.Series(
        pd.to_numeric(df["close"], errors="coerce").values, index=dates, name="vi"
    )
    return s


def _load_simple(df_raw: pd.DataFrame) -> pd.Series:
    """シンプル (date, vi) 形式を正規化。"""
    df = df_raw.copy()
    df.columns = df.columns.str.strip().str.lower()
    # 2列目を vi として使う場合に備え列名を探す
    vi_col = "vi" if "vi" in df.columns else df.columns[1]
    dates = pd.to_datetime(df["date"])
    s = pd.Series(
        pd.to_numeric(df[vi_col], errors="coerce").values, index=dates, name="vi"
    )
    return s


def seed(input_path: Path) -> None:
    print(f"読み込み: {input_path}")
    df_raw = pd.read_csv(input_path, thousands=",")
    fmt = _detect_format(df_raw)
    print(f"フォーマット判定: {fmt}")

    if fmt == "investing_ja":
        s = _load_investing_ja(df_raw)
    elif fmt == "investing":
        s = _load_investing(df_raw)
    elif fmt == "stooq":
        s = _load_stooq(df_raw)
    elif fmt == "simple":
        s = _load_simple(df_raw)
    else:
        # unknown: 列名を表示してユーザーに判断を促す
        print(f"\n[エラー] フォーマットを自動判定できませんでした。")
        print(f"  列名: {list(df_raw.columns)}")
        print(
            "  CSVを 'date,vi' の2列形式に整形してから再実行してください。\n"
            "  例:\n    date,vi\n    2024-01-04,22.15\n    ..."
        )
        sys.exit(1)

    # サニティチェック
    s.index = s.index.normalize()
    s.index.name = "date"
    s = s.dropna()
    out_of_range = s[(s < _VI_MIN) | (s > _VI_MAX)]
    if not out_of_range.empty:
        print(f"\n[警告] VI の範囲外({_VI_MIN}〜{_VI_MAX})の値 {len(out_of_range)} 行 → 除外")
        s = s[(s >= _VI_MIN) & (s <= _VI_MAX)]

    if s.empty:
        print("[エラー] 有効な VI 値がありません。")
        sys.exit(1)

    print(f"有効データ: {len(s)} 行  期間: {s.index.min().date()} 〜 {s.index.max().date()}")
    print(f"  VI 最小: {s.min():.2f}  最大: {s.max():.2f}  平均: {s.mean():.2f}")

    # 既存と結合（重複は新しい方を優先）
    config.HISTORY.mkdir(parents=True, exist_ok=True)
    existing = load_vi_history()
    if not existing.empty:
        print(f"\n既存 CSV: {len(existing)} 行 → マージ後に重複排除します")
        combined = pd.concat([existing, s])
    else:
        combined = s.copy()

    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined.name = "vi"
    combined.to_csv(config.VI_CSV, header=True, date_format="%Y-%m-%d")

    print(f"\n保存完了: {config.VI_CSV}")
    print(f"  合計 {len(combined)} 行  期間: {combined.index.min().date()} 〜 {combined.index.max().date()}")

    weeks = len(combined) / 5
    if len(combined) < 252:
        print(
            f"\n[注意] IV Rank/Percentile には 252 営業日分 が必要です。"
            f"現在 {len(combined)} 行（約 {weeks:.0f} 週分）。"
            f"不足分は夜間バッチで徐々に積み上げられます。"
        )
    else:
        print(f"  → 252 営業日以上のデータがあります。IV Rank/Percentile が正常に機能します。")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        print("使い方: python scripts/seed_vi_history.py <入力CSVパス>")
        return 1

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"[エラー] ファイルが見つかりません: {input_path}")
        return 1

    seed(input_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
