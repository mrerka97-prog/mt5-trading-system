"""P1.2-1: Арилжааны зардлын шинжилгээ (зөвхөн in-sample 2018–2023, H1 өгөгдөл).

Асуулт: стратегид зардалгүйгээр (gross) давуу тал байна уу? Байвал зардал л асуудал,
байхгүй бол дансны төрөл солих нь тус болохгүй.

Ажиллуулах:  python scripts/cost_analysis.py
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from bot.backtest.engine import BTConfig, Instrument, run_backtest   # noqa: E402
from bot.backtest.metrics import summarize                           # noqa: E402
from bot.config import load_config                                   # noqa: E402
from bot.data.store import fill_zero_spread, load_bars, load_spec, server_to_utc  # noqa: E402
from bot.strategy import donchian                                    # noqa: E402
from bot.strategy.trend_pullback import Params, generate_signals     # noqa: E402

SCENARIOS = [("Бүрэн зардал", 1.0, 0.5, True), ("Хагас зардал", 0.5, 0.25, True),
             ("Spread-гүй, swap-тай", 0.0, 0.0, True), ("Зардалгүй (gross)", 0.0, 0.0, False)]


def main() -> int:
    cfg = load_config()
    is_start, is_end = cfg["backtest"]["periods"]["in_sample"]
    raw, spreads = {}, []
    for s in cfg["symbols"]:
        h1, h4, spec = fill_zero_spread(load_bars(s, "H1")), load_bars(s, "H4"), load_spec(s)
        h1["time_utc"] = server_to_utc(h1["time"])
        h4 = h4[h4["time"] >= h1["time"].iloc[0] - pd.Timedelta(days=200)].reset_index(drop=True)
        raw[s] = (h1, h4, spec)
        pip_pts = 10 if spec["digits"] in (3, 5) else 1
        d = h1[(h1.time >= is_start) & (h1.time < is_end)]
        spreads.append({"symbol": s, "spread_median_pip": round(d.spread.median() / pip_pts, 2),
                        "spread_p90_pip": round(d.spread.quantile(0.9) / pip_pts, 2)})
    start = max(max(r[0].time.iloc[0] for r in raw.values()) + pd.Timedelta(days=60), pd.Timestamp(is_start))
    print(f"Зардлын шинжилгээ — in-sample {start:%Y-%m-%d} → {is_end}\n")
    print("Түүхэн spread (H1 лааны бүртгэлээр):")
    print(pd.DataFrame(spreads).to_string(index=False), "\n")

    base = BTConfig(risk_pct=cfg["risk"]["risk_per_trade_pct"],
                    max_open_positions=cfg["risk"]["max_open_positions"]).research()
    strategies = {
        "Pullback (одоогийн)": (
            [Instrument(generate_signals(h1, h4, Params.from_config(cfg, zone="ema")), sp)
             for h1, h4, sp in raw.values()], base),
        "Donchian H4 55/2.0": (
            [Instrument(donchian.generate_signals(h1, h4, donchian.DonchianParams(entry_n=55)), sp)
             for h1, h4, sp in raw.values()],
            replace(base, break_even_r=0.0, trail_atr=2.0, trail_start_r=0.0, max_hold_bars=24 * 60,
                    close_friday_utc_hour=None)),
    }
    rows = []
    for sname, (ins, c0) in strategies.items():
        for label, sm, slip, swap in SCENARIOS:
            c = replace(c0, spread_mult=sm, slippage_pips=slip, include_swap=swap)
            r = run_backtest(ins, c, str(start), is_end)
            s = summarize(r.trades, r.equity, c.initial_balance, c.risk_pct, str(start), is_end)
            rows.append({"Стратеги": sname, "Зардал": label, "Арилжаа": s.get("trades"),
                         "Win %": s.get("win_rate_pct"), "Expect R": s.get("expectancy_r"),
                         "PF": s.get("profit_factor"), "Max DD %": s.get("max_dd_pct")})
            print(f"  {sname} / {label}: {s.get('expectancy_r')}R", flush=True)
    print("\n" + pd.DataFrame(rows).to_string(index=False))
    print("\nТайлбар: 'Зардалгүй (gross)' мөр эерэг бөгөөд PF > 1.2 бол давуу тал бий, зардал л асуудал.\n"
          "         Сөрөг эсвэл ~0 бол зардлыг бууруулсан ч стратеги ашигтай болохгүй.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
