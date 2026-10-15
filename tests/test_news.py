"""Мэдээний календарийн шүүлтүүрийн тест (сүлжээ ашиглахгүй)."""
import json
from datetime import datetime, timedelta, timezone

from bot.news import NewsCalendar, parse_ff, symbol_currencies

UTC = timezone.utc
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)          # Лхагва 12:00 UTC

ITEMS = [
    # 08:30 NY (EDT, UTC-4) = 12:30 UTC
    {"title": "CPI m/m", "country": "USD", "date": "2026-10-14T08:30:00-04:00", "impact": "High",
     "forecast": "0.3%", "previous": "0.2%"},
    {"title": "Retail Sales", "country": "USD", "date": "2026-10-14T10:00:00-04:00", "impact": "Medium"},
    {"title": "ECB Press Conference", "country": "EUR", "date": "2026-10-15T08:45:00-04:00", "impact": "High"},
    {"title": "Bank Holiday", "country": "JPY", "date": "2026-10-12T19:00:00-04:00", "impact": "Holiday"},
    {"title": "broken", "country": "USD", "date": "not-a-date", "impact": "High"},
]


def cal(tmp_path, items=ITEMS, now=NOW, cfg=None, fail=False):
    calls = []

    def fetcher():
        calls.append(1)
        if fail:
            raise OSError("network down")
        return items
    c = NewsCalendar(tmp_path / "news.json", cfg or {}, fetcher=fetcher, clock=lambda: now)
    return c, calls


def test_parse_converts_to_utc_and_skips_bad():
    ev = parse_ff(ITEMS)
    assert len(ev) == 4
    cpi = next(e for e in ev if e.title == "CPI m/m")
    assert cpi.time_utc == datetime(2026, 10, 14, 12, 30, tzinfo=UTC)


def test_symbol_currencies():
    assert symbol_currencies("US500") == ["USD"]
    assert symbol_currencies("GER40Cash") == ["EUR"]
    assert symbol_currencies("EURUSD#") == ["EUR", "USD"]
    assert symbol_currencies("JP225") == ["JPY"]
    assert symbol_currencies("US500", {"US500": ["USD", "EUR"]}) == ["USD", "EUR"]


def test_blackout_window(tmp_path):
    c, _ = cal(tmp_path)
    c.refresh()
    cpi = datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
    assert c.blackout("US500", cpi - timedelta(minutes=31)) is None
    assert c.blackout("US500", cpi - timedelta(minutes=30)) is not None
    assert c.blackout("US500", cpi + timedelta(minutes=30)) is not None
    assert c.blackout("US500", cpi + timedelta(minutes=31)) is None
    assert c.blackout("GER40", cpi) is None                    # EUR-д нөлөөгүй
    assert c.blackout("EURUSD", cpi) is not None               # хосын аль нэг валют
    # Medium мэдээ (Retail Sales 14:00 UTC) хоригдохгүй
    assert c.blackout("US500", datetime(2026, 10, 14, 14, 0, tzinfo=UTC)) is None


def test_cache_and_rate_limit(tmp_path):
    c, calls = cal(tmp_path)
    assert c.refresh() is True
    assert c.refresh() is False and len(calls) == 1           # 6 цаг дотор дахин татахгүй
    saved = json.loads((tmp_path / "news.json").read_text(encoding="utf-8"))
    assert len(saved["items"]) == len(ITEMS)
    # Шинэ instance кэшээс уншина, сүлжээ дуудахгүй
    c2, calls2 = cal(tmp_path)
    assert c2.known() and c2.refresh() is False and not calls2


def test_fetch_failure_keeps_old_cache(tmp_path):
    c, _ = cal(tmp_path)
    c.refresh()
    later = NOW + timedelta(hours=7)
    c2, calls = cal(tmp_path, now=later, fail=True)
    assert c2.refresh() is False and calls
    assert c2.known(later)                                    # 7 цаг < stale 30 цаг
    assert c2.blackout("US500", datetime(2026, 10, 14, 12, 30, tzinfo=UTC))
    assert c2.refresh() is False and len(calls) == 1          # алдааны дараа 15 мин хүлээнэ


def test_unknown_calendar_fail_open_and_closed(tmp_path):
    c, _ = cal(tmp_path, fail=True)
    c.refresh()
    assert not c.known()
    assert c.entry_block_reason("US500") == ""                # fail_closed: false
    assert "Мэдээний календарь мэдэгдэхгүй" in c.status_line()
    c2, _ = cal(tmp_path / "x", fail=True, cfg={"fail_closed": True})
    c2.refresh()
    assert "fail_closed" in c2.entry_block_reason("US500")


