# 日経225 ボラティリティ監視ダッシュボード

日経225オプション「売り」の**環境判断**用。平日夜に当日の相場を集計し、静的HTMLを
GitHub Pages で公開して iPhone から見る。完全リアルタイムではなく夜間バッチ型。

> ⚠️ 本ツールは分析補助であり投資助言ではありません。表示される閾値は例示で、
> 実運用前に自身でバックテスト較正してください。

## 何が見えるか（無料フェーズ）
- 日経VI（水準）、IV Rank / IV Percentile
- HV（実現ボラ）5推定量：終値/Parkinson/Garman-Klass/Rogers-Satchell/**Yang-Zhang(主)**
- VRP（簡易）＝ 日経VI − HV20
- レジーム判定（STRESS=新規売り回避 / CALM=売り検討 / NEUTRAL）

## セットアップ（Windows）
`BUILD_PLAN.md` のフェーズ0〜3に沿って進める。要点だけ:
```powershell
# Claude Code（推奨・ネイティブ, Node不要）
irm https://claude.ai/install.ps1 | iex
# 依存
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# ローカル実行（実装完了後）
python run_local.py   # docs/index.html を生成
pytest                # テスト
```

## 使い方
- 夜間は GitHub Actions が自動で集計・公開（PC起動不要）。
- iPhone で Pages URL を開き「ホーム画面に追加」でアプリ風に。

## 何が見えるか（フェーズ4 実装済み）
- IV スキュー（モネーネス曲線・行使価格補助軸）
- IV 期間構造・先物期間構造（全限月 + 期近ズーム）
- IV 期間スロープ（期近 − 3ヶ月先、バックワーデーション/コンタンゴ判定）

## ドキュメント
- [GUIDE.md](GUIDE.md) — 各カード・チャートの読み方（ユーザー向け）
- [SPEC.md](SPEC.md) — 計算モデルの正典と実装仕様（開発者向け）
- [BUILD_PLAN.md](BUILD_PLAN.md) — フェーズ別の作業手順

## 構成
- `src/` 取得・計算・レポート、`data/history/` 積み上げCSV、`docs/` 公開HTML
- `CLAUDE.md` Claude Code 用の指針

## 拡張（有料/RSS）
オプション個別（スキュー・期間構造）は J-Quants Standard か 楽天RSS で追加。詳細は
[BUILD_PLAN.md](BUILD_PLAN.md) フェーズ4 と [SPEC.md](SPEC.md)。
