# フェーズ4 実装計画：JPX清算値段CSV統合取得・分析・可視化

作成日: 2026-08-02（初版）  
改訂日: 2026-08-02（実ファイル検証に基づく全面改訂）  
ステータス: **レビュー待ち（実装前承認が必要）**

---

## 0. 設計方針の確定

### 採用設計：B'（本プロジェクト内に自己完結した新規 fetcher を実装）

GitHub Actions (Ubuntu) 上で日次自律実行。既存 n225-supply-demand には一切変更しない。

### 主データ源の一本化（実ファイル検証で確定）

当初は `jpx_option_price.py` + `jpx_settlement.py` の 2 ファイル構成を想定していたが、  
実ファイル検証の結果、**清算値段 CSV（`rbYYYYMMDD.csv`）が上位互換**と判明したため統合する。

| 検討していたファイル | 結論 |
|-------------------|------|
| `ose〜tp.csv`（理論価格等情報） | ❌ 不使用（rb ファイルが同等以上の情報を含む） |
| `rbYYYYMMDD.csv`（清算値段） | ✅ 採用（先物行 + オプション行を同一ファイルに収録、IV 列・金利・残存日数あり） |
| svc.qri.jp リンク | ❌ 不使用（JPX ドメイン外・QUICK 系外部サービス） |

### 新規追加ファイル（最終構成）

```
src/fetch/jpx_derivatives.py     ← 新規（旧 jpx_option_price + jpx_settlement を統合）
src/compute/option_metrics.py    ← 新規（純関数）
data/history/jpx_derivatives.csv ← 新規（累積 upsert）
scripts/seed_jpx_derivatives.py  ← 新規（初回バックフィル専用）
```

---

## 1. 実ファイル仕様（検証済み）

### ファイル: `rbYYYYMMDD.csv`

| 項目 | 内容 |
|------|------|
| 取得元ページ | https://www.jpx.co.jp/markets/derivatives/settlement-price/index.html |
| ファイル URL 例 | `https://www.jpx.co.jp/markets/derivatives/settlement-price/tvdivq00000014l6-att/rb20260731.csv` |
| URL パターン | `{base_dir}/rb{YYYYMMDD}.csv`<br>ハッシュ部（`tvdivq...`）は変動しうるため index.html から動的抽出 |
| 文字コード | Shift-JIS（`cp932`） |
| 先頭行 | `＊` で始まる注記行が数行（可変）→ ヘッダ行を動的検出して読み込む |
| 公表タイミング | 当日 16:00 頃（21:00 バッチには余裕あり） |
| 過去ファイル保持 | 約 2 か月（初回は seed スクリプトでバックフィルが必要） |

### 列定義（実ファイル確認済み）

| 元の列名（日本語） | 内部列名 | 型 | 先物行 | オプション行 | 備考 |
|-----------------|----------|-----|--------|------------|------|
| 銘柄コード | code | str | あり | あり | |
| 銘柄名称 | name | str | あり | あり | |
| PUT/CAL | put_call | str / NaN | **NaN**（空欄） | "PUT" / "CAL" | |
| 限月 | expiry | str (YYYYMM) | あり | あり | |
| 権利行使価格 | strike | float / NaN | **NaN**（空欄） | あり | 整数だが NaN との共存で float |
| 清算価格 | settlement | float | あり | あり | オプション清算価格 or 先物清算値 |
| 理論価格 | theoretical | float / NaN | NaN | あり | |
| 原資産価格 | underlying | float | あり | あり | その日の現物終値 |
| ボラティリティ | iv | float / NaN | NaN | あり | **年率%表記**（例: 25.4）BS 逆算不要 |
| 金利 | rate | float / NaN | NaN | あり | BS 計算に使った金利（%）※参考値 |
| 残日数 | days_to_expiry | int / NaN | NaN | あり | カレンダー日数 |
| 原資産名称 | underlying_name | str | あり | あり | "日経225" / "TOPIX" 等 |

### フィルタ条件

```python
# 日経225 関連のみ保存（TOPIX, GOLD, JPX400 等は除外）
df = df[df["underlying_name"] == "日経225"]
```

---

## 2. 保存スキーマ: `data/history/jpx_derivatives.csv`

