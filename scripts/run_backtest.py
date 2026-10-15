"""P1: Trend + pullback стратегийг түүхэн өгөгдөл дээр турших.

Ажиллуулах:  python scripts/run_backtest.py
Үр дүн:      reports/<огноо_цаг>/ хавтаст тайлан, арилжааны жагсаалт, equity график.

Хоёр хувилбарыг харьцуулна (A/B): EMA бүс ба Fibonacci бүс.
Хоёр хугацаанд шалгана: in-sample (тохируулах) ба out-of-sample (огт хараагүй).
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from bot.backtest.engine import BTConfig, Instrument, run_backtest   # noqa: E402
from bot.backtest.metrics import by_symbol, passes_gate, summarize   # noqa: E402
from bot.config import ROOT, load_config                              # noqa: E402
from bot.data.store import load_bars, load_spec, server_to_utc        # noqa: E402
from bot.strategy.trend_pullback import Params, generate_signals      # noqa: E402

KEYS = ["trades", "trades_per_month", "win_rate_pct", "expectancy_r", "profit_factor",
        "return_pct", "cagr_pct", "max_dd_pct", "dd_95", "sharpe", "max_losing_streak", "swap_total"]
LABELS = {"trades": "Арилжаа", "trades_per_month": "Сард", "win_rate_pct": "Win %",
          "expectancy_r": "Expect R", "profit_factor": "PF", "return_pct": "Өгөөж %",
          "cagr_pct": "Жилд %", "max_dd_pct": "Max DD %", "dd_95": "MC DD95 %",
          "sharpe": "Sharpe", "max_losing_streak": "Дараалсан алдагдал", "swap_total": "Swap $"}


def build_instruments(cfg: dict, params: Params) -> list[Instrument]:
    out = []
    for sym in cfg["symbols"]:
        h1, h4, spec = load_bars(sym, "H1"), load_bars(sym, "H4"), load_spec(sym)
        h1["time_utc"] = server_to_utc(h1["time"])
        sig = generate_signals(h1, h4, params)
        out.append(Instrument(sig, spec))
    return out


def main() -> int:
    cfg = load_config()
    bt = cfg.get("backtest", {})
    btc = BTConfig(initial_balance=bt.get("initial_balance", 10_000),
                   risk_pct=cfg["risk"]["risk_per_trade_pct"],
                   daily_loss_limit_pct=cfg["risk"]["daily_loss_limit_pct"],
                   max_drawdown_pct=cfg["risk"]["max_drawdown_pct"],
                   max_open_positions=cfg["risk"]["max_open_positions"],
                   slippage_pips=bt.get("slippage_pips", 0.5),
                   break_even_r=bt.get("break_even_r", 1.0),
                   trail_atr=bt.get("trail_atr", 0.0),
                   max_hold_bars=bt.get("max_hold_bars", 120))
    periods = bt.get("periods", {"in_sample": ["2018-01-01", "2024-01-01"],
                                 "out_of_sample": ["2024-01-01", "2100-01-01"]})

    out_dir = ROOT / "reports" / datetime.now().strftime("%Y%m%d_%H%M")
    out_dir.mkdir(parents=True, exist_ok=True)
    lines, rows = [], []

    for variant in bt.get("variants", ["ema", "fib"]):
        params = Params.from_config(cfg, zone=variant)
        ins = build_instruments(cfg, params)
        data_start = max(i.df.time.iloc[0] for i in ins)
        data_end = min(i.df.time.iloc[-1] for i in ins)
        for pname, (s, e) in periods.items():
            s = max(pd.Timestamp(s), data_start + pd.Timedelta(days=60))   # индикатор халаах 60 хоног
            e = min(pd.Timestamp(e), data_end)
            if s >= e:
                lines.append(f"{variant}/{pname}: өгөгдөл хүрэлцэхгүй ({s:%Y-%m-%d}..{e:%Y-%m-%d})")
                continue
            res = run_backtest(ins, btc, str(s), str(e))
            summ = summarize(res.trades, res.equity, btc.initial_balance, btc.risk_pct, str(s), str(e))
            ok, fails = passes_gate(summ)
            rows.append({"Хувилбар": variant, "Хугацаа": f"{pname} {s:%Y-%m}..{e:%Y-%m}",
                         **{LABELS[k]: summ.get(k, "") for k in KEYS},
                         "Шалгуур": "ДАВСАН" if ok else "ДАВААГҮЙ"})
            tag = f"{variant}_{pname}"
            if not res.trades.empty:
                res.trades.to_csv(out_dir / f"trades_{tag}.csv", index=False)
                lines.append(f"\n== {tag} ==\n" + by_symbol(res.trades).to_string())
            if fails:
                lines.append(f"{tag} шалгуур: " + "; ".join(fails))
            if res.killed:
                lines.append(f"{tag}: KILL-SWITCH идэвхжсэн")
            _plot(res.equity, btc.initial_balance, out_dir / f"equity_{tag}.png", tag)

    table = pd.DataFrame(rows)
    text = ("Backtest тайлан  " + datetime.now().strftime("%Y-%m-%d %H:%M") + "\n"
            + f"Эрсдэл {btc.risk_pct}%/арилжаа, эхний баланс {btc.initial_balance:,.0f}, "
            + f"slippage {btc.slippage_pips} pip, spread = лаа бүрийн бодит spread\n"
            + "АНХААР: түүхэн мэдээний календарь байхгүй тул мэдээний шүүлтүүр backtest-д ороогүй.\n\n"
            + table.to_string(index=False) + "\n" + "\n".join(lines))
    (out_dir / "report.txt").write_text(text, encoding="utf-8")
    print(text)
    print(f"\nТайлан хадгалагдлаа: {out_dir}")
    return 0


def _plot(eq: pd.DataFrame, initial: float, path: Path, title: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    if eq.empty or eq.time.isna().all():
        return
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(eq.time, eq.balance, linewidth=1.2)
    ax.axhline(initial, color="grey", linewidth=0.8, linestyle="--")
    ax.set_title(f"Equity: {title}")
    ax.set_ylabel("Баланс (USD)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    sys.exit(main())
