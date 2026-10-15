"""P1.3 судалгааны туршилтууд — УРЬДЧИЛАН БҮРТГЭСЭН (2026-10-14).

Параметрүүдийг үр дүн харахаас ӨМНӨ тогтоосон. Үр дүнгээс хамаарч өөрчлөхгүй.

E1  Индексийн RSI(2) mean reversion (D1, long only): close > SMA200 ба RSI(2) < 10 (эсвэл < 5)
    → дараагийн өдөр орно. Гарах: close > SMA5, эсвэл 10 өдөр. SL 3×ATR (хамгаалалт).
E2  FX D1 богино хугацааны reversal: RSI(2) < 10 → long, > 90 → short. Гарах: SMA5-ыг давахад, 10 өдөр.
E3a Лондонгийн breakout (H1): Азийн хүрээ (00–07 UTC). 07–10 UTC-д close > хүрээний дээд → long
    (доод → short). SL = хүрээний өргөн, TP = 1× хүрээ. 20 UTC-д хаана. Өдөрт 1 удаа.
E3b Азийн хүрээний fade (H1): 07–12 UTC-д дээд хилийг нэвтлээд буцаад дотор хаагдвал → short,
    TP = хүрээний дунд, SL = өдрийн дээд + 0.5×ATR. 20 UTC-д хаана.
E4  H1 Bollinger mean reversion Азийн сессэд: 00–06 UTC, ADX(H1) < 20, close < BB(20,2) доод → long
    (дээд → short). Гарах: BB дунд шугам, эсвэл 12 лаа. SL 1.5×ATR.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot import indicators as ind

FAR = 50.0   # TP-г бараг хүрэхгүй болгох (гарах дохиогоор хаана)


def _finish(df: pd.DataFrame, sig, sl, tp, label: str) -> pd.DataFrame:
    df["signal"] = pd.Series(sig, index=df.index).fillna(0).astype(int)
    df.loc[df["atr"].isna() | pd.Series(sl, index=df.index).isna(), "signal"] = 0
    df["sl_dist"] = sl
    df["tp_dist"] = tp
    df["reason"] = np.where(df.signal != 0, label, "")
    for col in ("exit_long", "exit_short"):
        if col not in df:
            df[col] = False
        df[col] = df[col].fillna(False).astype(bool)
    return df


# ---------------- D1 ----------------
def e1_index_rsi2(d1: pd.DataFrame, thr: float = 10) -> pd.DataFrame:
    df = d1.copy().reset_index(drop=True)
    df["atr"] = ind.atr(df, 20)
    r2 = ind.rsi(df["close"], 2)
    sma200, sma5 = df["close"].rolling(200).mean(), df["close"].rolling(5).mean()
    sig = np.where((df["close"] > sma200) & (r2 < thr), 1, 0)
    df["exit_long"] = df["close"] > sma5
    return _finish(df, sig, 3 * df["atr"], FAR * df["atr"], f"E1_rsi2<{thr:g}")


def e2_fx_reversal(d1: pd.DataFrame) -> pd.DataFrame:
    df = d1.copy().reset_index(drop=True)
    df["atr"] = ind.atr(df, 20)
    r2 = ind.rsi(df["close"], 2)
    sma5 = df["close"].rolling(5).mean()
    sig = np.where(r2 < 10, 1, np.where(r2 > 90, -1, 0))
    df["exit_long"] = df["close"] > sma5
    df["exit_short"] = df["close"] < sma5
    return _finish(df, sig, 3 * df["atr"], FAR * df["atr"], "E2_fx_rev")


# ---------------- H1 (Азийн хүрээ) ----------------
def _asian_range(h1: pd.DataFrame) -> pd.DataFrame:
    df = h1.copy().reset_index(drop=True)
    df["atr"] = ind.atr(df, 14)
    hu = df["time_utc"].dt.hour
    df["date_utc"] = df["time_utc"].dt.date
    asia = df[hu < 7].groupby("date_utc").agg(a_hi=("high", "max"), a_lo=("low", "min"), a_n=("high", "size"))
    df = df.merge(asia, left_on="date_utc", right_index=True, how="left")
    df.loc[hu < 7, ["a_hi", "a_lo"]] = np.nan          # хүрээ 07:00-оос хойш л мэдэгдэнэ
    df["a_rng"] = df["a_hi"] - df["a_lo"]
    ok = (df["a_n"] >= 5) & (df["a_rng"] >= 2 * df["atr"]) & (df["a_rng"] <= 8 * df["atr"])
    df["range_ok"] = ok.fillna(False)
    df["exit_long"] = hu >= 20
    df["exit_short"] = hu >= 20
    return df


def _first_per_day(df: pd.DataFrame, sig: pd.Series) -> pd.Series:
    """Өдөрт зөвхөн эхний дохио."""
    nz = sig.ne(0)
    first = nz & (nz.astype(int).groupby(df["date_utc"]).cumsum() == 1)
    return sig.where(first, 0)


def e3a_london_breakout(h1: pd.DataFrame) -> pd.DataFrame:
    df = _asian_range(h1)
    hu = df["time_utc"].dt.hour
    win = (hu >= 7) & (hu < 10) & df["range_ok"] & (df["time_utc"].dt.weekday < 5)
    raw = pd.Series(np.where(win & (df.close > df.a_hi), 1, np.where(win & (df.close < df.a_lo), -1, 0)),
                    index=df.index)
    sig = _first_per_day(df, raw)
    return _finish(df, sig, df["a_rng"], df["a_rng"], "E3a_london_bo")


def e3b_asian_fade(h1: pd.DataFrame) -> pd.DataFrame:
    df = _asian_range(h1)
    hu = df["time_utc"].dt.hour
    day_hi = df.groupby("date_utc")["high"].cummax()
    day_lo = df.groupby("date_utc")["low"].cummin()
    win = (hu >= 7) & (hu < 12) & df["range_ok"] & (df["time_utc"].dt.weekday < 5)
    short = win & (df.high > df.a_hi) & (df.close < df.a_hi)
    long_ = win & (df.low < df.a_lo) & (df.close > df.a_lo)
    raw = pd.Series(np.where(short, -1, np.where(long_, 1, 0)), index=df.index)
    sig = _first_per_day(df, raw)
    mid = (df.a_hi + df.a_lo) / 2
    sl = np.where(sig == -1, day_hi + 0.5 * df.atr - df.close, df.close - (day_lo - 0.5 * df.atr))
    tp = (df.close - mid).abs()
    sl = pd.Series(sl, index=df.index).where(lambda x: x > 0)
    tp = tp.where(tp > 0)
    return _finish(df, sig.where(tp.notna(), 0), sl, tp, "E3b_asian_fade")


def e4_bb_asia(h1: pd.DataFrame) -> pd.DataFrame:
    df = h1.copy().reset_index(drop=True)
    df["atr"] = ind.atr(df, 14)
    mid = df["close"].rolling(20).mean()
    sd = df["close"].rolling(20).std()
    up, lo = mid + 2 * sd, mid - 2 * sd
    adx = ind.adx(df, 14)
    hu = df["time_utc"].dt.hour
    win = (hu < 6) & (adx < 20) & (df["time_utc"].dt.weekday < 5)
    sig = np.where(win & (df.close < lo), 1, np.where(win & (df.close > up), -1, 0))
    df["exit_long"] = df["close"] >= mid
    df["exit_short"] = df["close"] <= mid
    return _finish(df, sig, 1.5 * df["atr"], FAR * df["atr"], "E4_bb_asia")