```
date,code,name,put_call,expiry,strike,settlement,theoretical,underlying,iv,rate,days_to_expiry
2026-07-31,NK225E202609038000P,日経225OP 26/09 38000プット,PUT,202609,38000.0,450.0,448.3,38250.0,24.1,0.1,40
2026-07-31,NK225E202609038000C,日経225OP 26/09 38000コール,CAL,202609,38000.0,512.0,510.7,38250.0,22.8,0.1,40
2026-07-31,NK225F202609,日経225先物 26/09,,202609,,38250.0,,,,,
```

### 列仕様

| 列名 | 型 | 主キー | NULL 可 | 備考 |
|------|----|--------|---------|------|
| date | TEXT (YYYY-MM-DD) | ✅ | No | 取引日 |
| code | TEXT | ✅ | No | 銘柄コード（元ファイルの一意 ID） |
| name | TEXT | | No | 銘柄名称 |
| put_call | TEXT | | Yes | "PUT" / "CAL" / NaN（先物） |
| expiry | TEXT (YYYYMM) | | No | 限月 |
| strike | REAL | | Yes | 権利行使価格。先物は NaN |
| settlement | REAL | | No | 清算価格 |
| theoretical | REAL | | Yes | 理論価格。先物は NaN |
| underlying | REAL | | No | 原資産価格（現物終値） |
| iv | REAL | | Yes | ボラティリティ年率%。先物は NaN |
| rate | REAL | | Yes | 金利%。先物は NaN |
| days_to_expiry | REAL | | Yes | 残日数。先物は NaN |

**主キー**: `(date, code)`  
※ code が銘柄コードとして日付以外の一意性を保証するため、複合主キーは `(date, code)` で十分。

**upsert 方針**: **last-write-wins**（同一主キーがあれば上書き）。  
訂正・再掲配信への対応。seed スクリプトも同一方針。

**保存時ソート**: `date, expiry, strike, put_call` 昇順。

---

## 3. `src/fetch/jpx_derivatives.py` の契約

```python
"""JPX 清算値段CSV（rbYYYYMMDD.csv）の取得・正規化・蓄積。

データ源: https://www.jpx.co.jp/markets/derivatives/settlement-price/index.html
  - 先物行（PUT/CAL 空欄）とオプション行（PUT/CAL が "PUT" / "CAL"）を同一ファイルに収録
  - IV・金利・残日数・理論価格を直接提供するため BS 逆算は不要
  - 対象絞込: 原資産名称 == "日経225"（TOPIX・GOLD・JN400 は除外）

URL 解決戦略:
  1. index.html を requests で取得（User-Agent 設定）
  2. BeautifulSoup で href が "rb" + 8桁数字 + ".csv" に一致するリンクを抽出
  3. 相対パスなら base URL を補完してフルURLを構成
  4. ファイルをダウンロードし cp932 でデコード
  ※ ハッシュディレクトリ（tvdivq00000014l6-att 等）が変わっても追従できる

パース仕様:
  - 先頭の "＊" 行（注記）をスキップし "銘柄コード" で始まる行をヘッダとして検出
  - 数値列は strip + pd.to_numeric(errors="coerce") で型変換
  - 空文字 / ゼロ埋め / 全角スペースは NaN に落とす

公開関数:
    fetch_derivatives(trade_date: pd.Timestamp | None = None) -> pd.DataFrame
        trade_date が None なら当日。
        戻り値: jpx_derivatives.csv のスキーマに準拠した DataFrame。
        失敗時: RuntimeError を raise（呼び出し元で except して縮退運転）。

    upsert_derivatives(df: pd.DataFrame) -> None
        data/history/jpx_derivatives.csv に last-write-wins upsert。
        df が空でも正常終了（ログ警告のみ）。

    load_derivatives_latest(path: Path | None = None) -> pd.DataFrame
        CSV の最終 date の行を返す。空 or ファイル不在は空 DataFrame。

縮退運転:
    fetch 失敗時は run_local.py が except して fetch_errors に追記。
    既存 CSV 最終行のデータで option_metrics を計算し、
    ダッシュボードに "オプションデータ取得失敗・前回値を表示" バナーを出す。

GitHub Actions (Ubuntu) 上の注意:
    - encoding="cp932" を明示（pandas デフォルトは UTF-8）。
    - User-Agent を設定（JPX は空 UA で 403 を返す場合がある）。
    - リトライ: 指数バックオフ（1→2→4秒、最大3回）。5xx はリトライ、4xx は即失敗。
    - requests の timeout=30 を明示。
"""
```

---

## 4. `src/compute/option_metrics.py` の契約

