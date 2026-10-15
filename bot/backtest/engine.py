"""Backtest хөдөлгүүр (SimBroker). Live горимтой ижил Strategy + Risk кодыг ашиглана.

Бодит байдалд ойртуулах дүрмүүд (баримтын 10-р хэсэг):
  * MT5-ийн лаа нь BID үнэ. Long-д ASK (= bid + тухайн лааны spread)-аар орно,
    short-ийг ASK-аар хаана.
  * Орох болон SL-ээр гарахад slippage нэмнэ.
  * Нэг лаанд SL ба TP хоёулаа хүрвэл SL гэж тооцно (муу тал).
  * Үнэ SL-ийг давж нээгдвэл (gap) нээлтийн үнээр хаана.
  * Шөнө дамжуулбал swap, Лхагва гарагийн шөнө 3 дахин.
  * Lot = sizing.calculate_lot (доош тоймлоно, < 0.01 бол арилжаа хийхгүй).
  * Өдрийн алдагдлын лимит, max drawdown kill-switch, нээлттэй позицын хязгаар.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from bot.risk.sizing import SymbolSpec, calculate_lot


@dataclass(frozen=True)
class BTConfig:
    initial_balance: float = 10_000.0
    risk_pct: float = 0.5
    daily_loss_limit_pct: float = 2.0
    max_drawdown_pct: float = 10.0
    max_open_positions: int = 2
    slippage_pips: float = 0.5
    break_even_r: float = 1.0          # +1R хүрвэл SL-ийг орох үнэ рүү (0 = унтраалттай)
    trail_atr: float = 0.0             # 0 = trailing унтраалттай
    trail_start_r: float = 1.0         # trailing хэдэн R-ээс эхлэх (0 = шууд)
    max_hold_bars: int = 120           # 5 хоног (H1)
    close_friday_utc_hour: int | None = 20
    use_kill_switch: bool = True       # судалгааны горимд False
    use_daily_limit: bool = True       # судалгааны горимд False
    spread_mult: float = 1.0           # зардлын шинжилгээ: 0 = spread-гүй
    include_swap: bool = True

    def research(self, **kw) -> "BTConfig":
        """Судалгааны горим: kill-switch, өдрийн лимитгүйгээр бүх хугацааг хэмжинэ."""
        from dataclasses import replace
        return replace(self, use_kill_switch=False, use_daily_limit=False, **kw)


@dataclass
class Position:
    symbol: str
    side: int
    lot: float
    entry_time: pd.Timestamp
    entry: float
    sl: float
    tp: float
    risk_money: float
    atr: float
    reason: str
    sl_initial: float = 0.0
    bars: int = 0
    swap: float = 0.0
    be_done: bool = False
    mfe: float = 0.0     # хамгийн их ашигтай хөдөлгөөн (үнийн зай)
    mae: float = 0.0     # хамгийн их эсрэг хөдөлгөөн (үнийн зай)


@dataclass
class BTResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    events: list[str] = field(default_factory=list)
    killed: bool = False


class Instrument:
    """Нэг symbol-ын өгөгдөл, нөхцөл."""

    def __init__(self, signals: pd.DataFrame, spec: dict):
        self.df = signals.reset_index(drop=True)
        self.spec = spec
        self.name = spec["name"]
        self.pip = spec["point"] * 10 if spec["digits"] in (3, 5) else spec["point"]
        self.sizing_spec = SymbolSpec(spec["name"], spec["tick_size"], spec["tick_value"],
                                      spec["volume_min"], spec["volume_step"], spec["volume_max"],
                                      spec["digits"])

    def tick_value(self, price: float) -> float:
        """1 lot-ын 1 tick-ийн үнэ дансны валютаар (USDJPY-д үнээс хамаарч өөрчлөгдөнө)."""
        acc = self.spec.get("account_currency", "USD")
        if self.spec.get("currency_profit") == acc:
            return self.spec["tick_size"] * self.spec["contract_size"]
        if self.spec.get("currency_base") == acc:
            return self.spec["tick_size"] * self.spec["contract_size"] / price
        return self.spec["tick_value"]

    def money(self, price_diff: float, lot: float, price: float) -> float:
        return price_diff / self.spec["tick_size"] * self.tick_value(price) * lot

    def spec_at(self, price: float) -> SymbolSpec:
        s = self.sizing_spec
        return SymbolSpec(s.name, s.tick_size, self.tick_value(price), s.volume_min,
                          s.volume_step, s.volume_max, s.digits)

    def swap_money(self, pos: Position, price: float) -> float:
        pts = self.spec["swap_long"] if pos.side == 1 else self.spec["swap_short"]
        if self.spec.get("swap_mode", 1) == 1:   # points
            return self.money(pts * self.spec["point"], pos.lot, price)
        return pts * pos.lot                      # бусад горимд ойролцоогоор


def run_backtest(instruments: list[Instrument], cfg: BTConfig,
                 start: str | None = None, end: str | None = None) -> BTResult:
    # Хурдны тулд багана бүрийг numpy массив болгоно
    cols = []
    frames = []
    for k, ins in enumerate(instruments):
        d = ins.df
        c = {n: d[n].to_numpy() for n in ("open", "high", "low", "close", "signal", "sl_dist",
                                          "tp_dist", "atr", "reason")}
        c["spread"] = d["spread"].to_numpy() if "spread" in d else None
        # Стратегийн өөрийн гарах дохио (жишээ нь дундаж руу буцсан): лаа хаагдахад хаана
        c["exit_long"] = d["exit_long"].to_numpy() if "exit_long" in d else None
        c["exit_short"] = d["exit_short"].to_numpy() if "exit_short" in d else None
        c["time"] = list(d["time"].dt.to_pydatetime())
        c["time_utc"] = list(d["time_utc"].dt.to_pydatetime()) if "time_utc" in d else c["time"]
        cols.append(c)
        mask = pd.Series(True, index=d.index)
        if start:
            mask &= d["time"] >= pd.Timestamp(start)
        if end:
            mask &= d["time"] < pd.Timestamp(end)
        idx = d.index[mask].to_numpy()
        frames.append(pd.DataFrame({"time": d["time"].to_numpy()[idx], "k": k, "i": idx}))
    tl = pd.concat(frames).sort_values(["time", "k"])
    timeline = zip(tl["k"].to_numpy(), tl["i"].to_numpy())

    balance = peak = cfg.initial_balance
    killed = False
    day, day_start_bal, day_blocked = None, balance, False
    open_pos: dict[int, Position] = {}
    pending: dict[int, int] = {}          # k -> дохионы мөрийн индекс
    trades, equity, events = [], [], []

    def close(k: int, pos: Position, t, price: float, why: str):
        nonlocal balance, peak
        ins = instruments[k]
        pnl = ins.money((price - pos.entry) * pos.side, pos.lot, price) + pos.swap
        balance += pnl
        peak = max(peak, balance)
        rd = abs(pos.entry - pos.sl_initial) or 1e-12
        dg = ins.spec["digits"]
        trades.append(dict(symbol=ins.name, side="BUY" if pos.side == 1 else "SELL", lot=pos.lot,
                           entry_time=pos.entry_time, exit_time=t,
                           entry=round(pos.entry, dg), exit=round(price, dg),
                           sl_initial=round(pos.sl_initial, dg), tp=round(pos.tp, dg),
                           pnl=round(pnl, 2), swap=round(pos.swap, 2),
                           r=round(pnl / pos.risk_money, 3) if pos.risk_money else 0.0,
                           mfe_r=round(pos.mfe / rd, 2), mae_r=round(pos.mae / rd, 2),
                           bars=pos.bars, exit_reason=why, reason=pos.reason,
                           balance=round(balance, 2)))
        equity.append((t, balance))
        del open_pos[k]

    for k, i in timeline:
        ins, c = instruments[k], cols[k]
        t, t_utc = c["time"][i], c["time_utc"][i]
        spread_px = (c["spread"][i] * ins.spec["point"] * cfg.spread_mult
                     if c["spread"] is not None else 0.0)
        slip = cfg.slippage_pips * ins.pip
        o, h, l, cl = c["open"][i], c["high"][i], c["low"][i], c["close"][i]

        # --- Өдрийн лимит (UTC өдөр) ---
        d = t_utc.date()
        if d != day:
            day, day_start_bal, day_blocked = d, balance, False

        # --- Swap: серверийн өдөр солигдох үед ---
        if cfg.include_swap and k in open_pos and i > 0:
            prev_t = c["time"][i - 1]
            if t.date() != prev_t.date():
                pos = open_pos[k]
                # MT5: 3 = Лхагва. Лхагвын шөнө (Лхагва → Пүрэв) 3 дахин swap
                mult = 3 if prev_t.isoweekday() == ins.spec.get("triple_swap_day", 3) else 1
                pos.swap += ins.swap_money(pos, o) * mult

        # --- 1. Хүлээгдэж буй дохиогоор орох (энэ лааны нээлтэд) ---
        if k in pending:
            si = pending.pop(k)
            can = (not killed and not day_blocked and k not in open_pos
                   and len(open_pos) < cfg.max_open_positions)
            if can:
                side = int(c["signal"][si])
                sl_d, tp_d = c["sl_dist"][si], c["tp_dist"][si]
                entry = o + spread_px + slip if side == 1 else o - slip
                res = calculate_lot(balance, cfg.risk_pct, sl_d, ins.spec_at(entry), tp_distance=tp_d)
                if res.lot:
                    sl = entry - side * sl_d
                    tp = entry + side * tp_d
                    open_pos[k] = Position(ins.name, side, res.lot, t, entry, sl, tp, res.risk_money,
                                           c["atr"][si], c["reason"][si], sl_initial=sl)
                else:
                    events.append(f"{t} {ins.name}: {res.reason}")

        # --- 2. Нээлттэй позицыг удирдах ---
        if k in open_pos and killed:
            pos = open_pos[k]
            close(k, pos, t, o if pos.side == 1 else o + spread_px, "KILL")
        if k in open_pos:
            pos = open_pos[k]
            pos.bars += 1
            if pos.side == 1:   # long: BID-ээр хаана
                pos.mfe = max(pos.mfe, h - pos.entry)
                pos.mae = max(pos.mae, pos.entry - l)
                if l <= pos.sl:
                    close(k, pos, t, min(pos.sl, o) - slip, "SL" if not pos.be_done else "BE/TRAIL")
                elif h >= pos.tp:
                    close(k, pos, t, max(pos.tp, o), "TP")
            else:               # short: ASK-аар хаана
                pos.mfe = max(pos.mfe, pos.entry - (l + spread_px))
                pos.mae = max(pos.mae, (h + spread_px) - pos.entry)
                if h + spread_px >= pos.sl:
                    close(k, pos, t, max(pos.sl, o + spread_px) + slip, "SL" if not pos.be_done else "BE/TRAIL")
                elif l + spread_px <= pos.tp:
                    close(k, pos, t, min(pos.tp, o + spread_px), "TP")

            if k in open_pos:
                rd = abs(pos.entry - pos.sl_initial)
                r_now = (cl - pos.entry) * pos.side / rd
                if cfg.break_even_r and not pos.be_done and r_now >= cfg.break_even_r:
                    pos.sl, pos.be_done = (max(pos.sl, pos.entry) if pos.side == 1
                                           else min(pos.sl, pos.entry)), True
                if cfg.trail_atr and pos.mfe / rd >= cfg.trail_start_r:
                    new_sl = cl - pos.side * cfg.trail_atr * c["atr"][i]
                    if (pos.side == 1 and new_sl > pos.sl) or (pos.side == -1 and new_sl < pos.sl):
                        pos.sl, pos.be_done = new_sl, True
                exit_px = cl if pos.side == 1 else cl + spread_px
                flag = c["exit_long"] if pos.side == 1 else c["exit_short"]
                if flag is not None and bool(flag[i]):
                    close(k, pos, t, exit_px, "EXIT")
                elif pos.bars >= cfg.max_hold_bars:
                    close(k, pos, t, exit_px, "TIME")
                elif (cfg.close_friday_utc_hour is not None and t_utc.weekday() == 4
                      and t_utc.hour >= cfg.close_friday_utc_hour):
                    close(k, pos, t, exit_px, "FRIDAY")

        # --- 3. Лимитүүд ---
        if (cfg.use_daily_limit and not day_blocked
                and balance <= day_start_bal * (1 - cfg.daily_loss_limit_pct / 100)):
            day_blocked = True
            events.append(f"{t}: өдрийн алдагдлын лимит хүрлээ")
        if cfg.use_kill_switch and not killed and balance <= peak * (1 - cfg.max_drawdown_pct / 100):
            killed = True
            events.append(f"{t}: MAX DRAWDOWN {cfg.max_drawdown_pct}% — KILL-SWITCH")

        # --- 4. Энэ лаа хаагдсаны дараах дохио → дараагийн лаанд орно ---
        if c["signal"][i] != 0 and k not in open_pos and not killed:
            pending[k] = i

    tr = pd.DataFrame(trades)
    eq = pd.DataFrame(equity, columns=["time", "balance"])
    if eq.empty:
        eq = pd.DataFrame({"time": [pd.Timestamp(start) if start else pd.NaT],
                           "balance": [cfg.initial_balance]})
    return BTResult(tr, eq, events, killed)
