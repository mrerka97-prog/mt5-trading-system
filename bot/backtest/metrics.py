"""Гүйцэтгэлийн үзүүлэлтүүд (баримтын 9, 13-р хэсэг)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown_pct(balance: pd.Series) -> float:
    if balance.empty:
        return 0.0
    peak = balance.cummax()
    return float(((balance - peak) / peak).min() * 100)


def monte_carlo_dd(r: np.ndarray, risk_pct: float, runs: int = 10_000, seed: int = 7) -> dict:
    """Арилжааны R-ийн дарааллыг 10,000 удаа холиод drawdown-ийн тархалтыг тооцно."""
    if len(r) < 5:
        return {"dd_median": np.nan, "dd_95": np.nan, "dd_99": np.nan}
    rng = np.random.default_rng(seed)
    dds = np.empty(runs)
    for j in range(runs):
        seq = rng.permutation(r)
        bal = np.cumprod(1 + seq * risk_pct / 100)
        bal = np.concatenate([[1.0], bal])
        dds[j] = ((bal - np.maximum.accumulate(bal)) / np.maximum.accumulate(bal)).min() * 100
    return {"dd_median": float(np.median(dds)), "dd_95": float(np.percentile(dds, 5)),
            "dd_99": float(np.percentile(dds, 1))}


def summarize(trades: pd.DataFrame, equity: pd.DataFrame, initial: float, risk_pct: float,
              start: str, end: str) -> dict:
    n = len(trades)
    if n == 0:
        return {"trades": 0}
    r = trades["r"].to_numpy()
    wins, losses = trades[trades.pnl > 0], trades[trades.pnl <= 0]
    gross_win, gross_loss = wins.pnl.sum(), -losses.pnl.sum()
    final = float(trades["balance"].iloc[-1])
    years = max((pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25, 1e-9)
    bal = pd.concat([pd.Series([initial]), equity["balance"]], ignore_index=True)

    daily = equity.set_index("time")["balance"].resample("D").last().ffill()
    daily_ret = daily.pct_change().dropna()
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) if daily_ret.std() > 0 else 0.0

    streak = worst = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0
        worst = max(worst, streak)

    out = {
        "trades": n,
        "trades_per_month": round(n / (years * 12), 1),
        "win_rate_pct": round(len(wins) / n * 100, 1),
        "avg_win_r": round(float(wins.r.mean()) if len(wins) else 0, 2),
        "avg_loss_r": round(float(losses.r.mean()) if len(losses) else 0, 2),
        "expectancy_r": round(float(r.mean()), 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "net_profit": round(final - initial, 2),
        "return_pct": round((final / initial - 1) * 100, 2),
        "cagr_pct": round(((final / initial) ** (1 / years) - 1) * 100, 2) if final > 0 else -100.0,
        "max_dd_pct": round(max_drawdown_pct(bal), 2),
        "sharpe": round(sharpe, 2),
        "max_losing_streak": worst,
        "swap_total": round(float(trades.swap.sum()), 2),
    }
    mc = monte_carlo_dd(r, risk_pct)
    out.update({k: round(v, 2) for k, v in mc.items()})
    return out


def by_symbol(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    g = trades.groupby("symbol")
    return pd.DataFrame({
        "trades": g.size(),
        "win_rate_pct": (g.apply(lambda x: (x.pnl > 0).mean() * 100, include_groups=False)).round(1),
        "expectancy_r": g.r.mean().round(3),
        "net_profit": g.pnl.sum().round(2),
    })


def passes_gate(s: dict) -> tuple[bool, list[str]]:
    """Баримтын амжилтын шалгуур: PF ≥ 1.3, max DD ≤ 15%, ≥ 100 арилжаа, expectancy > 0."""
    fails = []
    if s.get("trades", 0) < 100:
        fails.append(f"арилжааны тоо {s.get('trades', 0)} < 100")
    if s.get("profit_factor", 0) < 1.3:
        fails.append(f"profit factor {s.get('profit_factor')} < 1.3")
    if s.get("max_dd_pct", -100) < -15:
        fails.append(f"max drawdown {s.get('max_dd_pct')}% > 15%")
    if s.get("expectancy_r", -1) <= 0:
        fails.append(f"expectancy {s.get('expectancy_r')}R ≤ 0")
    return (not fails), fails
