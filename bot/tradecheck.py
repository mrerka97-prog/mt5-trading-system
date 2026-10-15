"""Trade Check: хэрэглэгчийн арилжааны саналыг шалгах (дизайн баримтын 15-р хэсэг).

3 шат:
  1. Хатуу дүрэм (veto) — аль нэг нь зөрчигдвөл шууд ОРОХГҮЙ.
  2. Оноо (0–100) — trend, setup, хэлбэлзэл, сесс, мэдээ. Мэдэгдэхгүй хүчин зүйлийг (ML, эсвэл
     календарь татагдаагүй үеийн мэдээ) оноонд оруулахгүй, жинг бусад дээр дахин хуваарилна.
  3. Хэзээ орох — setup бүрдээгүй бол pullback бүсийн limit үнэ, хүчинтэй хугацаа.

АНХААР: Судалгаагаар H1 trend+pullback-д давуу тал олдоогүй. Оноо бол таамаглал биш,
сахилга батын шалгах жагсаалт. Үр дүнг бүртгэж, цаг хугацааны явцад хэмжинэ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from bot import indicators as ind
from bot.data.store import server_to_utc
from bot.risk.sizing import SymbolSpec, calculate_lot
from bot.strategy.experiments import e1_index_rsi2

INDICES = {"US500", "US30", "GER40", "JP225"}
WEIGHTS = {"trend": 25, "setup": 25, "volatility": 15, "session": 10, "news": 15}   # ML 10 — хараахан байхгүй
NEWS_LOOKAHEAD_H = 8          # саналын хүчинтэй хугацаа (8 цаг) доторх мэдээг тооцно


@dataclass
class Item:
    ok: bool | None          # True = ✅, False = ⚠️/❌, None = мэдээлэлгүй
    text: str


@dataclass
class CheckResult:
    symbol: str
    side: int
    decision: str                       # ОРОХ / ХҮЛЭЭХ / ОРОХГҮЙ
    score: int
    vetoes: list[str] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    plan: str = ""
    lot: float | None = None
    entry: float | None = None
    sl: float | None = None
    tp: float | None = None
    risk_money: float | None = None

    def text(self, now_local: str = "") -> str:
        side = "BUY" if self.side == 1 else "SELL"
        icon = {"ОРОХ": "✅", "ХҮЛЭЭХ": "⏳", "ОРОХГҮЙ": "⛔"}[self.decision]
        lines = [f"/check {self.symbol} {side}   {now_local}".rstrip(),
                 f"Шийдвэр: {icon} {self.decision}   (оноо {self.score}/100)", ""]
        for v in self.vetoes:
            lines.append(f"[ХОРИГ] {v}")
        for it in self.items:
            mark = "[OK]  " if it.ok else ("[--]  " if it.ok is None else "[!!]  ")
            lines.append(mark + it.text)
        if self.plan:
            lines += ["", self.plan]
        lines += ["", "Санамж: оноо бол баталгаажсан таамаглал биш, шалгах жагсаалт."]
        return "\n".join(lines)


def _session_score(utc: datetime) -> tuple[float, str]:
    h, wd = utc.hour, utc.weekday()
    if wd >= 5:
        return 0.0, "Амралтын өдөр"
    if 12 <= h < 16:
        return 1.0, "Лондон + Нью-Йорк давхцал (хамгийн идэвхтэй)"
    if 7 <= h < 12:
        return 0.85, "Лондонгийн сесс"
    if 16 <= h < 20:
        return 0.6, "Нью-Йоркийн сесс"
    return 0.25, "Азийн / нам гүм цаг"


def evaluate(symbol: str, side: int, h1: pd.DataFrame, h4: pd.DataFrame, d1: pd.DataFrame,
             bid: float, ask: float, spec: SymbolSpec, point: float, balance: float,
             now_utc: datetime, risk_pct: float = 1.0, flags: dict | None = None, news=None) -> CheckResult:
    """h1/h4/d1: ХААГДСАН лаанууд (серверийн цаг). flags: paused/killed/day_blocked/open_positions.
    news: bot.news.NewsCalendar эсвэл None."""
    flags = flags or {}
    res = CheckResult(symbol, side, "ОРОХГҮЙ", 0)
    price = ask if side == 1 else bid

    # ---------- үзүүлэлтүүд ----------
    c4 = h4["close"]
    ema50_4, ema200_4 = ind.ema(c4, 50).iloc[-1], ind.ema(c4, 200).iloc[-1]
    adx4 = float(ind.adx(h4, 14).iloc[-1])
    trend = 1 if (c4.iloc[-1] > ema200_4 and ema50_4 > ema200_4) else (
        -1 if (c4.iloc[-1] < ema200_4 and ema50_4 < ema200_4) else 0)
    c1 = h1["close"]
    ema20, ema50 = ind.ema(c1, 20).iloc[-1], ind.ema(c1, 50).iloc[-1]
    rsi = ind.rsi(c1, 14)
    atr1 = float(ind.atr(h1, 14).iloc[-1])
    atr_ratio = atr1 / float(ind.atr(h1, 14).tail(24 * 20).mean())
    spread_pts = (ask - bid) / point
    typical = float(h1["spread"].replace(0, np.nan).tail(500).median()) if "spread" in h1 else 0.0
    pip = spec.pip_size
    utc = now_utc.replace(tzinfo=None)

    # ---------- 1. ХАТУУ ДҮРЭМ ----------
    if flags.get("killed"):
        res.vetoes.append("Kill-switch идэвхтэй")
    if flags.get("paused"):
        res.vetoes.append("Бот түр зогссон (/pause)")
    if flags.get("day_blocked"):
        res.vetoes.append("Өдрийн алдагдлын лимит хүрсэн")
    if flags.get("open_positions", 0) >= flags.get("max_positions", 4):
        res.vetoes.append("Нээлттэй позицын хязгаар хүрсэн")
    if typical and spread_pts > 2 * typical:
        res.vetoes.append(f"Spread {spread_pts / 10 if spec.digits in (3, 5) else spread_pts:.1f} pip — "
                          f"хэвийнээс 2 дахин их")
    if trend != 0 and trend != side:
        res.vetoes.append(f"H4 trend-ийн эсрэг ({'өсөх' if trend == 1 else 'буурах'} trend)")
    if utc.weekday() == 4 and utc.hour >= 16 or utc.weekday() >= 5:
        res.vetoes.append("Баасан гарагийн орой / амралтын өдөр")
    server_hour = (pd.Timestamp(utc) + (h1["time"].iloc[-1] - h1["time_utc"].iloc[-1])).hour
    if server_hour in (23, 0):
        res.vetoes.append("Rollover цаг (spread өргөсдөг)")

    now_aware = utc.replace(tzinfo=timezone.utc)
    news_known = bool(news and news.enabled and news.known(now_aware))
    upcoming = []
    if news_known:
        ev = news.blackout(symbol, now_aware)
        if ev:
            res.vetoes.append(f"Өндөр нөлөөтэй мэдээний ±{news.minutes_before} мин: {ev.short(now_aware)}")
        upcoming = [e for e in news.upcoming(news.currencies(symbol), NEWS_LOOKAHEAD_H, now_aware)
                    if e.time_utc > now_aware]

    sl_dist = 1.5 * atr1
    tp_dist = 3.0 * atr1
    lot = calculate_lot(balance, risk_pct, sl_dist, spec, tp_distance=tp_dist)
    if not lot.lot:
        res.vetoes.append(lot.reason)

    # ---------- 2. ОНОО ----------
    s_trend = 0.0
    if trend == side:
        s_trend = min(1.0, max(0.0, (adx4 - 15) / 20))
    res.items.append(Item(trend == side and adx4 > 20,
                          f"H4 trend: {'өсөх' if trend == 1 else 'буурах' if trend == -1 else 'тодорхойгүй'}, "
                          f"ADX {adx4:.0f}"))
    lo, hi = min(ema20, ema50), max(ema20, ema50)
    recent = h1.tail(5)
    tol = 0.5 * atr1
    # Сүүлийн 5 лаанд бүсэд хүрсэн БӨГӨӨД одоогийн үнэ бүсээс хэт холдоогүй/нэвтрээгүй байх
    in_zone = ((recent["low"].min() <= hi and lo - tol <= price <= hi + 2 * tol) if side == 1
               else (recent["high"].max() >= lo and lo - 2 * tol <= price <= hi + tol))
    rsi_ok = (rsi.tail(5).min() <= 50) if side == 1 else (rsi.tail(5).max() >= 50)
    confirm = (c1.iloc[-1] > h1["high"].iloc[-2]) if side == 1 else (c1.iloc[-1] < h1["low"].iloc[-2])
    s_setup = (0.4 * in_zone + 0.3 * rsi_ok + 0.3 * confirm)
    above, below = price > hi + tol, price < lo - tol
    zone_word = ("хүрсэн" if in_zone else "дээш гарсан" if above else "доош гарсан" if below else "хүрээгүй")
    res.items.append(Item(bool(in_zone), f"Үнэ pullback бүсэд {zone_word} " if zone_word in ("хүрсэн", "хүрээгүй")
                          else f"Үнэ pullback бүсээс {zone_word} "
                                         f"(EMA20–50: {lo:.{spec.digits}f}–{hi:.{spec.digits}f}, одоо {price:.{spec.digits}f})"))
    res.items.append(Item(bool(rsi_ok), f"RSI(14) {rsi.iloc[-1]:.0f} — сүүлийн 5 лаанд "
                                        f"{'50-аас доош буусан' if side == 1 else '50-аас дээш гарсан'}: "
                                        f"{'тийм' if rsi_ok else 'үгүй'}"))
    trigger = h1["high"].iloc[-1] if side == 1 else h1["low"].iloc[-1]
    res.items.append(Item(bool(confirm), "Батлах лаа: " + ("бий" if confirm else
                          f"алга (H1 лаа {trigger:.{spec.digits}f}-аас {'дээш' if side == 1 else 'доош'} хаагдах ёстой)")))
    s_vol = 1.0 if 0.7 <= atr_ratio <= 1.5 else (0.5 if 0.5 <= atr_ratio <= 2.0 else 0.0)
    res.items.append(Item(s_vol >= 1.0, f"Хэлбэлзэл: ATR харьцаа {atr_ratio:.2f} (0.7–1.5 хэвийн)"))
    s_sess, sess_txt = _session_score(utc)
    res.items.append(Item(s_sess >= 0.6, f"Сесс: {sess_txt}"))
    if news_known:
        s_news = 1.0 if not upcoming else 0.3
        res.items.append(Item(not upcoming, (f"Мэдээ ({', '.join(news.currencies(symbol))}): "
                                             + (upcoming[0].short(now_aware) if upcoming
                                                else f"дараагийн {NEWS_LOOKAHEAD_H} цагт өндөр нөлөөтэй мэдээ алга"))))
    else:
        s_news = None
        res.items.append(Item(None, "Мэдээний календарь: " + (news.status_line(now_aware) if news
                                                              else "холбогдоогүй") + " — ForexFactory-оос өөрөө шалга"))
    if typical and not any("Spread" in v for v in res.vetoes):
        res.items.append(Item(True, f"Spread хэвийн ({spread_pts:.0f} point, дундаж {typical:.0f})"))

    total_w = sum(WEIGHTS.values()) - (WEIGHTS["news"] if s_news is None else 0)
    raw = (WEIGHTS["trend"] * s_trend + WEIGHTS["setup"] * s_setup
           + WEIGHTS["volatility"] * s_vol + WEIGHTS["session"] * s_sess
           + (WEIGHTS["news"] * s_news if s_news is not None else 0))
    res.score = int(round(raw / total_w * 100))

    if symbol in INDICES and len(d1) > 200:
        e1 = e1_index_rsi2(d1, 5).iloc[-1]
        res.items.append(Item(bool(e1["signal"] == 1 and side == 1),
                              f"E1b (индексийн RSI2) дохио: {'БАЙНА' if e1['signal'] == 1 else 'алга'}"))

    # ---------- 3. ШИЙДВЭР ба ХЭЗЭЭ ----------
    res.lot, res.risk_money = lot.lot, lot.risk_money if lot.lot else None
    if res.vetoes:
        res.decision = "ОРОХГҮЙ"
        res.plan = "Хориг арилсны дараа дахин шалгана уу."
        return res
    wait_note = ""
    overshoot = (side == 1 and price < lo - tol) or (side == -1 and price > hi + tol)
    if res.score >= 75 and confirm and not overshoot:
        res.decision = "ОРОХ"
        res.entry = price
    elif res.score >= 50 and overshoot:
        res.decision = "ХҮЛЭЭХ"
        res.plan = ("Үнэ pullback бүсийг " + ("доош" if side == 1 else "дээш")
                    + " нэвтэрсэн — trend сулрах эрсдэлтэй. Захиалга санал болгохгүй. "
                    "Үнэ бүс рүү буцаж ороод батлах лаа гарвал дахин шалга.")
        return res
    elif res.score >= 50:
        res.decision = "ХҮЛЭЭХ"
        if not in_zone:
            res.entry = hi if side == 1 else lo
            wait_note = "Үнэ pullback бүсэд хүрэхийг хүлээ (LIMIT)."
        else:
            res.entry = price
            wait_note = (f"Бүсэд байна. H1 лаа {trigger:.{spec.digits}f}-аас "
                         f"{'дээш' if side == 1 else 'доош'} хаагдвал MARKET-аар ор.")
    else:
        res.decision = "ОРОХГҮЙ"
    if res.decision != "ОРОХГҮЙ":
        res.sl = res.entry - side * sl_dist
        res.tp = res.entry + side * tp_dist
        d = spec.digits
        kind = "MARKET" if res.decision == "ОРОХ" or in_zone else "LIMIT"
        expiry = (utc + timedelta(hours=8)).strftime("%H:%M UTC")
        if upcoming:
            ev = upcoming[0]
            after = (ev.time_utc + timedelta(minutes=news.minutes_after)).strftime("%H:%M UTC")
            before = (ev.time_utc - timedelta(minutes=60)).strftime("%H:%M UTC")
            wait_note = (wait_note + "\n" if wait_note else "") + (
                f"Мэдээ {ev.currency} {ev.title}: {before}-аас өмнө биелээгүй LIMIT-ийг цуцал; "
                f"шинээр орох бол {after}-аас хойш дахин шалга.")
        res.plan = (f"Санал: {'BUY' if side == 1 else 'SELL'} {kind} {res.entry:.{d}f}, SL {res.sl:.{d}f}, "
                    f"TP {res.tp:.{d}f}, {lot.lot} lot\n"
                    f"Эрсдэл ≈ {lot.risk_money} ({lot.risk_pct}%), ашиг ≈ {lot.reward_money}, R/R 1:2"
                    + (f"\nХүчинтэй: {expiry} хүртэл" if res.decision == "ХҮЛЭЭХ" else "")
                    + (f"\n{wait_note}" if wait_note else ""))
    else:
        res.plan = "Нөхцөл бүрдээгүй. Trend, setup илүү тод болохыг хүлээ."
    return res


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    df["time_utc"] = server_to_utc(df["time"])
    return df


def check_live(broker, cfg: dict, st, sym: str, side: int, root, news=None) -> str:
    """MT5-аас бодит өгөгдөл аваад шалгаж, бүртгээд текст буцаана (скрипт ба Telegram хоёулаа ашиглана)."""
    import csv
    from datetime import timezone as _tz

    from bot.data.store import fill_zero_spread

    aliases = cfg.get("research_d1", {}).get("universe", {}).get(sym, [sym])
    name = broker.resolve_symbol(aliases)
    if not name:
        return f"{sym}: XM дээр олдсонгүй. Жишээ: EURUSD, GBPUSD, US500, GOLD"
    bars = {}
    for tf, n in (("H1", 700), ("H4", 400), ("D1", 400)):
        df = broker.rates(name, tf, n).iloc[:-1]
        bars[tf] = prepare(fill_zero_spread(df))
    tick = broker.tick(name)
    spec = broker.symbol_spec(name)
    acc = broker.account()
    flags = {"paused": st.get("paused"), "killed": st.get("killed"), "day_blocked": st.get("day_blocked"),
             "open_positions": len(st.open_positions(virtual=False)),
             "max_positions": cfg.get("live", {}).get("max_open_positions", 4)}
    now = datetime.now(_tz.utc)
    if news is None and cfg.get("news", {}).get("enabled", True):
        from bot.news import NewsCalendar
        news = NewsCalendar(root / "data" / "news_calendar.json", cfg.get("news", {}))
    if news is not None:
        news.refresh()
    res = evaluate(sym, side, bars["H1"], bars["H4"], bars["D1"], tick.bid, tick.ask, spec, broker.point(name),
                   acc.balance, now, risk_pct=cfg.get("live", {}).get("risk_pct", 1.0), flags=flags,
                   news=news)
    path = root / "data" / "trade_checks.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_utc", "symbol", "side", "decision", "score", "price", "entry", "sl", "tp", "lot",
                        "vetoes"])
        w.writerow([now.strftime("%Y-%m-%d %H:%M"), sym, "BUY" if side == 1 else "SELL", res.decision, res.score,
                    tick.ask if side == 1 else tick.bid, res.entry, res.sl, res.tp, res.lot, " | ".join(res.vetoes)])
    st.log("CHECK", sym, f"{'BUY' if side == 1 else 'SELL'} → {res.decision} ({res.score})")
    local = now.astimezone(_tz(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")
    return res.text(local + " (UTC+7)")
