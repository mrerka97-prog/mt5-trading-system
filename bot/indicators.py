"""Техникийн индикаторууд (pandas). Бүгд зөвхөн өнгөрсөн өгөгдөл ашиглана.

Томъёонууд (баримтын 13-р хэсэг):
  EMA  = α·үнэ + (1−α)·өмнөх EMA, α = 2/(n+1)
  TR   = max(H−L, |H−C₋₁|, |L−C₋₁|);  ATR = Wilder-ийн дундаж
  RSI  = 100 − 100/(1+RS), RS = дундаж өсөлт / дундаж уналт (Wilder)
  ADX  = DX-ийн Wilder дундаж
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    prev = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()],
                     axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder(true_range(df), n)


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    gain = wilder(d.clip(lower=0), n)
    loss = wilder((-d).clip(lower=0), n)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = wilder(true_range(df), n)
    plus_di = 100 * wilder(plus_dm, n) / tr
    minus_di = 100 * wilder(minus_dm, n) / tr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return wilder(dx, n)


def confirmed_swings(df: pd.DataFrame, k: int = 5) -> pd.DataFrame:
    """Fractal swing: лааны high нь өмнөх k ба дараах k лааны high-аас өндөр бол swing high.
    k лааны дараа л баталгаажна, тиймээс утгыг k лаагаар ХОЙШ шилжүүлнэ (look-ahead-гүй).
    Буцаах: last_swing_high, last_swing_low — тухайн мөчид мэдэгдэж байсан хамгийн сүүлийн swing."""
    w = 2 * k + 1
    hi = df["high"]
    lo = df["low"]
    is_high = hi == hi.rolling(w, center=True).max()
    is_low = lo == lo.rolling(w, center=True).min()
    sh = hi.where(is_high).shift(k)   # k лааны дараа мэдэгдэнэ
    sl = lo.where(is_low).shift(k)
    return pd.DataFrame({"swing_high": sh.ffill(), "swing_low": sl.ffill()}, index=df.index)


def fib_zone(swing_low: pd.Series, swing_high: pd.Series, lo_r: float = 0.382, hi_r: float = 0.618,
             direction: str = "long") -> tuple[pd.Series, pd.Series]:
    """Fibonacci retracement бүс. Long: High − (High−Low)·r. Буцаах: (доод, дээд) хил."""
    rng = swing_high - swing_low
    if direction == "long":
        return swing_high - rng * hi_r, swing_high - rng * lo_r
    return swing_low + rng * lo_r, swing_low + rng * hi_r