```python
"""オプション・先物データからの指標算出（副作用なしの純関数群）。

入力: jpx_derivatives.csv から読み込んだ DataFrame（最新日付分）
出力: チャート用 Series / DataFrame、サマリー用スカラー

単位の約束:
    iv は年率%表記（例: 25.4）で受け取り、そのまま返す。×100 や /100 は不要。
"""
```

### 公開関数一覧

| 関数 | シグネチャ | 戻り値 | 用途 |
|------|----------|--------|------|
| `filter_options` | `(df, expiry=None, put_call=None)` | DataFrame | 限月・P/C フィルタ |
| `filter_futures` | `(df, expiry=None)` | DataFrame | 先物行を抽出 |
| `nearest_expiry` | `(df)` | str (YYYYMM) | 出来高代替: 残日数が最短の限月 |
| `atm_iv` | `(df, expiry)` | float | ATM IV（Call/Put 平均）→ VRP 計算に使用 |
| `iv_skew_series` | `(df, expiry)` | DataFrame[moneyness, iv_put, iv_call] | スキューチャート用 |
| `iv_term_structure` | `(df)` | Series[expiry → atm_iv] | IV 期間構造チャート用 |
| `futures_term_structure` | `(df)` | Series[expiry → settlement] | 先物期間構造チャート用 |
| `flag_iv_outliers` | `(skew_df, threshold_iqr=3.0)` | Series[bool] | 異常値フラグ（後述） |

---

## 5. 可視化設計（確定版）

### チャート①: IV スキュー

**目的**: プット・コール別のIVを行使価格軸でプロット。スキュー（プットの割高）を視覚化。

**設計決定**: **Put/Call 2本色分け**（OTM ブレンド単曲線は採用しない）

> **根拠**: OTM ブレンドは "プットスキューが実在する" という市場の実態を隠蔽する。  
> Put IV（青実線）と Call IV（橙実線）を別個に表示することで、  
> ①スキューの傾きの非対称性、②Put-Call の乖離幅（パリティ崩れ）を直接読み取れる。  
> オプション売り戦略の観点では Put の割高水準が主要シグナルのため有用性が高い。

| 属性 | 仕様 |
|------|------|
| X 軸 | モネーネス = strike / underlying（1.0 が ATM） |
| Y 軸 | IV 年率%（jpx_derivatives.csv の iv 列をそのまま使用） |
| 対象限月 | 残日数最短の期近限月（`nearest_expiry()` で選択） |
| Put 系列 | 青実線（opacity=1.0） |
| Call 系列 | 橙実線（opacity=1.0） |
| 異常値 | `flag_iv_outliers()` でフラグ→ opacity=0.2 で淡色表示（除外しない） |
| ATM マーカー | X=1.0 に縦破線（グレー）＋ "ATM" ラベル |

**実装関数**: `_chart_skew(series: dict) -> str`

---

### チャート②: IV 期間構造

**目的**: 限月ごとの ATM IV を折れ線でプロット。短期/中期ボラ格差を確認。

**ATM IV 定義（確定）**: 各限月において `underlying` に最も近い `strike` の  
**Call IV と Put IV の平均値**を採用する。

> **根拠**: Put-Call パリティの理論上 ATM IV は Call/Put で同値だが、  
> 実際には需給・流動性で乖離する。平均を取ることで単側の歪みを中和し、  
> より安定した「市場のコンセンサス ATM IV」を表現できる。  
> 実装コメントにこの根拠を残すこと（`atm_iv()` 関数内）。

| 属性 | 仕様 |
|------|------|
| X 軸 | 限月（YYYYMM → "YY/MM" 表示） |
| Y 軸 | ATM IV 年率%（上記定義） |
| データ点 | マーカー付き折れ線 |
| 日経 VI 水平線 | 当日の日経 VI 値を水平破線で重ね合わせ。ラベル: "日経VI (NVI)" |
| 残日数注記 | 残日数が短い期近（残 ≤ 7 日）はマーカーに "⚠ 満期近接" ツールチップ |

**実装関数**: `_chart_iv_term(series: dict) -> str`

---

### チャート③: 先物期間構造

**目的**: 先物の限月別清算値をプロット。コンタンゴ/バックワーデーション確認。

