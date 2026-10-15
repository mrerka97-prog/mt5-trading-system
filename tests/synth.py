"""Тестэд зориулсан хуурамч (synthetic) лааны өгөгдөл үүсгэгч."""
from __future__ import annotations

import numpy as np
import pandas as pd


def make_h1(n: int = 6000, start: str = "2020-01-06", price: float = 1.10, seed: int = 1,
            vol: float = 0.0012, drift_period: int = 900) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = pd.date_range(start, periods=n * 2, freq="h")
    t = t[t.dayofweek < 5][:n]                       # амралтын өдөргүй
    drift = 0.00025 * np.sin(np.arange(n) * 2 * np.pi / drift_period)
    ret = drift + rng.normal(0, vol, n) * 0.3
    close = price * np.exp(np.cumsum(ret))
    open_ = np.concatenate([[price], close[:-1]])
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol * 0.3, n)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol * 0.3, n)))
    return pd.DataFrame({"time": t, "open": open_, "high": hi, "low": lo, "close": close,
                         "tick_volume": 100, "spread": 8})


def to_h4(h1: pd.DataFrame) -> pd.DataFrame:
    g = h1.set_index("time").resample("4h", label="left", closed="left")
    h4 = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(),
                       "close": g.close.last(), "spread": g.spread.max()}).dropna().reset_index()
    return h4


EURUSD_SPEC = {"name": "EURUSD", "digits": 5, "point": 0.00001, "tick_size": 0.00001,
               "tick_value": 1.0, "contract_size": 100000, "volume_min": 0.01, "volume_step": 0.01,
               "volume_max": 50, "currency_base": "EUR", "currency_profit": "USD",
               "account_currency": "USD", "swap_mode": 1, "swap_long": -7.0, "swap_short": 2.0,
               "triple_swap_day": 3, "stops_level": 0, "filling": "IOC"}
