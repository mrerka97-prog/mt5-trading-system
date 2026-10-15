import pandas as pd

from bot.backtest.engine import BTConfig, Instrument, run_backtest
from bot.backtest.metrics import summarize
from bot.data.store import server_to_utc
from bot.strategy.d1_trend import D1Params, generate_signals
from tests.synth import EURUSD_SPEC, make_h1


def _d1(seed=2):
    h1 = make_h1(40000, seed=seed)
    g = h1.set_index("time").resample("1D")
    d1 = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                       "close": g.close.last(), "spread": g.spread.median()}).dropna().reset_index()
    d1["time_utc"] = server_to_utc(d1["time"])
    return d1


def test_d1_no_lookahead():
    for p in (D1Params(mode="donchian", entry_n=20), D1Params(mode="ema_cross", ema_fast=20, ema_slow=100)):
        d1 = _d1()
        full = generate_signals(d1, p).signal.iloc[:1000].reset_index(drop=True)
        cut = generate_signals(d1.iloc[:1100], p).signal.iloc[:1000].reset_index(drop=True)
        pd.testing.assert_series_equal(full, cut)
        assert (full != 0).sum() > 3


def test_costs_reduce_results():
    d1 = _d1()
    ins = [Instrument(generate_signals(d1, D1Params(entry_n=20)), EURUSD_SPEC)]
    base = BTConfig(break_even_r=0, trail_atr=3, trail_start_r=0, max_hold_bars=10**5,
                    close_friday_utc_hour=None).research()
    from dataclasses import replace
    net = run_backtest(ins, base)
    gross = run_backtest(ins, replace(base, spread_mult=0, slippage_pips=0, include_swap=False))
    s0, e0 = str(d1.time.iloc[0]), str(d1.time.iloc[-1])
    assert (summarize(gross.trades, gross.equity, 10_000, 0.5, s0, e0)["expectancy_r"]
            >= summarize(net.trades, net.equity, 10_000, 0.5, s0, e0)["expectancy_r"])
    assert gross.trades.swap.abs().sum() == 0
