"""P2: E1b ботыг XM ДЕМО дансанд ажиллуулна. config.yaml-ийн live хэсгийг үз.

Ажиллуулах:  python scripts/run_live.py          (байнга ажиллана)
             python scripts/run_live.py --once   (өдөрт нэг удаа: шийдвэр гаргаад өөрөө унтарна)
Зогсоох:     Ctrl+C  (эсвэл Telegram /stop)
Лог:         logs/live.log     Төлөв: data/live_state.sqlite
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.broker.mt5_broker import BrokerError, MT5Broker   # noqa: E402
from bot.config import ROOT, load_config, load_secrets      # noqa: E402
from bot.live.notifier import Notifier                       # noqa: E402
from bot.live.runner import Runner                           # noqa: E402
from bot.live.state import State                             # noqa: E402
from bot.news import NewsCalendar                            # noqa: E402


def single_instance_lock():
    """Нэг удаад зөвхөн нэг бот: хоёр бот зэрэг ажиллавал давхар захиалга гарах эрсдэлтэй."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 47821))
    except OSError:
        print("Өөр бот аль хэдийн ажиллаж байна. Давхар ажиллуулахгүй.")
        sys.exit(0)
    return s


def main() -> int:
    # Windows гаралтыг файл руу чиглүүлэхэд cp1252 кирилл үсэг бичиж чаддаггүй
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    _lock = single_instance_lock()  # noqa: F841 — процесс дуустал барина
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(ROOT / "logs" / "live.log", encoding="utf-8"),
                                  logging.StreamHandler(sys.stdout)])
    cfg = load_config()
    sec = load_secrets()
    if cfg.get("mode") != "demo" or cfg.get("allow_live"):
        print("Зөвхөн демо горимд ажиллана (mode: demo, allow_live: false).")
        return 1
    broker = MT5Broker(sec, allow_live=False)
    try:
        broker.connect()
    except BrokerError as e:
        print("[XX]", e)
        return 1
    if broker.account().trade_mode != "DEMO":
        print("Энэ данс ДЕМО биш. Бот зогслоо.")
        return 1
    news = NewsCalendar(ROOT / "data" / "news_calendar.json", cfg.get("news", {}))
    runner = Runner(cfg, broker, State(ROOT / "data" / "live_state.sqlite"),
                    Notifier(sec.telegram_token, sec.telegram_chat_id), news=news)
    try:
        if "--once" in sys.argv:
            runner.run_once(cfg["live"].get("once_max_minutes", 30))
        else:
            runner.run_forever(cfg["live"].get("check_interval_sec", 60))
    except KeyboardInterrupt:
        pass
    finally:
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
