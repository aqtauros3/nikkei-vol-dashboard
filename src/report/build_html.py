"""静的HTMLダッシュボード生成（jinja2 + plotly）。

契約:
    build(metrics: dict, series: dict) -> None
        - templates/dashboard.html.j2 をレンダリングして docs/index.html を書き出す
        - plotly を CDN or inline で埋め込み、単一HTMLで自己完結（iPhoneで開ける）
        - 先頭に「サマリーカード」: 日経VI, IVパーセンタイル, HV20(YZ), VRP, レジーム
        - チャート: VI推移＋MA / HV各推定量 / VRP推移 / VIピークからの位置
        - レジームが STRESS のとき赤バナーで「新規売り回避」を明示

metrics 例:
    {"date": "2026-07-31", "vi": 41.29, "iv_percentile": 88.0,
     "hv": {"yang_zhang": 38.5, ...}, "vrp": 2.8, "regime": "STRESS"}
series 例: {"vi": <Series>, "vi_ma": <Series>, "hv_yz": <Series>, "vrp": <Series>}

モバイル最適化: viewport meta, レスポンシブ幅, 数値は大きめフォント。
"""
from __future__ import annotations


def build(metrics: dict, series: dict) -> None:
    raise NotImplementedError("Claude Code が jinja2+plotly で docs/index.html を生成する")
