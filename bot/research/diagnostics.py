"""Стратегийн оношлогоо: алдагдал хаанаас гарч байгааг олох.

ЗӨВХӨН in-sample өгөгдөл дээр ажиллуулна (out-of-sample-ийг дахин харахгүй).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def trend_edge(df: pd.DataFrame, horizons=(24, 72)) -> pd.DataFrame:
    """H4 trend-ийн чиглэл ирээдүйн үнийн хөдөлгөөнийг таамаглаж чадах уу?
    fwd_R = (close[t+h] − close[t]) / ATR × trend.  Эерэг дундаж = trend шүүлтүүрт утга бий.
    t-stat-ыг давхцалгүй (h алхамтай) түүврээр тооцно."""
    rows = []
    d = df[(df["trend"] != 0) & df["atr"].notna()]
    for h in horizons:
        fwd = (df["close"].shift(-h) - df["close"]) / df["atr"]
        x = (fwd.loc[d.index] * d["trend"]).dropna()
        xs = x.iloc[::h]
        t = xs.mean() / (xs.std() / np.sqrt(len(xs))) if len(xs) > 2 and xs.std() > 0 else np.nan
        rows.append({"horizon_h1": h, "n": len(x), "mean_atr": round(x.mean(), 3),
                     "pct_positive": round((x > 0).mean() * 100, 1), "t_stat": round(t, 2)})
    return pd.DataFrame(rows)


def barrier_grid(df: pd.DataFrame, point: float, pip: float, sl_list, rr_list,
                 max_bars: int = 120, slippage_pips: float = 0.5,
                 start=None, end=None) -> pd.DataFrame:
    """Дохио бүрийг SL/TP-ийн хослол бүрээр (BE, Баасан, позицын хязгааргүй) дуусгавар хүртэл дагана.
    Буцаах: хослол бүрийн expectancy (R), win %, арилжааны тоо. Spread, slippage тооцсон."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    spr = df["spread"].to_numpy() * point if "spread" in df else np.zeros(len(df))
    atr = df["atr"].to_numpy()
    sig = df["signal"].to_numpy()
    mask = sig != 0
    if start is not None:
        mask &= (df["time"] >= pd.Timestamp(start)).to_numpy()
    if end is not None:
        mask &= (df["time"] < pd.Timestamp(end)).to_numpy()
    idx = np.flatnonzero(mask)
    idx = idx[idx + 2 < len(df)]
    slip = slippage_pips * pip
    res = {(s, r): [] for s in sl_list for r in rr_list}
    for i in idx:
        side = sig[i]
        a, b = i + 1, min(i + 1 + max_bars, len(df))
        H, L, S = h[a:b], l[a:b], spr[a:b]
        if side == 1:
            entry = o[a] + spr[a] + slip
            adverse, favor = entry - L, H - entry           # BID-ээр хаана
            last = c[b - 1] - entry
        else:
            entry = o[a] - slip
            adverse, favor = (H + S) - entry, entry - (L + S)  # ASK-аар хаана
            last = entry - (c[b - 1] + S[-1])
        for s in sl_list:
            sl = s * atr[i]
            hit_sl = np.flatnonzero(adverse >= sl)
            for r in rr_list:
                hit_tp = np.flatnonzero(favor >= sl * r)
                ks = hit_sl[0] if len(hit_sl) else 10**9
                kt = hit_tp[0] if len(hit_tp) else 10**9
                if ks == 10**9 and kt == 10**9:
                    out = last / sl
                elif kt < ks:
                    out = r
                else:
                    out = -1 - slip / sl
                res[(s, r)].append(out)
    rows = []
    for (s, r), v in res.items():
        v = np.array(v)
        if len(v):
            rows.append({"sl_atr": s, "rr": r, "trades": len(v), "win_pct": round((v > 0).mean() * 100, 1),
                         "expectancy_r": round(v.mean(), 3)})
    return pd.DataFrame(rows)


def breakdown(trades: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Арилжааг гарсан шалтгаан, жил, цаг, чиглэл, хосоор задлах."""
    if trades.empty:
        return {}
    t = trades.copy()
    t["year"] = pd.to_datetime(t["entry_time"]).dt.year
    t["hour"] = pd.to_datetime(t["entry_time"]).dt.hour

    def agg(g):
        return pd.DataFrame({"trades": g.size(), "win_pct": g.apply(lambda x: (x.r > 0).mean() * 100,
                                                                     include_groups=False).round(1),
                             "avg_r": g.r.mean().round(3), "sum_r": g.r.sum().round(1)})
    out = {k: agg(t.groupby(k)) for k in ("exit_reason", "symbol", "side", "year", "hour")}
    reached = t[t.mfe_r >= 1.0]
    out["mfe"] = pd.DataFrame({
        "metric": ["+1R хүрсэн арилжааны хувь", "  тэдгээрээс TP-д хүрсэн %",
                   "  тэдгээрээс BE/TRAIL/SL-ээр хаагдсан %", "+2R хүрсэн %",
                   "Ялагчдын дундаж MAE (R)", "Ялагдагчдын дундаж MFE (R)"],
        "value": [round(len(reached) / len(t) * 100, 1),
                  round((reached.exit_reason == "TP").mean() * 100, 1) if len(reached) else 0,
                  round(reached.exit_reason.isin(["BE/TRAIL", "SL"]).mean() * 100, 1) if len(reached) else 0,
                  round((t.mfe_r >= 2.0).mean() * 100, 1),
                  round(t[t.r > 0].mae_r.mean(), 2) if (t.r > 0).any() else 0,
                  round(t[t.r <= 0].mfe_r.mean(), 2) if (t.r <= 0).any() else 0]})
    return out
