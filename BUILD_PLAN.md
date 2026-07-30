# 制作計画（Claude Code / VS Code）

前提（確定済）: OS=Windows / ダッシュボードは相場データのみ・公開ホスティングOK / Git不慣れ。
方針: **無料データで試作 → 有料/RSSへ拡張**。夜間バッチ（クラウド）で当日分を集計し、
静的HTMLを GitHub Pages 公開 → iPhone で閲覧。

各フェーズに「あなたがやること」と「Claude Code に貼るプロンプト」を用意した。プロンプトは
そのままコピペしてよい。困ったら Claude Code に「このステップの意味を説明して」と聞く。

---

## フェーズ0：環境構築（Windows）— 30〜60分

あなたがやること（PowerShell を管理者で開いて順に）:
1. Git: https://git-scm.com/download/win からインストール（既定でOK）。確認 `git --version`
2. Python 3.12: https://www.python.org/downloads/ 。インストール時に **"Add python.exe to PATH" にチェック**。確認 `python --version`
3. VS Code: https://code.visualstudio.com/ 。拡張機能「Python」を入れる。
4. GitHub CLI（後でリポジトリ作成に使う）: `winget install GitHub.cli` 。確認 `gh --version`
5. Claude Code（ネイティブinstaller・Node不要／推奨）:
   ```powershell
   irm https://claude.ai/install.ps1 | iex
   ```
   確認 `claude --version`。npm派なら Node.js 18+ を入れて `npm install -g @anthropic-ai/claude-code` でも可。
   ※Claude Code の利用には Claude の有料プラン（Pro/Max等）または API クレジットが必要。
6. GitHub にログイン: `gh auth login`（ブラウザ認証。Git の認証もこれで通る）。

