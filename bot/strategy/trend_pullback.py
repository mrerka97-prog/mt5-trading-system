"""Trend + pullback стратеги (баримтын 5-р хэсэг).

Long (short нь эсрэг тал):
  1. H4: close > EMA200, EMA50 > EMA200, ADX > adx_min
  2. H1: сүүлийн `lookback` лаанд үнэ pullback бүсэд хүрсэн (EMA20–EMA50 эсвэл Fibonacci 38.2–61.8%)
  3. H1: тэр хугацаанд RSI rsi_low..rsi_mid хооронд хүртэл буусан
  4. H1: батлах лаа — close > өмнөх лааны high, close > open
  SL = signal_close − sl_atr·ATR,  TP = signal_close + tp_atr·ATR

Дохио лаа ХААГДСАНЫ дараа гарч, дараагийн лааны нээлтэд орно (look-ahead-гүй).
Шүүлтүүрүүд: сесс (UTC), rollover (серверийн цаг), spread.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from bot import indicators as ind


@dataclass(frozen=True)
class Params:
    zone: str = "ema"            # "ema" | "fib"
    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 200
    adx_min: float = 20.0
    rsi_len: int = 14
    rsi_low: float = 35.0
    rsi_mid: float = 50.0
    lookback: int = 5
    atr_len: int = 14
    sl_atr: float = 1.5
    tp_atr: float = 3.0
    swing_k: int = 5
    session_utc: tuple[int, int] = (7, 20)        # Лондон нээгдэхээс НЙ-ийн дунд хүртэл
    rollover_server_hours: tuple[int, ...] = (23, 0)
    friday_cutoff_utc: int = 16
    max_spread_multiple: float = 2.0

    @classmethod
    def from_config(cls, cfg: dict, **override) -> "Params":
        s = dict(cfg.get("strategy", {}))
        s.update(override)
        if "session_utc" in s:
            s["session_utc"] = tuple(s["session_utc"])
        if "rollover_server_hours" in s:
            s["rollover_server_hours"] = tuple(s["rollover_server_hours"])
        return cls(**{k: v for k, v in s.items() if k in cls.__dataclass_fields__})


def h4_trend(h4: pd.DataFrame, p: Params) -> pd.DataFrame:
    """H4 trend-ийн төлөв, H4 лаа хаагдсан цагтай (close_time)."""
    out = pd.DataFrame({
        "close_time": h4["time"] + pd.Timedelta(hours=4),
        "h4_close": h4["close"],
        "h4_ema_slow": ind.ema(h4["close"], p.ema_slow),
        "h4_ema_trend": ind.ema(h4["close"], p.ema_trend),
        "h4_adx": ind.adx(h4, 14),
    })
    up = (out.h4_close > out.h4_ema_trend) & (out.h4_ema_slow > out.h4_ema_trend) & (out.h4_adx > p.adx_min)
    dn = (out.h4_close < out.h4_ema_trend) & (out.h4_ema_slow < out.h4_ema_trend) & (out.h4_adx > p.adx_min)
    out["trend"] = np.where(up, 1, np.where(dn, -1, 0))
    return out[["close_time", "trend", "h4_adx"]]


def generate_signals(h1: pd.DataFrame, h4: pd.DataFrame, p: Params) -> pd.DataFrame:
    """h1, h4: time (серверийн цаг, лаа НЭЭГДСЭН цаг), open, high, low, close, spread (+ time_utc).
    Буцаах: h1-ийн мөр бүрт signal (1/-1/0), sl_dist, tp_dist, atr болон шалтгаан."""
    df = h1.copy().reset_index(drop=True)
    df["close_time"] = df["time"] + pd.Timedelta(hours=1)

    # H4 trend-ийг зөвхөн ХААГДСАН H4 лаанаас авна
    tr = h4_trend(h4, p).sort_values("close_time")
    df = pd.merge_asof(df.sort_values("close_time"), tr, on="close_time", direction="backward")

    c = df["close"]
    df["ema_f"] = ind.ema(c, p.ema_fast)
    df["ema_s"] = ind.ema(c, p.ema_slow)
    df["rsi"] = ind.rsi(c, p.rsi_len)
    df["atr"] = ind.atr(df, p.atr_len)
    lb = p.lookback
    min_low = df["low"].rolling(lb).min()
    max_high = df["high"].rolling(lb).max()
    min_rsi = df["rsi"].rolling(lb).min()
    max_rsi = df["rsi"].rolling(lb).max()

    if p.zone == "fib":
        sw = ind.confirmed_swings(df, p.swing_k)
        l_lo, l_hi = ind.fib_zone(sw.swing_low, sw.swing_high, direction="long")
        s_lo, s_hi = ind.fib_zone(sw.swing_low, sw.swing_high, direction="short")
        valid = sw.swing_high > sw.swing_low
    else:
        l_lo = s_lo = np.minimum(df.ema_f, df.ema_s)
        l_hi = s_hi = np.maximum(df.ema_f, df.ema_s)
        valid = pd.Series(True, index=df.index)

    tol = 0.5 * df["atr"]
    long_zone = valid & (min_low <= l_hi) & (min_low >= l_lo - tol)
    short_zone = valid & (max_high >= s_lo) & (max_high <= s_hi + tol)

    long_rsi = (min_rsi >= p.rsi_low) & (min_rsi <= p.rsi_mid)
    short_rsi = (max_rsi <= 100 - p.rsi_low) & (max_rsi >= 100 - p.rsi_mid)

    long_conf = (c > df["high"].shift(1)) & (c > df["open"])
    short_conf = (c < df["low"].shift(1)) & (c < df["open"])

    # Шүүлтүүрүүд
    if "time_utc" in df:
        h_utc = df["time_utc"].dt.hour
        session_ok = (h_utc >= p.session_utc[0]) & (h_utc < p.session_utc[1])
        # Баасан гарагийн орой шинэ арилжаа нээхгүй (амралтын өдрийн өмнө хаагдана)
        session_ok &= ~((df["time_utc"].dt.weekday == 4) & (h_utc >= p.friday_cutoff_utc))
    else:
        session_ok = pd.Series(True, index=df.index)
    # Дохионы лаа болон ОРОХ лаа (дараагийнх) хоёулаа rollover-оос гадуур байх ёстой
    rollover_ok = (~df["time"].dt.hour.isin(p.rollover_server_hours)
                   & ~(df["time"] + pd.Timedelta(hours=1)).dt.hour.isin(p.rollover_server_hours))
    if "spread" in df:
        med = df["spread"].rolling(500, min_periods=50).median()
        spread_ok = (df["spread"] <= p.max_spread_multiple * med) | med.isna()
    else:
        spread_ok = pd.Series(True, index=df.index)
    filt = session_ok & rollover_ok & spread_ok & df["atr"].notna()

    go_long = (df.trend == 1) & long_zone & long_rsi & long_conf & filt
    go_short = (df.trend == -1) & short_zone & short_rsi & short_conf & filt

    df["signal"] = np.where(go_long, 1, np.where(go_short, -1, 0))
    df["sl_dist"] = p.sl_atr * df["atr"]
    df["tp_dist"] = p.tp_atr * df["atr"]
    df["reason"] = np.where(df.signal != 0,
                            "trend=" + df.trend.astype(str) + " adx=" + df.h4_adx.round(1).astype(str)
                            + f" zone={p.zone} rsi=" + np.where(df.signal == 1, min_rsi, max_rsi).round(1).astype(str),
                            "")
    return df.sort_values("time").reset_index(drop=True)
