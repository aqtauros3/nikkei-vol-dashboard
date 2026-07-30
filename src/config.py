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
