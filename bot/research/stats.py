"""Арилжааны дүрэмгүй статистик туршилтууд (E5 улирлын хэв маяг, E6 cross-sectional momentum)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def hour_seasonality(h1: pd.DataFrame, start, end) -> pd.DataFrame:
    """UTC цаг бүрийн H1 лааны дундаж өгөөж (bp) ба t-stat."""
    d = h1[(h1.time >= pd.Timestamp(start)) & (h1.time < pd.Timestamp(end))]
    r = (d["close"] / d["open"] - 1) * 1e4
    g = r.groupby(d["time_utc"].dt.hour)
    out = pd.DataFrame({"n": g.size(), "mean_bp": g.mean(), "t": g.mean() / (g.std() / np.sqrt(g.size()))})
    return out.round(3)


def xs_momentum(closes: pd.DataFrame, spread_pct: pd.Series, lookback: int = 63, n_side: int = 3,
                start=None, end=None) -> dict:
    """Сар бүр: 63 өдрийн өгөөж / хэлбэлзэлээр эрэмбэлж, шилдэг 3-ыг long, сүүлийн 3-ыг short
    (хэлбэлзлийн урвуугаар жигнэсэн). Зардал = эргэлт × spread. Swap тооцоогүй."""
    px = closes.ffill()
    ret = px.pct_change()
    vol = ret.rolling(lookback).std()
    score = (px / px.shift(lookback) - 1) / (vol * np.sqrt(lookback))
    month_end = px.index.to_series().groupby(px.index.to_period("M")).max().values
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    cur = pd.Series(0.0, index=px.columns)
    costs = pd.Series(0.0, index=px.index)
    for t in px.index:
        if t in month_end and score.loc[t].notna().sum() >= 2 * n_side:
            s = score.loc[t].dropna().sort_values()
            new = pd.Series(0.0, index=px.columns)
            inv = 1 / vol.loc[t]
            longs, shorts = s.index[-n_side:], s.index[:n_side]
            new[longs] = inv[longs] / inv[longs].sum() * 0.5
            new[shorts] = -inv[shorts] / inv[shorts].sum() * 0.5
            costs[t] = ((new - cur).abs() * spread_pct.reindex(px.columns).fillna(0)).sum()
            cur = new
        w.loc[t] = cur
    port = (w.shift(1) * ret).sum(axis=1) - costs
    if start:
        port = port[port.index >= pd.Timestamp(start)]
    if end:
        port = port[port.index < pd.Timestamp(end)]
    port = port[port.index.dayofweek < 5]
    ann = port.mean() * 252
    vola = port.std() * np.sqrt(252)
    return {"ann_return_pct": round(ann * 100, 2), "ann_vol_pct": round(vola * 100, 2),
            "sharpe": round(ann / vola, 2) if vola > 0 else 0.0, "days": len(port)}


def ts_momentum(closes: pd.DataFrame, spread_pct: pd.Series, lookback: int = 252, vol_lb: int = 63,
                start=None, end=None) -> dict:
    """P1.4 F4: сар бүр 252 өдрийн өгөөжийн тэмдгээр long/short, хэлбэлзлийн урвуугаар жигнэж,
    нийт |жин| = 1. Зардал = эргэлт × spread. Swap тооцоогүй."""
    px = closes.ffill()
    ret = px.pct_change()
    vol = ret.rolling(vol_lb).std()
    mom = px / px.shift(lookback) - 1
    month_end = set(px.index.to_series().groupby(px.index.to_period("M")).max().values)
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    cur = pd.Series(0.0, index=px.columns)
    costs = pd.Series(0.0, index=px.index)
    sp = spread_pct.reindex(px.columns).fillna(0)
    for t in px.index:
        if t in month_end:
            m, v = mom.loc[t], vol.loc[t]
            ok = m.notna() & v.notna() & (v > 0)
            if ok.sum() >= 5:
                raw = np.sign(m[ok]) / v[ok]
                new = pd.Series(0.0, index=px.columns)
                new[ok[ok].index] = raw / raw.abs().sum()
                costs[t] = ((new - cur).abs() * sp).sum()
                cur = new
        w.loc[t] = cur
    port = (w.shift(1) * ret).sum(axis=1) - costs
    if start:
        port = port[port.index >= pd.Timestamp(start)]
    if end:
        port = port[port.index < pd.Timestamp(end)]
    port = port[port.index.dayofweek < 5]
    ann = port.mean() * 252
    vola = port.std() * np.sqrt(252)
    return {"ann_return_pct": round(ann * 100, 2), "ann_vol_pct": round(vola * 100, 2),
            "sharpe": round(ann / vola, 2) if vola > 0 else 0.0, "days": len(port)}
