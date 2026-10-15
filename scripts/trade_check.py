"""Trade Check: арилжааны саналыг шалгана. ЗАХИАЛГА ИЛГЭЭХГҮЙ.

Ажиллуулах:
  python scripts/trade_check.py EURUSD BUY
  python scripts/trade_check.py US500 SELL
  python scripts/trade_check.py GOLD BUY        (XAUUSD-ийн XM нэр ч болно)

Шалгалт бүр data/trade_checks.csv-д бүртгэгдэнэ. Дараа нь үр дүнг нь хэмжинэ.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from bot.broker.mt5_broker import BrokerError, MT5Broker   # noqa: E402
from bot.config import ROOT, load_config, load_secrets      # noqa: E402
from bot.live.state import State                             # noqa: E402
from bot.tradecheck import check_live                         # noqa: E402


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[2].upper() not in ("BUY", "SELL"):
        print("Хэрэглээ: python scripts/trade_check.py EURUSD BUY   (эсвэл SELL)")
        return 1
    sym, side = sys.argv[1].upper(), 1 if sys.argv[2].upper() == "BUY" else -1
    cfg = load_config()
    broker = MT5Broker(load_secrets(), allow_live=False)
    try:
        broker.connect()
    except BrokerError as e:
        print("[XX]", e)
        return 1
    try:
        print(check_live(broker, cfg, State(ROOT / "data" / "live_state.sqlite"), sym, side, ROOT))
    finally:
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