def test_stale_cache_is_unknown(tmp_path):
    c, _ = cal(tmp_path)
    c.refresh()
    assert not c.known(NOW + timedelta(hours=31))


def test_upcoming(tmp_path):
    c, _ = cal(tmp_path)
    c.refresh()
    ev = c.upcoming(["USD", "EUR"], 48)
    assert [e.title for e in ev] == ["CPI m/m", "ECB Press Conference"]
    assert "мин-ийн дараа" in ev[0].short(NOW)


def test_disabled(tmp_path):
    c, calls = cal(tmp_path, cfg={"enabled": False})
    assert c.refresh() is False and not calls
    assert c.blackout("US500", datetime(2026, 10, 14, 12, 30, tzinfo=UTC)) is None


# ---------------------------------------------------------------- runner-тэй холбох
def _runner_with_news(tmp_path, news_minutes_after_entry):
    """E1b-ийн нэг дохионы гүйцэтгэх цагт мэдээ тааруулна."""
    from bot.data.store import server_to_utc
    from bot.strategy.experiments import e1_index_rsi2
    from tests.test_live import index_d1, make_runner

    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=True)
    sig = e1_index_rsi2(d1.assign(time_utc=server_to_utc(d1.time)), 5)
    i = int(sig.index[(sig.signal == 1) & (sig.index > 320)][0])
    exec_time = b.goto(d1.time.iloc[i + 1], 1)
    ev_time = exec_time + timedelta(minutes=news_minutes_after_entry)
    items = [{"title": "Non-Farm Employment Change", "country": "USD",
              "date": ev_time.isoformat(), "impact": "High"}]
    news = NewsCalendar(tmp_path / "n.json", {"symbol_currencies": {"IDX": ["USD"]}},
                        fetcher=lambda: items, clock=lambda: b.now)
    r.news = news
    return r, b, st, tg, d1, i


def test_runner_defers_entry_during_news_then_enters(tmp_path):
    r, b, st, tg, d1, i = _runner_with_news(tmp_path, 10)       # мэдээ гүйцэтгэхээс 10 мин дараа
    b.goto(d1.time.iloc[i + 1], 1)
    r.startup()
    r.step()                                                    # шинэ лаа → pending enter, мэдээ → хүлээнэ
    r.step()
    assert st.get_pending("IDX") and not st.open_positions("IDX")
    assert sum("📰" in m for m in tg.sent) == 1                  # нэг л удаа мэдэгдэнэ
    assert any(row["event"] == "NEWS_WAIT" for row in st.db.execute("select event from journal"))
    b.now = b.now + timedelta(minutes=41)                       # мэдээнээс 31 мин өнгөрсөн
    r.step()
    assert st.open_positions("IDX") and not st.get_pending("IDX")
    assert st.get("news_wait:IDX") is None


def test_runner_news_does_not_block_exit(tmp_path):
    r, b, st, tg, d1, i = _runner_with_news(tmp_path, 10_000)   # мэдээ хол
    b.goto(d1.time.iloc[i + 1], 1)
    r.startup()
    for h in (1, 3):
        b.goto(d1.time.iloc[i + 1], h)
        r.step()
    assert st.open_positions("IDX")
    # Позиц нээлттэй үед мэдээний цонхонд гарах дохио гүйцэтгэгдэх ёстой
    for k in range(i + 2, i + 12):
        b.goto(d1.time.iloc[k], 1)
        r.step()
        if st.get_pending("IDX"):
            b.goto(d1.time.iloc[k], 3)
            r.news = NewsCalendar(tmp_path / "n2.json", {"symbol_currencies": {"IDX": ["USD"]}},
                                  clock=lambda: b.now, fetcher=lambda: [
                {"title": "CPI", "country": "USD", "date": b.now.isoformat(), "impact": "High"}])
            r.news.refresh()
            assert r.news.blackout("IDX") is not None
            r.step()
            break
    assert not st.open_positions("IDX")


def test_runner_status_lists_news(tmp_path):
    r, b, st, tg, d1, i = _runner_with_news(tmp_path, 120)
    b.goto(d1.time.iloc[i + 1], 1)
    r.news.refresh()
    lines = r.news_lines()
    assert any("Non-Farm" in x for x in lines)
    assert "USD" in lines[0]
