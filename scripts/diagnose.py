"""P1.1: Стратегийн оношлогоо ба тогтвортой байдлын тест. ЗӨВХӨН in-sample (2018–2023) өгөгдөл.

Ажиллуулах:  python scripts/diagnose.py          (5–15 минут)
Үр дүн:      reports/diag_<огноо_цаг>/diagnose.txt
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace
from datetime import datetime
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from bot.backtest.engine import BTConfig, Instrument, run_backtest      # noqa: E402
from bot.backtest.metrics import summarize                              # noqa: E402
from bot.config import ROOT, load_config                                # noqa: E402
from bot.data.store import load_bars, load_spec, server_to_utc          # noqa: E402
from bot.research.diagnostics import barrier_grid, breakdown, trend_edge  # noqa: E402
from bot.strategy import donchian                                       # noqa: E402
from bot.strategy.trend_pullback import Params, generate_signals        # noqa: E402

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)


def main() -> int:
    t0 = time.time()
    cfg = load_config()
    bt = cfg.get("backtest", {})
    is_start, is_end = bt["periods"]["in_sample"]
    out_dir = ROOT / "reports" / ("diag_" + datetime.now().strftime("%Y%m%d_%H%M"))
    out_dir.mkdir(parents=True, exist_ok=True)
    rep: list[str] = []

    def say(title: str, obj=None):
        block = f"\n{'=' * 78}\n{title}\n{'=' * 78}\n" + ("" if obj is None else
                                                       (obj if isinstance(obj, str) else obj.to_string()))
        rep.append(block)
        print(block, flush=True)

    raw = {}
    for s in cfg["symbols"]:
        h1, h4, spec = load_bars(s, "H1"), load_bars(s, "H4"), load_spec(s)
        h1["time_utc"] = server_to_utc(h1["time"])
        h4 = h4[h4["time"] >= h1["time"].iloc[0] - pd.Timedelta(days=200)].reset_index(drop=True)
        raw[s] = (h1, h4, spec)
    start = max(max(r[0].time.iloc[0] for r in raw.values()) + pd.Timedelta(days=60), pd.Timestamp(is_start))
    say(f"ОНОШЛОГОО — зөвхөн in-sample: {start:%Y-%m-%d} → {is_end}  (out-of-sample-ийг ашиглаагүй)")

    base = BTConfig(initial_balance=bt.get("initial_balance", 10_000),
                    risk_pct=cfg["risk"]["risk_per_trade_pct"],
                    max_open_positions=cfg["risk"]["max_open_positions"],
                    slippage_pips=bt.get("slippage_pips", 0.5)).research()

    # ---------- A. Trend шүүлтүүрийн таамаглах чадвар ----------
    rows = []
    sigs = {}
    for s, (h1, h4, spec) in raw.items():
        d = generate_signals(h1, h4, Params.from_config(cfg, zone="ema"))
        sigs[s] = d
        dd = d[(d.time >= start) & (d.time < pd.Timestamp(is_end))]
        e = trend_edge(dd)
        e.insert(0, "symbol", s)
        rows.append(e)
    say("A. H4 trend шүүлтүүр ирээдүйн хөдөлгөөнийг таамаглаж чадах уу?\n"
        "   mean_atr > 0 ба t_stat > 2 бол утгатай. ~0 бол trend шүүлтүүр санамсаргүйтэй адил.",
        pd.concat(rows, ignore_index=True))

    # ---------- B. SL/TP хослолын тор (exit удирдлагагүй) ----------
    for zone in ("ema", "fib"):
        parts = []
        for s, (h1, h4, spec) in raw.items():
            d = sigs[s] if zone == "ema" else generate_signals(h1, h4, Params.from_config(cfg, zone=zone))
            pip = spec["point"] * 10 if spec["digits"] in (3, 5) else spec["point"]
            g = barrier_grid(d, spec["point"], pip, [1.0, 1.5, 2.0, 2.5], [1.0, 1.5, 2.0, 3.0],
                             start=start, end=is_end)
            g["symbol"] = s
            parts.append(g)
        g = pd.concat(parts)
        g["sum_r"] = g.expectancy_r * g.trades
        tot = g.groupby(["sl_atr", "rr"]).agg(trades=("trades", "sum"), sum_r=("sum_r", "sum")).reset_index()
        tot["expectancy_r"] = (tot.sum_r / tot.trades).round(3)
        piv = tot.pivot(index="sl_atr", columns="rr", values="expectancy_r")
        piv.columns = [f"RR {c}" for c in piv.columns]
        say(f"B. [{zone}] SL (ATR) × R/R торын expectancy (R), 3 хос нийлбэр. "
            f"Дохио {int(tot.trades.iloc[0])}.\n   Бүх нүд сөрөг бол орох цэг өөрөө давуу талгүй.", piv)

    # ---------- C. Одоогийн тохиргооны задаргаа (судалгааны горим) ----------
    ins = [Instrument(sigs[s], raw[s][2]) for s in raw]
    res = run_backtest(ins, base, str(start), is_end)
    summ = summarize(res.trades, res.equity, base.initial_balance, base.risk_pct, str(start), is_end)
    say("C. Одоогийн тохиргоо, kill-switch-гүй (бүтэн хугацаа)",
        pd.Series(summ).to_string())
    for k, v in breakdown(res.trades).items():
        say(f"C. задаргаа: {k}", v)
    if not res.trades.empty:
        res.trades.to_csv(out_dir / "trades_current_research.csv", index=False)

    # ---------- D. Тогтвортой байдлын тор (engine-ээр) ----------
    grid = []
    combos = list(product([15, 20, 25], [1.0, 1.5, 2.0], [1.5, 2.0, 3.0], [0.0, 1.0]))
    print(f"\nD. {len(combos)} хослол туршиж байна...", flush=True)
    cache = {}
    for n, (adx_min, sl, rr, be) in enumerate(combos, 1):
        if adx_min not in cache:
            cache[adx_min] = {s: generate_signals(h1, h4, Params.from_config(cfg, zone="ema", adx_min=adx_min))
                              for s, (h1, h4, _) in raw.items()}
        ins = []
        for s, d in cache[adx_min].items():
            d = d.copy()
            d["sl_dist"] = sl * d["atr"]
            d["tp_dist"] = sl * rr * d["atr"]
            ins.append(Instrument(d, raw[s][2]))
        r = run_backtest(ins, replace(base, break_even_r=be), str(start), is_end)
        sm = summarize(r.trades, r.equity, base.initial_balance, base.risk_pct, str(start), is_end)
        grid.append({"adx_min": adx_min, "sl_atr": sl, "rr": rr, "break_even": be,
                     **{k: sm.get(k) for k in ("trades", "win_rate_pct", "expectancy_r",
                                               "profit_factor", "max_dd_pct")}})
        if n % 9 == 0:
            print(f"   {n}/{len(combos)}", flush=True)
    gdf = pd.DataFrame(grid)
    gdf.to_csv(out_dir / "grid.csv", index=False)
    # Хөршүүдийн дундаж: нэг нүд биш, хүрээгээрээ сайн эсэх
    gdf["neighbor_exp"] = gdf.apply(lambda r: gdf[(gdf.break_even == r.break_even)
                                                  & ((gdf.adx_min - r.adx_min).abs() <= 5)
                                                  & ((gdf.sl_atr - r.sl_atr).abs() <= 0.5)
                                                  & ((gdf.rr - r.rr).abs() <= 1.0)].expectancy_r.mean(), axis=1).round(3)
    say("D. Тогтвортой байдлын тор — expectancy-гаар эрэмбэлсэн эхний 15\n"
        "   neighbor_exp = ойролцоох тохиргоонуудын дундаж. Ганц өндөр нүд биш, хөршүүд нь ч эерэг байх ёстой.",
        gdf.sort_values("expectancy_r", ascending=False).head(15).to_string(index=False))
    say("D. Хамгийн муу 5", gdf.sort_values("expectancy_r").head(5).to_string(index=False))
    pos = (gdf.expectancy_r > 0).mean() * 100
    say(f"D. Нийт {len(gdf)} хослолын {pos:.0f}% нь эерэг expectancy-тэй.")

    # ---------- E. Donchian breakout (харьцуулах суурь) ----------
    drows = []
    for n_entry, trail in product([20, 55], [2.0, 3.0]):
        p = donchian.DonchianParams(entry_n=n_entry)
        ins = [Instrument(donchian.generate_signals(h1, h4, p), spec) for h1, h4, spec in raw.values()]
        c = replace(base, break_even_r=0.0, trail_atr=trail, trail_start_r=0.0,
                    max_hold_bars=24 * 60, close_friday_utc_hour=None)
        r = run_backtest(ins, c, str(start), is_end)
        sm = summarize(r.trades, r.equity, base.initial_balance, base.risk_pct, str(start), is_end)
        drows.append({"entry_n_H4": n_entry, "trail_atr_H4": trail,
                      **{k: sm.get(k) for k in ("trades", "win_rate_pct", "expectancy_r", "profit_factor",
                                                "return_pct", "max_dd_pct", "swap_total")}})
    say("E. Donchian breakout (H4), trailing stop, Баасан гарагт хаахгүй", pd.DataFrame(drows).to_string(index=False))

    say(f"Дууслаа: {time.time() - t0:.0f} сек. Файлууд: {out_dir}")
    (out_dir / "diagnose.txt").write_text("\n".join(rep), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
