"""Telegram listener-ийн командуудын тест (хуурамч брокер)."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

from bot.live.state import State

spec = importlib.util.spec_from_file_location("tl", Path(__file__).parent.parent / "scripts" / "telegram_listener.py")
tl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tl)


class B:
    def __init__(self):
        self.closed = []
        self.pos = [NS(symbol="US500Cash", ticket=1)]

    def ensure_connected(self):
        pass

    def account(self):
        return NS(balance=9712.48, equity=9700.0, currency="USD")

    def positions(self, magic):
        return list(self.pos)

    def close_position(self, p, c):
        self.closed.append(p.ticket)
        self.pos = []


CFG = {"live": {"dry_run": True}, "execution": {"magic_number": 240101}}


def test_help_and_bad_check(tmp_path):
    st = State(tmp_path / "s.sqlite")
    assert "/check" in tl.handle("/help", B(), CFG, st)
    assert "Жишээ" in tl.handle("/check EURUSD", B(), CFG, st)
    assert "Тодорхойгүй" in tl.handle("/foo", B(), CFG, st)


def test_pause_resume_stop(tmp_path):
    st = State(tmp_path / "s.sqlite")
    b = B()
    tl.handle("/pause", b, CFG, st)
    assert st.get("paused") is True
    tl.handle("/resume", b, CFG, st)
    assert st.get("paused") is False and st.get("peak_equity") == 9700.0
    r = tl.handle("/stop", b, CFG, st)
    assert st.get("killed") is True and b.closed == [1] and "1 позиц" in r


def test_status(tmp_path):
    st = State(tmp_path / "s.sqlite")
    r = tl.handle("/status", B(), CFG, st)
    assert "9,712.48" in r and "DRY-RUN" in r
