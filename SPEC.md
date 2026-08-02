# 日経225オプション売り 監視ダッシュボード 計算モデル＆データ取得仕様書

> 目的：前章で定義した監視パラメータを実装するための、(A) 計算モデル（複数手法併記）、(B) データ取得手段（コスト・精度・遅延・時間制約）をまとめる。
> 注意：本書は技術仕様であり投資助言ではない。閾値・パラメータは自身でバックテスト較正すること。

---

## 0. 計算の共通基盤：Black‑76（先物ベース）

日経225オプションは**ヨーロピアン型**（早期行使なし）。指数の配当・金利推定に伴う誤差を避けるため、**同一限月の日経225先物価格 F を原資産に使う Black‑76 が実務標準**。

```
C = e^(-rT) [ F·N(d1) − K·N(d2) ]
P = e^(-rT) [ K·N(-d2) − F·N(-d1) ]
d1 = [ ln(F/K) + (σ²/2)T ] / (σ√T)
d2 = d1 − σ√T
```
- F：同一SQの日経225先物価格（現物Sではなく先物を使うのが要点）
- T：残存年数（暦日/365 または営業日/245等。VIとの整合を取るなら暦日ベース）
- r：無зリスク金利（短期国債・OIS。日本は低水準で影響小）
- N：標準正規累積分布、φ：標準正規密度

---

## 1. IV（インプライド・ボラティリティ）＝価格→σ の逆算

| 手法 | 特徴 | 弱点 |
|---|---|---|
| Newton‑Raphson | `σ_{n+1}=σ_n −(BS(σ_n)−P_mkt)/Vega(σ_n)`。数回で収束、高速 | 深いOTMでVega→0となり発散 |
| Bisection / Brent | 区間探索。頑健で必ず収束 | やや遅い |
| **ハイブリッド（推奨）** | NRで試行→失敗時Brentに切替 | — |

- 初期値：Brenner‑Subrahmanyam近似 `σ0 ≈ √(2π/T)·(P/F)`
- **入力データ**：オプション価格（bid‑askの**中間値**を使う）、F、K、T、r
- **精度上の制約**：流動性の低い深OTMはスプレッドが広くIVが不安定。約定薄い銘柄は気配のズレがIVを歪める。

---

## 2. 日経VI（30日先モデルフリー・ボラティリティ）

3つの取得/算出アプローチ：

| 手法 | 内容 | データ要件 | 精度 |
|---|---|---|---|
| (a) 公式値を利用（推奨・最簡便） | 日経が算出・公表する日経平均VIをそのまま使用（15秒間隔） | 日経VI配信（下表） | 公式・高 |
| (b) 自前でVIX式分散を算出 | `σ² = (2e^(rT)/T)·Σ_i (ΔK_i/K_i²)·Q(K_i) − (1/T)(F/K0−1)²`。近2限月を満期30日に線形補間 | 全OTM気配・F・r | 自作、要検証 |
| (c) ATM IV代用 | J-Quants の ATMプット/コールIV中間値で近似 | J-Quants Standard | 簡便・VIとは別物 |

- (b)はCBOE/日経VI方式の中核式。個別IVを使わず**OTMオプション価格のポートフォリオ**として分散を復元する（前章のCarr–Madan分散スワップ複製に一致）。

---

## 3. HV（ヒストリカル/実現ボラティリティ）— 推定量は複数

年率化係数 A＝営業日換算（例 245〜252）。r_i = ln(C_i / C_{i-1})。

| 推定量 | 式（分散） | 利点 | 欠点 |
|---|---|---|---|
| Close‑to‑Close（標準） | `σ² = A/(n−1)·Σ(r_i − r̄)²` | 単純・広く比較可能 | 効率が低い（分散大） |
| Parkinson (1980) | `σ² = A/(4ln2·n)·Σ(ln(H_i/L_i))²` | 高安幅利用でC2Cの約5倍効率 | 窓（オーバーナイト）とジャンプを無視 |
| Garman‑Klass (1980) | OHLC利用 | さらに高効率 | 同上、ギャップ弱い |
| Rogers‑Satchell (1991) | OHLC、ドリフト非依存 | トレンド相場に頑健 | ギャップ非対応 |
| **Yang‑Zhang (2000)（日経推奨）** | オーバーナイト分散＋RS＋オープン分散の加重 | **夜間ギャップ＋ドリフト対応、最高効率** | 実装がやや複雑 |
| 高頻度RV | `RV = Σ r_{intraday}²`（5分足等） | 最も正確、日次で低ノイズ | 日中データ必須、マイクロ構造ノイズ処理要 |

