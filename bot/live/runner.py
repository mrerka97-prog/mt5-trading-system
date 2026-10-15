"""P2: Бодит цагийн runner — E1b индексийн RSI(2) mean reversion (D1, long only).

Ажиллах зарчим (минут тутам step()):
  1. Холболт, данс, kill-switch, өдрийн лимит, Telegram команд шалгана.
  2. Symbol бүрт шинэ D1 лаа ХААГДСАН бол дохиог тооцоод "pending" үйлдэл (enter/exit) үүсгэнэ.
     (Backtest-тэй ижил: дохио хаагдсан лаанаас, гүйцэтгэл дараагийн өдрийн эхэнд.)
  3. Pending-ийг зах зээл нээлттэй, spread хэвийн үед гүйцэтгэнэ. 6 цагт гүйцэтгэгдээгүй бол цуцална.

Мэдээний шүүлтүүр (bot/news.py): өндөр нөлөөтэй мэдээний ±30 минутад шинэ арилжааг
хойшлуулна (цуцлахгүй). Гарах үйлдлийг хэзээ ч хориглохгүй.

Горимууд:
  trade_symbols       — бодит захиалга (dry_run: true үед virtual)
  signal_only_symbols — үргэлж virtual (дохио ба үр дүнг бүртгэнэ, захиалга илгээхгүй)
"""
from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timedelta, timezone

import pandas as pd

from bot.broker.mt5_broker import BrokerError
from bot.data.store import fill_zero_spread, server_to_utc, utc_to_server_epoch
from bot.live.notifier import Notifier
from bot.live.state import State
from bot.risk.sizing import calculate_lot
from bot.strategy.experiments import e1_index_rsi2

log = logging.getLogger("bot")


