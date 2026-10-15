"""Мэдээний календарийн шүүлтүүр (дизайн баримтын 7, 13-р хэсэг).

Дүрэм: өндөр нөлөөтэй мэдээний ±30 минутад тухайн валюттай хэрэгслээр ШИНЭ арилжаа нээхгүй.
Нээлттэй позицыг хаахыг хориглохгүй.

Эх үүсвэр: ForexFactory-ийн үнэгүй долоо хоногийн JSON (faireconomy.media). Түлхүүр шаардахгүй.
  - Зөвхөн энэ долоо хоногийг (Ням–Бямба) агуулна.
  - Хэт олон удаа татвал түр хаадаг тул кэшлэнэ: data/news_calendar.json,
    refresh_hours (6 цаг) өнгөрөөгүй бол дахин татахгүй.
  - Татаж чадаагүй бол хуучин кэшийг ашиглана. Кэш хэт хуучин (stale_hours) бол
    календарь "мэдэгдэхгүй" төлөвт орно → fail_closed тохиргооноос хамаарч шийднэ.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("bot")

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
UTC = timezone.utc
KNOWN = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "CNY"}

# Индекс, түүхий эд → нөлөөлөх валют. config.yaml-ийн news.symbol_currencies-ээр дарж болно.
DEFAULT_SYMBOL_CURRENCIES = {
    "US500": ["USD"], "US30": ["USD"], "US100": ["USD"], "GER40": ["EUR"], "JP225": ["JPY"],
    "UK100": ["GBP"], "XAUUSD": ["USD"], "GOLD": ["USD"], "XAGUSD": ["USD"], "SILVER": ["USD"],
    "OIL": ["USD"],
}


@dataclass(frozen=True)
class NewsEvent:
    time_utc: datetime
    currency: str
    impact: str
    title: str

    def local(self, hours: int = 7) -> str:
        return (self.time_utc + timedelta(hours=hours)).strftime("%m-%d %H:%M")

    def short(self, now: datetime | None = None) -> str:
        s = f"{self.currency} {self.title} {self.local()} (UTC+7)"
        if now is not None:
            mins = int((self.time_utc - now).total_seconds() // 60)
            if mins >= 0:
                s += f", {mins // 60} ц {mins % 60} мин-ийн дараа" if mins >= 60 else f", {mins} мин-ийн дараа"
            else:
                s += f", {-mins} мин-ийн өмнө"
        return s


def symbol_currencies(sym: str, overrides: dict | None = None) -> list[str]:
    """US500 → [USD], EURUSD → [EUR, USD], EURUSD# → [EUR, USD]."""
    s = sym.upper()
    if overrides and s in overrides:
        return list(overrides[s])
    if s in DEFAULT_SYMBOL_CURRENCIES:
        return DEFAULT_SYMBOL_CURRENCIES[s]
    base, quote = s[:3], s[3:6]
    if base in KNOWN and quote in KNOWN:
        return [base, quote]
    for k, v in DEFAULT_SYMBOL_CURRENCIES.items():      # US500Cash, GER40Cash гэх мэт
        if s.startswith(k.upper()):
            return v
    return []


def parse_ff(items: list[dict]) -> list[NewsEvent]:
    out = []
    for it in items:
        try:
            t = datetime.fromisoformat(it["date"]).astimezone(UTC)
        except (KeyError, ValueError, TypeError):
            continue
        out.append(NewsEvent(t, str(it.get("country", "")).upper(), str(it.get("impact", "")),
                             str(it.get("title", "")).strip()))
    return sorted(out, key=lambda e: e.time_utc)


def fetch_ff(url: str = FF_URL, timeout: int = 15) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (forex-bot demo)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("Календарийн хариу жагсаалт биш байна")
    return data


