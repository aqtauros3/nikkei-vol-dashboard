# 設計案: 定数満期 30 日 IV（Constant Maturity 30-Day IV）補間

> ステータス: **Draft（未実装）**
> 目的: 将来の実装検討用メモ。現行ダッシュボードには含まれない。

---

## 背景と動機

現行の `atm_iv()` は**限月固有の満期**（例: DTE=11の8月SQ、DTE=40の9月など）の IV を返す。
限月間で DTE が異なるため、時系列で並べると「限月切替」のたびにジャンプが生じる：

```
7/31: 202608(DTE=14) ATM_IV = 35.5%  ← 14日残存の価格
8/3:  202608(DTE=11) ATM_IV = 36.0%  ← 11日残存の価格（同一限月でもDTE違い）
8/14: 202609(DTE=40) ATM_IV = 31.0%  ← 限月切替後。40日残存へジャンプ
```

このジャンプは**満期効果**（term structure の形状による）であり、IV そのものの水準変化ではない。
定数満期（固定 DTE=30 など）に統一することでこの歪みを除去し、連続な時系列として比較可能になる。

VIX（CBOE）は同様の手法で 30 日定数満期 IV を算出している（2 限月補間）。

---

## 補間アルゴリズム

### 基本方式（線形補間）

```
CM30_IV = w1 * IV_near + w2 * IV_far

w1 = (DTE_far - 30) / (DTE_far - DTE_near)
w2 = (30 - DTE_near) / (DTE_far - DTE_near)

ただし DTE_near < 30 < DTE_far が条件。
```

例:
- DTE_near = 11 (202608), IV_near = 36.0%
- DTE_far  = 40 (202609), IV_far  = 31.0%
- w1 = (40-30)/(40-11) = 10/29 ≈ 0.345
- w2 = (30-11)/(40-11) = 19/29 ≈ 0.655
- CM30_IV = 0.345 × 36.0 + 0.655 × 31.0 ≈ 32.9%

### エッジケース

| ケース | 対応 |
|--------|------|
| DTE_near ≥ 30（両限月とも30日超） | 最短2限月で外挿（低精度・警告ログ） |
| DTE_far ≤ 30（両限月とも30日未満） | 最長2限月で外挿（低精度・警告ログ） |
| 有効限月が1つのみ | NaN を返す |
| atm_iv() が NaN の限月を含む | スキップして次の候補を使用 |

### VIX 方式との差異

CBOE VIX は分散スワップの厳密な公式（全ストライクのオプション価格を積分）を用いるが、
本ダッシュボードは ATM IV の 2 点線形補間で近似する。
この近似はスキューが緩やかな場合に有効で、実装コストが低い。

---

## 実装スケッチ

```python
# src/compute/option_metrics.py に追加予定

def cm30_atm_iv(df: pd.DataFrame) -> float:
    """定数満期 30 日 ATM IV を 2 限月補間で返す。

    DTE が 30 日を挟む最短 2 月次限月を特定し線形補間する。
    該当しない場合や両限月の ATM IV が NaN の場合は NaN。
    """
    opts = filter_options(df)
    valid = opts[
        (opts["expiry"].astype(str).str.len() == 6) &  # 月次のみ
        (opts["days_to_expiry"].fillna(0) > 0)
    ]
    if valid.empty:
        return float("nan")

    dte_by_expiry = (
        valid.groupby("expiry")["days_to_expiry"]
        .median()
        .sort_values()
    )

    # DTE が 30 を挟む near/far を特定
    below = dte_by_expiry[dte_by_expiry < 30]
    above = dte_by_expiry[dte_by_expiry >= 30]

    if below.empty or above.empty:
        # 外挿ケース（精度低下）
        logger.warning("cm30_atm_iv: 30日を挟む限月ペアが存在しない。NaN を返す。")
        return float("nan")

    near_exp, near_dte = below.index[-1], float(below.iloc[-1])
    far_exp, far_dte = above.index[0], float(above.iloc[0])

    iv_near = atm_iv(df, near_exp)
    iv_far = atm_iv(df, far_exp)

    if not (math.isfinite(iv_near) and math.isfinite(iv_far)):
        return float("nan")

    w1 = (far_dte - 30.0) / (far_dte - near_dte)
    w2 = (30.0 - near_dte) / (far_dte - near_dte)
    return w1 * iv_near + w2 * iv_far
```

---

## ダッシュボードへの統合案

1. **サマリーカード**: `CM30 IV` カードを追加（現行の ATM IV カードの隣）
2. **時系列チャート**: 日経VI・HV20 と並べて CM30 IV を表示 → VRP の精度向上
3. **VRP の改善**: `VRP_CM30 = CM30_IV - HV30_YZ`（HV の窓も 30 日に統一）

---

## 前提条件と制約

| 項目 | 内容 |
|------|------|
| データ | JPX 清算値段 CSV（現行と同じ。追加調達不要） |
| 追加ライブラリ | 不要 |
| 精度上の注意 | ATM 1 点補間のため Deep OTM/ITM のスキュー情報を無視 |
| SQ 直前 | DTE < 7 の限月は `nearest_expiry` と同様に除外推奨 |
| 蓄積頻度 | 毎日 CM30 IV を history CSV に書き出すことで IV Rank/Percentile が計算可能 |

---

## 実装優先度

現時点では **低**。現行の atm_iv（限月固有満期）でも環境判断の実用上は十分。
以下のケースで優先度が上がる：

- 日次 VRP 精度の改善が必要になったとき
- 複数日の IV 推移を時系列で比較したいとき
- J-Quants 等でオプション時系列が利用可能になったとき（ストライク全体の補間が可能になる）
