"""jpx_derivatives のテスト（ネットワーク不要）。"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import src.config as cfg
from src.fetch.jpx_derivatives import (
    _parse_rb_csv,
    fetch_derivatives,
    load_derivatives_latest,
    upsert_derivatives,
)

# ---------------------------------------------------------------------------
# モック CSV（CP932 エンコードして使用）
# ---------------------------------------------------------------------------

_MOCK_CSV_TEXT = (
    "＊この情報は例示です。投資判断には使用しないこと。\n"
    "＊注記行2\n"
    "銘柄コード,銘柄名称,PUT/CAL,限月,権利行使価格,清算価格,理論価格,原資産価格,"
    "ボラティリティ,金利,残日数,原資産名称\n"
    "NK225F2609,日経225先物 26/09,,202609,,38250,,38250,,,,日経225\n"
    "NK225E202609038000P,日経225OP 38000プット,PUT,202609,38000,450,448.3,38250,24.1,0.1,40,日経225\n"
    "NK225E202609038000C,日経225OP 38000コール,CAL,202609,38000,512,510.7,38250,22.8,0.1,40,日経225\n"
    "NK225E202609036000P,日経225OP 36000プット,PUT,202609,36000,120,119.0,38250,26.5,0.1,40,日経225\n"
    "TOPIXOP999P,TOPIX OP,PUT,202609,1000,5,4.9,1250,12.0,0.1,40,TOPIX\n"
)

_MOCK_CSV_BYTES = _MOCK_CSV_TEXT.encode("cp932")


# ---------------------------------------------------------------------------
# _parse_rb_csv のテスト
# ---------------------------------------------------------------------------

def test_parse_filters_topix():
    """原資産名称が日経225以外の行は除外されること。"""
    df = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    assert "TOPIX" not in df["name"].values
    assert len(df) == 4  # 先物1 + オプション3（TOPIX除外）


def test_parse_date_column():
    """date 列が付与されること。"""
    df = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    assert "date" in df.columns
    assert (df["date"] == "2026-07-31").all()


def test_parse_futures_row_has_nan_put_call():
    """先物行の put_call は NaN であること。"""
    df = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    futures = df[df["code"] == "NK225F2609"]
    assert len(futures) == 1
    assert pd.isna(futures.iloc[0]["put_call"])


def test_parse_futures_row_has_nan_strike():
    """先物行の strike は NaN であること。"""
    df = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    futures = df[df["code"] == "NK225F2609"]
    assert pd.isna(futures.iloc[0]["strike"])


def test_parse_option_numeric_types():
    """オプション行の数値列が数値型（int または float）になること。"""
    df = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    opts = df[df["put_call"].notna()]
    # iv と strike は NaN が混在するため float
    assert opts["iv"].dtype.kind == "f"
    assert opts["strike"].dtype.kind == "f"
    # settlement は全行に値があれば int でも可（数値型であることを確認）
    assert opts["settlement"].dtype.kind in ("f", "i")


def test_parse_comment_lines_skipped():
    """＊ 注記行がスキップされ、ヘッダ行から読み込まれること。"""
    df = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    # ＊ で始まる行がデータに混入していないこと
    assert not df["code"].astype(str).str.startswith("＊").any()


def test_parse_put_call_values():
    """PUT/CAL の値が 'PUT' / 'CAL' であること。"""
    df = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    opts = df[df["put_call"].notna()]
    assert set(opts["put_call"].unique()).issubset({"PUT", "CAL"})


def test_parse_schema_columns():
    """出力に必要な列がすべて含まれること。"""
    df = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    required = {"date", "code", "name", "put_call", "expiry",
                "strike", "settlement", "underlying", "iv"}
    assert required.issubset(set(df.columns))


def test_parse_expiry_is_6digit_string():
    """expiry が 6桁文字列であること（例: '202609'）。"""
    df = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    assert df["expiry"].str.len().eq(6).all()


# ---------------------------------------------------------------------------
# upsert_derivatives のテスト
# ---------------------------------------------------------------------------

def test_upsert_creates_file(tmp_path, monkeypatch):
    """ファイル不在の初回 upsert でファイルが作成されること。"""
    monkeypatch.setattr(cfg, "JPX_DERIVATIVES_CSV", tmp_path / "jpx_derivatives.csv")
    df = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    upsert_derivatives(df)
    assert (tmp_path / "jpx_derivatives.csv").exists()


def test_upsert_last_write_wins(tmp_path, monkeypatch):
    """同一 (date, code) の行が上書きされること（last-write-wins）。"""
    monkeypatch.setattr(cfg, "JPX_DERIVATIVES_CSV", tmp_path / "jpx_derivatives.csv")
    df1 = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    upsert_derivatives(df1)

    # 同日の同コードを iv を変えて再 upsert
    df2 = df1.copy()
    df2.loc[df2["code"] == "NK225E202609038000P", "iv"] = 99.9
    upsert_derivatives(df2)

    out = pd.read_csv(tmp_path / "jpx_derivatives.csv", dtype={"expiry": str, "code": str})
    row = out[(out["date"] == "2026-07-31") & (out["code"] == "NK225E202609038000P")]
    assert len(row) == 1
    assert abs(row.iloc[0]["iv"] - 99.9) < 0.01


def test_upsert_no_duplicate_rows(tmp_path, monkeypatch):
    """同じデータを2回 upsert しても重複行が生じないこと。"""
    monkeypatch.setattr(cfg, "JPX_DERIVATIVES_CSV", tmp_path / "jpx_derivatives.csv")
    df = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    upsert_derivatives(df)
    upsert_derivatives(df)

    out = pd.read_csv(tmp_path / "jpx_derivatives.csv")
    assert len(out) == len(df)


def test_upsert_accumulates_multiple_dates(tmp_path, monkeypatch):
    """異なる日付のデータが両方保存されること。"""
    monkeypatch.setattr(cfg, "JPX_DERIVATIVES_CSV", tmp_path / "jpx_derivatives.csv")
    df1 = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-30")
    df2 = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    upsert_derivatives(df1)
    upsert_derivatives(df2)

    out = pd.read_csv(tmp_path / "jpx_derivatives.csv")
    assert set(out["date"].unique()) == {"2026-07-30", "2026-07-31"}


def test_upsert_empty_df_is_noop(tmp_path, monkeypatch):
    """空 DataFrame を渡してもエラーにならないこと。"""
    monkeypatch.setattr(cfg, "JPX_DERIVATIVES_CSV", tmp_path / "jpx_derivatives.csv")
    upsert_derivatives(pd.DataFrame())
    assert not (tmp_path / "jpx_derivatives.csv").exists()


# ---------------------------------------------------------------------------
# load_derivatives_latest のテスト
# ---------------------------------------------------------------------------

def test_load_latest_returns_latest_date(tmp_path, monkeypatch):
    """最新日付の行だけ返すこと。"""
    monkeypatch.setattr(cfg, "JPX_DERIVATIVES_CSV", tmp_path / "jpx_derivatives.csv")
    df1 = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-30")
    df2 = _parse_rb_csv(_MOCK_CSV_BYTES, "2026-07-31")
    upsert_derivatives(df1)
    upsert_derivatives(df2)

    latest = load_derivatives_latest()
    assert (latest["date"] == "2026-07-31").all()


def test_load_latest_file_not_found(tmp_path, monkeypatch):
    """ファイル不在でも空 DataFrame を返すこと（例外なし）。"""
    monkeypatch.setattr(cfg, "JPX_DERIVATIVES_CSV", tmp_path / "no_file.csv")
    df = load_derivatives_latest()
    assert df.empty


# ---------------------------------------------------------------------------
# fetch_derivatives URL 日付検証のテスト
# ---------------------------------------------------------------------------

def test_fetch_derivatives_url_date_mismatch_raises():
    """取得 URL のファイル名日付が要求日付と一致しない場合 RuntimeError を送出すること。"""
    trade_date = pd.Timestamp("2026-07-31")

    mock_resp = MagicMock()
    mock_resp.url = "https://example.com/some-hash/rb20260730.csv"  # 別日付

    with (
        patch("src.fetch.jpx_derivatives._resolve_base_url", return_value="https://example.com/some-hash"),
        patch("src.fetch.jpx_derivatives._fetch_with_retry", return_value=mock_resp),
    ):
        with pytest.raises(RuntimeError, match="ファイル名の日付が一致しません"):
            fetch_derivatives(trade_date=trade_date)


def test_fetch_derivatives_url_date_matches():
    """取得 URL のファイル名日付が要求日付と一致する場合 DataFrame が返ること。"""
    trade_date = pd.Timestamp("2026-07-31")

    mock_resp = MagicMock()
    mock_resp.url = "https://example.com/some-hash/rb20260731.csv"
    mock_resp.content = _MOCK_CSV_BYTES

    with (
        patch("src.fetch.jpx_derivatives._resolve_base_url", return_value="https://example.com/some-hash"),
        patch("src.fetch.jpx_derivatives._fetch_with_retry", return_value=mock_resp),
    ):
        df = fetch_derivatives(trade_date=trade_date)

    assert not df.empty
    assert (df["date"] == "2026-07-31").all()
