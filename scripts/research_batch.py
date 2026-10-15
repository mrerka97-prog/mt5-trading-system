"""P1.3: Урьдчилан бүртгэсэн 6 туршилт (bot/strategy/experiments.py-ийн тайлбарыг үз).

Хугацаа:  D1 — in-sample 2010–2019, validation 2020–2023
          H1 — in-sample 2018-11..2021, validation 2022–2023
          2024 оноос хойшхийг АШИГЛАХГҮЙ.
Шалгуур:  in-sample БА validation хоёуланд net expectancy > 0, PF ≥ 1.2, тус бүр ≥ 30 арилжаа.

Ажиллуулах:  python scripts/research_batch.py
"""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from bot.backtest.engine import BTConfig, Instrument, run_backtest            # noqa: E402
from bot.backtest.metrics import summarize                                    # noqa: E402
from bot.config import ROOT                                                   # noqa: E402
from bot.data.store import fill_zero_spread, load_bars, load_spec, server_to_utc  # noqa: E402
from bot.research.stats import hour_seasonality, xs_momentum                  # noqa: E402
from bot.strategy import experiments as ex                                    # noqa: E402

pd.set_option("display.width", 220)
D1_P = {"in_sample": ("2010-01-01", "2020-01-01"), "validation": ("2020-01-01", "2024-01-01")}
H1_P = {"in_sample": ("2018-11-23", "2022-01-01"), "validation": ("2022-01-01", "2024-01-01")}
FX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
      "EURJPY", "GBPJPY", "EURGBP", "AUDJPY"]
INDICES = ["US500", "US30", "GER40", "JP225"]
H1_SYMS = ["EURUSD", "GBPUSD", "USDJPY"]
ALL_D1 = FX + INDICES + ["XAUUSD", "XAGUSD", "OIL"]


def load(sym: str, tf: str) -> tuple[pd.DataFrame, dict]:
    d = fill_zero_spread(load_bars(sym, tf))
    d["time_utc"] = server_to_utc(d["time"])
    return d, load_spec(sym)


def evaluate(name, syms, tf, fn, periods, cfg) -> tuple[list[dict], list[pd.DataFrame]]:
    ins = []
    for s in syms:
        d, spec = load(s, tf)
        ins.append(Instrument(fn(d), spec))
    rows, per = [], []
    for pname, (a, b) in periods.items():
        for cl, c in (("net", cfg), ("gross", replace(cfg, spread_mult=0, slippage_pips=0, include_swap=False))):
            r = run_backtest(ins, c, a, b)
            sm = summarize(r.trades, r.equity, c.initial_balance, c.risk_pct, a, b)
            rows.append({"Туршилт": name, "Хугацаа": pname, "Зардал": cl, "Арилжаа": sm.get("trades", 0),
                         "Win %": sm.get("win_rate_pct"), "Expect R": sm.get("expectancy_r"),
                         "PF": sm.get("profit_factor"), "Max DD %": sm.get("max_dd_pct"),
                         "Sharpe": sm.get("sharpe")})
            if cl == "net" and not r.trades.empty:
                g = r.trades.groupby("symbol").r.agg(["count", "mean"]).round(3)
                g.columns = [f"{pname}_n", f"{pname}_R"]
                per.append(g)
    return rows, per


def verdict(rows: list[dict], name: str) -> str:
    net = {r["Хугацаа"]: r for r in rows if r["Туршилт"] == name and r["Зардал"] == "net"}
    ok = all(net.get(p, {}).get("Арилжаа", 0) >= 30 and (net[p]["Expect R"] or -1) > 0
             and (net[p]["PF"] or 0) >= 1.2 for p in ("in_sample", "validation"))
    return "ДАВСАН" if ok else "ДАВААГҮЙ"


