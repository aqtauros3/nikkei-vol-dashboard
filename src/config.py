"""集中設定。閾値・窓・データソース・パスを一元管理。
※閾値は戦略章の代表値。実運用前に必ず自分でバックテスト較正すること。
"""
from __future__ import annotations

from pathlib import Path

# --- パス ---
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HISTORY = DATA / "history"
RAW = DATA / "raw"
DOCS = ROOT / "docs"                      # GitHub Pages 公開フォルダ
VI_CSV = HISTORY / "nikkei_vi.csv"        # date,vi
OHLC_CSV = HISTORY / "nikkei_ohlc.csv"    # date,open,high,low,close

# --- 計算パラメータ ---
ANNUALIZATION = 245        # 日本株の年間営業日数の目安（252 でも可・要統一）
HV_WINDOW = 20             # 実現ボラ窓（日経VIの30日と概ね対応）
IV_HISTORY_WINDOW = 252    # IV Rank/Percentile の参照窓
VI_MA_WINDOW = 20          # レジーム判定の移動平均窓
VI_SLOPE_LOOKBACK = 5
VI_PEAK_LOOKBACK = 20
HV_PRIMARY = "yang_zhang"  # 主表示に使う推定量

# --- エントリー/管理 閾値（戦略章の代表値・例示） ---
IV_PERCENTILE_ENTRY = 50.0     # これ以上で売り検討
VRP_ENTRY_VOLPTS = 3.0         # VI − HV20 がこれ以上
SHORT_STRIKE_DELTA = (0.10, 0.16)
PROFIT_TARGET = 0.50           # 受取プレミアムの50%で利確
STOP_LOSS_MULT = 2.0           # 受取クレジットの2倍損失で撤退
DELTA_DEFENSE = 0.30           # ショートΔがこれ超で防御
DTE_ENTRY = (30, 45)
DTE_MANAGE = 21

# --- データソース（無料フェーズ） ---
# 日経225現物 OHLC: yfinance の ^N225 か Stooq の ^nkx を利用（fetch側で実装）
NIKKEI_YAHOO_TICKER = "^N225"
NIKKEI_STOOQ_SYMBOL = "^nkx"
# 日経VI: 無料の公開値をスクレイプ（fetch側で複数ソースをフォールバック実装）
#   例: nikkei.com / investing.com。初回は手動DL CSV で history をシード。
VI_SEED_NOTE = "data/history/nikkei_vi.csv を投資サイトの履歴CSVで一度シードする"

# --- 表示 ---
SITE_TITLE = "日経225 ボラティリティ監視ダッシュボード"
TIMEZONE = "Asia/Tokyo"

# --- JPX デリバティブデータ設定 ---
JPX_DERIVATIVES_CSV     = HISTORY / "jpx_derivatives.csv"
JPX_SETTLEMENT_INDEX_URL = (
    "https://www.jpx.co.jp/markets/derivatives/settlement-price/index.html"
)
JPX_TARGET_UNDERLYING   = "日経225"      # フィルタ対象の原資産名称
JPX_OPTION_PUT_CALL     = ("PUT", "CAL") # CSVの値そのまま

# ATM IV 計算: underlying ±この割合以内の strike を ATM 候補とみなす
ATM_MONEYNESS_BAND      = 0.02           # ±2%

# IV 異常値フィルタ: ローリング中央値（window=5）からの相対乖離率閾値
IV_OUTLIER_PCT_THRESH   = 0.30           # ±30%超で淡色表示

# nearest_expiry(): 月次限月のみ選択・最小残存日数フロア
NEAREST_EXPIRY_MONTHLY_ONLY = True   # True = 6桁限月のみ（Weekly除外）
NEAREST_EXPIRY_MIN_DTE      = 7      # DTE がこれ未満の限月は除外（直前SQ効果を避ける）

# レジーム判定: 不感帯・絶対水準閾値
REGIME_DEAD_BAND_PCT     = 0.02   # |VI-MA|/MA がこれ未満なら強制 NEUTRAL（誤判定抑制）
REGIME_HIGH_IV_THRESHOLD = 70.0   # IV Percentile がこれ以上で「高IV水準」バッジを表示（例示）

# seed 時の遡り営業日数（JPXは約2ヶ月保持なので60で大半を回収可能）
SEED_LOOKBACK_BDAYS     = 60
