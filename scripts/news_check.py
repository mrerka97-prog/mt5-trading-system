"""Мэдээний календарийг шалгах (MT5 шаардахгүй).

Ажиллуулах:
  python scripts/news_check.py              ботын хэрэгслүүдийн валют (USD, EUR, JPY), 7 хоног
  python scripts/news_check.py USD GBP      сонгосон валютууд
  python scripts/news_check.py --force      кэшийг үл тоон шинээр татна
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from bot.config import ROOT, load_config   # noqa: E402
from bot.news import NewsCalendar           # noqa: E402


def main() -> int:
    cfg = load_config()
    news = NewsCalendar(ROOT / "data" / "news_calendar.json", cfg.get("news", {}))
    ok = news.refresh(force="--force" in sys.argv)
    now = datetime.now(timezone.utc)
    print("Татсан:" if ok else "Кэшээс:", news.status_line(now))
    if not news.known(now):
        print("[XX] Календарь ашиглах боломжгүй.", news.last_error)
        return 1
    args = [a.upper() for a in sys.argv[1:] if not a.startswith("--")]
    lc = cfg.get("live", {})
    syms = list(lc.get("trade_symbols", [])) + list(lc.get("signal_only_symbols", []))
    cur = sorted(set(args)) if args else sorted({c for s in syms for c in news.currencies(s)})
    print(f"Нийт {len(news.events)} үйл явдал. Шүүлтүүр: impact {sorted(news.impacts)}, валют {cur}")
    print()
    ev = news.upcoming(cur, 24 * 7, now)
    if not ev:
        print("Энэ долоо хоногт үлдсэн өндөр нөлөөтэй мэдээ алга.")
    for e in ev:
        print("  ", e.short(now))
    print()
    for s in syms:
        r = news.entry_block_reason(s, now)
        print(f"  {s:6} {'[ХОРИГ] ' + r if r else '[OK] одоо арилжаа нээж болно'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
