"""fetch モジュールの単体テスト（ネットワーク不要）。

CSV 書き込み・読み込み・upsert ロジックのみ検証。
ネットワーク通信を要するテストは scripts/check_fetch.py で手動確認する。
"""
from __future__ import annotations

import pandas as pd
import pytest

import src.config as cfg
from src.fetch import nikkei_ohlc, nikkei_vi


# ---------- ヘルパ ----------

def _sample_ohlc(n: int = 10, base_date: str = "2024-01-01") -> pd.DataFrame:
    dates = pd.bdate_range(base_date, periods=n)
    return pd.DataFrame(
        {"open": 30000.0, "high": 30100.0, "low": 29900.0, "close": 30050.0},
        index=dates,
    )


# ---------- nikkei_ohlc ----------

def test_upsert_creates_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "HISTORY", tmp_path)
    monkeypatch.setattr(cfg, "OHLC_CSV", tmp_path / "nikkei_ohlc.csv")

    df = _sample_ohlc(5)
    combined = nikkei_ohlc.upsert_history(df)

    assert len(combined) == 5
    assert (tmp_path / "nikkei_ohlc.csv").exists()


def test_upsert_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "HISTORY", tmp_path)
    monkeypatch.setattr(cfg, "OHLC_CSV", tmp_path / "nikkei_ohlc.csv")

    df1 = _sample_ohlc(5)   # 2024-01-01 〜 01-05
    df2 = _sample_ohlc(8)   # 2024-01-01 〜 01-10（5日分は重複）
    nikkei_ohlc.upsert_history(df1)
    combined = nikkei_ohlc.upsert_history(df2)

    assert len(combined) == 8


def test_upsert_overwrites_duplicate_row(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "HISTORY", tmp_path)
    monkeypatch.setattr(cfg, "OHLC_CSV", tmp_path / "nikkei_ohlc.csv")

    d = pd.bdate_range("2024-01-01", periods=1)
    df_old = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}, index=d)
    df_new = pd.DataFrame({"open": 9.0, "high": 9.9, "low": 8.8, "close": 9.5}, index=d)
    nikkei_ohlc.upsert_history(df_old)
    combined = nikkei_ohlc.upsert_history(df_new)

    assert len(combined) == 1
    assert combined["close"].iloc[0] == pytest.approx(9.5)


# ---------- nikkei_vi ----------

def test_append_vi_and_load(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "HISTORY", tmp_path)
    monkeypatch.setattr(cfg, "VI_CSV", tmp_path / "nikkei_vi.csv")

    d1 = pd.Timestamp("2024-01-10")
    d2 = pd.Timestamp("2024-01-11")
    nikkei_vi.append_vi(d1, 25.5)
    nikkei_vi.append_vi(d2, 26.0)

    s = nikkei_vi.load_vi_history()
    assert len(s) == 2
    assert s[d1] == pytest.approx(25.5)
    assert s[d2] == pytest.approx(26.0)


def test_append_vi_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "HISTORY", tmp_path)
    monkeypatch.setattr(cfg, "VI_CSV", tmp_path / "nikkei_vi.csv")

    d = pd.Timestamp("2024-01-10")
    nikkei_vi.append_vi(d, 25.5)
    nikkei_vi.append_vi(d, 27.0)  # 同日・上書き

    s = nikkei_vi.load_vi_history()
    assert len(s) == 1
    assert s[d] == pytest.approx(27.0)


def test_load_vi_empty_when_no_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "HISTORY", tmp_path)
    monkeypatch.setattr(cfg, "VI_CSV", tmp_path / "nikkei_vi.csv")

    s = nikkei_vi.load_vi_history()
    assert s.empty
    assert s.dtype == float
