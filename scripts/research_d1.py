"""P1.2-2: D1 trend-following, олон зах зээл.

Ажиллуулах:
  python scripts/research_d1.py            in-sample (2010–2019) + validation (2020–2023)
  python scripts/research_d1.py --final    + out-of-sample (2024–). ЗӨВХӨН НЭГ УДАА, сонголт хийсний дараа!
Үр дүн: reports/d1_<огноо_цаг>/report.txt
"""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from bot.backtest.engine import BTConfig, Instrument, run_backtest    # noqa: E402
from bot.backtest.metrics import summarize                            # noqa: E402
from bot.config import ROOT, load_config                              # noqa: E402
from bot.data.store import bars_path, fill_zero_spread, load_bars, load_spec, server_to_utc  # noqa: E402
from bot.strategy.d1_trend import D1Params, generate_signals          # noqa: E402

pd.set_option("display.width", 200)


def main() -> int:
    final = "--final" in sys.argv
    cfg = load_config()
    rc = cfg["research_d1"]
    periods = dict(rc["periods"])
    if not final:
        periods.pop("out_of_sample")
    keys = [k for k in rc["universe"] if bars_path(k, "D1").exists()]
    if not keys:
        print("D1 өгөгдөл алга. Эхлээд: python scripts/download_universe.py")
        return 1
    data = {}
    for k in keys:
        d = fill_zero_spread(load_bars(k, "D1"))
        d["time_utc"] = server_to_utc(d["time"])
        data[k] = (d, load_spec(k))

    out_dir = ROOT / "reports" / ("d1_" + datetime.now().strftime("%Y%m%d_%H%M"))
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"D1 trend-following судалгаа  {datetime.now():%Y-%m-%d %H:%M}",
             f"Хэрэгсэл ({len(keys)}): {', '.join(keys)}",
             f"Эрсдэл {rc['risk_pct']}%/арилжаа, нэг зэрэг ≤ {rc['max_open_positions']} позиц, "
             f"kill-switch-гүй (судалгааны горим)",
             "Анхаар: кросс хос, индексийн 1 tick-ийн үнийг татсан өдрийн утгаар тогтмол гэж тооцсон.",
             ""]
    rows, per_inst = [], []
    for v in rc["variants"]:
        v = dict(v)
        trail = v.pop("trail_atr")
        p = D1Params(**v)
        ins = [Instrument(generate_signals(d, p), spec) for d, spec in data.values()]
        base = BTConfig(risk_pct=rc["risk_pct"], max_open_positions=rc["max_open_positions"],
                        break_even_r=0.0, trail_atr=trail, trail_start_r=0.0, max_hold_bars=100_000,
                        close_friday_utc_hour=None).research()
        for pname, (s, e) in periods.items():
            for cost_label, c in (("net", base), ("gross", replace(base, spread_mult=0, slippage_pips=0,
                                                                   include_swap=False))):
                r = run_backtest(ins, c, s, e)
                e2 = min(pd.Timestamp(e), max(d.time.iloc[-1] for d, _ in data.values()))
                sm = summarize(r.trades, r.equity, c.initial_balance, c.risk_pct, s, str(e2))
                rows.append({"Хувилбар": f"{p.label} tr{trail}", "Хугацаа": pname, "Зардал": cost_label,
                             "Арилжаа": sm.get("trades"), "Win %": sm.get("win_rate_pct"),
                             "Expect R": sm.get("expectancy_r"), "PF": sm.get("profit_factor"),
                             "Жилд %": sm.get("cagr_pct"), "Max DD %": sm.get("max_dd_pct"),
                             "Sharpe": sm.get("sharpe"), "Swap $": sm.get("swap_total")})
                if cost_label == "net" and not r.trades.empty:
                    g = r.trades.groupby("symbol").r.agg(["count", "mean", "sum"]).round(2)
                    g.insert(0, "period", pname)
                    g.insert(0, "variant", f"{p.label} tr{trail}")
                    per_inst.append(g.reset_index())
                    r.trades.to_csv(out_dir / f"trades_{p.label.replace('/', '-')}_tr{trail}_{pname}.csv",
                                    index=False)
            print(f"  {p.label} tr{trail} / {pname} дууслаа", flush=True)

    table = pd.DataFrame(rows)
    lines += ["ХУРААНГУЙ", table.to_string(index=False), ""]
    if per_inst:
        pi = pd.concat(per_inst)
        piv = pi[pi.period != "out_of_sample"].pivot_table(index="symbol", columns="variant",
                                                           values="sum", aggfunc="sum").round(1)
        lines += ["ХЭРЭГСЭЛ БҮРИЙН НИЙТ R (in-sample + validation, net)", piv.to_string(), ""]
    lines += ["Үнэлэх дүрэм: in-sample БА validation хоёуланд net expectancy > 0, PF > 1.2,",
              "олон хэрэгсэлд тархсан ашигтай хувилбарыг л сонгоно. Дараа нь --final-ийг НЭГ удаа ажиллуулна."]
    text = "\n".join(lines)
    (out_dir / "report.txt").write_text(text, encoding="utf-8")
    print("\n" + text + f"\n\nХадгалагдлаа: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
