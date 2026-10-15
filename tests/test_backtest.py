import pandas as pd
import pytest

from bot.backtest.engine import BTConfig, Instrument, run_backtest
from bot.backtest.metrics import summarize
from bot.data.store import server_to_utc
from bot.strategy.trend_pullback import Params, generate_signals
from tests.synth import EURUSD_SPEC, make_h1, to_h4


def _signals(n=8000, seed=3, zone="ema"):
    h1 = make_h1(n, seed=seed)
    h1["time_utc"] = server_to_utc(h1["time"])
    return generate_signals(h1, to_h4(h1), Params(zone=zone))


@pytest.mark.parametrize("zone", ["ema", "fib"])
def test_signals_no_lookahead(zone):
    """Ирээдүйн өгөгдлийг хасахад өнгөрсөн дохио өөрчлөгдөх ёсгүй."""
    h1 = make_h1(6000, seed=5)
    h1["time_utc"] = server_to_utc(h1["time"])
    full = generate_signals(h1, to_h4(h1), Params(zone=zone))
    cut_h1 = h1.iloc[:4000]
    cut = generate_signals(cut_h1, to_h4(cut_h1), Params(zone=zone))
    a = full.set_index("time")["signal"].iloc[:3990]
    b = cut.set_index("time")["signal"].iloc[:3990]
    pd.testing.assert_series_equal(a, b)


def test_signals_exist_and_have_sl():
    s = _signals()
    sig = s[s.signal != 0]
    assert len(sig) > 10
    assert (sig.sl_dist > 0).all() and (sig.tp_dist > sig.sl_dist).all()


def test_backtest_runs_and_respects_risk():
    s = _signals()
    cfg = BTConfig(initial_balance=10_000, risk_pct=0.5)
    res = run_backtest([Instrument(s, EURUSD_SPEC)], cfg)
    assert not res.trades.empty
    # SL-ээр хаагдсан арилжааны алдагдал ≈ −1R (slippage, gap-аас бага зэрэг илүү байж болно)
    sl = res.trades[res.trades.exit_reason == "SL"]
    assert (sl.r < 0).all() and (sl.r > -1.6).all()
    # Нэг арилжааны алдагдал 0.5%-иас хэт давахгүй
    assert (sl.pnl > -10_000 * 0.005 * 1.6 - 50).all()
    s2 = summarize(res.trades, res.equity, 10_000, 0.5, str(s.time.iloc[0]), str(s.time.iloc[-1]))
    assert s2["trades"] == len(res.trades)


def test_max_open_positions_respected():
    s1, s2, s3 = _signals(seed=3), _signals(seed=4), _signals(seed=6)
    spec2 = dict(EURUSD_SPEC, name="GBPUSD")
    spec3 = dict(EURUSD_SPEC, name="AUDUSD")
    res = run_backtest([Instrument(s1, EURUSD_SPEC), Instrument(s2, spec2), Instrument(s3, spec3)],
                       BTConfig(max_open_positions=2))
    t = res.trades
    events = [(r.entry_time, 1) for r in t.itertuples()] + [(r.exit_time, -1) for r in t.itertuples()]
    events.sort(key=lambda x: (x[0], x[1]))
    cur = peak = 0
    for _, d in events:
        cur += d
        peak = max(peak, cur)
    assert peak <= 2


def test_kill_switch_stops_trading():
    s = _signals()
    res = run_backtest([Instrument(s, EURUSD_SPEC)], BTConfig(risk_pct=5.0, max_drawdown_pct=10.0))
    if res.killed:
        kill_time = pd.Timestamp(res.events[-1].split(": ")[0]) if res.events else None
        assert kill_time is not None
        after = res.trades[res.trades.entry_time > kill_time]
        assert after.empty
