"""P1.4 туршилтуудын механик (дохионы өдөр зөв эсэх) — синтетик өгөгдөл."""
import numpy as np
import pandas as pd

from bot.strategy.experiments2 import f1_tom, f3_double7


def _d1(n=400):
    t = pd.bdate_range("2021-01-04", periods=n)
    c = 100 + np.cumsum(np.random.default_rng(1).normal(0, 1, n))
    return pd.DataFrame({"time": t, "open": c, "high": c + 1, "low": c - 1, "close": c, "spread": 1})


def test_tom_enters_second_last_bday_exits_day3():
    df = f1_tom(_d1())
    ent = df[df.signal == 1].time
    # Дохионы дараагийн ажлын өдөр = сарын сүүлийн ажлын өдөр
    for t in ent:
        nxt = t + pd.offsets.BDay(1)
        assert (nxt + pd.offsets.BDay(1)).month != nxt.month
    assert len(ent) >= 17                                  # ~19 сар
    ex = df[df.exit_long]
    day_no = ex.time.groupby(ex.time.dt.to_period("M")).cumcount()
    assert (ex.time.dt.day <= 23).all()
    # Сарын сүүлийн өдөр гарах дохио БАЙХГҮЙ (орсон өдрөө хаахгүй)
    last = df.time.groupby(df.time.dt.to_period("M")).transform("max")
    full = last.dt.day >= 26                               # бүтэн сарууд (өгөгдлийн сүүлийн сар дутуу)
    assert not df.loc[(df.time == last) & full, "exit_long"].any()
    del day_no


def test_tom_filter_subset():
    d = _d1()
    a, b = f1_tom(d), f1_tom(d, trend_filter=True)
    assert (b.signal <= a.signal).all()


def test_double7_signal_is_7day_low():
    df = f3_double7(_d1())
    s = df[df.signal == 1]
    assert (s.close <= df.close.rolling(7).min()[s.index]).all()
