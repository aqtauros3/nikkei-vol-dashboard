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

# 期近ズームで表示する限月数
_FRONT_MONTHS_ZOOM = 4

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
        "iv_term_zoom": _chart_iv_term_zoom(series),
        "futures_term_zoom": _chart_futures_term_zoom(series),
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
    上部補助軸（xaxis2）に主要モネーネス位置の行使価格実額を併記（参考）。

    設計根拠: OTM プットのプレミアム割高（プットスキュー）を直接視覚化するため、
    Put と Call を別系列として描画する。OTM ブレンド単曲線は市場の非対称性を隠蔽する。
    行使価格補助軸は主軸（モネーネス）の時系列一貫性を保ちつつ実額の直感を補う。

    モネーネス基準・行使価格軸: 期近限月の先物清算値を優先（SPEC §0準拠）。
    先物なし限月（Weekly等）は現物終値にフォールバック。
    将来、複数限月を重ね描きする場合は限月ごとに基準価格が異なるため注意。
    """
    skew_df = series.get("iv_skew")
    if skew_df is None or (hasattr(skew_df, "empty") and skew_df.empty):
        return _empty_chart("IVスキュー（データなし）")

    expiry = series.get("iv_skew_expiry", "")
    title_exp = f"{expiry[:4]}/{expiry[4:]}" if len(expiry) == 6 else expiry

    # スキュー軸基準: 期近先物清算値を優先、なければ現物終値
    spot = series.get("futures_underlying", float("nan"))
    skew_ref = series.get("skew_futures_price", float("nan"))
    _use_futures = (
        isinstance(skew_ref, (int, float))
        and math.isfinite(skew_ref)
        and abs(skew_ref - spot) > 0.01  # 実質的に先物価格が取得できた場合
    )
    underlying = skew_ref if _use_futures else spot
    _x_label = (
        f"モネーネス（行使価格 / 先物清算値）"
        if _use_futures
        else "モネーネス（行使価格 / 現物終値）"
    )
    _strike_axis_label = "行使価格（円, 先物基準）" if _use_futures else "行使価格（円）"

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
    layout["xaxis"]["title"] = _x_label
    layout["yaxis"]["title"] = "IV（年率%）"

    # 行使価格補助軸: 主要モネーネス位置に対応する行使価格実額（参考）
    if isinstance(underlying, (int, float)) and math.isfinite(underlying) and underlying > 0:
        _key_m = [0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15]
        _ticktext = [f"{underlying * m:,.0f}" for m in _key_m]
        # x 軸レンジをデータから確定し両軸に明示してズレを防ぐ
        _xmin = float(skew_df["moneyness"].min()) - 0.01
        _xmax = float(skew_df["moneyness"].max()) + 0.01
        # ダミートレースの y に使う代表値（Put/Call IV の平均）
        _iv_flat = [
            v for col in ("iv_put", "iv_call")
            for v in skew_df[col].tolist()
            if isinstance(v, float) and not math.isnan(v) and v > 0
        ]
        _y_dummy = sum(_iv_flat) / len(_iv_flat) if _iv_flat else 25.0
        layout["xaxis"]["range"] = [_xmin, _xmax]
        layout["margin"]["t"] = 62
        layout["xaxis2"] = dict(
            title=dict(text=_strike_axis_label, font=dict(size=10), standoff=4),
            overlaying="x",
            side="top",
            tickmode="array",
            tickvals=_key_m,
            ticktext=_ticktext,
            range=[_xmin, _xmax],
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=9),
        )
        # Plotly は参照トレースが無い軸を描画しないため、不可視ダミートレースで xaxis2 を有効化
        fig.add_trace(go.Scatter(
            x=_key_m, y=[_y_dummy] * len(_key_m),
            xaxis="x2", yaxis="y",
            mode="markers",
            marker=dict(size=1, opacity=0, color="rgba(0,0,0,0)"),
            showlegend=False, hoverinfo="none", name="",
        ))

    fig.update_layout(**layout)
    return _to_div(fig)


def _chart_iv_term(series: dict) -> str:
    """IV 期間構造チャート（限月別 ATM IV + 日経 VI 参照線）。

    ATM IV 定義: 各限月で先物清算値（先物なし限月は現物終値）に最近接ストライクの
    Call/Put IV の平均値。先物なし限月は淡色の開マーカーで区別表示する。
    日経 VI（NVI）を水平線で重ね、スポット VI との乖離を確認できる。
    """
    iv_term = series.get("iv_term")
    if iv_term is None or (hasattr(iv_term, "empty") and iv_term.empty):
        return _empty_chart("IV 期間構造（データなし）")

    iv_term = iv_term.dropna()
    fallback_exp = series.get("iv_term_fallback_expiries", set())

    # 先物ベース限月とフォールバック限月に分離
    normal_mask = [e not in fallback_exp for e in iv_term.index]
    fallback_mask = [e in fallback_exp for e in iv_term.index]
    iv_normal = iv_term[normal_mask]
    iv_fallback = iv_term[fallback_mask]

    normal_labels = [f"{e[:4]}/{e[4:]}" if len(e) == 6 else e for e in iv_normal.index]
    fallback_labels = [f"{e[:4]}/{e[4:]}" if len(e) == 6 else e for e in iv_fallback.index]
    all_labels = [f"{e[:4]}/{e[4:]}" if len(e) == 6 else e for e in iv_term.index]

    fig = go.Figure()

    # 全限月を結ぶ線（先物ベース＋フォールバック通し）
    fig.add_trace(go.Scatter(
        x=all_labels, y=iv_term.values.tolist(),
        mode="lines",
        line=dict(color="#1565C0", width=1.5),
        showlegend=False,
        hoverinfo="skip",
    ))

    # 先物ベース限月: 塗りつぶしマーカー
    if not iv_normal.empty:
        fig.add_trace(go.Scatter(
            x=normal_labels, y=iv_normal.values.tolist(),
            mode="markers",
            name="ATM IV（先物基準）",
            marker=dict(size=9, color="#1565C0"),
        ))

    # フォールバック限月: 開マーカー＋淡色（先物なし → 現物終値でATM判定）
    if not iv_fallback.empty:
        fig.add_trace(go.Scatter(
            x=fallback_labels, y=iv_fallback.values.tolist(),
            mode="markers",
            name="ATM IV（現物基準・先物なし）",
            marker=dict(size=9, color="#90A4AE", symbol="circle-open", line=dict(width=2)),
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


def _chart_iv_term_zoom(series: dict) -> str:
    """IV 期間構造・期近ズームチャート（前 _FRONT_MONTHS_ZOOM 限月のみ）。
    縦軸をデータ範囲にフィットさせ各点に IV 値ラベルを表示。傾き方向を動的に注記。
    先物なし限月は開マーカーで区別表示する。
    """
    iv_term = series.get("iv_term")
    if iv_term is None or (hasattr(iv_term, "empty") and iv_term.empty):
        return _empty_chart("IV 期間構造・期近ズーム（データなし）")
    iv_term = iv_term.dropna()
    if iv_term.empty:
        return _empty_chart("IV 期間構造・期近ズーム（データなし）")

    front = iv_term.head(_FRONT_MONTHS_ZOOM)
    fallback_exp = series.get("iv_term_fallback_expiries", set())
    labels = [f"{e[:4]}/{e[4:]}" if len(e) == 6 else e for e in front.index]
    y_vals = front.values.tolist()

    # 傾き方向でバックワーデーション/コンタンゴを判定
    _slope_ann = ""
    if len(y_vals) >= 2:
        _slope_ann = (
            "▲ バックワーデーション（期近高IV・目先緊張）" if y_vals[0] > y_vals[-1]
            else "▽ コンタンゴ（期近低IV・平時型）"
        )

    fig = go.Figure()

    # 線で全点をつなぐ（フォールバック混在でも連続線を維持）
    fig.add_trace(go.Scatter(
        x=labels, y=y_vals,
        mode="lines",
        line=dict(color="#1565C0", width=2.0),
        showlegend=False,
        hoverinfo="skip",
    ))

    # 各点: 先物ベースは塗りつぶし、フォールバックは開マーカー
    for label, exp, val in zip(labels, front.index, y_vals):
        is_fallback = exp in fallback_exp
        fig.add_trace(go.Scatter(
            x=[label], y=[val],
            mode="markers+text",
            text=[f"{val:.1f}%"],
            textposition="top center",
            textfont=dict(size=11, color="#90A4AE" if is_fallback else "#1565C0"),
            showlegend=False,
            marker=dict(
                size=10,
                color="#90A4AE" if is_fallback else "#1565C0",
                symbol="circle-open" if is_fallback else "circle",
                line=dict(width=2) if is_fallback else dict(width=0),
            ),
            hovertemplate=(
                f"{label}: {val:.1f}%<br>{'(現物基準・先物なし)' if is_fallback else '(先物基準)'}"
                "<extra></extra>"
            ),
        ))

    if _slope_ann:
        fig.add_annotation(
            text=_slope_ann,
            x=0.5, y=0.97,
            xref="paper", yref="paper",
            showarrow=False,
            font=dict(size=10, color="#555"),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#BDBDBD",
            borderwidth=1,
            xanchor="center",
            yanchor="top",
        )

    # 縦軸をデータ範囲にフィット（VI 水平線による引き伸ばしを回避）
    layout = _base_layout(f"IV 期間構造・期近{len(front)}限月ズーム（年率%）")
    layout["xaxis"]["title"] = "限月"
    layout["yaxis"]["title"] = "ATM IV（年率%）"
    layout["yaxis"]["range"] = [min(y_vals) - 0.5, max(y_vals) + 2.5]
    fig.update_layout(**layout)
    return _to_div(fig)


def _chart_futures_term_zoom(series: dict) -> str:
    """先物期間構造・期近ズームチャート（前 _FRONT_MONTHS_ZOOM 限月のみ）。
    縦軸をデータ範囲にフィットさせ各点に清算値ラベルを表示。傾き方向を動的に注記。
    """
    fut_term = series.get("futures_term")
    if fut_term is None or (hasattr(fut_term, "empty") and fut_term.empty):
        return _empty_chart("先物期間構造・期近ズーム（データなし）")
    fut_term = fut_term.dropna()
    if fut_term.empty:
        return _empty_chart("先物期間構造・期近ズーム（データなし）")

    front = fut_term.head(_FRONT_MONTHS_ZOOM)
    labels = [f"{e[:4]}/{e[4:]}" if len(e) == 6 else e for e in front.index]
    y_vals = front.values.tolist()

    # 先物構造判定: 後限 > 前限 = コンタンゴ（順鞘・通常）
    _slope_ann = ""
    if len(y_vals) >= 2:
        _slope_ann = (
            "▲ バックワーデーション（逆鞘・前限高）" if y_vals[0] > y_vals[-1]
            else "▽ コンタンゴ（順鞘・後限高）"
        )

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=y_vals,
        mode="lines+markers+text",
        text=[f"{v:,.0f}" for v in y_vals],
        textposition="top center",
        textfont=dict(size=10, color="#2E7D32"),
        name="先物清算値",
        line=dict(color="#2E7D32", width=2.0),
        marker=dict(size=10, color="#2E7D32"),
    ))

    if _slope_ann:
        fig.add_annotation(
            text=_slope_ann,
            x=0.5, y=0.97,
            xref="paper", yref="paper",
            showarrow=False,
            font=dict(size=10, color="#555"),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor="#BDBDBD",
            borderwidth=1,
            xanchor="center",
            yanchor="top",
        )

    # 現物終値水平線
    fut_underlying = series.get("futures_underlying")
    _has_underlying = (
        fut_underlying is not None
        and not (isinstance(fut_underlying, float) and math.isnan(fut_underlying))
    )
    if _has_underlying:
        fig.add_hline(
            y=fut_underlying, line_dash="solid", line_color="#555", line_width=1,
            annotation_text=f"現物終値: {fut_underlying:,.0f}円",
            annotation_position="top left",
            annotation_font_size=10,
        )

    # 縦軸をデータ範囲にフィット（現物終値も含めてスパンを計算）
    all_y = y_vals + ([float(fut_underlying)] if _has_underlying else [])
    _y_span = max(max(all_y) - min(all_y), 100)
    layout = _base_layout(f"先物期間構造・期近{len(front)}限月ズーム（円）")
    layout["xaxis"]["title"] = "限月"
    layout["yaxis"]["title"] = "清算値段（円）"
    layout["yaxis"]["tickformat"] = ","
    layout["yaxis"]["range"] = [min(all_y) - _y_span * 0.3, max(all_y) + _y_span * 0.9]
    fig.update_layout(**layout)
    return _to_div(fig)