- **日経は夜間（グローベックス/米国）ギャップが大きい**ため、C2CやParkinsonは過小/過大評価しやすい。Yang‑Zhangが妥当。
- 窓長 n：日経VIの30日と対応させるなら概ね **n=20〜21営業日**。
- **入力データ**：日経225の日足OHLC（無料多数）。高頻度RVは先物の分足/Tick（証券会社API）。

---

## 4. IV Rank / IV Percentile

```
IV Rank      = (IV_now − min_{252}) / (max_{252} − min_{252}) × 100
IV Percentile = #{ IV_t < IV_now : t ∈ 過去252 } / 252 × 100
```
- IV Rank はレンジ内の相対位置、IV Percentile は分布内の順位。**スパイクに引っ張られにくいのは Percentile**。
- **入力データ**：日経VI（またはATM IV）の過去252営業日時系列。J-Quants Standard か日経VIヒストリカルで構築。

---

## 5. VRP（分散リスクプレミアム）

| 手法 | 式 | 備考 |
|---|---|---|
| 厳密（分散ベース） | `VRP = IV² − E_t[RV²]`（期間を揃える） | E[RV]予測に HAR‑RV / GARCH を用いる |
| 簡易（ボラ単位） | `VRP ≈ 日経VI − HV20` | ダッシュボード表示向き |

- HAR‑RV：`RV_{t+1} = c + β_d·RV_t^{(日)} + β_w·RV_t^{(週)} + β_m·RV_t^{(月)}`（実現ボラ予測の実務標準）。
- **入力データ**：§4のIVと§3のHV。

---

## 6. 期間構造（ターム・ストラクチャー）

| 手法 | 指標 | データ |
|---|---|---|
| ATM IV スロープ | `TS = ATM_IV(期先) − ATM_IV(期近)`、または比 `IV2/IV1` | 各限月チェーンからATM IVを算出 |
| VI先物カーブ | 日経平均VI先物の期近/期先の気配差 | VI先物気配（証券会社） |

- `TS>0`＝コンタンゴ（平時、売り環境）、`TS<0`＝バックワーデーション（ストレス、売り回避）。

---

## 7. スキュー（25デルタ リスクリバーサル / バタフライ）

```
RR25 = IV(call, Δ=+0.25) − IV(put, Δ=−0.25)      （株価指数は通常マイナス＝プット高）
BF25 = [ IV(call25) + IV(put25) ] / 2 − IV(ATM)   （テールの盛り上がり）
```
算出手順：
1. 各ストライクKでσ（§1）を求める
2. 各(K,σ)からΔ（§8）を計算
3. Δ=±0.25となるKを**補間探索**
4. そのKのσを読む（SVIやスプライン等でサーフェスを平滑化すると安定）

- **入力データ**：フルチェーンのσ、F、r。

---

## 8. グリークス（解析式）＋ポートフォリオ集計

BSスポット版（配当利回りq、スポットS）。Black‑76版はSをFに置換しe^(-rT)で調整。

```
Δcall = e^(-qT)·N(d1)             Δput = −e^(-qT)·N(−d1)
Γ     = e^(-qT)·φ(d1) / (S·σ·√T)
Vega  = S·e^(-qT)·φ(d1)·√T        （1.00=100vol pt。1vol pt当たりは /100）
Θ, ρ  も解析式あり（必要に応じ）
ドルガンマ = Γ·S²·乗数             （ガンマ危険度の実感指標）
```
ポートフォリオ集計：
```
net_X = Σ_j ( 数量_j × X_j × 乗数 )     X ∈ {Δ,Γ,Vega,Θ}
数量：売り = −、買い = +   乗数：日経225OP=1000、ミニOP=100
```
- **注意**：単純BSグリークスは σ一定（sticky‑strike）前提でIV変化を無視する。スキューを織り込むなら **Minimum‑Variance Delta**（Δ_MV = Δ_BS + Vega·∂σ/∂S）で調整すると、実現デルタに近づく。
- **入力データ**：各建玉のσ（§1）、S/F、K、T、r。

---

## 9. 各ショートΔ

§8の出力のうち、**売り建てストライクのΔ**を個別に監視（損益分岐点への接近度・アサインメント確率の代理）。閾値運用（例：|Δ|>0.30で防御）に直結。

---

## 10. 証拠金使用率

