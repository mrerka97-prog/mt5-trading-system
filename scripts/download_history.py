"""P1-1: MT5-аас H1, H4 лааны бүх түүхийг татаж data/ хавтаст хадгална. ЗАХИАЛГА ХИЙХГҮЙ.

Ажиллуулах:  python scripts/download_history.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.broker.mt5_broker import BrokerError, MT5Broker   # noqa: E402
from bot.config import load_config, load_secrets            # noqa: E402
from bot.data.store import save_bars, save_spec             # noqa: E402


def main() -> int:
    cfg = load_config()
    broker = MT5Broker(load_secrets(), allow_live=cfg.get("allow_live", False))
    try:
        broker.connect()
    except BrokerError as e:
        print("[XX]", e)
        return 1
    try:
        for base in cfg["symbols"]:
            name = broker.find_symbol(base)
            if not name:
                print(f"[XX] {base}: symbol олдсонгүй")
                continue
            spec = broker.spec_dict(name)
            spec["name"] = base   # файлын нэрийг энгийн байлгана
            spec["broker_symbol"] = name
            save_spec(spec, base)
            for tf in ("H1", "H4"):
                df = broker.rates_max(name, tf)
                p = save_bars(df, base, tf)
                print(f"[OK] {base} {tf}: {len(df):,} лаа  {df.time.iloc[0]:%Y-%m-%d} → "
                      f"{df.time.iloc[-1]:%Y-%m-%d}  ({p.name})")
    finally:
        broker.disconnect()
    print("\nДууслаа. Дараа нь: python scripts/run_backtest.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
