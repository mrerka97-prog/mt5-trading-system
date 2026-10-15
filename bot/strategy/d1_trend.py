"""D1 trend-following, олон зах зээлд (баримтын P1.2 судалгаа).

Хоёр орох дүрэм:
  donchian:  D1 close > өмнөх N өдрийн хамгийн өндөр → long (short эсрэг)
  ema_cross: EMA(fast) EMA(slow)-ыг дээш огтолсон → long (short эсрэг)
Гарах: анхны SL = sl_atr × ATR(20), дараа нь trail_atr × ATR trailing stop (engine-ийн тохиргоо).
Позицын хэмжээ ATR-аас хамаардаг тул хэрэгсэл бүрийн эрсдэл ижил (хэлбэлзэлд тохируулсан).
Дохио D1 лаа хаагдсаны дараа гарч, дараагийн өдрийн нээлтэд орно.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from bot import indicators as ind


@dataclass(frozen=True)
class D1Params:
    mode: str = "donchian"      # donchian | ema_cross
    entry_n: int = 55
    ema_fast: int = 50
    ema_slow: int = 200
    atr_len: int = 20
    sl_atr: float = 2.0
    tp_atr: float = 50.0        # бараг хүрэхгүй — ашгийг trailing-ээр авна

    @property
    def label(self) -> str:
        return (f"donchian{self.entry_n}" if self.mode == "donchian"
                else f"ema{self.ema_fast}/{self.ema_slow}")


def generate_signals(d1: pd.DataFrame, p: D1Params) -> pd.DataFrame:
    df = d1.copy().reset_index(drop=True)
    df["atr"] = ind.atr(df, p.atr_len)
    if p.mode == "donchian":
        up = df["high"].shift(1).rolling(p.entry_n).max()
        dn = df["low"].shift(1).rolling(p.entry_n).min()
        raw = np.where(df["close"] > up, 1, np.where(df["close"] < dn, -1, 0))
        raw = pd.Series(raw, index=df.index)
        sig = raw.where(raw != raw.shift(1), 0)          # зөвхөн шинэ breakout
    else:
        f, s = ind.ema(df["close"], p.ema_fast), ind.ema(df["close"], p.ema_slow)
        state = np.sign(f - s)
        sig = state.where(state != state.shift(1), 0).fillna(0)
    df["signal"] = np.where(df["atr"].notna(), sig, 0).astype(int)
    df["sl_dist"] = p.sl_atr * df["atr"]
    df["tp_dist"] = p.tp_atr * df["atr"]
    df["reason"] = np.where(df.signal != 0, p.label, "")
    return df
