"""MT5Broker: XM MT5 терминалтай холбогдох adapter.

P0 хувилбар: ЗӨВХӨН УНШИНА. Захиалга илгээх функц байхгүй.
MetaTrader5 сан зөвхөн Windows дээр, MT5 терминал асаалттай үед ажиллана.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from bot.config import Secrets
from bot.risk.sizing import SymbolSpec

try:
    import MetaTrader5 as mt5
except ImportError:  # Windows биш орчинд (тест) импорт хийгдэхгүй
    mt5 = None

TIMEFRAMES = {"M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
              "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1"}
TRADE_MODES = {0: "DEMO", 1: "CONTEST", 2: "REAL"}


class BrokerError(RuntimeError):
    pass


@dataclass
class AccountSnapshot:
    login: int
    server: str
    company: str
    currency: str
    leverage: int
    balance: float
    equity: float
    margin_free: float
    margin_level: float
    trade_mode: str
    margin_call_level: float
    stop_out_level: float


class MT5Broker:
    def __init__(self, secrets: Secrets, allow_live: bool = False):
        if mt5 is None:
            raise BrokerError("MetaTrader5 сан суугаагүй байна (pip install MetaTrader5). "
                              "Зөвхөн Windows дээр ажиллана.")
        self.secrets = secrets
        self.allow_live = allow_live
        self.connected = False

    # ---------- холболт ----------
    def connect(self) -> None:
        kwargs = dict(login=self.secrets.mt5_login, password=self.secrets.mt5_password,
                      server=self.secrets.mt5_server)
        if self.secrets.mt5_path:
            kwargs["path"] = self.secrets.mt5_path
        if not mt5.initialize(**kwargs):
            raise BrokerError(f"MT5-тай холбогдож чадсангүй: {mt5.last_error()}. "
                              "MT5 терминал асаалттай, нэвтрэх мэдээлэл зөв эсэхийг шалгана уу.")
        acc = mt5.account_info()
        if acc is None:
            raise BrokerError(f"Дансны мэдээлэл уншиж чадсангүй: {mt5.last_error()}")
        if acc.trade_mode == 2 and not self.allow_live:
            mt5.shutdown()
            raise BrokerError("Энэ бол БОДИТ данс. config.yaml-д allow_live: false тул бот зогслоо.")
        self.connected = True

    def disconnect(self) -> None:
        if mt5 and self.connected:
            mt5.shutdown()
            self.connected = False

    def ensure_connected(self, retries: int = 3) -> None:
        """Холболт тасарсан бол 5, 10, 30 секундийн зайтай дахин оролдоно."""
        info = mt5.terminal_info()
        if info is not None and info.connected:
            return
        for wait in (5, 10, 30)[:retries]:
            time.sleep(wait)
            try:
                self.connect()
                return
            except BrokerError:
                continue
        raise BrokerError("MT5 холболтыг сэргээж чадсангүй")

    # ---------- данс ----------
    def account(self) -> AccountSnapshot:
        a = mt5.account_info()
        return AccountSnapshot(
            login=a.login, server=a.server, company=a.company, currency=a.currency,
            leverage=a.leverage, balance=a.balance, equity=a.equity,
            margin_free=a.margin_free, margin_level=a.margin_level or 0.0,
            trade_mode=TRADE_MODES.get(a.trade_mode, str(a.trade_mode)),
            margin_call_level=a.margin_so_call, stop_out_level=a.margin_so_so,
        )

    def terminal_trade_allowed(self) -> bool:
        info = mt5.terminal_info()
        return bool(info and info.trade_allowed)

    # ---------- symbol ----------
    def find_symbol(self, base: str) -> str | None:
        """XM дагавартай нэрийг олно (EURUSD -> EURUSD эсвэл EURUSD# гэх мэт)."""
        if mt5.symbol_info(base) is not None:
            return base
        candidates = mt5.symbols_get(group=f"*{base}*") or []
        names = sorted((s.name for s in candidates if s.name.startswith(base)), key=len)
        return names[0] if names else None

    def symbol_spec(self, name: str) -> SymbolSpec:
        if not mt5.symbol_select(name, True):
            raise BrokerError(f"{name} symbol-ыг идэвхжүүлж чадсангүй")
        s = mt5.symbol_info(name)
        return SymbolSpec(name=s.name, tick_size=s.trade_tick_size, tick_value=s.trade_tick_value,
                          volume_min=s.volume_min, volume_step=s.volume_step,
                          volume_max=s.volume_max, digits=s.digits)

    def symbol_details(self, name: str) -> dict:
        s = mt5.symbol_info(name)
        return {
            "spread_points": s.spread,
            "stops_level_points": s.trade_stops_level,
            "swap_long": s.swap_long,
            "swap_short": s.swap_short,
            "triple_swap_day": s.swap_rollover3days,   # 3 = Лхагва
            "filling": self.filling_mode_name(s.filling_mode),
        }

    def resolve_symbol(self, aliases: list[str]) -> str | None:
        """Хэд хэдэн боломжит нэрээс (GOLD, XAUUSD гэх мэт) брокерт байгааг нь олно."""
        for a in aliases:
            if mt5.symbol_info(a) is not None:
                return a
        for a in aliases:
            found = self.find_symbol(a)
            if found:
                return found
        return None

    def all_symbols(self) -> list[dict]:
        return [{"name": s.name, "path": s.path, "description": s.description}
                for s in (mt5.symbols_get() or [])]

    def spec_dict(self, name: str) -> dict:
        """Backtest-д хэрэгтэй symbol-ын бүх нөхцөл (data/<symbol>_spec.json-д хадгална)."""
        s = mt5.symbol_info(name)
        acc = mt5.account_info()
        return {
            "name": s.name, "digits": s.digits, "point": s.point,
            "tick_size": s.trade_tick_size, "tick_value": s.trade_tick_value,
            "contract_size": s.trade_contract_size,
            "volume_min": s.volume_min, "volume_step": s.volume_step, "volume_max": s.volume_max,
            "currency_base": s.currency_base, "currency_profit": s.currency_profit,
            "account_currency": acc.currency,
            "swap_mode": s.swap_mode, "swap_long": s.swap_long, "swap_short": s.swap_short,
            "triple_swap_day": s.swap_rollover3days,
            "stops_level": s.trade_stops_level, "filling": self.filling_mode_name(s.filling_mode),
            "spread_now_points": s.spread,
        }

    def rates_max(self, name: str, timeframe: str, max_bars: int = 200_000):
        """Терминалд байгаа бүх түүхийг татна (MT5-ийн 'Max bars in chart' тохиргоогоор хязгаарлагдана)."""
        import pandas as pd
        tf = getattr(mt5, TIMEFRAMES[timeframe])
        for count in (max_bars, 100_000, 50_000, 20_000, 10_000):
            data = mt5.copy_rates_from_pos(name, tf, 0, count)
            if data is not None and len(data):
                df = pd.DataFrame(data)
                df["time"] = pd.to_datetime(df["time"], unit="s")
                return df[["time", "open", "high", "low", "close", "tick_volume", "spread"]]
        raise BrokerError(f"{name} {timeframe} түүх татаж чадсангүй: {mt5.last_error()}")

    @staticmethod
    def filling_mode_name(flags: int) -> str:
        """symbol_info().filling_mode bitmask: 1 = FOK, 2 = IOC. Аль нь ч биш бол RETURN."""
        if flags & 1:
            return "FOK"
        if flags & 2:
            return "IOC"
        return "RETURN"

    # ---------- үнэ ----------
    def tick(self, name: str):
        t = mt5.symbol_info_tick(name)
        if t is None:
            raise BrokerError(f"{name}-ийн үнэ авч чадсангүй: {mt5.last_error()}")
        return t

    def rates(self, name: str, timeframe: str, count: int = 300):
        """Сүүлийн `count` лааг pandas DataFrame-ээр буцаана (time нь серверийн цаг)."""
        import pandas as pd
        mt5.symbol_select(name, True)
        tf = getattr(mt5, TIMEFRAMES[timeframe])
        data = mt5.copy_rates_from_pos(name, tf, 0, count)
        if data is None or len(data) == 0:
            raise BrokerError(f"{name} {timeframe} лаа авч чадсангүй: {mt5.last_error()}")
        df = pd.DataFrame(data)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    def server_utc_offset_hours(self, name: str) -> int:
        """Серверийн цаг UTC-ээс хэдэн цагаар зөрөхийг tick-ийн цагаас тооцно.
        Зах зээл хаалттай (амралтын өдөр) үед найдваргүй."""
        return round((self.tick(name).time - time.time()) / 3600)

    # ================= P2: захиалга (зөвхөн DEMO, allow_live=false үед) =================
    def _filling_const(self, name: str):
        mode = self.filling_mode_name(mt5.symbol_info(name).filling_mode)
        return {"FOK": mt5.ORDER_FILLING_FOK, "IOC": mt5.ORDER_FILLING_IOC,
                "RETURN": mt5.ORDER_FILLING_RETURN}[mode]

    def positions(self, magic: int) -> list:
        """Зөвхөн энэ ботын (magic number) нээлттэй позицууд."""
        return [p for p in (mt5.positions_get() or []) if p.magic == magic]

    def _guard_demo(self) -> None:
        acc = mt5.account_info()
        if acc is None or (acc.trade_mode == 2 and not self.allow_live):
            raise BrokerError("Бодит дансанд захиалга илгээхийг хориглосон (allow_live: false)")

    def _send(self, request: dict, retries: int = 3) -> object:
        self._guard_demo()
        chk = mt5.order_check(request)
        if chk is None or chk.retcode not in (0, mt5.TRADE_RETCODE_DONE):
            raise BrokerError(f"order_check амжилтгүй: {getattr(chk, 'retcode', None)} "
                              f"{getattr(chk, 'comment', mt5.last_error())}")
        last = None
        for _ in range(retries):
            res = mt5.order_send(request)
            last = res
            if res is not None and res.retcode == mt5.TRADE_RETCODE_DONE:
                return res
            if res is not None and res.retcode in (mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_PRICE_CHANGED,
                                                    mt5.TRADE_RETCODE_PRICE_OFF):
                tick = mt5.symbol_info_tick(request["symbol"])
                request["price"] = tick.ask if request["type"] == mt5.ORDER_TYPE_BUY else tick.bid
                time.sleep(1)
                continue
            break
        raise BrokerError(f"order_send амжилтгүй: {getattr(last, 'retcode', None)} "
                          f"{getattr(last, 'comment', mt5.last_error())}")

    def open_market(self, name: str, side: int, lot: float, sl: float, magic: int,
                    comment: str, deviation: int = 20):
        """Market захиалга, SL-ийг серверт хамт илгээнэ."""
        s = mt5.symbol_info(name)
        tick = mt5.symbol_info_tick(name)
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": name, "volume": float(lot),
               "type": mt5.ORDER_TYPE_BUY if side == 1 else mt5.ORDER_TYPE_SELL,
               "price": tick.ask if side == 1 else tick.bid, "sl": round(sl, s.digits), "tp": 0.0,
               "deviation": deviation, "magic": magic, "comment": comment[:31],
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling_const(name)}
        return self._send(req)

    def close_position(self, pos, comment: str = "close", deviation: int = 20):
        tick = mt5.symbol_info_tick(pos.symbol)
        buy = pos.type == mt5.POSITION_TYPE_BUY
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": pos.volume,
               "type": mt5.ORDER_TYPE_SELL if buy else mt5.ORDER_TYPE_BUY, "position": pos.ticket,
               "price": tick.bid if buy else tick.ask, "deviation": deviation, "magic": pos.magic,
               "comment": comment[:31], "type_time": mt5.ORDER_TIME_GTC,
               "type_filling": self._filling_const(pos.symbol)}
        return self._send(req)

    def set_sl(self, pos, sl: float):
        s = mt5.symbol_info(pos.symbol)
        req = {"action": mt5.TRADE_ACTION_SLTP, "symbol": pos.symbol, "position": pos.ticket,
               "sl": round(sl, s.digits), "tp": pos.tp, "magic": pos.magic}
        return self._send(req)

    def point(self, name: str) -> float:
        return mt5.symbol_info(name).point
