import numpy as np
import pandas as pd
import pytest

from bot import indicators as ind
from bot.data.store import server_to_utc
from tests.synth import make_h1


def test_ema_formula():
    s = pd.Series([1.0, 2, 3, 4, 5, 6])
    e = ind.ema(s, 3)
    a = 2 / 4
    manual = [s[0]]
    for x in s[1:]:
        manual.append(a * x + (1 - a) * manual[-1])
    assert e.iloc[-1] == pytest.approx(manual[-1])


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 50, dtype=float))
    assert ind.rsi(up, 14).iloc[-1] == pytest.approx(100.0)
    df = make_h1(2000)
    r = ind.rsi(df.close, 14).dropna()
    assert r.between(0, 100).all()


def test_atr_positive():
    df = make_h1(500)
    a = ind.atr(df, 14).dropna()
    assert (a > 0).all()


def test_adx_range():
    df = make_h1(2000)
    a = ind.adx(df, 14).dropna()
    assert a.between(0, 100).all()


def test_swings_have_no_lookahead():
    df = make_h1(1500)
    full = ind.confirmed_swings(df, 5)
    cut = ind.confirmed_swings(df.iloc[:1000], 5)
    pd.testing.assert_frame_equal(full.iloc[:1000], cut)


def test_fib_zone():
    lo, hi = ind.fib_zone(pd.Series([1.08]), pd.Series([1.09]), direction="long")
    assert lo.iloc[0] == pytest.approx(1.09 - 0.01 * 0.618)
    assert hi.iloc[0] == pytest.approx(1.09 - 0.01 * 0.382)


def test_server_to_utc_dst():
    t = pd.Series(pd.to_datetime(["2026-07-01 10:00", "2026-01-15 10:00"]))
    u = server_to_utc(t)
    assert u.iloc[0] == pd.Timestamp("2026-07-01 07:00")   # зун UTC+3
    assert u.iloc[1] == pd.Timestamp("2026-01-15 08:00")   # өвөл UTC+2
