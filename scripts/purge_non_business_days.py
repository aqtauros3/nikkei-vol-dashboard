"""非営業日（土日・祝日）の行を history CSV から削除するユーティリティ。

対象:
    data/history/nikkei_vi.csv       -- date 列がインデックス
    data/history/nikkei_ohlc.csv     -- date 列がインデックス
    data/history/jpx_derivatives.csv -- date 列が通常列

実行前に .bak バックアップを作成する。
"""
from __future__ import annotations

import datetime
import shutil
import sys
from pathlib import Path

import jpholiday
import pandas as pd

_ROOT = Path(__file__).parent.parent
_HISTORY = _ROOT / "data" / "history"


def _is_jbday(d: datetime.date) -> bool:
    return d.weekday() < 5 and not jpholiday.is_holiday(d)


def _purge_index_csv(path: Path) -> tuple[int, int]:
    """date がインデックスの CSV を浄化して上書き保存。(before, removed) を返す。"""
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index = pd.to_datetime(df.index).normalize()
    before = len(df)
    mask = pd.Series(
        [_is_jbday(ts.date()) for ts in df.index], index=df.index, dtype=bool
    )
    removed_df = df[~mask]
    df = df[mask]
    if not removed_df.empty:
        print(f"  削除行:")
        for idx, row in removed_df.iterrows():
            print(f"    {idx.date()}  {row.to_dict()}")
    df.to_csv(path, date_format="%Y-%m-%d")
    return before, int((~mask).sum())


def _purge_col_csv(path: Path, date_col: str = "date") -> tuple[int, int]:
    """date が通常列の CSV を浄化して上書き保存。(before, removed) を返す。"""
    df = pd.read_csv(path, dtype={"expiry": str, "code": str})
    df[date_col] = pd.to_datetime(df[date_col]).dt.normalize()
    before = len(df)
    mask = df[date_col].map(lambda ts: _is_jbday(ts.date()))
    removed_df = df[~mask]
    df = df[mask]
    if not removed_df.empty:
        print(f"  削除日付: {sorted(removed_df[date_col].dt.date.unique())}")
        print(f"  削除行数: {len(removed_df)}")
    df.to_csv(path, index=False)
    return before, int((~mask).sum())


def main() -> int:
    targets = [
        (_HISTORY / "nikkei_vi.csv", "index"),
        (_HISTORY / "nikkei_ohlc.csv", "index"),
        (_HISTORY / "jpx_derivatives.csv", "col"),
    ]

    # バックアップ作成
    print("=== バックアップ作成 ===")
    for path, _ in targets:
        if path.exists():
            bak = path.with_suffix(".csv.bak")
            shutil.copy2(path, bak)
            print(f"  {path.name} → {bak.name}")
        else:
            print(f"  {path.name}: 存在しないためスキップ")

    print()
    print("=== 非営業日行の検出・削除 ===")
    total_removed = 0
    for path, kind in targets:
        if not path.exists():
            print(f"[skip] {path.name}: ファイルなし")
            continue
        print(f"[{path.name}]")
        if kind == "index":
            before, removed = _purge_index_csv(path)
        else:
            before, removed = _purge_col_csv(path)
        total_removed += removed
        status = f"削除 {removed} 行" if removed > 0 else "汚染なし"
        print(f"  {before} 行 → {before - removed} 行  ({status})")

    print()
    print(f"=== 完了: 合計 {total_removed} 行を削除 ===")
    if total_removed > 0:
        print("  バックアップ: *.csv.bak（不要なら手動削除してください）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
