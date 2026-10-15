"""P2 бодит цагийн runner-ийн тестүүд (хуурамч брокер)."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from bot.backtest.engine import BTConfig, Instrument, run_backtest
from bot.data.store import server_to_utc
from bot.live.runner import Runner
from bot.live.state import State
from bot.strategy.experiments import e1_index_rsi2
from tests.fake_broker import FakeBroker, FakeNotifier

SPEC = {"name": "IDX", "digits": 2, "point": 0.01, "tick_size": 0.01, "tick_value": 0.01,
        "contract_size": 1.0, "volume_min": 0.1, "volume_step": 0.1, "volume_max": 100,
        "currency_base": "USD", "currency_profit": "USD", "account_currency": "USD",
        "swap_mode": 3, "swap_long": 0.0, "swap_short": 0.0, "triple_swap_day": 3}


def index_d1(n=900, seed=4):
    """Өсөлттэй, үе үе огцом уналттай индекс маягийн D1."""
    rng = np.random.default_rng(seed)
    t = pd.bdate_range("2021-01-04", periods=n)
    r = 0.0004 + rng.normal(0, 0.011, n)
    c = 4000 * np.exp(np.cumsum(r))
    o = np.r_[4000, c[:-1]] * (1 + rng.normal(0, 0.002, n))
    hi = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.004, n)))
    return pd.DataFrame({"time": t, "open": o, "high": hi, "low": lo, "close": c, "tick_volume": 1,
                         "spread": 50})


def make_runner(tmp_path, d1, dry=True, signal_only=(), commands=None, balance=100_000.0):
    cfg = {"live": {"trade_symbols": ["IDX"] if "IDX" not in signal_only else [],
                    "signal_only_symbols": list(signal_only), "dry_run": dry, "risk_pct": 1.0,
                    "max_open_positions": 4, "max_hold_days": 10, "rsi_threshold": 5,
                    "pending_timeout_hours": 6, "max_spread_multiple": 2.0},
           "execution": {"magic_number": 240101},
           "risk": {"daily_loss_limit_pct": 2.0, "max_drawdown_pct": 10.0}}
    b = FakeBroker({"IDX": d1}, {"IDX": SPEC}, balance=balance)
    st = State(tmp_path / "s.sqlite")
    tg = FakeNotifier(commands)
    r = Runner(cfg, b, st, tg, clock=lambda: b.now)
    return r, b, st, tg


def replay(r, b, d1, start_idx=300):
    b.goto(d1.time.iloc[start_idx])
    r.startup()
    for day in d1.time.iloc[start_idx:]:
        for hour in (1, 3):                 # шинэ лаа боловсруулах, дараа нь гүйцэтгэх
            b.goto(day, hour)
            r.step()


def test_live_matches_backtest(tmp_path):
    """Бодит цагийн (dry-run) шийдвэрүүд backtest-ийн арилжаатай ижил байх ёстой."""
    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=True)
    replay(r, b, d1)
    live = pd.DataFrame([dict(x) for x in st.closed_positions()])

    sig = e1_index_rsi2(d1.assign(time_utc=server_to_utc(d1.time)), 5)
    cfg = replace(BTConfig(initial_balance=100_000, risk_pct=1.0, break_even_r=0, slippage_pips=0,
                           max_open_positions=4).research(),
                  close_friday_utc_hour=None, max_hold_bars=10, spread_mult=0)
    bt = run_backtest([Instrument(sig, SPEC)], cfg, str(d1.time.iloc[301]), str(d1.time.iloc[-1]))
    t = bt.trades[bt.trades.exit_reason.isin(["EXIT", "TIME"])]
    assert len(live) >= 5
    # Орсон өдрүүд ижил
    live_days = set(pd.to_datetime(live.entry_bar_time).dt.date)
    bt_days = set(pd.to_datetime(t.entry_time).dt.date)
    assert len(live_days & bt_days) >= 0.8 * len(bt_days)
    assert not b.orders                     # dry-run: нэг ч захиалга илгээгээгүй


def test_real_orders_have_sl_and_close(tmp_path):
    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=False)
    replay(r, b, d1)
    opens = [o for o in b.orders if o["op"] == "open"]
    closes = [o for o in b.orders if o["op"] == "close"]
    assert opens and closes
    assert all(o["sl"] > 0 for o in opens)
    assert len(closes) >= len(opens) - 1     # сүүлийнх нь нээлттэй байж болно


def test_signal_only_never_sends_orders(tmp_path):
    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=False, signal_only=("IDX",))
    replay(r, b, d1)
    assert not b.orders
    assert st.closed_positions()


def test_kill_switch_closes_everything(tmp_path):
    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=False)
    b.goto(d1.time.iloc[300])
    r.startup()
    b.goto(d1.time.iloc[300], 3)
    r.step()
    b.pos.append(__import__("tests.fake_broker", fromlist=["FakePos"]).FakePos(1, "IDX", 0.1, 4000, 3900, 0, 240101, 0))
    b.equity_override = 100_000 * 0.85
    r.step()
    assert st.get("killed") is True
    assert not b.pos
    assert any("KILL" in m for m in tg.sent)


def test_pause_blocks_entries(tmp_path):
    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=False, commands=["/pause"])
    replay(r, b, d1)
    assert not [o for o in b.orders if o["op"] == "open"]


def test_min_lot_skip(tmp_path):
    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=False, balance=1_000.0)
    replay(r, b, d1)
    assert not [o for o in b.orders if o["op"] == "open"]
    assert any("хамгийн бага" in m for m in tg.sent)


def test_reconcile_sets_missing_sl(tmp_path):
    from tests.fake_broker import FakePos
    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=False)
    b.goto(d1.time.iloc[400])
    b.pos.append(FakePos(77, "IDX", 0.1, 5000.0, 0.0, 0.0, 240101, 0))
    r.startup()
    assert b.pos[0].sl > 0
    assert any(x["ticket"] == 77 for x in st.open_positions())


def test_catch_up_after_missed_days(tmp_path):
    """Компьютер хэдэн өдөр унтарсан ч алгассан өдрийн гарах дохиог барина."""
    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=True)
    sig = e1_index_rsi2(d1.assign(time_utc=server_to_utc(d1.time)), 5)
    entries = sig.index[(sig.signal == 1) & (sig.index > 320)]
    i = int(entries[0])
    b.goto(d1.time.iloc[i + 1])
    r.startup()
    for h in (1, 3):
        b.goto(d1.time.iloc[i + 1], h)
        r.step()
    assert st.open_positions("IDX")
    # 6 өдөр унтарсан, дараа нь асав
    b.goto(d1.time.iloc[i + 8], 3)
    r.step()
    b.goto(d1.time.iloc[i + 8], 4)
    r.step()
    assert not st.open_positions("IDX")
    assert any(row["event"] == "CATCH_UP" for row in st.db.execute("select event from journal"))


def test_run_once_finishes(tmp_path, monkeypatch):
    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=True)
    b.goto(d1.time.iloc[500], 3)
    monkeypatch.setattr("bot.live.runner._time.sleep", lambda s: None)
    r.run_once(max_minutes=1)
    assert any("Өдрийн шалгалт дууслаа" in m or "гүйцэтгэгдээгүй" in m for m in tg.sent)


def test_uses_yesterday_bar_when_today_not_open(tmp_path, monkeypatch):
    """Зах зээл өнөөдөр нээгдээгүй (өнөөдрийн лаа алга) үед өчигдрийн бүтэн лааг хасахгүй."""
    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=True)
    b.goto(d1.time.iloc[500], 2)
    orig = b.rates
    monkeypatch.setattr(b, "rates", lambda n, tf, c: orig(n, tf, c).iloc[:-1])   # өнөөдрийн лаа байхгүй
    df = r.closed_d1("IDX")
    assert df.time.iloc[-1] == d1.time.iloc[499]
    monkeypatch.setattr(b, "rates", orig)                                        # өнөөдрийн лаа бий
    assert r.closed_d1("IDX").time.iloc[-1] == d1.time.iloc[499]


def test_stale_data_waits_then_processes(tmp_path, monkeypatch):
    """MT5 хуучин түүх өгвөл last_bar-ыг ахиулахгүй, run_once анхааруулна; шинэ өгөгдөл ирэхэд боловсруулна."""
    d1 = index_d1()
    r, b, st, tg = make_runner(tmp_path, d1, dry=True)
    b.goto(d1.time.iloc[500], 2)
    orig = b.rates
    monkeypatch.setattr(b, "rates", lambda n, tf, c: orig(n, tf, c).iloc[:-3])   # 2 өдрөөр хоцорсон
    monkeypatch.setattr("bot.live.runner._time.sleep", lambda s: None)
    r.run_once(max_minutes=0)
    assert st.get("last_bar:IDX") is None
    assert any("өгөгдөл шинэчлэгдсэнгүй" in m for m in tg.sent)
    monkeypatch.setattr(b, "rates", orig)
    r.stale.clear()
    r.step()
    assert st.get("last_bar:IDX") == str(d1.time.iloc[499])
