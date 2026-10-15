import numpy as np
import pandas as pd

from bot.backtest.engine import BTConfig, Instrument, run_backtest
from bot.data.store import server_to_utc
from bot.research.diagnostics import barrier_grid, breakdown, trend_edge
from bot.strategy import donchian
from bot.strategy.trend_pullback import Params, generate_signals
from tests.synth import EURUSD_SPEC, make_h1, to_h4


def _h1(n=6000, seed=5):
    h1 = make_h1(n, seed=seed)
    h1["time_utc"] = server_to_utc(h1["time"])
    return h1


def test_donchian_no_lookahead():
    h1 = _h1()
    full = donchian.generate_signals(h1, to_h4(h1), donchian.DonchianParams(entry_n=20))
    cut_h1 = h1.iloc[:4000]
    cut = donchian.generate_signals(cut_h1, to_h4(cut_h1), donchian.DonchianParams(entry_n=20))
    a = full.set_index("time")["signal"].iloc[:3990]
    b = cut.set_index("time")["signal"].iloc[:3990]
    pd.testing.assert_series_equal(a, b)
    assert (full.signal != 0).sum() > 5


def test_barrier_grid_shapes_and_bounds():
    h1 = _h1()
    d = generate_signals(h1, to_h4(h1), Params())
    g = barrier_grid(d, 0.00001, 0.0001, [1.0, 2.0], [1.0, 2.0])
    assert len(g) == 4
    assert (g.expectancy_r <= g.rr).all()
    assert (g.expectancy_r >= -1.2).all()


def test_trend_edge_runs():
    h1 = _h1()
    d = generate_signals(h1, to_h4(h1), Params())
    e = trend_edge(d)
    assert set(e.columns) >= {"mean_atr", "t_stat"}


def test_research_mode_never_kills():
    h1 = _h1(8000, 3)
    d = generate_signals(h1, to_h4(h1), Params())
    r = run_backtest([Instrument(d, EURUSD_SPEC)], BTConfig(risk_pct=5.0).research())
    assert not r.killed
    b = breakdown(r.trades)
    assert "exit_reason" in b and "mfe" in b
    assert {"mfe_r", "mae_r"} <= set(r.trades.columns)
    assert (r.trades.mfe_r >= 0).all() and (r.trades.mae_r >= 0).all()