class Runner:
    def __init__(self, cfg: dict, broker, state: State, notifier: Notifier, clock=None, news=None):
        self.cfg, self.b, self.st, self.tg = cfg, broker, state, notifier
        self.news = news                                   # NewsCalendar эсвэл None (шүүлтүүргүй)
        lc = cfg["live"]
        self.trade = list(lc["trade_symbols"])
        self.signal_only = list(lc.get("signal_only_symbols", []))
        self.dry = bool(lc.get("dry_run", True))
        self.magic = int(cfg["execution"]["magic_number"])
        self.risk_pct = float(lc["risk_pct"])
        self.max_pos = int(lc.get("max_open_positions", 4))
        self.max_hold = int(lc.get("max_hold_days", 10))
        self.rsi_thr = float(lc.get("rsi_threshold", 5))
        self.pending_hours = float(lc.get("pending_timeout_hours", 20))
        self.spread_mult = float(lc.get("max_spread_multiple", 2.0))
        self.daily_limit = float(cfg["risk"]["daily_loss_limit_pct"])
        self.max_dd = float(cfg["risk"]["max_drawdown_pct"])
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.names: dict[str, str] = {}
        self.stale: dict[str, str] = {}                    # symbol → сүүлийн лааны огноо (өгөгдөл хоцорсон)

    # ------------------------------------------------------------------ helpers
    def virtual(self, sym: str) -> bool:
        return sym in self.signal_only or self.dry

    def name(self, sym: str) -> str:
        if sym not in self.names:
            aliases = self.cfg.get("research_d1", {}).get("universe", {}).get(sym, [sym])
            n = self.b.resolve_symbol(aliases)
            if not n:
                raise BrokerError(f"{sym}: symbol олдсонгүй")
            self.names[sym] = n
        return self.names[sym]

    def server_today(self) -> pd.Timestamp:
        return pd.Timestamp(utc_to_server_epoch(self.clock()), unit="s").normalize()

    def closed_d1(self, sym: str) -> pd.DataFrame:
        df = self.b.rates(self.name(sym), "D1", 400)
        # Сүүлийн мөр нь ӨНӨӨДРИЙН (дуусаагүй) лаа бол хасна. Зах зээл өнөөдөр хараахан нээгдээгүй
        # бол сүүлийн мөр нь өчигдрийн БҮТЭН лаа тул үлдээнэ (өмнө нь энд нэг өдөр алдагдаж байсан).
        if len(df) and pd.Timestamp(df["time"].iloc[-1]).normalize() >= self.server_today():
            df = df.iloc[:-1]
        df = df.reset_index(drop=True)
        df = fill_zero_spread(df)
        df["time_utc"] = server_to_utc(df["time"])
        return df

    # ------------------------------------------------------------------ main step
    def startup(self) -> None:
        self.b.ensure_connected()
        for sym in self.trade + self.signal_only:
            self.name(sym)
        self.reconcile()
        news_txt = ""
        if self.news:
            self.news.refresh()
            news_txt = "\n" + self.news.status_line(self.clock())
        mode = "DRY-RUN (захиалга илгээхгүй)" if self.dry else "ЗАХИАЛГА ИДЭВХТЭЙ (демо)"
        self.tg.send(f"Бот асав: E1b, {mode}\nАрилжаа: {', '.join(self.trade)}\n"
                     f"Зөвхөн сигнал: {', '.join(self.signal_only) or '—'}\nЭрсдэл {self.risk_pct}%/арилжаа"
                     + news_txt)
        self.st.log("START", details=mode)

    def step(self) -> None:
        self.b.ensure_connected()
        acc = self.b.account()
        self.check_limits(acc)
        if self.news:
            self.news.refresh()                            # кэш 6 цаг хүчинтэй, алдаа ботыг зогсоохгүй
        if self.cfg["live"].get("runner_handles_commands", True):
            self.handle_commands(acc)
        for sym in self.trade + self.signal_only:
            try:
                self.process_new_bar(sym)
                self.execute_pending(sym, acc)
            except BrokerError as e:
                self.st.log("ERROR", sym, str(e), "ERROR")
                log.error("%s: %s", sym, e)
        self.st.set("heartbeat", self.clock().strftime("%Y-%m-%d %H:%M:%S"))

    # ------------------------------------------------------------------ risk limits
    def check_limits(self, acc) -> None:
        eq = acc.equity
        peak = max(self.st.get("peak_equity", eq), eq)
        self.st.set("peak_equity", peak)
        today = self.clock().strftime("%Y-%m-%d")
        if self.st.get("day") != today:
            self.st.set("day", today)
            self.st.set("day_start_equity", eq)
            self.st.set("day_blocked", False)
        start = self.st.get("day_start_equity", eq)
        if not self.st.get("day_blocked") and eq <= start * (1 - self.daily_limit / 100):
            self.st.set("day_blocked", True)
            self.tg.send(f"⚠️ Өдрийн алдагдлын лимит ({self.daily_limit}%) хүрлээ. Өнөөдөр шинэ арилжаа нээхгүй.")
            self.st.log("DAILY_LIMIT", details=f"equity {eq:.2f} / start {start:.2f}", level="WARN")
        if not self.st.get("killed") and eq <= peak * (1 - self.max_dd / 100):
            self.kill(f"MAX DRAWDOWN {self.max_dd}% (equity {eq:.2f}, peak {peak:.2f})")

    def kill(self, why: str) -> None:
        self.st.set("killed", True)
        for p in self.b.positions(self.magic):
            try:
                self.b.close_position(p, "KILL")
            except BrokerError as e:
                self.st.log("ERROR", p.symbol, f"kill close: {e}", "ERROR")
        for r in self.st.open_positions():
            self.st.close_position(r["id"], r["entry"], 0.0, "KILL")
        self.tg.send(f"🛑 KILL-SWITCH: {why}\nБүх позиц хаагдлаа. Гараар шалгаж /resume хийх хүртэл бот зогсоно.")
        self.st.log("KILL", details=why, level="CRITICAL")

    # ------------------------------------------------------------------ telegram
    def handle_commands(self, acc) -> None:
        cmds, off = self.tg.poll_commands(self.st.get("tg_offset", 0))
        self.st.set("tg_offset", off)
        for c in cmds:
            if c == "/status":
                self.tg.send(self.status_text(acc))
            elif c == "/pause":
                self.st.set("paused", True)
                self.tg.send("⏸ Шинэ арилжаа түр зогслоо (нээлттэй позицыг удирдсаар байна).")
            elif c == "/resume":
                self.st.set("paused", False)
                self.st.set("killed", False)
                self.st.set("peak_equity", acc.equity)
                self.tg.send("▶️ Үргэлжилж байна.")
            elif c == "/stop":
                self.kill("Telegram /stop команд")

    def status_text(self, acc) -> str:
        lines = [f"Баланс {acc.balance:,.2f} / equity {acc.equity:,.2f} {acc.currency}",
                 f"Горим: {'DRY-RUN' if self.dry else 'захиалга'}"
                 + (" | ТҮР ЗОГССОН" if self.st.get("paused") else "")
                 + (" | KILLED" if self.st.get("killed") else "")]
        for r in self.st.open_positions():
            lines.append(f"{'V ' if r['virtual'] else ''}{r['symbol']} {'BUY' if r['side'] == 1 else 'SELL'} "
                         f"{r['lot']} @ {r['entry']} SL {r['sl']}")
        closed = self.st.closed_positions()
        if closed:
            rs = [c["r"] for c in closed if c["r"] is not None]
            lines.append(f"Хаагдсан {len(rs)} арилжаа, нийт {sum(rs):+.2f}R")
        lines += self.news_lines()
        return "\n".join(lines)

    def news_lines(self, hours: float = 24) -> list[str]:
        """Ботын хэрэгслүүдэд хамаарах өндөр нөлөөтэй мэдээ (дараагийн 24 цаг)."""
        if not self.news or not self.news.enabled:
            return []
        now = self.clock()
        if not self.news.known(now):
            return [self.news.status_line(now)]
        cur = sorted({c for s in self.trade + self.signal_only for c in self.news.currencies(s)})
        ev = self.news.upcoming(cur, hours, now)
        if not ev:
            return [f"Мэдээ ({', '.join(cur)}, 24 цаг): өндөр нөлөөтэй мэдээ алга"]
        return [f"Мэдээ ({', '.join(cur)}, 24 цаг):"] + [f"  • {e.short(now)}" for e in ev[:8]]

    # ------------------------------------------------------------------ signals
    def process_new_bar(self, sym: str) -> None:
        df = self.closed_d1(sym)
        if df.empty:
            return
        bar_time = str(df["time"].iloc[-1])
        # MT5 асаад удаагүй үед хуучин (кэшэлсэн) түүх өгдөг: өчигдрийн лаа ирээгүй бол хүлээнэ
        expected = self.server_today() - pd.offsets.BDay(1)
        if pd.Timestamp(df["time"].iloc[-1]).normalize() < expected:
            self.stale[sym] = bar_time[:10]
            if self.st.get(f"stale:{sym}") != bar_time:
                self.st.set(f"stale:{sym}", bar_time)
                self.st.log("DATA_STALE", sym, f"сүүлийн хаагдсан лаа {bar_time[:10]}, хүлээгдэж буй "
                            f"{expected:%Y-%m-%d}", "WARN")
            return
        self.stale.pop(sym, None)
        last = self.st.get(f"last_bar:{sym}")
        if last == bar_time:
            return
        allsig = e1_index_rsi2(df, self.rsi_thr)
        sig = allsig.iloc[-1]
        # Компьютер унтарсан үед алгассан өдрүүд (зөөврийн компьютер): гарах дохиог тэдгээрээс ч шалгана
        missed = allsig[allsig["time"] > pd.Timestamp(last)] if last else allsig.tail(1)
        if len(missed) > 1:
            self.st.log("CATCH_UP", sym, f"{len(missed)} өдөр алгассан, нөхөж шалгав")
        self.st.set(f"last_bar:{sym}", bar_time)
        opens = self.st.open_positions(sym)
        if opens:
            entry_bar = opens[0]["entry_bar_time"]
            held = int((df["time"] >= pd.Timestamp(entry_bar)).sum())
            after_entry = missed[missed["time"] >= pd.Timestamp(entry_bar)]
            exit_flag = bool(after_entry["exit_long"].any()) if len(after_entry) else bool(sig["exit_long"])
            if exit_flag or held >= self.max_hold:
                why = "close > SMA5" if exit_flag else f"{held} өдөр"
                self.st.set_pending(sym, "exit", 0.0, bar_time)
                self.st.log("SIGNAL_EXIT", sym, why)
        elif int(sig["signal"]) == 1:
            # Шинэ дохиог зөвхөн хамгийн сүүлд хаагдсан лаанаас авна (хуучин дохио хүчингүй)
            self.st.set_pending(sym, "enter", float(sig["sl_dist"]), bar_time)
            self.st.log("SIGNAL_ENTER", sym, sig["reason"])

    def run_once(self, max_minutes: int = 30, interval: int = 60) -> None:
        """Зөөврийн компьютерт: асаад шийдвэр гаргаж, pending-ийг гүйцэтгээд (≤ max_minutes) унтарна."""
        self.startup()
        deadline = _time.time() + max_minutes * 60
        while True:
            try:
                self.step()
            except BrokerError as e:
                log.error("step алдаа: %s", e)
            pend = [s for s in self.trade + self.signal_only if self.st.get_pending(s)]
            if not pend and not self.stale:
                self.tg.send("\n".join(["✅ Өдрийн шалгалт дууслаа. " + self.summary_line()] + self.news_lines()))
                return
            # Зөвхөн мэдээ дуусахыг хүлээж байгаа бол нэмж 75 минут хүлээнэ (±30 мин + нөөц)
            news_wait = bool(pend) and not self.stale and all(self.st.get(f"news_wait:{s}") for s in pend)
            if _time.time() > deadline and not (news_wait and _time.time() < deadline + 75 * 60):
                msg = []
                if pend:
                    msg.append(f"⌛ {max_minutes} минутад гүйцэтгэгдээгүй: {', '.join(pend)}. "
                               "Дараагийн удаа асахад дахин оролдоно.")
                if self.stale:
                    msg.append("⚠️ MT5-ийн өгөгдөл шинэчлэгдсэнгүй: "
                               + ", ".join(f"{k} (сүүлийн лаа {v})" for k, v in self.stale.items())
                               + ". Баярын өдөр эсвэл MT5 түүх татаагүй. Дараагийн удаа нөхөж шалгана.")
                self.tg.send("\n".join(msg + [self.summary_line()]))
                return
            _time.sleep(interval)

    def summary_line(self) -> str:
        opens = self.st.open_positions()
        closed = [c["r"] for c in self.st.closed_positions() if c["r"] is not None]
        return (f"Нээлттэй позиц {len(opens)}"
                + (f" ({', '.join(r['symbol'] for r in opens)})" if opens else "")
                + f", хаагдсан {len(closed)} арилжаа, нийт {sum(closed):+.2f}R")

    # ------------------------------------------------------------------ execution
    def market_ok(self, sym: str):
        n = self.name(sym)
        t = self.b.tick(n)
        now_server = utc_to_server_epoch(self.clock())
        if now_server - t.time > 300:                      # 5 минутаас хуучин үнэ = зах зээл хаалттай
            return None, "зах зээл хаалттай"
        spread_pts = (t.ask - t.bid) / self.b.point(n)
        typical = self.closed_d1(sym)["spread"].tail(20).median()
        if typical and spread_pts > self.spread_mult * typical:
            return None, f"spread {spread_pts:.0f} > {self.spread_mult}×{typical:.0f}"
        return t, ""

    def execute_pending(self, sym: str, acc) -> None:
        p = self.st.get_pending(sym)
        if not p:
            return
        created = datetime.strptime(p["created"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        if self.clock() - created > timedelta(hours=self.pending_hours):
            self.st.clear_pending(sym)
            self.st.set(f"news_wait:{sym}", None)
            self.st.log("PENDING_EXPIRED", sym, p["action"], "WARN")
            self.tg.send(f"⌛ {sym}: {p['action']} {self.pending_hours} цагт гүйцэтгэгдсэнгүй, цуцаллаа.")
            return
        if p["action"] == "enter" and self.news:
            key, reason = self.news.entry_block(sym, self.clock())
            if key:
                if self.st.get(f"news_wait:{sym}") != key:      # нэг мэдээнд нэг л удаа мэдэгдэнэ
                    self.st.set(f"news_wait:{sym}", key)
                    self.st.log("NEWS_WAIT", sym, reason, "WARN")
                    self.tg.send(f"📰 {sym}: дохио бий, гэхдээ {reason}. Мэдээ өнгөртөл хүлээнэ.")
                return                                     # цуцлахгүй, дараагийн минутад дахин шалгана
            self.st.set(f"news_wait:{sym}", None)
        tick, why = self.market_ok(sym)
        if tick is None:
            return                                         # дараагийн минутад дахин оролдоно
        if p["action"] == "exit":
            self.do_exit(sym, tick)
        else:
            self.do_enter(sym, tick, acc, p)
        self.st.clear_pending(sym)

    def do_enter(self, sym: str, tick, acc, p) -> None:
        blocked = ("түр зогссон" if self.st.get("paused") else "kill-switch" if self.st.get("killed")
                   else "өдрийн лимит" if self.st.get("day_blocked")
                   else "позицын хязгаар" if len(self.st.open_positions(virtual=False)) >= self.max_pos
                   else "")
        if blocked and not sym in self.signal_only:
            self.st.log("ENTER_BLOCKED", sym, blocked, "WARN")
            self.tg.send(f"🚫 {sym}: дохио байсан ч арилжаа нээгээгүй ({blocked}).")
            return
        n = self.name(sym)
        spec = self.b.symbol_spec(n)
        entry = tick.ask
        sl_dist = p["sl_dist"]
        sl = entry - sl_dist
        res = calculate_lot(acc.balance, self.risk_pct, sl_dist, spec)
        virtual = self.virtual(sym)
        lot = res.lot if res.lot else spec.volume_min
        if not res.lot and not sym in self.signal_only:
            self.st.log("ENTER_SKIPPED", sym, res.reason, "WARN")
            self.tg.send(f"⚠️ {sym}: {res.reason}")
            return
        ticket = None
        if not virtual:
            self.b.open_market(n, 1, lot, sl, self.magic, "E1b")
            new = [q for q in self.b.positions(self.magic) if q.symbol == n
                   and q.ticket not in {r["ticket"] for r in self.st.open_positions(sym)}]
            ticket = new[-1].ticket if new else None
            entry = new[-1].price_open if new else entry
        self.st.add_position(ticket=ticket, symbol=sym, virtual=int(virtual), side=1, lot=lot, entry=entry,
                             sl=round(sl, 5), sl_dist=sl_dist, entry_time=self.clock().strftime("%Y-%m-%d %H:%M:%S"),
                             entry_bar_time=str(pd.Timestamp(utc_to_server_epoch(self.clock()), unit="s").normalize()))
        tag = "СИГНАЛ" if sym in self.signal_only else ("DRY" if virtual else "ЗАХИАЛГА")
        risk_money = res.risk_money if res.lot else None
        self.st.log("ENTER", sym, f"{tag} BUY {lot} @ {entry} SL {sl:.2f} risk {risk_money}")
        self.tg.send(f"🟢 [{tag}] {sym} BUY {lot} lot @ {entry}\nSL {sl:.2f}"
                     + (f" (эрсдэл ≈ {risk_money} {acc.currency}, {res.risk_pct}%)" if risk_money else ""))

    def do_exit(self, sym: str, tick) -> None:
        n = self.name(sym)
        for r in self.st.open_positions(sym):
            price = tick.bid
            if not r["virtual"]:
                for q in self.b.positions(self.magic):
                    if q.ticket == r["ticket"]:
                        self.b.close_position(q, "E1b exit")
            rr = (price - r["entry"]) * r["side"] / r["sl_dist"] if r["sl_dist"] else 0.0
            self.st.close_position(r["id"], price, round(rr, 3), "EXIT")
            tag = "СИГНАЛ" if r["virtual"] and sym in self.signal_only else ("DRY" if r["virtual"] else "ЗАХИАЛГА")
            self.st.log("EXIT", sym, f"{tag} @ {price} R={rr:+.2f}")
            self.tg.send(f"🔵 [{tag}] {sym} хаалаа @ {price}  {rr:+.2f}R")

    # ------------------------------------------------------------------ reconcile
    def reconcile(self) -> None:
        """Асах бүрт: MT5 дээрх позицуудыг бүртгэлтэй тулгана, SL-гүй позицод SL тавина."""
        live = {q.ticket: q for q in self.b.positions(self.magic)}
        for r in self.st.open_positions(virtual=False):
            if r["ticket"] not in live:                    # SL-ээр эсвэл гараар хаагдсан
                self.st.close_position(r["id"], r["sl"], -1.0, "CLOSED_OUTSIDE")
                self.st.log("RECONCILE", r["symbol"], f"ticket {r['ticket']} MT5-д алга → хаагдсанд тооцов", "WARN")
        known = {r["ticket"] for r in self.st.open_positions(virtual=False)}
        for t, q in live.items():
            if q.sl == 0:
                df = self.closed_d1(self._sym_of(q.symbol))
                from bot import indicators as ind
                sl = q.price_open - 3 * float(ind.atr(df, 20).iloc[-1])
                self.b.set_sl(q, sl)
                self.tg.send(f"🛡 {q.symbol}: SL байхгүй позиц олдлоо, SL {sl:.2f} тавилаа.")
            if t not in known:
                self.st.add_position(ticket=t, symbol=self._sym_of(q.symbol), virtual=0, side=1, lot=q.volume,
                                     entry=q.price_open, sl=q.sl, sl_dist=abs(q.price_open - q.sl) or 1.0,
                                     entry_time=self.clock().strftime("%Y-%m-%d %H:%M:%S"),
                                     entry_bar_time=str(pd.Timestamp(q.time, unit="s").normalize()))
                self.st.log("RECONCILE", q.symbol, f"бүртгэлгүй позиц {t} нэмэв", "WARN")

    def _sym_of(self, broker_name: str) -> str:
        for k, v in self.names.items():
            if v == broker_name:
                return k
        return broker_name

    # ------------------------------------------------------------------ loop
    def run_forever(self, interval: int = 60) -> None:
        self.startup()
        fails = 0
        while True:
            try:
                self.step()
                fails = 0
            except BrokerError as e:
                fails += 1
                log.error("step алдаа: %s", e)
                if fails in (1, 5, 30):
                    self.tg.send(f"❗ MT5 алдаа ({fails} дахь удаа): {e}")
            except KeyboardInterrupt:
                self.tg.send("Бот гараар зогсоов (Ctrl+C).")
                raise
            except Exception as e:                       # гэнэтийн алдаа ботыг унагахгүй
                fails += 1
                log.exception("Гэнэтийн алдаа")
                if fails in (1, 5, 30):
                    self.tg.send(f"❗ Гэнэтийн алдаа: {e}")
            _time.sleep(interval)