| 属性 | 仕様 |
|------|------|
| X 軸 | 限月（"YY/MM" 表示） |
| Y 軸 | 清算価格（円） |
| データ点 | マーカー付き折れ線 |
| 現物終値水平線 | 対応する underlying 値を水平実線で追加。ラベル: "現物終値" |
| プレミアム表示 | 各点のツールチップに「先物 − 現物 = ±XXXXX 円」を含む |

**実装関数**: `_chart_futures_term(series: dict) -> str`

---

## 6. 異常値フィルタの設計（`flag_iv_outliers`）

流動性が低い建値（出来高 0 の建値など）により IV が近傍から大きく浮くケースが実在する（検証例: strike 64000 の Call IV が近傍から逸脱）。

**アルゴリズム**:

```python
def flag_iv_outliers(skew_df: pd.DataFrame, threshold_iqr: float = 3.0) -> pd.Series:
    """
    各 put_call ごとに IV の IQR を計算し、
    中央値 ± threshold_iqr × IQR を外れた点を True でフラグ。
    threshold_iqr のデフォルト 3.0 は保守的（極端な外れ値のみ捕捉）。
    """
```

**描画**: フラグが立った点は opacity=0.2 で描画。除外はしない（データは保持、視覚的に抑制）。  
**config に追加**: `IV_OUTLIER_IQR_THRESH = 3.0`（調整可能）

---

## 7. 縮退運転とフラグの全体像

```
jpx_derivatives 取得成功 → upsert → compute → 3 チャート描画（通常）
jpx_derivatives 取得失敗 → fetch_errors に追記 → 既存 CSV 最終行でフォールバック
                        → metrics["option_data_ok"] = False
                        → ダッシュボード orange バナー: "オプションデータ取得失敗・前回値を表示"
                        → 3 チャートは前回値で描画（日付ラベルに "前回値" を付記）

既存 CSV も不在 → option_metrics を全 NaN で返す → チャートを空で描画
```

**metrics 辞書に追加する項目**:

```python
metrics["atm_iv"]           = float            # ATM IV（期近・%）。NaN 可
metrics["vrp_option"]       = float            # オプション由来 VRP（参考値）。NaN 可
metrics["option_data_ok"]   = bool             # fetch 成否フラグ
metrics["option_data_date"] = str              # 使用した option データの基準日
```

---

## 8. `scripts/seed_jpx_derivatives.py` 設計

### 目的

JPX は約 2 か月で過去ファイルを削除するため、初回実装時に過去 60 営業日分のバックフィルが必要。  
以降は `run_local.py` が毎日 upsert するため seed は一度だけ実行する。

### 処理フロー

```
1. index.html を取得して rb*.csv のベース URL（ハッシュディレクトリ含む）を確定
2. 当日から遡って過去 LOOKBACK_DAYS 営業日のリストを生成（日本の祝日は pd.bdate_range で近似）
3. 各営業日ごとに {base_url}/rb{YYYYMMDD}.csv を試行
   - 200: ダウンロード → パース → DataFrame 化
   - 404: "当日ファイルなし（休場日等）" として skip
   - 5xx: 指数バックオフで最大 3 回リトライ後 skip
4. 全日分を concat して jpx_derivatives.csv に upsert（last-write-wins）
5. 取得成功日数・失敗日数をサマリーとして出力
```

### CLI インターフェース

```
python scripts/seed_jpx_derivatives.py [--lookback DAYS] [--dry-run]
  --lookback DAYS  : 遡り営業日数（デフォルト 60）
  --dry-run        : CSV 書き込みを行わず取得内容のみを stdout に表示
```

### 公開関数（seed スクリプト内部）

| 関数 | 役割 |
|------|------|
| `resolve_base_url()` | index.html をパースして rb*.csv のディレクトリ URL を返す |
| `download_rb(base_url, trade_date)` | 1 日分の rb ファイルをダウンロード・パースして DataFrame を返す |
| `seed_range(lookback_days, dry_run)` | 上記をまとめて走査・upsert |

### 注意点

- `pd.bdate_range` は日本の祝日を考慮しないため、**祝日は 404 として自動 skip** される設計で問題ない。
- 既に CSV に存在する日付は last-write-wins で上書きされる（重複実行安全）。
- 初回実行時間の目安: 60 日 × 1 ファイル ≈ 60 リクエスト、リトライなしで数分。

---

## 9. `src/config.py` に追加する定数（案）

