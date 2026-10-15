"""Telegram командыг хүлээн авч хариулна. Компьютер асаалттай үед ажиллуулна.

Ажиллуулах:  python scripts/telegram_listener.py      Зогсоох: Ctrl+C
Автоматаар:  setup_listener_task.ps1 — Windows-д нэвтрэх бүрт далд (цонхгүй) асаана.
             Тэр үед --service горимтой: MT5 холбогдохгүй бол 60 сек тутам дахин оролдоно.
Командууд:   /check EURUSD BUY, /status, /checks, /pause, /resume, /stop, /help
"""
from __future__ import annotations

import logging
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from bot.broker.mt5_broker import BrokerError, MT5Broker   # noqa: E402
from bot.config import ROOT, load_config, load_secrets      # noqa: E402
from bot.live.notifier import Notifier                       # noqa: E402
from bot.live.state import State                             # noqa: E402
from bot.tradecheck import check_live                        # noqa: E402

log = logging.getLogger("bot")
HELP = ("Командууд:\n"
        "/check EURUSD BUY — арилжааны санал шалгах (BUY эсвэл SELL)\n"
        "/status — данс, ботын төлөв, позиц\n"
        "/checks — сүүлийн 5 шалгалт\n"
        "/news — дараагийн 24 цагийн өндөр нөлөөтэй мэдээ (USD EUR JPY ...)\n"
        "/pause — шинэ арилжаа түр зогсоох\n"
        "/resume — үргэлжлүүлэх\n"
        "/stop — бүх позицыг хааж ботыг зогсоох (kill-switch)\n\n"
        "Хэрэгслүүд: EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD EURJPY GBPJPY EURGBP AUDJPY "
        "GOLD SILVER US500 US30 GER40 JP225 OIL")


def news_text(cfg: dict, args: list[str], news=None) -> str:
    """/news [USD EUR ...] — өндөр нөлөөтэй мэдээ, дараагийн 24 цаг."""
    from datetime import datetime, timezone

    from bot.news import NewsCalendar
    news = news or NewsCalendar(ROOT / "data" / "news_calendar.json", cfg.get("news", {}))
    news.refresh()
    now = datetime.now(timezone.utc)
    if not news.known(now):
        return news.status_line(now) + "\nForexFactory-оос өөрөө шалгана уу."
    if args:
        cur = sorted({a.upper() for a in args})
    else:
        lc = cfg.get("live", {})
        syms = list(lc.get("trade_symbols", [])) + list(lc.get("signal_only_symbols", []))
        cur = sorted({c for s in syms for c in news.currencies(s)}) or ["USD", "EUR", "JPY"]
    ev = news.upcoming(cur, 24, now)
    head = f"Өндөр нөлөөтэй мэдээ ({', '.join(cur)}), дараагийн 24 цаг:"
    if not ev:
        return head + "\nАлга. " + news.status_line(now)
    return "\n".join([head] + [f"• {e.short(now)}" for e in ev] + [
        f"Эдгээрийн ±{news.minutes_before} минутад бот шинэ арилжаа нээхгүй."])