- **現行方式（2023/11/6〜）**：JSCC **HS‑VaR方式**。過去5年（1250日）のヒストリカルシナリオ＋ストレスシナリオで、損失上位2.5%平均（≒97.5%期待ショートフォール、正規近似で99%相当）をカバー。**売り/買い・限月で非対称、日次変動、反景気循環調整あり**。
- 証券会社の所要額式（例）：
```
証拠金所要額 = (VaR証拠金額 × 証券会社の掛目) − ネット・オプション価値総額
             + 先物両建て証拠金 + オプション保有枚数割増
```
- **自前完全再現は困難**（JSCCのシナリオ集合・調整ロジックが必要）。実務的取得手段：
  - (a) **証券会社のリアルタイム所要証拠金・有効証拠金**（最も正確・即時）
  - (b) **JSCC Web試算環境（OpenGamma提供）**：任意ポジションの前営業日ベース試算、当日分は17:30頃更新
```
証拠金使用率 = 建玉所要証拠金 / 有効証拠金(預託金 ± 評価損益)
閾値例：50%超で新規停止・減量、70〜80%で強制ロスカット接近
```

---

## 11. 直近ピークからのVI変化（レジーム判定）

| 手法 | 式 |
|---|---|
| ピークアウト検出 | `ΔVI = VI_now / max(VI, 過去k日) − 1`（0近傍＝高止まり、負に転じる＝低下開始） |
| モメンタム | `VI_now / VI_prev − 1`、5日移動平均の傾き |
| レジーム | VI>MA かつ 上昇＝ストレス継続（**売り回避**）／ VI<MA かつ 低下＝平常回帰（**売り検討**） |

- **入力データ**：日経VI時系列。

---

## データ取得マトリクス（コスト・精度・遅延・時間制約）

| ソース | 種別 | 取得データ | 遅延/更新 | コスト | 精度 | 用途 |
|---|---|---|---|---|---|---|
| **J‑Quants API Standard** | EOD REST | 日経225OP四本値・清算値・理論価格・**ATM IV中間値**（10年） | EOD（夕方更新） | 月3,300円 | 取引所公式・高 | 履歴・IVR/HV/バックテスト |
| **J‑Quants API Premium** | EOD REST | ＋先物/全オプション四本値（全期間2008〜）・前場後場 | EOD | 月16,500円 | 公式・高 | 長期検証・フルチェーン履歴 |
| J‑Quants Free | EOD REST | 同上だが**12週間遅延**・5req/分 | 12週遅延 | 無料 | 公式だが陳腐化 | 学習・試作のみ |
| **楽天 マケスピII RSS** | 準リアルタイム(Excel) | 国内先物・OP気配/約定/建玉/余力。Greeksは自前計算 | リアルタイム（**一部指数は10〜20分遅延**） | 口座あれば無料 | 業者フィード | 実運用の即時監視・自動化 |
| auカブコム(三菱UFJ eスマート) kabuステーションAPI | リアルタイム REST/push | 先物OP時価・発注 | リアルタイム | 条件付き無料 ※要確認 | 業者フィード | プログラム連携 |
| Interactive Brokers TWS/Web API | リアルタイム | OSE日経OP、Greeks配信 | リアルタイム | OSE市場データ 月数ドル＋口座 | 業者フィード | プログラム・海外併用 |
| 日経VI（nikkei.com / Investing.com） | 指数値 | 日経平均VI | 公式15秒／無料webは約20分遅延 | 無料（遅延） | 日経公式 | VI水準・レジーム |
| Bloomberg / LSEG(Refinitiv) | プロ端末 | フルサーフェス・Greeks・履歴 | リアルタイム | 月 数万〜数十万円 | 最高 | 非現実的（個人） |
| Yahoo!ファイナンス / Stooq | EOD | 日経225現物OHLC | EOD | 無料 | 概ね可 | HV算出の原資産OHLC |

---

## 推奨構成（予算別）

- **最小（¥0〜）**：J‑Quants Free/Standard ＋ 日経VI遅延web ＋ 無料OHLC → **EODダッシュボード**。リアルタイム性なし、検証・学習用。
- **実運用（月3,300円＋口座）**：J‑Quants Standard（履歴・IVR構築）＋ 楽天RSS or kabuステーションAPI（リアルタイム気配・自前Greeks・証拠金） → **準リアルタイム**。最もコスパが高い個人向け構成。
- **高度**：IB API（リアルタイムGreeks・海外資産併用）、またはプロベンダー（高額）。

---

## 実装上の注意（精度・時間制約）

1. **価格は必ず中間値**（bid‑ask mid）。約定値/清算値はタイミングがズレIVを歪める。
2. **先物Fと同一SQを厳密対応**させる（限月ミスマッチはIV・Greeksを破壊）。
3. **残存Tの規約**（暦日/営業日、SQ当日の扱い）を全計算で統一。
4. **深OTMのIVは信頼度が低い**。RR/BFやVI(b)算出時は流動性フィルタ（建玉・出来高・スプレッド幅）をかける。
5. **サーフェスは平滑化**（SVI/スプライン）してからΔ探索・スキュー算出すると安定。
6. **リアルタイム性の限界**：RSSの一部指数は10〜20分遅延。VI水準トリガーはこの遅延を前提に設計。
7. **証拠金は業者値が最終**。自前VaRはあくまで概算・事前見積り用。

