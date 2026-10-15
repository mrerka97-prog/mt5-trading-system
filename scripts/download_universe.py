"""P1.2: Олон хэрэгслийн D1 түүх татах. ЗАХИАЛГА ХИЙХГҮЙ.

Ажиллуулах:  python scripts/download_universe.py
Мөн XM дээрх бүх symbol-ын жагсаалтыг data/symbols_available.csv-д хадгална.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from bot.broker.mt5_broker import BrokerError, MT5Broker   # noqa: E402
from bot.config import load_config, load_secrets            # noqa: E402
from bot.data.store import DATA_DIR, save_bars, save_spec   # noqa: E402


def main() -> int:
    cfg = load_config()
    universe = cfg["research_d1"]["universe"]
    broker = MT5Broker(load_secrets(), allow_live=cfg.get("allow_live", False))
    try:
        broker.connect()
    except BrokerError as e:
        print("[XX]", e)
        return 1
    found, missing = [], []
    try:
        DATA_DIR.mkdir(exist_ok=True)
        pd.DataFrame(broker.all_symbols()).to_csv(DATA_DIR / "symbols_available.csv", index=False)
        for key, aliases in universe.items():
            name = broker.resolve_symbol(aliases)
            if not name:
                missing.append(key)
                print(f"[--] {key}: олдсонгүй ({', '.join(aliases)})")
                continue
            try:
                spec = broker.spec_dict(name)
                spec["name"], spec["broker_symbol"] = key, name
                df = broker.rates_max(name, "D1", 20_000)
            except BrokerError as e:
                missing.append(key)
                print(f"[XX] {key} ({name}): {e}")
                continue
            save_spec(spec, key)
            save_bars(df, key, "D1")
            found.append(key)
            print(f"[OK] {key:7} ({name}): {len(df):,} өдөр  {df.time.iloc[0]:%Y-%m-%d} → "
                  f"{df.time.iloc[-1]:%Y-%m-%d}  spread≈{df.spread.median():.0f} point")
    finally:
        broker.disconnect()
    print(f"\nОлдсон {len(found)}, олдоогүй {len(missing)}: {', '.join(missing) or '—'}")
    print("Олдоогүй хэрэгслийн XM нэрийг data/symbols_available.csv-ээс харж болно.")
    print("Дараа нь: python scripts/cost_analysis.py  ба  python scripts/research_d1.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
