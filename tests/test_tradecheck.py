from datetime import datetime

import numpy as np
import pandas as pd

from bot.risk.sizing import SymbolSpec
from bot.tradecheck import evaluate, prepare
from tests.synth import make_h1, to_h4

SPEC = SymbolSpec("EURUSD", 0.00001, 1.0, 0.01, 0.01, 50, 5)


def _data(trend_up=True, seed=3):
    h1 = make_h1(3000, seed=seed)
    if not trend_up:
        h1[["open", "high", "low", "close"]] = 2.2 - h1[["open", "high", "low", "close"]].values
        h1["high"], h1["low"] = h1[["open", "high", "low", "close"]].max(axis=1), h1[["open", "high", "low", "close"]].min(axis=1)
    h4 = to_h4(h1)
    g = h1.set_index("time").resample("1D")
    d1 = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                       "close": g.close.last(), "spread": g.spread.median()}).dropna().reset_index()
    return prepare(h1), prepare(h4), prepare(d1)


def _run(side, flags=None, balance=10_000, when=None):
    h1, h4, d1 = _data()
    bid = float(h1.close.iloc[-1])
    now = when or datetime(2020, 6, 3, 9, 0)            # Лхагва, Лондон
    return evaluate("EURUSD", side, h1, h4, d1, bid, bid + 0.00016, SPEC, 0.00001, balance, now,
                    flags=flags)


def test_score_in_range_and_text():
    r = _run(1)
    assert 0 <= r.score <= 100
    assert r.decision in ("ОРОХ", "ХҮЛЭЭХ", "ОРОХГҮЙ")
    assert "Санамж" in r.text()


def test_kill_switch_vetoes():
    r = _run(1, flags={"killed": True})
    assert r.decision == "ОРОХГҮЙ" and any("Kill" in v for v in r.vetoes)


def test_against_trend_veto_one_side_only():
    a, b = _run(1), _run(-1)
    against = [x for x in (a, b) if any("эсрэг" in v for v in x.vetoes)]
    assert len(against) <= 1


def test_small_account_min_lot_veto():
    r = _run(1, balance=50)
    assert r.decision == "ОРОХГҮЙ"


def test_weekend_veto():
    r = _run(1, when=datetime(2020, 6, 6, 10, 0))        # Бямба
    assert any("амралтын" in v for v in r.vetoes)


def test_orders_have_sl_tp_on_right_side():
    for side in (1, -1):
        r = _run(side)
        if r.entry is not None:
            assert (r.sl < r.entry < r.tp) if side == 1 else (r.tp < r.entry < r.sl)


def _news(tmp_path, when):
    from datetime import timezone

    from bot.news import NewsCalendar
    t = when.replace(tzinfo=timezone.utc)
    items = [{"title": "CPI m/m", "country": "USD", "date": t.isoformat(), "impact": "High"}]
    n = NewsCalendar(tmp_path / "n.json", {}, fetcher=lambda: items, clock=lambda: t)
    n.refresh()
    return n


def test_news_veto_inside_window(tmp_path):
    from datetime import timedelta
    now = datetime(2020, 6, 3, 9, 0)
    h1, h4, d1 = _data()
    bid = float(h1.close.iloc[-1])
    n = _news(tmp_path, now + timedelta(minutes=20))
    r = evaluate("EURUSD", 1, h1, h4, d1, bid, bid + 0.00016, SPEC, 0.00001, 10_000, now, news=n)
    assert r.decision == "ОРОХГҮЙ" and any("мэдээ" in v for v in r.vetoes)
    r2 = evaluate("AUDNZD", 1, h1, h4, d1, bid, bid + 0.00016, SPEC, 0.00001, 10_000, now, news=n)
    assert not any("мэдээ" in v for v in r2.vetoes)


def test_news_upcoming_lowers_score(tmp_path):
    from datetime import timedelta
    now = datetime(2020, 6, 3, 9, 0)
    h1, h4, d1 = _data()
    bid = float(h1.close.iloc[-1])
    far = _news(tmp_path / "a", now + timedelta(hours=30))
    near = _news(tmp_path / "b", now + timedelta(hours=3))
    a = evaluate("EURUSD", 1, h1, h4, d1, bid, bid + 0.00016, SPEC, 0.00001, 10_000, now, news=far)
    b = evaluate("EURUSD", 1, h1, h4, d1, bid, bid + 0.00016, SPEC, 0.00001, 10_000, now, news=near)
    assert b.score < a.score
    assert any("CPI" in it.text for it in b.items)
