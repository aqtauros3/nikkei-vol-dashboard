# PROGRESS.md — セッション引き継ぎ記録

最終更新: 2026-08-02

---

## 完了済み

### フェーズ4: JPXオプションデータ統合（全実装完了）

- **`src/fetch/jpx_derivatives.py`**
  - JPX清算値段CSV（`rbYYYYMMDD.csv`）を `index.html` から動的URL抽出（BeautifulSoup、`rb\d{8}\.csv` パターン）
  - CP932デコード、`＊`注記行スキップ、"銘柄コード"ヘッダ検出
  - 原資産名称 == "日経225" フィルタ（TOPIX等除外）
  - `last-write-wins` upsert: `(date, code)` を主キーとして `data/history/jpx_derivatives.csv` に蓄積
  - **縮退ロジック修正(A)**: `option_data_ok = not deriv_latest.empty`（蓄積データの有無のみで判定。フェッチ失敗でも前回値を表示）
  - **非営業日スキップ(B)**: `trade_date.dayofweek >= 5` → 直近営業日（金曜）にロールバック

- **`src/compute/option_metrics.py`**
  - `filter_options()` / `filter_futures()`
  - `nearest_expiry()`: `days_to_expiry > 0` の最小限月
  - `atm_iv(df, expiry)`: 原資産価格に最近接ストライクの Call/Put IV の平均（片側需給バイアスを打ち消す）
  - `iv_skew_series(df, expiry)`: 列 `moneyness, iv_put, iv_call, outlier_put, outlier_call`
  - `_flag_iv_outliers(iv_series)`: ローリング中央値（window=5）±30%を外れた点を True（淡色表示、除外しない）
  - `iv_term_structure(df)`: index=expiry, values=atm_iv
  - `futures_term_structure(df)`: index=expiry, values=settlement
  - `futures_underlying_price(df)`: 先物行の underlying 平均

- **`src/report/build_html.py`** / **`templates/dashboard.html.j2`**
  - サマリーカード: 日経VI・IVパーセンタイル・HV20・VRP・ATM IV・VRP(OP)・レジームの7枚
  - アンカーナビ（`<a href="#vol">` 等）＋ `<details open>` 折りたたみ（JS不要）
  - IVスキューチャート: Put=青・Call=橙の2本、異常値は opacity=0.2 で淡色表示、ATM垂直線
  - IV期間構造チャート: ATM IV点折れ線 + 日経VI水平破線
  - 先物期間構造チャート: 清算値段点折れ線 + 現物終値水平線
  - JPX警告バナー2段階: 前回値表示中（橙）/ データなし（橙）
  - Plotly.newPlot が計7回（テストで検証済み）

- **`tests/`**: `test_fetch_jpx.py`（16テスト）・`test_option_metrics.py`（23テスト）・`test_build_html.py`（更新済み）。pytest 61テスト全通過。

- **`scripts/seed_jpx_derivatives.py`**: バックフィル用CLIスクリプト（`--dry-run`, `--lookback 60` オプション付き）

- **`scripts/diag_jpx_url.py`**: URL抽出診断スクリプト（診断専用、修正なし）

---

## データ状況

| ファイル | 内容 |
|---|---|
| `data/history/jpx_derivatives.csv` | 2026-07-31 の1日分のみ（12,781行）|
| `data/history/nikkei_ohlc.csv` | 取得済み（291行程度）|
| `data/history/vi_history.csv` | 取得済み |

**seedは未実行**。`scripts/seed_jpx_derivatives.py` は実装済みで、次のセッションで即実行可能:

```bash
python scripts/seed_jpx_derivatives.py --dry-run   # まず確認
python scripts/seed_jpx_derivatives.py             # 実行（60営業日バックフィル）
```

---

## 既知の論点・確定事項

- **URL動的抽出は正常**: hash `tvdivq00000014l6-att`（ゼロ6個）を正しく取得。以前ユーザーが疑った「ゼロ7個」問題は、バナー文字の読み間違いで実バグなし（`diag_jpx_url.py` で確認済み）。
- **土曜(2026-08-02)の404は正常**: JPX休場のため。非営業日スキップにより 7/31 データを取得して描画済み。
- **月曜(2026-08-04)に実地検証が必要**: 平日データ取得が正常に動作するか（200レスポンス、2日目が追記されるか）確認する。

---

## 次にやること（優先順）

1. **seed実行**: JPXは約2ヶ月でロールオフするため早めに実行。遡れない日（祝日等）の欠損は許容。
2. **月曜の平日データ取得検証**: 夜間バッチ or `run_local.py` を手動実行し、2026-08-04 データが正しく追記されるか確認。
3. **チャート改善（未着手）**:
   - IVスキュー: モネーネス軸に対応行使価格の補助軸（top axis）追加
   - 期間構造: 期近3〜4限月ズームビュー追加（`<details>` 内）
   - IV期間スロープ（期近−3M ATM IV差分）をサマリーカードに追加
   - 期近は満期効果でIVが不安定になる旨の注記追加

---

## 運用方針（不変）

- クラウド自律運用（GitHub Actions夜間バッチ）、PC非依存を維持
- 別プロジェクト `n225-supply-demand` は参照のみ可。変更不可。
- ダッシュボードは分析補助ツール。投資助言ではない（画面・README に明記済み）。
- 閾値はすべて「例示」として画面に表示している。
