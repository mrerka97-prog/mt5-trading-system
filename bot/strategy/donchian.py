"""Donchian breakout (харьцуулах суурь стратеги, "Turtle" төрлийн trend-following).

Long (short нь эсрэг тал):
  H4 лаа хаагдахад close > өмнөх `entry_n` H4 лааны хамгийн өндөр үнэ → дараагийн H1 лааны нээлтэд орно.
  SL = sl_atr × ATR(H4). TP маш хол (tp_atr), ашгийг ATR trailing stop-оор авна.

Шүүлтүүрүүд trend_pullback-тай ижил (rollover, Баасан гарагийн орой, spread).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from bot import indicators as ind


@dataclass(frozen=True)
class DonchianParams:
    entry_n: int = 55
    atr_len: int = 20
    sl_atr: float = 2.0
    tp_atr: float = 20.0
    rollover_server_hours: tuple[int, ...] = (23, 0)
    friday_cutoff_utc: int = 16
    max_spread_multiple: float = 2.0


def generate_signals(h1: pd.DataFrame, h4: pd.DataFrame, p: DonchianParams) -> pd.DataFrame:
    h4 = h4.copy().reset_index(drop=True)
    h4["close_time"] = h4["time"] + pd.Timedelta(hours=4)
    upper = h4["high"].shift(1).rolling(p.entry_n).max()
    lower = h4["low"].shift(1).rolling(p.entry_n).min()
    h4["atr4"] = ind.atr(h4, p.atr_len)
    h4["brk"] = np.where(h4["close"] > upper, 1, np.where(h4["close"] < lower, -1, 0))
    # Зөвхөн шинэ breakout (өмнөх H4 лаа breakout биш байсан бол)
    h4["brk"] = np.where(h4["brk"] != h4["brk"].shift(1), h4["brk"], 0)

    df = h1.copy().reset_index(drop=True)
    df["close_time"] = df["time"] + pd.Timedelta(hours=1)
    df = pd.merge_asof(df.sort_values("close_time"), h4[["close_time", "atr4"]],
                       on="close_time", direction="backward")
    ev = h4.loc[h4["brk"] != 0, ["close_time", "brk"]]
    df = df.merge(ev, on="close_time", how="left")      # H4 хаагдсан яг тэр H1 лаанд л дохио
    df["brk"] = df["brk"].fillna(0).astype(int)

    ok = (~df["time"].dt.hour.isin(p.rollover_server_hours)
          & ~(df["time"] + pd.Timedelta(hours=1)).dt.hour.isin(p.rollover_server_hours))
    if "time_utc" in df:
        ok &= ~((df["time_utc"].dt.weekday == 4) & (df["time_utc"].dt.hour >= p.friday_cutoff_utc))
    if "spread" in df:
        med = df["spread"].rolling(500, min_periods=50).median()
        ok &= (df["spread"] <= p.max_spread_multiple * med) | med.isna()
    ok &= df["atr4"].notna()

    df["signal"] = np.where(ok, df["brk"], 0)
    df["atr"] = df["atr4"]                      # trailing stop H4 ATR-аар
    df["sl_dist"] = p.sl_atr * df["atr"]
    df["tp_dist"] = p.tp_atr * df["atr"]
    df["reason"] = np.where(df.signal != 0, f"donchian{p.entry_n}", "")
    return df.sort_values("time").reset_index(drop=True)
