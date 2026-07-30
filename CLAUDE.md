# CLAUDE.md — プロジェクト指針（Claude Code はまずこれを読む）

## 目的
日経225オプション「売り」の環境判断のための**夜間バッチ型ダッシュボード**。
平日 21:00〜24:00 に当日の相場を確認できればよい（完全リアルタイム不要）。
生成した静的HTMLを GitHub Pages で公開し、**iPhone のブラウザ**から見る。

## 非目標（やらないこと）
- 完全リアルタイム配信・自動発注は作らない。
- **個人情報（建玉・証拠金・口座）はダッシュボードに載せない**（相場データのみ・公開ホスティング前提）。
- 秘密情報をコードに直書きしない（有料APIキーは `.env` / GitHub Secrets）。
- 投資助言の文面を出力しない。閾値は「例示」であることを画面にも明記する。

## 動作環境
- 開発: Windows + VS Code + Claude Code。Python 3.12。
- 夜間実行: GitHub Actions（Ubuntu, クラウド）。PCは起動不要。
- 依存は `requirements.txt`。

## アーキテクチャ（無料フェーズ）
```
GitHub Actions(21:00 JST) → fetch(日経225 OHLC, 日経VI) → compute(HV/IVR/VRP/regime)
   → report(docs/index.html 生成) → commit/push → GitHub Pages → iPhone
```
- 履歴は `data/history/*.csv` に積み上げてコミット（IV Rank に過去252日が必要）。

## ディレクトリ
- `src/config.py` … 閾値・窓・パス・データソース（**数値の変更は必ずここ**）
- `src/fetch/` … データ取得（`nikkei_ohlc.py`, `nikkei_vi.py`）※要実装
- `src/compute/` … `realized_vol.py`(実装済), `iv_metrics.py`(実装済), `regime.py`(実装済)
- `src/report/` … `build_html.py` + `templates/` ※要実装
- `run_local.py` … パイプライン統合（TODOを埋める）
- `.github/workflows/nightly.yml` … 夜間ジョブ
- `SPEC.md` … 計算モデルとデータ取得の詳細仕様（数式の正典）
- `BUILD_PLAN.md` … フェーズ別の作業手順とプロンプト

## 指標の定義（正典は SPEC.md）
- HV: close_to_close / parkinson / garman_klass / rogers_satchell / **yang_zhang(主)**。年率%表示。
- IV Rank / IV Percentile: 日経VIの過去252営業日から算出。エントリー判定は Percentile を主に使う。
- VRP(簡易) = 日経VI − HV20（ボラポイント）。正で大きいほど売り妙味。
- レジーム: VI>MA かつ上昇=STRESS(売り回避), VI<MA かつ低下=CALM(売り検討), 他=NEUTRAL。

## コーディング規約
- 型ヒント必須。副作用（I/O）は fetch / report に閉じ込め、compute は純関数に保つ。
- `pytest` が通ること。**compute のテストはネットワーク禁止**（合成データで検証）。
- 例外は握りつぶさない。夜間無人運用のため、取得失敗時は「前回値で縮退運転し、画面に失敗を明示」。
- 単位の約束を厳守: VI と HV は「％表記」、realized_vol の戻り値は「小数」なので ×100 して渡す。

## 完了の定義（DoD）
1. `pytest` 緑。2. `python run_local.py` がローカルで `docs/index.html` を生成。
3. iPhone Safari でレイアウトが崩れない。4. STRESS 時に赤バナーが出る。

## Git 運用（ユーザーはGit不慣れ。Claude Codeが代行しつつ説明する）
- 変更は小さく。各タスク完了ごとに意味のある単位でコミット（日本語メッセージ可）。
- コミット前に必ず `pytest` を実行。壊れたまま push しない。
- 破壊的操作（force push, reset --hard）は事前に理由を説明し確認を取る。

## 有料/RSS 拡張（フェーズ4・SPEC.md参照）
- オプション個別（スキュー, 期間構造）が必要になったら:
  - クラウド継続なら **J-Quants Standard(¥3,300/月)** を `src/fetch/jquants_option.py` で追加（鍵は Secrets）。
  - 当日値/無料志向なら **楽天マーケットスピードII RSS(Windows/Excel)** をローカルで叩き CSV 出力 → 取り込む（クラウド不可なのでこの経路は手元PC実行）。
