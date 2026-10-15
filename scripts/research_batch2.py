"""P1.4: Урьдчилан бүртгэсэн 4 туршилт (bot/strategy/experiments2.py-ийн тайлбарыг үз).

Хугацаа:  D1 — in-sample 2010–2019, validation 2020–2023. 2024 оноос хойшхийг АШИГЛАХГҮЙ.
Шалгуур:  F1–F3: хоёр хугацаанд net expectancy > 0, PF ≥ 1.2, тус бүр ≥ 30 арилжаа.
          F4: хоёр хугацаанд Sharpe > 0.5.

Ажиллуулах:  python scripts/research_batch2.py
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from bot.backtest.engine import BTConfig, Instrument, run_backtest   # noqa: E402
from bot.config import ROOT                                          # noqa: E402
from bot.research.stats import ts_momentum                           # noqa: E402
from bot.strategy import experiments as ex                           # noqa: E402
from bot.strategy import experiments2 as ex2                         # noqa: E402

_spec = importlib.util.spec_from_file_location("rb1", Path(__file__).parent / "research_batch.py")
rb1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rb1)
D1_P, INDICES, ALL_D1, load, evaluate, verdict = (rb1.D1_P, rb1.INDICES, rb1.ALL_D1, rb1.load,
                                                  rb1.evaluate, rb1.verdict)
pd.set_option("display.width", 220)


def entry_days(fn, syms, cfg, a, b) -> set:
    ins = [Instrument(fn(load(s, "D1")[0]), load(s, "D1")[1]) for s in syms]
    t = run_backtest(ins, cfg, a, b).trades
    return set(zip(t.symbol, pd.to_datetime(t.entry_time).dt.date)) if not t.empty else set()


def main() -> int:
    out = ROOT / "reports" / ("batch2_" + datetime.now().strftime("%Y%m%d_%H%M"))
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"P1.4 урьдчилан бүртгэсэн туршилтууд  {datetime.now():%Y-%m-%d %H:%M}",
             "Эрсдэл 0.5%/арилжаа, судалгааны горим (kill-switch-гүй). 2024+ ашиглаагүй.", ""]
    base = BTConfig(risk_pct=0.5, break_even_r=0.0, trail_atr=0.0).research()
    d1cfg = replace(base, close_friday_utc_hour=None, max_hold_bars=10, max_open_positions=4)
    plan = [
        ("F1 index TOM", lambda d: ex2.f1_tom(d)),
        ("F2 index TOM+SMA200", lambda d: ex2.f1_tom(d, trend_filter=True)),
        ("F3 index double7", ex2.f3_double7),
    ]
    all_rows, extra = [], []
    for name, fn in plan:
        rows, perinst = evaluate(name, INDICES, "D1", fn, D1_P, d1cfg)
        all_rows += rows
        print(f"  {name}: {verdict(rows, name)}", flush=True)
        if perinst:
            extra += [f"-- {name}: хэрэгсэл бүрээр (net R)", pd.concat(perinst, axis=1).to_string(), ""]
    table = pd.DataFrame(all_rows)
    summary = [f"{n}: {verdict(all_rows, n)}" for n in dict.fromkeys(table["Туршилт"])]

    # E1b-тэй давхцал (in-sample+validation, орсон өдөр)
    a, b = D1_P["in_sample"][0], D1_P["validation"][1]
    e1 = entry_days(lambda d: ex.e1_index_rsi2(d, 5), INDICES, d1cfg, a, b)
    overlap = []
    for name, fn in plan:
        f = entry_days(fn, INDICES, d1cfg, a, b)
        near = {(s, d) for (s, d) in f for (s2, d2) in e1 if s == s2 and abs((d - d2).days) <= 3}
        overlap.append(f"  {name}: {len(f)} арилжаа, E1b-ээс ±3 өдөрт орсон {len(near)} "
                       f"({100 * len(near) / max(len(f), 1):.0f}%)")

    # F4 time-series momentum
    closes, spct = {}, {}
    for s in ALL_D1:
        d, spec = load(s, "D1")
        d = d[d.time >= "2008-01-01"]
        closes[s] = d.set_index("time")["close"]
        spct[s] = float((d["spread"] * spec["point"] / d["close"]).median())
    cl = pd.DataFrame(closes).sort_index()
    f4 = ["F4 Time-series momentum (18 хэрэгсэл, 252 өдөр, сар бүр, swap-гүй)"]
    ok = True
    for pname, (a2, b2) in D1_P.items():
        m = ts_momentum(cl, pd.Series(spct), start=a2, end=b2)
        ok &= m["sharpe"] > 0.5
        f4.append(f"  {pname}: жилийн өгөөж {m['ann_return_pct']}%, хэлбэлзэл {m['ann_vol_pct']}%, "
                  f"Sharpe {m['sharpe']}")
    summary.append(f"F4 TSMOM: {'ДАВСАН' if ok else 'ДАВААГҮЙ'}")
    f4.append("  Шалгуур: хоёр хугацаанд Sharpe > 0.5")

    lines += (["ХУРААНГУЙ", table.to_string(index=False), "", "ДҮГНЭЛТ"] + summary + ["",
              "E1b-тэй давхцал (2010–2023)"] + overlap + [""] + f4 + [""] + extra)
    text = "\n".join(lines)
    (out / "report.txt").write_text(text, encoding="utf-8")
    print("\n" + text + f"\n\nХадгалагдлаа: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