class NewsCalendar:
    """Кэштэй мэдээний календарь. fetcher-ийг тестэд солино."""

    def __init__(self, cache_path: Path, cfg: dict | None = None, fetcher=None, clock=None):
        c = cfg or {}
        self.path = Path(cache_path)
        self.enabled = bool(c.get("enabled", True))
        self.minutes_before = int(c.get("blackout_minutes_before", c.get("blackout_minutes", 30)))
        self.minutes_after = int(c.get("blackout_minutes_after", c.get("blackout_minutes", 30)))
        self.impacts = {str(x) for x in c.get("impacts", ["High"])}
        self.refresh_hours = float(c.get("refresh_hours", 6))
        self.stale_hours = float(c.get("stale_hours", 30))
        self.fail_closed = bool(c.get("fail_closed", False))
        self.overrides = {k.upper(): v for k, v in (c.get("symbol_currencies") or {}).items()}
        self.url = c.get("url", FF_URL)
        self.fetcher = fetcher or (lambda: fetch_ff(self.url))
        self.clock = clock or (lambda: datetime.now(UTC))
        self.events: list[NewsEvent] = []
        self.fetched_at: datetime | None = None
        self.last_error = ""
        self._last_attempt: datetime | None = None
        self._load_cache()

    # ------------------------------------------------------------------ cache
    def _load_cache(self) -> None:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.fetched_at = datetime.fromisoformat(d["fetched_at"])
            self.events = parse_ff(d["items"])
        except FileNotFoundError:
            pass
        except Exception as e:                            # эвдэрсэн кэш → хоосон гэж үзнэ
            log.warning("Мэдээний кэш уншигдсангүй: %s", e)

    def refresh(self, force: bool = False) -> bool:
        """Кэш хуучирсан бол шинээр татна. Амжилттай бол True. Алдаа ботыг зогсоохгүй."""
        if not self.enabled:
            return False
        now = self.clock()
        if not force and self.fetched_at and now - self.fetched_at < timedelta(hours=self.refresh_hours):
            return False
        # Амжилтгүй оролдлогын дараа 15 минут хүлээнэ (сайтыг хэт олон дуудахгүй)
        if not force and self._last_attempt and now - self._last_attempt < timedelta(minutes=15):
            return False
        self._last_attempt = now
        try:
            items = self.fetcher()
            events = parse_ff(items)
        except Exception as e:
            self.last_error = str(e)
            log.warning("Мэдээний календарь татагдсангүй: %s", e)
            return False
        self.events, self.fetched_at, self.last_error = events, now, ""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"fetched_at": now.isoformat(), "source": self.url, "items": items},
                                            ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            log.warning("Мэдээний кэш бичигдсэнгүй: %s", e)
        log.info("Мэдээний календарь шинэчлэгдэв: %d үйл явдал", len(events))
        return True

    # ------------------------------------------------------------------ queries
    def known(self, now: datetime | None = None) -> bool:
        """Календарь итгэж болохуйц шинэ эсэх (энэ долоо хоногийг хамарч байгаа)."""
        now = now or self.clock()
        if not self.fetched_at or now - self.fetched_at > timedelta(hours=self.stale_hours):
            return False
        return bool(self.events) and now <= self.events[-1].time_utc + timedelta(days=1)

    def currencies(self, sym: str) -> list[str]:
        return symbol_currencies(sym, self.overrides)

    def _relevant(self, cur: list[str]) -> list[NewsEvent]:
        wanted = set(cur) | {"ALL"}
        return [e for e in self.events if e.impact in self.impacts and e.currency in wanted]

    def blackout(self, sym: str, now: datetime | None = None) -> NewsEvent | None:
        """sym-д хамаарах өндөр нөлөөтэй мэдээний ±N минутын дотор байвал тэр мэдээг буцаана."""
        if not self.enabled:
            return None
        now = now or self.clock()
        for e in self._relevant(self.currencies(sym)):
            if e.time_utc - timedelta(minutes=self.minutes_before) <= now <= e.time_utc + timedelta(
                    minutes=self.minutes_after):
                return e
        return None

    def upcoming(self, currencies: list[str], hours: float = 24, now: datetime | None = None) -> list[NewsEvent]:
        now = now or self.clock()
        end = now + timedelta(hours=hours)
        return [e for e in self._relevant(currencies) if now - timedelta(minutes=self.minutes_after)
                <= e.time_utc <= end]

    def entry_block(self, sym: str, now: datetime | None = None) -> tuple[str, str]:
        """Шинэ арилжаа нээхийг хориглох эсэх: (тогтмол түлхүүр, тайлбар). ("", "") = болно.
        Түлхүүр нь нэг мэдээнд өөрчлөгдөхгүй тул давхар мэдэгдэл илгээхгүй."""
        if not self.enabled:
            return "", ""
        now = now or self.clock()
        ev = self.blackout(sym, now)
        if ev:
            return (f"{ev.currency}|{ev.title}|{ev.time_utc:%Y-%m-%d %H:%M}",
                    f"өндөр нөлөөтэй мэдээ: {ev.short(now)}")
        if self.fail_closed and not self.known(now):
            return "unknown", "мэдээний календарь мэдэгдэхгүй (fail_closed: true)"
        return "", ""

    def entry_block_reason(self, sym: str, now: datetime | None = None) -> str:
        return self.entry_block(sym, now)[1]

    def status_line(self, now: datetime | None = None) -> str:
        now = now or self.clock()
        if not self.enabled:
            return "Мэдээний шүүлтүүр унтраалттай"
        if self.known(now):
            age = int((now - self.fetched_at).total_seconds() // 3600)
            return f"Мэдээний календарь OK ({age} цагийн өмнө шинэчилсэн)"
        why = f": {self.last_error}" if self.last_error else ""
        return "⚠️ Мэдээний календарь мэдэгдэхгүй" + why
