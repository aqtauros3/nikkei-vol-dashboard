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

import math
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
from jinja2 import Environment, FileSystemLoader

from src import config as cfg

TEMPLATE_DIR = Path(__file__).parent / "templates"

# 推定量の表示名（日本語）
_HV_LABELS: dict[str, str] = {
    "yang_zhang": "YZ（主）",
    "close_to_close": "C2C",
    "parkinson": "Parkinson",
    "garman_klass": "GK",
    "rogers_satchell": "RS",
}
_PALETTE = ["#1565C0", "#2E7D32", "#F57C00", "#6A1B9A", "#C62828"]


def build(metrics: dict, series: dict) -> None:
    """metrics と series を受け取り docs/index.html を生成する。"""
    charts = {
        "vi": _chart_vi(series),
        "hv": _chart_hv(series),
        "vrp": _chart_vrp(series),
        "drawdown": _chart_drawdown(series),
    }

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=False)
    env.filters["fmt"] = _fmt
    template = env.get_template("dashboard.html.j2")
    html = template.render(metrics=metrics, charts=charts, cfg=cfg)

    cfg.DOCS.mkdir(parents=True, exist_ok=True)
    out = cfg.DOCS / "index.html"
    out.write_text(html, encoding="utf-8")


# ---------- Jinja2 フィルタ ----------

def _fmt(value: object, spec: str = ".1f") -> str:
    """NaN / None を 'N/A' に変換してフォーマットする Jinja2 フィルタ。"""
    if value is None:
        return "N/A"
    if isinstance(value, float) and math.isnan(value):
        return "N/A"
    return format(float(value), spec)


# ---------- チャート生成 ----------

def _base_layout(title: str) -> dict:
    return dict(
        title=dict(text=title, font=dict(size=13, color="#555"), x=0.01),
        height=280,
        margin=dict(l=46, r=12, t=38, b=44),
        paper_bgcolor="white",
        plot_bgcolor="#FAFAFA",
        legend=dict(
            orientation="h", y=-0.28, font=dict(size=10),
            bgcolor="rgba(0,0,0,0)", xanchor="left", x=0,
        ),
        font=dict(size=11, family="-apple-system, 'Helvetica Neue', sans-serif"),
        xaxis=dict(showgrid=True, gridcolor="#EEEEEE", zeroline=False),
        yaxis=dict(showgrid=True, gridcolor="#EEEEEE", zeroline=False),
    )


def _to_div(fig: go.Figure) -> str:
    return pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs=False,
        config={"responsive": True, "displayModeBar": False},
    )


def _chart_vi(series: dict) -> str:
    """VI + 移動平均 チャート。"""
    vi = series["vi"].dropna()
    ma = series["vi_ma"].dropna()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=vi.index.tolist(), y=vi.tolist(),
        name="日経VI", line=dict(color="#1565C0", width=2.5),
    ))
    fig.add_trace(go.Scatter(
        x=ma.index.tolist(), y=ma.tolist(),
        name=f"MA{cfg.VI_MA_WINDOW}日", line=dict(color="#F57C00", width=1.8, dash="dash"),
    ))
    fig.update_layout(**_base_layout("日経VI 推移（%）"))
    return _to_div(fig)


def _chart_hv(series: dict) -> str:
    """HV 各推定量 + VI 参照線 チャート。"""
    fig = go.Figure()
    hv_all: dict = series.get("hv_all", {})
    for i, (name, s) in enumerate(hv_all.items()):
        s = s.dropna()
        is_primary = name == cfg.HV_PRIMARY
        fig.add_trace(go.Scatter(
            x=s.index.tolist(), y=s.tolist(),
            name=_HV_LABELS.get(name, name),
            line=dict(color=_PALETTE[i % len(_PALETTE)], width=2.5 if is_primary else 1.2),
            opacity=1.0 if is_primary else 0.55,
        ))
    vi = series["vi"].dropna()
    fig.add_trace(go.Scatter(
        x=vi.index.tolist(), y=vi.tolist(),
        name="日経VI（参照）",
        line=dict(color="#90A4AE", width=1.2, dash="dot"),
    ))
    fig.update_layout(**_base_layout("HV 各推定量 vs 日経VI（年率%）"))
    return _to_div(fig)


def _chart_vrp(series: dict) -> str:
    """VRP 棒グラフ（正=緑, 負=赤）。"""
    vrp = series["vrp"].dropna()
    colors = ["#2E7D32" if v >= 0 else "#C62828" for v in vrp.tolist()]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=vrp.index.tolist(), y=vrp.tolist(),
        marker_color=colors, name="VRP",
    ))
    fig.add_hline(y=0, line_color="#555", line_width=1)
    fig.add_hline(
        y=cfg.VRP_ENTRY_VOLPTS,
        line_dash="dash", line_color="#2E7D32",
        annotation_text=f"売り目安 +{cfg.VRP_ENTRY_VOLPTS:.0f}pt（例示）",
        annotation_position="top left",
        annotation_font_size=10,
    )
    fig.update_layout(**_base_layout("VRP = VI − HV20（ボラポイント）"))
    return _to_div(fig)


def _chart_drawdown(series: dict) -> str:
    """VI ピークからの距離チャート。"""
    dd = series["vi_drawdown"].dropna() * 100  # % 表示

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dd.index.tolist(), y=dd.tolist(),
        name="ピーク比",
        fill="tozeroy",
        fillcolor="rgba(21,101,192,0.10)",
        line=dict(color="#1565C0", width=1.8),
    ))
    fig.add_hline(y=0, line_color="#555", line_width=1)
    fig.update_layout(**_base_layout(
        f"VI ピークからの位置（直近{cfg.VI_PEAK_LOOKBACK}日最大比, %）"
    ))
    return _to_div(fig)
