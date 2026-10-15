"""Position sizing: lot тооцоолол.

Дүрмүүд (баримтын 7-р хэсэг):
  1. Lot-ыг үргэлж lot-ын алхам руу ДООШ тоймлоно.
  2. Тооцоолсон lot нь хамгийн бага lot-оос бага бол арилжаа хийхгүй (None).
  3. Тоймлосны дараа SL/TP-ийн мөнгөн дүнг дахин тооцно.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN


@dataclass(frozen=True)
class SymbolSpec:
    """MT5-ийн symbol_info()-оос авах мэдээлэл."""
    name: str
    tick_size: float      # үнийн хамгийн бага алхам (EURUSD: 0.00001)
    tick_value: float     # 1 lot-ын 1 tick-ийн үнэ дансны валютаар (EURUSD, USD данс: 1.0)
    volume_min: float     # хамгийн бага lot (0.01)
    volume_step: float    # lot-ын алхам (0.01)
    volume_max: float     # хамгийн их lot
    digits: int           # үнийн аравтын орон (EURUSD: 5, USDJPY: 3)

    @property
    def point(self) -> float:
        return 10 ** (-self.digits)

    @property
    def pip_size(self) -> float:
        """5 эсвэл 3 оронтой үнэд 1 pip = 10 point, бусад үед 1 point."""
        return self.point * 10 if self.digits in (3, 5) else self.point

    @property
    def pip_value_per_lot(self) -> float:
        return self.pip_size / self.tick_size * self.tick_value


@dataclass(frozen=True)
class SizingResult:
    lot: float | None          # None = арилжаа хийхгүй
    raw_lot: float             # тоймлохоос өмнөх утга
    risk_money: float          # тоймлосны дараах бодит эрсдэл (мөнгөөр)
    risk_pct: float            # тоймлосны дараах бодит эрсдэл (%)
    reward_money: float        # TP хүрвэл олох ашиг
    reason: str


def money_per_lot(spec: SymbolSpec, price_distance: float) -> float:
    """1 lot-оор price_distance зайд хөдлөхөд гарах мөнгөн дүн."""
    return abs(price_distance) / spec.tick_size * spec.tick_value


def _floor_to_step(value: float, step: float) -> float:
    v, s = Decimal(str(value)), Decimal(str(step))
    return float((v / s).to_integral_value(rounding=ROUND_DOWN) * s)


def calculate_lot(
    balance: float,
    risk_pct: float,
    sl_distance: float,
    spec: SymbolSpec,
    tp_distance: float = 0.0,
) -> SizingResult:
    """balance: дансны үлдэгдэл; risk_pct: 0.5 = 0.5%;
    sl_distance / tp_distance: үнийн зай (EURUSD 30 pip = 0.0030)."""
    if balance <= 0 or risk_pct <= 0:
        return SizingResult(None, 0.0, 0.0, 0.0, 0.0, "Баланс эсвэл эрсдэлийн хувь буруу")
    if sl_distance <= 0:
        return SizingResult(None, 0.0, 0.0, 0.0, 0.0, "SL заагаагүй: арилжаа хийхгүй")

    risk_budget = balance * risk_pct / 100
    loss_per_lot = money_per_lot(spec, sl_distance)
    raw = risk_budget / loss_per_lot
    lot = min(_floor_to_step(raw, spec.volume_step), spec.volume_max)

    if lot < spec.volume_min:
        return SizingResult(
            None, raw, 0.0, 0.0, 0.0,
            f"Lot {raw:.4f} < хамгийн бага {spec.volume_min}: арилжаа хийхгүй",
        )

    risk_money = round(lot * loss_per_lot, 2)
    reward_money = round(lot * money_per_lot(spec, tp_distance), 2) if tp_distance else 0.0
    return SizingResult(
        lot=lot,
        raw_lot=raw,
        risk_money=risk_money,
        risk_pct=round(risk_money / balance * 100, 3),
        reward_money=reward_money,
        reason="OK",
    )