---

## 主要情報源

- J‑Quants API 日経225オプション四本値仕様（ATM IV含む） https://jpx.gitbook.io/j-quants-ja/api-reference/index_option
- J‑Quants プラン別データ期間・料金 https://jpx.gitbook.io/j-quants-ja/outline/data-spec ／ 料金（東証マネ部！） https://money-bu-jpx.com/news/article047172/
- 楽天証券 マーケットスピードII RSS（更新頻度・対象商品） https://marketspeed.jp/ms2_rss/
- JSCC 新証拠金計算方式（VaR方式）とWeb試算環境 https://www.jpx.co.jp/jscc/seisan/sakimono/shokokin_seido/VaR.html ／ 概要（フィリップ証券） https://www.phillip.co.jp/information/info/9143
- 日経平均VI 算出要領・現況 https://indexes.nikkei.co.jp/nkave/index/profile?idx=nk225vi
- 推定量原典：Parkinson(1980), Garman‑Klass(1980), Rogers‑Satchell(1991), Yang‑Zhang(2000)／HAR‑RV: Corsi(2009)／分散スワップ複製: Carr‑Madan(1998)

*本書は計算モデルとデータ取得手段の技術調査であり、投資助言ではありません。数値・閾値は例示で、実運用前に自身で検証してください。*

---

## 実装仕様（Implementation Reference）

本セクションは、上記の理論モデルを実装したコードベースの仕様を記述する。

### パイプライン概要

```
GitHub Actions（平日 21:00 JST ≈ 12:00 UTC）
  ↓ fetch
    src/fetch/nikkei_ohlc.py       日経225現物 OHLC（yfinance ^N225 / Stooq ^nkx フォールバック）
    src/fetch/nikkei_vi.py         日経VI当日値（nikkei.com / investing.com スクレイプ）
    src/fetch/jpx_derivatives.py   JPX清算値段CSV（オプション・先物・無料・当日公開分）
  ↓ upsert → data/history/*.csv（日次蓄積）
  ↓ compute
    src/compute/realized_vol.py    HV 5推定量（Yang-Zhang主）
    src/compute/iv_metrics.py      IV Rank / Percentile / VRP
    src/compute/regime.py          レジーム判定
    src/compute/option_metrics.py  ATM IV / スキュー / 期間構造 / スロープ（純関数）
  ↓ report
    src/report/build_html.py       Plotly チャート埋め込み・静的HTML生成
    src/report/templates/dashboard.html.j2
  ↓ docs/index.html 生成
  ↓ git commit "chore: nightly update [skip ci]" → push → GitHub Pages 自動更新
```

### ディレクトリ構成

```
nikkei-vol-dashboard/
├── src/
│   ├── config.py               閾値・窓・パス一元管理（数値変更はここだけ）
│   ├── compute/
│   │   ├── option_metrics.py   IV スキュー・期間構造・スロープ（純関数）
│   │   ├── iv_metrics.py       IV Rank / Percentile / VRP
│   │   ├── realized_vol.py     HV 5推定量
│   │   └── regime.py           レジーム判定
│   ├── fetch/
│   │   ├── jpx_derivatives.py  JPX 清算値段CSV 取得・蓄積
│   │   ├── nikkei_ohlc.py      日経225 OHLC 取得
│   │   └── nikkei_vi.py        日経VI 取得
│   └── report/
│       ├── build_html.py       Plotly チャート + HTML 生成
│       └── templates/
│           └── dashboard.html.j2  Jinja2 テンプレート
├── data/history/
│   ├── nikkei_vi.csv           date,vi（日次蓄積）
│   ├── nikkei_ohlc.csv         date,open,high,low,close（日次蓄積）
│   └── jpx_derivatives.csv     JPX 清算値段（1行1銘柄・日次蓄積）
├── docs/
│   └── index.html              GitHub Pages 公開HTML（自動生成）
├── tests/                      pytest（compute のみ・ネットワーク禁止）
├── run_local.py                パイプライン統合エントリポイント
├── .github/workflows/
│   └── nightly.yml             夜間バッチ定義
└── scripts/
    └── seed_jpx_derivatives.py 過去データ手動シード（初回のみ）
```

### データソース（現行使用）

