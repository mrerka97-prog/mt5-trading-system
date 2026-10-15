"""P1.4 судалгааны туршилтууд — УРЬДЧИЛАН БҮРТГЭСЭН (2026-10-14 23:10 UTC+7, өгөгдөл харахаас ӨМНӨ).

Сонгосон шалтгаан: P1.3-д зөвхөн индексийн богино хугацааны давуу тал (E1b) олдсон. Иймд
(а) индексийн өөр, баримтжсан хэв маяг, (б) P1.2-оос өөр хэлбэрийн trend-following-ийг шалгана.
Параметрүүдийг ном зохиолын стандарт утгаар тогтоосон, үр дүнгээс хамаарч ӨӨРЧЛӨХГҮЙ.

F1  Сарын эргэлт (turn-of-month), индексүүд, long. Сарын сүүлийн ажлын өдрийн НЭЭЛТЭД орно
    (дохио: сүүлээсээ 2 дахь ажлын өдрийн хаалт). Шинэ сарын 3 дахь арилжааны өдрийн хаалтаар
    гарах дохио (дараагийн нээлтэд хаана). SL 3×ATR(20) (хамгаалалт). Шүүлтүүргүй.
    Эх сурвалж: Lakonishok & Smidt (1988), McConnell & Xu (2008).
F2  F1 + close > SMA200 шүүлтүүр (E1b-тэй ижил trend шүүлтүүр).
F3  "Double 7" индекс: close > SMA200 ба close = сүүлийн 7 өдрийн хамгийн бага хаалт → long.
    Гарах: close = сүүлийн 7 өдрийн хамгийн их хаалт, эсвэл 10 өдөр. SL 3×ATR(20).
    Эх сурвалж: Connors & Alvarez (2009). АНХААР: E1b-тэй төстэй, корреляцийг тусад нь хэмжинэ.
F4  Time-series momentum (bot/research/stats.py: ts_momentum), 18 хэрэгсэл, сар бүр:
    252 өдрийн өгөөжийн тэмдгээр long/short, 63 өдрийн хэлбэлзлийн урвуугаар жигнэж, нийт
    жин = 1. Зардал = эргэлт × spread. Swap тооцоогүй. Эх сурвалж: Moskowitz, Ooi, Pedersen (2012).

Хугацаа: in-sample 2010–2019, validation 2020–2023. 2024 оноос хойшхийг АШИГЛАХГҮЙ.
Шалгуур (F1–F3): хоёр хугацаанд net expectancy > 0, PF ≥ 1.2, тус бүр ≥ 30 арилжаа.
Шалгуур (F4): хоёр хугацаанд Sharpe > 0.5.
Олон туршилт: 4 таамаглал тул санамсаргүй давах магадлал өндөр — давсан нь ч демо forward test шаардана.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot import indicators as ind
from bot.strategy.experiments import FAR, _finish


def _tom_flags(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(enter, exit). Сарын сүүлийн ажлын өдрийг хуанлиас (Да–Ба) тооцно — урьдчилан мэдэгдэнэ."""
    t = pd.to_datetime(df["time"]).dt.normalize()
    month_end = t + pd.offsets.MonthEnd(0)
    last_bday = month_end.where(month_end.dt.weekday < 5, month_end - pd.offsets.BDay(1))
    nxt = t + pd.offsets.BDay(1)                           # дараагийн ажлын өдөр
    enter = (nxt == last_bday) & (t.dt.month == nxt.dt.month)
    # Тухайн сарын хэд дэх арилжааны өдөр (өгөгдөл дээрх лааны дугаар — causal).
    # 3..15 = шинэ сарын 3 дахь өдрөөс хойш гарна (сарын сүүлийн өдөр ≥ 18 тул орсон өдрөө гарахгүй).
    day_no = t.groupby(t.dt.to_period("M")).cumcount() + 1
    exit_ = (day_no >= 3) & (day_no <= 15)
    return enter.fillna(False), exit_.fillna(False)


def f1_tom(d1: pd.DataFrame, trend_filter: bool = False) -> pd.DataFrame:
    df = d1.copy().reset_index(drop=True)
    df["atr"] = ind.atr(df, 20)
    enter, exit_ = _tom_flags(df)
    cond = enter
    if trend_filter:
        cond = cond & (df["close"] > df["close"].rolling(200).mean())
    df["exit_long"] = exit_
    return _finish(df, np.where(cond, 1, 0), 3 * df["atr"], FAR * df["atr"],
                   "F2_tom_sma200" if trend_filter else "F1_tom")


def f3_double7(d1: pd.DataFrame) -> pd.DataFrame:
    df = d1.copy().reset_index(drop=True)
    df["atr"] = ind.atr(df, 20)
    c = df["close"]
    sig = (c > c.rolling(200).mean()) & (c <= c.rolling(7).min())
    df["exit_long"] = c >= c.rolling(7).max()
    return _finish(df, np.where(sig, 1, 0), 3 * df["atr"], FAR * df["atr"], "F3_double7")
