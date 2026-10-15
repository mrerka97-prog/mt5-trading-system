"""Демо дансанд захиалгын замыг НЭГ УДАА шалгах: хамгийн бага lot-оор BUY нээж, SL өөрчилж, шууд хаана.

Зорилго: бот жинхэнэ дохио дээр захиалга илгээхээс ӨМНӨ MT5-ийн тохиргоо (AutoTrading, filling mode,
stop level, хамгийн бага lot) зөв эсэхийг мэдэх. Бүх үйлдэл ~10 секунд. Зардал нь spread (демо мөнгө).

Хамгаалалт:
  - Зөвхөн ДЕМО дансанд ажиллана.
  - Тусдаа magic 999001 ашиглана — бот (240101) энэ позицыг өөрийнх гэж үзэхгүй.
  - --yes гэж бичихгүй бол юу ч илгээхгүй, зөвхөн order_check хийнэ.

Ажиллуулах:  python scripts/order_test.py            (зөвхөн шалгалт, захиалга илгээхгүй)
             python scripts/order_test.py --yes      (нээгээд хаана)
             python scripts/order_test.py GER40 --yes
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import MetaTrader5 as mt5  # noqa: E402

from bot import indicators as ind                          # noqa: E402
from bot.broker.mt5_broker import BrokerError, MT5Broker   # noqa: E402
from bot.config import load_config, load_secrets           # noqa: E402

MAGIC = 999001


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sym = (args[0] if args else "US500").upper()
    go = "--yes" in sys.argv
    cfg = load_config()
    b = MT5Broker(load_secrets(), allow_live=False)
    try:
        b.connect()
    except BrokerError as e:
        print("[XX]", e)
        return 1
    try:
        acc = b.account()
        if acc.trade_mode != "DEMO":
            print("[XX] Энэ данс ДЕМО биш. Зогслоо.")
            return 1
        term = mt5.terminal_info()
        print(f"[OK] Демо данс, баланс {acc.balance:,.2f} {acc.currency}")
        print(f"[{'OK' if term.trade_allowed else 'XX'}] MT5 AutoTrading (Algo Trading) товч: "
              f"{'асаалттай' if term.trade_allowed else 'УНТРААЛТТАЙ — MT5 дээрх Algo Trading товчийг дар'}")
        aliases = cfg.get("research_d1", {}).get("universe", {}).get(sym, [sym])
        n = b.resolve_symbol(aliases)
        if not n:
            print(f"[XX] {sym} олдсонгүй")
            return 1
        spec = b.symbol_spec(n)
        info = mt5.symbol_info(n)
        d1 = b.rates(n, "D1", 60)
        atr = float(ind.atr(d1, 20).iloc[-1])
        for _ in range(10):
            tick = b.tick(n)
            if tick.time > 0:
                break
            time.sleep(1)
        lot = spec.volume_min
        sl = tick.ask - 3 * atr
        print(f"[OK] {n}: хамгийн бага lot {lot}, stop level {info.trade_stops_level} point, "
              f"filling {b.filling_mode_name(info.filling_mode)}")
        print(f"     BUY {lot} @ {tick.ask}, SL {sl:.2f} (3×ATR = {3 * atr:.2f})")
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": n, "volume": float(lot), "type": mt5.ORDER_TYPE_BUY,
               "price": tick.ask, "sl": round(sl, info.digits), "tp": 0.0, "deviation": 20, "magic": MAGIC,
               "comment": "order_test", "type_time": mt5.ORDER_TIME_GTC, "type_filling": b._filling_const(n)}
        chk = mt5.order_check(req)
        ok = chk is not None and chk.retcode in (0, mt5.TRADE_RETCODE_DONE)
        print(f"[{'OK' if ok else 'XX'}] order_check: retcode {getattr(chk, 'retcode', None)} "
              f"{getattr(chk, 'comment', mt5.last_error())}, шаардах margin {getattr(chk, 'margin', '?')}")
        if not ok or not go:
            if ok:
                print("\nЗахиалга илгээгээгүй (шалгалт л). Жинхэнээр турших бол:  python scripts/order_test.py --yes")
            return 0 if ok else 1

        t0 = time.time()
        res = b.open_market(n, 1, lot, sl, MAGIC, "order_test")
        print(f"[OK] Нээгдлээ: order {res.order}, үнэ {res.price} (хүссэн {tick.ask}, "
              f"slippage {res.price - tick.ask:+.2f}), {time.time() - t0:.1f} сек")
        time.sleep(1)
        pos = [p for p in b.positions(MAGIC) if p.symbol == n]
        if not pos:
            print("[XX] Позиц олдсонгүй!")
            return 1
        p = pos[-1]
        print(f"[{'OK' if p.sl > 0 else 'XX'}] Позиц {p.ticket}: SL серверт {p.sl}")
        b.set_sl(p, p.sl - atr * 0.5)
        time.sleep(1)
        p = [q for q in b.positions(MAGIC) if q.ticket == p.ticket][0]
        print(f"[OK] SL өөрчлөгдлөө → {p.sl}")
        res = b.close_position(p, "order_test close")
        time.sleep(1)
        left = [q for q in b.positions(MAGIC) if q.ticket == p.ticket]
        print(f"[{'XX' if left else 'OK'}] Хаагдлаа @ {res.price}. "
              f"{'ПОЗИЦ НЭЭЛТТЭЙ ҮЛДСЭН — MT5 дээр гараар хаа!' if left else 'Нээлттэй позиц үлдээгүй.'}")
        print("\nДүгнэлт: захиалгын зам ажиллаж байна. Ботыг dry_run: false болгоход бэлэн.")
    except BrokerError as e:
        print("[XX]", e)
        left = b.positions(MAGIC)
        if left:
            print(f"[!!] magic {MAGIC}-тай {len(left)} позиц нээлттэй байна — MT5 дээр шалгаж хаана уу.")
        return 1
    finally:
        b.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
