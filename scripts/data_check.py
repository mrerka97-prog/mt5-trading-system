"""MT5-ийн D1 өгөгдөл шинэ эсэх, E1b-ийн сүүлийн дохиог шалгана. ЗАХИАЛГА ИЛГЭЭХГҮЙ, төлөв өөрчлөхгүй.

Ажиллуулах:  python scripts/data_check.py
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pandas as pd  # noqa: E402

from bot import indicators as ind                                  # noqa: E402
from bot.broker.mt5_broker import BrokerError, MT5Broker           # noqa: E402
from bot.config import load_config, load_secrets                   # noqa: E402
from bot.data.store import fill_zero_spread, utc_to_server_epoch   # noqa: E402
from bot.strategy.experiments import e1_index_rsi2                 # noqa: E402


def main() -> int:
    cfg = load_config()
    b = MT5Broker(load_secrets(), allow_live=False)
    try:
        b.connect()
    except BrokerError as e:
        print("[XX]", e)
        return 1
    now = datetime.now(timezone.utc)
    today = pd.Timestamp(utc_to_server_epoch(now), unit="s").normalize()
    expected = today - pd.offsets.BDay(1)
    print(f"Серверийн өнөөдөр: {today:%Y-%m-%d %a}. Хүлээгдэж буй сүүлийн бүтэн лаа: {expected:%Y-%m-%d}\n")
    lc = cfg["live"]
    try:
        for sym in lc["trade_symbols"] + lc.get("signal_only_symbols", []):
            aliases = cfg.get("research_d1", {}).get("universe", {}).get(sym, [sym])
            n = b.resolve_symbol(aliases)
            df = None
            for attempt in range(6):                     # MT5 түүхээ татахыг 5 сек тутам хүлээнэ
                df = b.rates(n, "D1", 400)
                last = pd.Timestamp(df["time"].iloc[-1]).normalize()
                closed = df.iloc[:-1] if last >= today else df
                if pd.Timestamp(closed["time"].iloc[-1]).normalize() >= expected:
                    break
                time.sleep(5)
            closed = fill_zero_spread(closed.reset_index(drop=True))
            closed["time_utc"] = closed["time"]
            sig = e1_index_rsi2(closed, float(lc.get("rsi_threshold", 5))).iloc[-1]
            rsi2 = float(ind.rsi(closed["close"], 2).iloc[-1])
            sma200 = float(closed["close"].rolling(200).mean().iloc[-1])
            tick = b.tick(n)
            age_min = (utc_to_server_epoch(now) - tick.time) / 60
            fresh = pd.Timestamp(closed["time"].iloc[-1]).normalize() >= expected
            print(f"{sym:6} ({n})  өнөөдрийн лаа: {'БИЙ' if last >= today else 'алга'}  "
                  f"сүүлийн бүтэн лаа: {closed['time'].iloc[-1]:%Y-%m-%d} {'[OK]' if fresh else '[ХОЦОРСОН]'}")
            print(f"        close {closed['close'].iloc[-1]:.2f}  RSI2 {rsi2:.1f}  SMA200 {sma200:.2f}  "
                  f"→ E1b дохио: {'БАЙНА' if sig['signal'] == 1 else 'алга'}   "
                  f"сүүлийн үнэ {age_min:.0f} мин-ийн өмнө ({'зах зээл нээлттэй' if age_min < 5 else 'хаалттай'})")
    finally:
        b.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
