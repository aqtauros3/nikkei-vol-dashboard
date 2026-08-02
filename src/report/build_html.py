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
        "skew": _chart_skew(series),
        "iv_term": _chart_iv_term(series),
        "futures_term": _chart_futures_term(series),
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


def _empty_chart(title: str) -> str:
    """データなし時のプレースホルダチャートを返す。"""
    fig = go.Figure()
    fig.add_annotation(
        text="データなし", x=0.5, y=0.5,
        xref="paper", yref="paper",
        showarrow=False,
        font=dict(size=16, color="#9E9E9E"),
    )
    fig.update_layout(**_base_layout(title))
    return _to_div(fig)


def _chart_skew(series: dict) -> str:
    """IV スキューチャート（Put/Call 2本色分け、異常値淡色表示）。

    設計根拠: OTM プットのプレミアム割高（プットスキュー）を直接視覚化するため、
    Put と Call を別系列として描画する。OTM ブレンド単曲線は市場の非対称性を隠蔽する。
    """
    skew_df = series.get("iv_skew")
    if skew_df is None or (hasattr(skew_df, "empty") and skew_df.empty):
        return _empty_chart("IVスキュー（データなし）")

    expiry = series.get("iv_skew_expiry", "")
    title_exp = f"{expiry[:4]}/{expiry[4:]}" if len(expiry) == 6 else expiry

    fig = go.Figure()

    # --- Put 系列 ---
    normal_put = skew_df[~skew_df["outlier_put"].fillna(False)]
    outlier_put = skew_df[skew_df["outlier_put"].fillna(False)]

    if not normal_put.empty:
        fig.add_trace(go.Scatter(
            x=normal_put["moneyness"].tolist(),
            y=normal_put["iv_put"].tolist(),
            name="Put IV", mode="lines+markers",
            line=dict(color="#1565C0", width=2.0),
            marker=dict(size=5),
        ))
    if not outlier_put.empty:
        fig.add_trace(go.Scatter(
            x=outlier_put["moneyness"].tolist(),
            y=outlier_put["iv_put"].tolist(),
            name="Put IV（低流動性）", mode="markers",
            marker=dict(color="#1565C0", opacity=0.2, size=8, symbol="circle-open"),
            showlegend=True,
        ))

    # --- Call 系列 ---
    normal_call = skew_df[~skew_df["outlier_call"].fillna(False)]
    outlier_call = skew_df[skew_df["outlier_call"].fillna(False)]

    if not normal_call.empty:
        fig.add_trace(go.Scatter(
            x=normal_call["moneyness"].tolist(),
            y=normal_call["iv_call"].tolist(),
            name="Call IV", mode="lines+markers",
            line=dict(color="#F57C00", width=2.0),
            marker=dict(size=5),
        ))
    if not outlier_call.empty:
        fig.add_trace(go.Scatter(
            x=outlier_call["moneyness"].tolist(),
            y=outlier_call["iv_call"].tolist(),
            name="Call IV（低流動性）", mode="markers",
            marker=dict(color="#F57C00", opacity=0.2, size=8, symbol="circle-open"),
            showlegend=True,
        ))

    fig.add_vline(x=1.0, line_dash="dash", line_color="#9E9E9E", line_width=1,
                  annotation_text="ATM", annotation_position="top right",
                  annotation_font_size=10)
    layout = _base_layout(f"IVスキュー — {title_exp}限月（行使価格モネーネス近似）")
    layout["xaxis"]["title"] = "モネーネス（行使価格 / 現物終値）"
    layout["yaxis"]["title"] = "IV（年率%）"
    fig.update_layout(**layout)
    return _to_div(fig)


def _chart_iv_term(series: dict) -> str:
    """IV 期間構造チャート（限月別 ATM IV + 日経 VI 参照線）。

    ATM IV 定義: 各限月で原資産価格に最近接ストライクの Call/Put IV の平均値。
    日経 VI（NVI）を水平線で重ね、スポット VI との乖離を確認できる。
    """
    iv_term = series.get("iv_term")
    if iv_term is None or (hasattr(iv_term, "empty") and iv_term.empty):
        return _empty_chart("IV 期間構造（データなし）")

    iv_term = iv_term.dropna()
    expiry_labels = [f"{e[:4]}/{e[4:]}" if len(e) == 6 else e for e in iv_term.index]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=expiry_labels, y=iv_term.values.tolist(),
        mode="lines+markers",
        name="ATM IV（Call/Put 平均）",
        line=dict(color="#1565C0", width=2.0),
        marker=dict(size=9, color="#1565C0"),
    ))

    # 日経 VI 水平線
    vi_s = series.get("vi")
    if vi_s is not None and not vi_s.dropna().empty:
        vi_val = float(vi_s.dropna().iloc[-1])
        fig.add_hline(
            y=vi_val, line_dash="dash", line_color="#F57C00", line_width=1.5,
            annotation_text=f"日経VI (NVI): {vi_val:.1f}%",
            annotation_position="top left",
            annotation_font_size=10,
        )

    layout = _base_layout("IV 期間構造（ATM IV by 限月, 年率%）")
    layout["xaxis"]["title"] = "限月"
    layout["yaxis"]["title"] = "ATM IV（年率%）"
    fig.update_layout(**layout)
    return _to_div(fig)


def _chart_futures_term(series: dict) -> str:
    """先物期間構造チャート（限月別清算値 + 現物終値参照線）。"""
    fut_term = series.get("futures_term")
    if fut_term is None or (hasattr(fut_term, "empty") and fut_term.empty):
        return _empty_chart("先物期間構造（データなし）")

    fut_term = fut_term.dropna()
    expiry_labels = [f"{e[:4]}/{e[4:]}" if len(e) == 6 else e for e in fut_term.index]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=expiry_labels, y=fut_term.values.tolist(),
        mode="lines+markers",
        name="先物清算値",
        line=dict(color="#2E7D32", width=2.0),
        marker=dict(size=9, color="#2E7D32"),
    ))

    # 現物終値水平線
    fut_underlying = series.get("futures_underlying")
    if fut_underlying is not None and not (isinstance(fut_underlying, float) and math.isnan(fut_underlying)):
        fig.add_hline(
            y=fut_underlying, line_dash="solid", line_color="#555", line_width=1,
            annotation_text=f"現物終値: {fut_underlying:,.0f}円",
            annotation_position="top left",
            annotation_font_size=10,
        )

    layout = _base_layout("先物期間構造（限月別清算値, 円）")
    layout["xaxis"]["title"] = "限月"
    layout["yaxis"]["title"] = "清算値段（円）"
    layout["yaxis"]["tickformat"] = ","
    fig.update_layout(**layout)
    return _to_div(fig)