| データ | ソース | 更新タイミング | 蓄積先 |
|--------|--------|--------------|--------|
| 日経225現物 OHLC | yfinance (^N225) / Stooq (^nkx) | EOD | nikkei_ohlc.csv |
| 日経平均VI | nikkei.com / investing.com | EOD（夜間更新後） | nikkei_vi.csv |
| オプション・先物清算値段 | JPX 公開CSV（無料・当日分のみ） | EOD（夜間） | jpx_derivatives.csv |

### CSV スキーマ

**nikkei_vi.csv**
```
date    … YYYY-MM-DD（インデックス）
vi      … 日経平均VI 終値（例: 24.1）
```

**nikkei_ohlc.csv**
```
date                      … YYYY-MM-DD（インデックス）
open, high, low, close    … 日経225現物（円）
```

**jpx_derivatives.csv（1行1銘柄）**
```
date           … YYYY-MM-DD
code           … 銘柄コード（例: NK225E202609038000P）
name           … 銘柄名
put_call       … "PUT" / "CAL"（先物行は NaN）
expiry         … 限月コード: 月次=YYYYMM(6桁) / Weekly=YYYYMMDD(8桁)
strike         … 行使価格（円）。先物は NaN
settlement     … 清算値段
theoretical    … 理論価格
underlying     … 原資産価格（現物終値）
iv             … IV（%年率、例: 22.5）
rate           … 無リスク金利（%）
days_to_expiry … 残存日数（営業日）
```

upsert: `date + code` を複合キーとして `drop_duplicates(keep="last")`。再実行しても重複しない。

### 計算パラメータ（config.py 主要値）

| パラメータ | 値 | 意味 |
|-----------|-----|------|
| ANNUALIZATION | 245 | 年率換算係数（年間営業日数） |
| HV_WINDOW | 20 | HV 計算窓（営業日） |
| IV_HISTORY_WINDOW | 252 | IV Rank/Percentile 参照期間（営業日） |
| VI_MA_WINDOW | 20 | レジーム判定 MA 窓 |
| IV_OUTLIER_PCT_THRESH | 0.30 | IV 異常値フラグ閾値（±30%超で淡色表示） |

### ATM IV 実装

- ATM = `|strike / underlying − 1|` が最小の strike
- そのストライクの CAL と PUT の IV の平均（片方のみの場合はその値）
- IV 期間構造・スロープは **月次スタンダード限月（6桁 YYYYMM）のみ**対象
- IV スロープ = `front_ATM_IV − far_ATM_IV`（far = DTE が 90 日に最も近い限月）
  - 正 = バックワーデーション（期近 IV 高・目先緊張）
  - 負 = コンタンゴ（期近 IV 低・平時型）

### 縮退運転の動作仕様

| 失敗対象 | 動作 | 画面表示 |
|---------|------|---------|
| OHLC 取得失敗 | 既存 CSV で継続計算 | 「更新失敗」バナー（橙）+ エラー詳細 |
| VI 取得失敗 | 既存 CSV で継続計算 | 同上 |
| JPX derivatives 取得失敗 | 既存 CSV で継続計算 | `option_fetched_today=False` を表示 |
| jpx_derivatives.csv 未存在 | `option_data_ok=False` | オプション系カード・チャートが「データなし」 |
| OHLC CSV 未存在 | `main()` が 1 を返して終了 | GitHub Actions 赤ステータス |

### 夜間バッチ仕様（nightly.yml）

- スケジュール: 毎平日 12:00 UTC（= JST 21:00）、高負荷時 ±30 分ずれあり
- 手動実行: `workflow_dispatch` で任意実行可
- 権限: `contents: write`（history CSV と docs/ をコミット）
- コミットメッセージ: `"chore: nightly update [skip ci]"`（CI 再帰防止）
- 変更なしの場合: `git diff --cached --quiet` で検出してコミットスキップ

### 限月の扱いと既知の制約

| 事項 | 内容 |
|-----|------|
| 月次スタンダード限月 | expiry が 6 桁（YYYYMM）。IV 期間構造・スロープはこれのみ使用 |
| Weekly オプション | expiry が 8 桁（YYYYMMDD）。DTE が月次より小さいため `nearest_expiry()` が Weekly を返す場合がある（IV スキューチャートに影響） |
| IV 異常値 | 深 OTM・流動性極薄のストライクは IV が不安定。outlier フラグで淡色表示するが計算には含む |
| JPX CSV 保存期間 | JPX は約 2 か月分のみ公開。初回は `scripts/seed_jpx_derivatives.py` でシード |

*実装仕様セクションは投資助言ではありません。閾値・パラメータは例示です。*