def handle(text: str, broker: MT5Broker, cfg: dict, st: State) -> str:
    parts = text.split()
    cmd = parts[0].lower().split("@")[0]
    if cmd in ("/start", "/help"):
        return HELP
    if cmd == "/check":
        if len(parts) < 3 or parts[2].upper() not in ("BUY", "SELL"):
            return "Жишээ: /check EURUSD BUY"
        broker.ensure_connected()
        return check_live(broker, cfg, st, parts[1].upper(), 1 if parts[2].upper() == "BUY" else -1, ROOT)
    if cmd == "/status":
        broker.ensure_connected()
        a = broker.account()
        opens = st.open_positions()
        closed = [c["r"] for c in st.closed_positions() if c["r"] is not None]
        lines = [f"Баланс {a.balance:,.2f} / equity {a.equity:,.2f} {a.currency}",
                 f"Горим: {'DRY-RUN' if cfg['live'].get('dry_run', True) else 'ЗАХИАЛГА'}"
                 + (" | ТҮР ЗОГССОН" if st.get("paused") else "") + (" | KILLED" if st.get("killed") else ""),
                 f"Сүүлд ажилласан: {st.get('heartbeat', '—')} UTC"]
        for r in opens:
            lines.append(f"{'V ' if r['virtual'] else ''}{r['symbol']} BUY {r['lot']} @ {r['entry']} SL {r['sl']}")
        lines.append(f"Хаагдсан {len(closed)} арилжаа, нийт {sum(closed):+.2f}R")
        return "\n".join(lines)
    if cmd == "/checks":
        p = ROOT / "data" / "trade_checks.csv"
        if not p.exists():
            return "Шалгалт хараахан алга."
        rows = p.read_text(encoding="utf-8").strip().splitlines()[1:][-5:]
        return "Сүүлийн шалгалтууд:\n" + "\n".join(
            f"{r.split(',')[0]} {r.split(',')[1]} {r.split(',')[2]} → {r.split(',')[3]} ({r.split(',')[4]})"
            for r in rows)
    if cmd == "/news":
        return news_text(cfg, parts[1:])
    if cmd == "/pause":
        st.set("paused", True)
        st.log("PAUSE", details="Telegram")
        return "⏸ Шинэ арилжаа түр зогслоо. Нээлттэй позицыг удирдсаар байна. /resume"
    if cmd == "/resume":
        st.set("paused", False)
        st.set("killed", False)
        broker.ensure_connected()
        st.set("peak_equity", broker.account().equity)
        st.log("RESUME", details="Telegram")
        return "▶️ Үргэлжилж байна."
    if cmd == "/stop":
        broker.ensure_connected()
        magic = int(cfg["execution"]["magic_number"])
        closed = 0
        for p in broker.positions(magic):
            try:
                broker.close_position(p, "STOP")
                closed += 1
            except BrokerError as e:
                st.log("ERROR", p.symbol, f"/stop close: {e}", "ERROR")
        st.set("killed", True)
        st.log("KILL", details="Telegram /stop", level="CRITICAL")
        return f"🛑 Зогслоо. {closed} позиц хаагдлаа. Дахин эхлүүлэх: /resume"
    return "Тодорхойгүй команд. /help"


def main() -> int:
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", 47822))
    except OSError:
        print("Telegram listener аль хэдийн ажиллаж байна.")
        return 0
    (ROOT / "logs").mkdir(exist_ok=True)
    service = "--service" in sys.argv
    handlers = [logging.FileHandler(ROOT / "logs" / "telegram.log", encoding="utf-8")]
    if sys.stdout is not None:                     # pythonw (далд горим) үед консол байхгүй
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    cfg = load_config()
    sec = load_secrets()
    tg = Notifier(sec.telegram_token, sec.telegram_chat_id)
    if not tg.enabled:
        log.error("Telegram тохируулаагүй. Эхлээд: python scripts/telegram_setup.py")
        return 1
    broker = MT5Broker(sec, allow_live=False)
    tries = 0
    while True:
        try:
            broker.connect()
            break
        except BrokerError as e:
            tries += 1
            log.error("MT5 холболт (%d): %s", tries, e)
            if not service:
                print("[XX]", e)
                return 1
            if tries == 5:
                tg.send(f"❗ Telegram listener MT5-тай холбогдож чадахгүй байна: {e}\nДахин оролдсоор байна.")
            time.sleep(60)
    st = State(ROOT / "data" / "live_state.sqlite")
    off = st.get("tg_offset", 0)
    tg.send("🟢 Telegram listener асав. /help")
    log.info("Listener ажиллаж байна. Зогсоох: Ctrl+C")
    try:
        while True:
            try:
                msgs, off = tg.poll_messages(off)
                st.set("tg_offset", off)
            except Exception:               # гэнэтийн алдаа (DB түгжигдсэн гэх мэт) listener-ийг унагахгүй
                log.exception("Listener алдаа, 30 сек хүлээгээд үргэлжилнэ")
                time.sleep(30)
                continue
            for m in msgs:
                log.info("Команд: %s", m)
                try:
                    reply = handle(m, broker, cfg, st)
                except Exception as e:      # нэг командын алдаа listener-ийг унагахгүй
                    log.exception("Командын алдаа")
                    reply = f"❗ Алдаа: {e}"
                tg.send(reply)
            if not msgs:
                time.sleep(1)
    except KeyboardInterrupt:
        tg.send("🔴 Telegram listener зогслоо.")
    finally:
        broker.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