def main() -> int:
    out = ROOT / "reports" / ("batch_" + datetime.now().strftime("%Y%m%d_%H%M"))
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"P1.3 урьдчилан бүртгэсэн туршилтууд  {datetime.now():%Y-%m-%d %H:%M}",
             "Эрсдэл 0.5%/арилжаа, судалгааны горим (kill-switch-гүй). 2024+ ашиглаагүй.", ""]
    base = BTConfig(risk_pct=0.5, break_even_r=0.0, trail_atr=0.0).research()
    d1cfg = replace(base, close_friday_utc_hour=None, max_hold_bars=10)
    plan = [
        ("E1a index RSI2<10", INDICES, "D1", lambda d: ex.e1_index_rsi2(d, 10), D1_P,
         replace(d1cfg, max_open_positions=4)),
        ("E1b index RSI2<5", INDICES, "D1", lambda d: ex.e1_index_rsi2(d, 5), D1_P,
         replace(d1cfg, max_open_positions=4)),
        ("E2 FX D1 reversal", FX, "D1", ex.e2_fx_reversal, D1_P, replace(d1cfg, max_open_positions=5)),
        ("E3a London breakout", H1_SYMS, "H1", ex.e3a_london_breakout, H1_P,
         replace(base, max_open_positions=3, max_hold_bars=24)),
        ("E3b Asian fade", H1_SYMS, "H1", ex.e3b_asian_fade, H1_P,
         replace(base, max_open_positions=3, max_hold_bars=24)),
        ("E4 BB Asia MR", H1_SYMS, "H1", ex.e4_bb_asia, H1_P,
         replace(base, max_open_positions=3, max_hold_bars=12)),
    ]
    all_rows = []
    for name, syms, tf, fn, per, cfg in plan:
        rows, perinst = evaluate(name, syms, tf, fn, per, cfg)
        all_rows += rows
        print(f"  {name}: {verdict(rows, name)}", flush=True)
        if perinst:
            lines += [f"-- {name}: хэрэгсэл бүрээр (net R)", pd.concat(perinst, axis=1).to_string(), ""]
    table = pd.DataFrame(all_rows)
    summary = [f"{n}: {verdict(all_rows, n)}" for n in dict.fromkeys(table["Туршилт"])]
    lines = lines[:3] + ["ХУРААНГУЙ", table.to_string(index=False), "", "ДҮГНЭЛТ"] + summary + [""] + lines[3:]

    # E5: цагийн улирлын хэв маяг
    lines += ["E5 UTC цаг бүрийн H1 өгөөж: in-sample |t| > 3.2 (Bonferroni), validation-д ижил тэмдэгтэй эсэх"]
    for s in H1_SYMS:
        d, _ = load(s, "H1")
        a = hour_seasonality(d, *H1_P["in_sample"])
        b = hour_seasonality(d, *H1_P["validation"])
        sig = a[a.t.abs() > 3.2]
        if sig.empty:
            lines.append(f"  {s}: ач холбогдолтой цаг алга")
        for h, r in sig.iterrows():
            same = (b.loc[h, "mean_bp"] * r.mean_bp > 0) if h in b.index else False
            lines.append(f"  {s} {h:02d}:00 UTC: IS {r.mean_bp:+.2f}bp t={r.t:.1f} | VAL {b.loc[h, 'mean_bp']:+.2f}bp "
                         f"t={b.loc[h, 't']:.1f} → {'давтагдсан' if same else 'давтагдаагүй'}")
    lines.append("")

    # E6: cross-sectional momentum
    closes, spct = {}, {}
    for s in ALL_D1:
        d, spec = load(s, "D1")
        d = d[d.time >= "2009-01-01"]
        closes[s] = d.set_index("time")["close"]
        spct[s] = float((d["spread"] * spec["point"] / d["close"]).median())
    cl = pd.DataFrame(closes).sort_index()
    sp = pd.Series(spct)
    lines.append("E6 Cross-sectional momentum (18 хэрэгсэл, сар бүр, 3 long / 3 short, swap-гүй)")
    for pname, (a, b) in D1_P.items():
        m = xs_momentum(cl, sp, start=a, end=b)
        lines.append(f"  {pname}: жилийн өгөөж {m['ann_return_pct']}%, хэлбэлзэл {m['ann_vol_pct']}%, Sharpe {m['sharpe']}")
    lines.append("  Шалгуур: хоёр хугацаанд Sharpe > 0.5")

    text = "\n".join(lines)
    (out / "report.txt").write_text(text, encoding="utf-8")
    print("\n" + text + f"\n\nХадгалагдлаа: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
