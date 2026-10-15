"""Тестэд зориулсан хуурамч MT5 брокер: D1 өгөгдлийг өдөр өдрөөр "тоглуулна"."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta, timezone
from types import SimpleNamespace as NS

import pandas as pd

from bot.data.store import server_to_utc, utc_to_server_epoch
from bot.risk.sizing import SymbolSpec


@dataclass
class FakePos:
    ticket: int
    symbol: str
    volume: float
    price_open: float
    sl: float
    tp: float
    magic: int
    time: int
    type: int = 0          # 0 = BUY


class FakeBroker:
    def __init__(self, d1: dict[str, pd.DataFrame], specs: dict[str, dict], balance=10_000.0):
        self.d1 = {k: v.reset_index(drop=True) for k, v in d1.items()}
        self.specs = specs
        self.i = {k: 0 for k in d1}
        self.balance = balance
        self.equity_override = None
        self.pos: list[FakePos] = []
        self.orders: list[dict] = []
        self.ticket = 1000
        self.now = None

    # --- simulation control ---
    def goto(self, server_day: pd.Timestamp, hour: int = 2):
        """Серверийн тухайн өдрийн `hour` цаг руу шилжинэ (өмнөх өдрүүд хаагдсан)."""
        for k, d in self.d1.items():
            self.i[k] = int((d["time"] < server_day).sum())
        server = server_day + pd.Timedelta(hours=hour)
        utc = server_to_utc(pd.Series([server])).iloc[0]
        self.now = utc.to_pydatetime().replace(tzinfo=timezone.utc)
        return self.now

    def _bar(self, k):
        return self.d1[k].iloc[min(self.i[k], len(self.d1[k]) - 1)]

    # --- broker API used by Runner ---
    def ensure_connected(self):
        pass

    def resolve_symbol(self, aliases):
        return next((a for a in aliases if a in self.d1), None)

    def account(self):
        eq = self.equity_override if self.equity_override is not None else self.balance + sum(
            (self._bar(p.symbol)["open"] - p.price_open) * p.volume for p in self.pos)
        return NS(balance=self.balance, equity=eq, currency="USD", trade_mode="DEMO")

    def rates(self, name, tf, count):
        d = self.d1[name].iloc[: self.i[name] + 1]       # + өнөөдрийн дуусаагүй лаа
        return d.tail(count + 1).reset_index(drop=True)

    def tick(self, name):
        b = self._bar(name)
        sp = self.specs[name]
        return NS(time=int(utc_to_server_epoch(self.now)), bid=b["open"],
                  ask=b["open"] + b.get("spread", 0) * sp["point"])

    def point(self, name):
        return self.specs[name]["point"]

    def symbol_spec(self, name):
        s = self.specs[name]
        return SymbolSpec(name, s["tick_size"], s["tick_value"], s["volume_min"], s["volume_step"],
                          s["volume_max"], s["digits"])

    def positions(self, magic):
        return [p for p in self.pos if p.magic == magic]

    def open_market(self, name, side, lot, sl, magic, comment, deviation=20):
        self.ticket += 1
        t = self.tick(name)
        self.pos.append(FakePos(self.ticket, name, lot, t.ask, sl, 0.0, magic, t.time))
        self.orders.append({"op": "open", "symbol": name, "lot": lot, "sl": sl})

    def close_position(self, pos, comment="close", deviation=20):
        t = self.tick(pos.symbol)
        self.balance += (t.bid - pos.price_open) * pos.volume
        self.pos = [p for p in self.pos if p.ticket != pos.ticket]
        self.orders.append({"op": "close", "symbol": pos.symbol, "ticket": pos.ticket})

    def set_sl(self, pos, sl):
        pos.sl = sl
        self.orders.append({"op": "sl", "symbol": pos.symbol, "sl": sl})


class FakeNotifier:
    def __init__(self, commands=None):
        self.sent, self.commands = [], list(commands or [])

    def send(self, text):
        self.sent.append(text)

    def poll_commands(self, offset):
        cmds, self.commands = self.commands, []
        return cmds, offset + len(cmds)