```python
# --- JPX デリバティブデータ設定 ---
JPX_DERIVATIVES_CSV        = HISTORY / "jpx_derivatives.csv"
JPX_SETTLEMENT_INDEX_URL   = "https://www.jpx.co.jp/markets/derivatives/settlement-price/index.html"
JPX_TARGET_UNDERLYING      = "日経225"        # フィルタ対象の原資産名称
JPX_OPTION_PUT_CALL_VALUES = ("PUT", "CAL")   # CSV の値そのまま

# ATM IV 計算
ATM_MONEYNESS_BAND = 0.02   # ±2% 以内の strike を ATM 候補とみなす

# IV 異常値フィルタ
IV_OUTLIER_IQR_THRESH = 3.0  # IQR の何倍を外れ値とするか（保守的）

# BS 近似パラメータ（現フェーズでは逆算を行わないが定数として持つ）
BS_RISK_FREE_RATE  = 0.001   # 無リスク金利（年率小数）※ CSV の rate 列で代替
BS_DIVIDEND_YIELD  = 0.020   # 配当利回り（年率小数）近似値

# シード設定
SEED_LOOKBACK_BDAYS = 60     # seed 時の遡り営業日数
```

---

## 10. 既存モジュールとの接続点

### `run_local.py` への追加（fetch フェーズ）

```python
# 追加: JPX デリバティブデータ
try:
    from src.fetch.jpx_derivatives import fetch_derivatives, upsert_derivatives
    deriv_df = fetch_derivatives()
    upsert_derivatives(deriv_df)
    logger.info("JPX derivatives: %d 行取得", len(deriv_df))
except Exception as exc:
    fetch_errors.append(f"JPX derivatives 取得失敗: {exc}")
    logger.warning("%s → 前回 CSV で縮退運転", fetch_errors[-1])
```

### `run_local.py` への追加（compute フェーズ）

```python
from src.fetch.jpx_derivatives import load_derivatives_latest
from src.compute.option_metrics import (
    filter_options, filter_futures, nearest_expiry,
    atm_iv, iv_skew_series, iv_term_structure, futures_term_structure,
)

deriv_latest = load_derivatives_latest(config.JPX_DERIVATIVES_CSV)
option_data_ok = not deriv_latest.empty

if option_data_ok:
    exp = nearest_expiry(deriv_latest)
    atm_iv_val = atm_iv(deriv_latest, exp)
    skew_df    = iv_skew_series(deriv_latest, exp)
    iv_term    = iv_term_structure(deriv_latest)
    fut_term   = futures_term_structure(deriv_latest)
else:
    atm_iv_val = float("nan")
    skew_df = iv_term = fut_term = (空のデータ構造)

metrics["atm_iv"]         = atm_iv_val
metrics["vrp_option"]     = iv_metrics.vrp_proxy(atm_iv_val, hv_primary)
metrics["option_data_ok"] = option_data_ok
metrics["option_data_date"] = str(deriv_latest.iloc[0]["date"]) if option_data_ok else "N/A"

series["iv_skew"]      = skew_df
series["iv_term"]      = iv_term
series["futures_term"] = fut_term
```

### `iv_metrics.py` との関係

- **既存の VI ベース VRP は現フェーズで維持**（日経 VI カードはそのまま）
- `metrics["vrp_option"]` を追加カードとして**並列表示**（切り替えではなく隣に置く）
- 将来フェーズで VI → ATM IV への切り替えを検討するが、今回は手をつけない

---

## 11. テスト方針

| ファイル | 内容 |
|---------|------|
| `tests/test_fetch_jpx.py` | ① `_parse_rb_csv()` にモック CSV 文字列を渡してスキーマを検証<br>② upsert の重複排除（last-write-wins）<br>③ 注記行スキップのパース<br>④ 異常 encoding の graceful 処理<br>⑤ 原資産フィルタ（日経225 以外が除外されること） |
| `tests/test_option_metrics.py` | ① `atm_iv()` が NaN のない値を返すこと<br>② `iv_skew_series()` の moneyness 列が単調増加<br>③ `flag_iv_outliers()` が既知スパイクを捕捉<br>④ `futures_term_structure()` が先物行のみ返すこと |
| `tests/test_build_html.py` | `Plotly.newPlot` カウントを `>= 4` から `>= 7` に更新（新チャート 3 種追加） |

**全テストはネットワーク禁止**（合成 CSV 文字列を io.StringIO で渡す方式）。

---

## 12. リスク・制約・ダッシュボードへの注記

### 12-a. デルタ非存在による近似誤差