> Git が不慣れなら、GUIの「GitHub Desktop」(https://desktop.github.com/) も入れておくと、
> 変更履歴やコミットが目で見えて安心。コミット/プッシュはボタンで押せる。

---

## フェーズ1：リポジトリ作成と Git 連携 — 15分

この雛形フォルダ `nikkei-vol-dashboard/` を VS Code で開く（File > Open Folder）。
統合ターミナル（Ctrl+`）で以下。**意味はコメントの通り**。

```powershell
git init                              # このフォルダをGit管理下に
git add .                             # 全ファイルをステージ（コミット候補に）
git commit -m "init: 雛形"            # 最初のスナップショットを記録
gh repo create nikkei-vol-dashboard --public --source=. --push
#   ↑ GitHub上に公開リポジトリを作り、今の内容をアップロード
```

GitHub Pages を有効化（ブラウザで1回だけ）:
- リポジトリ > **Settings > Pages** > Source を「Deploy from a branch」
- Branch=`main` / フォルダ=`/docs` を選び Save。数分で `https://<ユーザー名>.github.io/nikkei-vol-dashboard/` が生える。

> まだ `docs/index.html` が無いので最初は404でOK。フェーズ2で生成される。

Claude Code に貼るプロンプト（Gitの使い方を自分仕様で覚えさせる）:
```
このリポジトリのCLAUDE.mdを読んで。私はGitに不慣れなので、今後あなたが
変更のたびに (1)pytestを実行 (2)日本語で意味の分かるコミットメッセージを付けて
コミット (3)pushまで代行して。破壊的な操作の前は必ず日本語で理由を説明して確認を取って。
```

---

## フェーズ2：無料試作の実装（当日の相場を集計）— Claude Code主体

`realized_vol.py` / `iv_metrics.py` / `regime.py` / `config.py` は実装済み。
残り（データ取得・レポート生成・統合）を Claude Code に作らせる。**1タスクずつ**貼る。

### 2-1 データ取得
```
src/fetch/nikkei_ohlc.py と src/fetch/nikkei_vi.py の契約(docstring)を満たす実装をして。
OHLCはyfinanceの^N225を一次、Stooqの^nkxをフォールバックに。日経VIは無料の公開ページから
当日終値をスクレイプ（複数ソースをtry/exceptで多重化）。どちらもdata/history配下のCSVに
重複排除でupsert。ネット失敗時は例外を投げる。取得できたことを確認する小さなスクリプトも作って。
```

### 2-2 日経VI履歴のシード（IV Rankに過去1年が必要）
```
IV Rank/Percentileには過去252営業日の日経VIが要る。私が投資情報サイトから日経VIの
1年分の履歴CSVを手で用意する。その想定フォーマットを提示し、data/history/nikkei_vi.csv へ
取り込むワンショットのスクリプトを書いて（列: date, vi）。
```
（あなた: 投資サイトで日経VIの過去1年をCSVダウンロードし、指示に従って置く）

### 2-3 集計パイプライン
```
run_local.py のTODOを実装して。history読み込み→realized_vol.all_latest、
iv_metrics(IV Rank/Percentile)、vrp_proxy、regime一式を計算し、metrics/series辞書に
まとめてbuild_html.buildへ渡す。取得失敗時は前回CSVで縮退運転し、失敗フラグを立てて。
```

### 2-4 ダッシュボードHTML（iPhone最適化）
```
src/report/build_html.py と templates/dashboard.html.j2 を実装して。jinja2+plotlyで
docs/index.htmlを単一HTML生成。最上部にサマリーカード（日経VI/IVパーセンタイル/HV20(YZ)/
VRP/レジーム）。下にチャート4種（VI+移動平均、HV各推定量、VRP推移、VIピークからの位置）。
regimeがSTRESSなら赤バナーで「新規売り回避（例示）」。viewport meta付き・レスポンシブ・
数値は大きめ。iPhoneのSafariで崩れないこと。最後にpytestを通してコミットして。
```

### 2-5 ローカル確認
```
python run_local.py を実行してdocs/index.htmlを開き、内容の妥当性をレビューして。
おかしい数値があれば原因を特定して直して。
```

DoD（フェーズ2完了条件）: `pytest`緑 / `docs/index.html`生成 / iPhoneでレイアウトOK。

---

## フェーズ3：夜間自動化 & iPhone確認 — 10分

`.github/workflows/nightly.yml` は同梱済み（21:00 JST=12:00 UTC 平日 + 手動実行）。

```
nightly.ymlの想定通り、run_local.pyがCI環境（ネットワークあり・表示なし）でも動くか確認して。
matplotlib等のGUI依存があればhead lessに直して。問題なければpushして、
GitHub ActionsのタブでworkflowをdispatchしてPagesが更新されるところまで見届けて。
```

あなた: Actions タブ > nightly-dashboard > Run workflow（手動実行）→ 数分後 Pages URL を
iPhone Safari で開く → **共有ボタン >「ホーム画面に追加」** でアプリ風アイコンにする。

---

## フェーズ4：有料/RSS拡張（オプション個別＝スキュー・期間構造）

無料フェーズは指数レベル（VI/IVR/HV/VRP/レジーム）。オプション個別が要るなら二択:

- **A. J-Quants Standard（¥3,300/月・クラウド継続向き）**
  ```
  src/fetch/jquants_option.py を追加。J-Quants v2 APIで日経225オプション四本値と
  ATM IVを取得（鍵はGitHub Secretsから読む）。ATM IVの期近/期先で期間構造、
  各strikeのIVから25Δリスクリバーサル/バタフライを算出し、compute層に足して
  ダッシュボードにスキュー・期間構造カードを追加して。SPEC.mdの式に従うこと。
  ```
  ※更新タイミング（当日夜に当日分が来るか、翌日か）は要確認。翌日なら surface は T-1 表示になる。

- **B. 楽天マーケットスピードII RSS（Windows/Excel・当日・追加課金なし）**
  - RSSはExcel常駐のためクラウド不可 → 手元PCで夜間実行する経路になる。
  ```
  Windowsの手元PCで、マーケットスピードII RSSのExcelブックから日経225オプションの
  チェーン(気配/IV/グリークス)をCSVに書き出す運用を設計して。そのCSVを取り込み、
  スキュー・期間構造を計算してdocs/index.htmlに反映するローカル用スクリプトと、
  タスクスケジューラで夜間起動するbatを用意して。
  ```

どちらも「相場データのみ・公開OK」の範囲。個人建玉を載せる場合は公開ホスティングを見直す。

---

## 運用・保守メモ
- スクレイプは壊れやすい。取得失敗で縮退運転→数日直らなければソース差し替え。
- GitHub Actions の cron は高負荷で遅延しうる（21:00ちょうどに固執しない）。
- 閾値は `src/config.py` 一箇所。バックテストで見直したらここだけ変える。
- **これは分析補助であり投資助言ではない**。画面と README に明記する。
