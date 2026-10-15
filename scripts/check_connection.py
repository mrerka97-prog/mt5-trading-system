"""P0: XM демо дансанд холбогдож, мэдээлэл уншина. ЗАХИАЛГА ХИЙХГҮЙ.

Ажиллуулах:  python scripts/check_connection.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.broker.mt5_broker import BrokerError, MT5Broker  # noqa: E402
from bot.config import load_config, load_secrets           # noqa: E402
from bot.risk.sizing import calculate_lot                  # noqa: E402

OK, WARN, FAIL = "[OK]  ", "[!!]  ", "[XX]  "


def main() -> int:
    cfg = load_config()
    broker = MT5Broker(load_secrets(), allow_live=cfg.get("allow_live", False))

    print("=" * 60)
    print("XM MT5 холболтын шалгалт (P0, зөвхөн унших)")
    print("=" * 60)
    try:
        broker.connect()
    except BrokerError as e:
        print(FAIL, e)
        return 1
    print(OK, "MT5-тай холбогдлоо")

    try:
        acc = broker.account()
        mark = OK if acc.trade_mode == "DEMO" else WARN
        print(mark, f"Дансны төрөл: {acc.trade_mode}")
        print(OK, f"Данс {acc.login} @ {acc.server} ({acc.company})")
        print(OK, f"Баланс {acc.balance:,.2f} {acc.currency}, equity {acc.equity:,.2f}, leverage 1:{acc.leverage}")
        print(OK, f"Margin call {acc.margin_call_level}%, stop out {acc.stop_out_level}%")
        if not broker.terminal_trade_allowed():
            print(WARN, "MT5 дээр Algo Trading (AutoTrading) унтраалттай байна. P2-оос өмнө асаана")
        else:
            print(OK, "Algo Trading асаалттай")

        risk_pct = cfg["risk"]["risk_per_trade_pct"]
        print("-" * 60)
        for base in cfg["symbols"]:
            name = broker.find_symbol(base)
            if not name:
                print(FAIL, f"{base}: symbol олдсонгүй")
                continue
            spec = broker.symbol_spec(name)
            det = broker.symbol_details(name)
            t = broker.tick(name)
            spread_pips = (t.ask - t.bid) / spec.pip_size
            print(OK, f"{name}: bid {t.bid}  ask {t.ask}  spread {spread_pips:.1f} pip  "
                      f"filling {det['filling']}")
            print("      ", f"pip={spec.pip_size}  1 lot-ын 1 pip = {spec.pip_value_per_lot:.2f} {acc.currency}  "
                           f"lot {spec.volume_min}..{spec.volume_max} алхам {spec.volume_step}")
            print("      ", f"swap long {det['swap_long']}  short {det['swap_short']}  "
                           f"3 дахин swap өдөр={det['triple_swap_day']}  stops level {det['stops_level_points']} point")

            h1 = broker.rates(name, "H1", 3)
            last = h1.iloc[-2]
            print("      ", f"Сүүлийн хаагдсан H1 лаа: {last['time']}  O {last['open']} H {last['high']} "
                           f"L {last['low']} C {last['close']}")

            r = calculate_lot(acc.balance, risk_pct, 30 * spec.pip_size, spec, tp_distance=60 * spec.pip_size)
            if r.lot:
                print("      ", f"Жишээ ({risk_pct}% эрсдэл, SL 30 pip, TP 60 pip): lot {r.lot}, "
                               f"SL -{r.risk_money} {acc.currency}, TP +{r.reward_money} {acc.currency}")
            else:
                print("      ", f"Жишээ: {r.reason}")

        print("-" * 60)
        base0 = broker.find_symbol(cfg["symbols"][0])
        if base0:
            off = broker.server_utc_offset_hours(base0)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            weekend = datetime.now(timezone.utc).weekday() >= 5
            mark = WARN if weekend else OK
            print(mark, f"Серверийн цаг UTC{off:+d} (одоо {now})"
                        + (" — амралтын өдөр тул найдваргүй" if weekend else ""))
    finally:
        broker.disconnect()

    print("=" * 60)
    print("Дууслаа. Ямар ч захиалга илгээгээгүй.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