JPX 無料 CSV にデルタは含まれない。スキューは行使価格モネーネスによる近似であり、**25Δ リスクリバーサル（25ΔRR）とは一致しない**。

**ダッシュボードへの注記**: 「スキュー値はデルタ非保有のため行使価格モネーネス近似。25ΔRRとは異なります。閾値はすべて例示。」

### 12-b. 流動性起因の IV 異常値

出来高のない建値は IV が近傍から大きく乖離する（例: 超遠ストライクの Call）。  
→ `flag_iv_outliers()` で捕捉し、淡色表示で対処。  
**ダッシュボードへの注記**: 「低流動性建値の IV は参考値（淡色表示）。実取引は流動性を確認してください。」

### 12-c. 満期近接効果

残日数 7 日以内の期近は満期効果（ガンマ・ベガ急変）で IV が不安定になりうる。  
→ 期間構造チャートで該当点に警告マーカーを付与。  
**ダッシュボードへの注記**: 「期近の残存日数が短い場合、IV は不安定になります（満期効果）。」

### 12-d. VRP（オプション由来）の誤差源

`vrp_option = atm_iv - hv_primary` では、ATM IV の定義（moneyness band、Call/Put 平均）や HV の推定量の選択で数ポイントの誤差が生じる。  
**ダッシュボードへの注記**: 「VRP（オプション由来）は ATM IV と HV20 の差分の近似値。投資助言ではありません（例示）。」

---

## 13. 実装ステップ（フェーズ4 作業順序）

| ステップ | 内容 | 依存 | 備考 |
|---------|------|------|------|
| **4-0** | URL 確定: index.html を fetch して rb*.csv リンクの抽出をテスト | なし | 実装前に確認 |
| **4-1** | `src/fetch/jpx_derivatives.py` 実装 + `tests/test_fetch_jpx.py` | 4-0 | |
| **4-2** | `scripts/seed_jpx_derivatives.py` を実行して 60 日分バックフィル | 4-1 | 一度だけ実行 |
| **4-3** | `src/compute/option_metrics.py` 実装 + `tests/test_option_metrics.py` | 4-1 | |
| **4-4** | `src/config.py` に新定数追加 | 4-1〜4-3 | |
| **4-5** | `run_local.py` に fetch/compute を追加（縮退運転含む） | 4-1〜4-4 | |
| **4-6** | `build_html.py` に 3 チャート追加 + テンプレート修正 | 4-3〜4-5 | |
| **4-7** | ローカル動作確認（`python run_local.py` → index.html レビュー） | 4-6 | |
| **4-8** | pytest 全通過確認 → commit → push | 4-7 | |

---

## 14. 確定済み設計決定（2026-08-02 承認）

### チャート配置：サマリー＋セクション分割（タブ不使用）

- **最上部**: サマリーカード群（既存5枚 + ATM IV 新規追加）
- **ナビゲーション**: アンカーリンクボタン（横スクロール対応）を直下に配置
- **チャートセクション**: ネイティブ `<details open>` で折りたたみ可能に区分
  - `#vol` ボラティリティ推移（既存4チャート）
  - `#skew` IV スキュー（新規1チャート）
  - `#term` 期間構造（新規2チャート）
- **禁則**: タブ UI 不使用。JS 無効でも全チャートを表示できるプログレッシブエンハンスメントを維持。

### 異常値フィルタ

- アルゴリズム: ローリング窓（window=5, center=True）の中央値から ±`IV_OUTLIER_PCT_THRESH` 以上乖離した点を淡色化
- 初期閾値: `IV_OUTLIER_PCT_THRESH = 0.30`（±30%）
- 除外はしない（opacity=0.2 で視覚的に抑制するのみ）
- `src/config.py` で調整可能

### バックフィル方針

- seed 実行時に過去 `SEED_LOOKBACK_BDAYS` 営業日を試行し、取得できた分を upsert
- JPX の約2ヶ月ロールオフで取得不能な日は欠損として許容
- seed は初回のみ実行。以降は `run_local.py` が毎日 upsert

### その他承認事項

- 主キー: `(date, code)` ✅
- IV スキュー: Put/Call **2本色分け** ✅
- 異常値: **淡色表示（除外しない）** ✅
- ATM IV カード: 既存 VRP カードと**並列表示** ✅
- URL 確定 (4-0) は実装者が index.html 動的抽出で対応 ✅
