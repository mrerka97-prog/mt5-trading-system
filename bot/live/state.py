"""Ботын төлөв (SQLite): бот дахин асахад юу ч мартахгүй.

Хүснэгтүүд:
  kv        — paused, killed, peak_equity, day_start_equity, last_bar:<symbol>, tg_offset ...
  pending   — дараагийн өдрийн нээлтэд гүйцэтгэх үйлдэл (enter / exit)
  positions — ботын позицын нэмэлт мэдээлэл (бодит эсвэл virtual)
  journal   — бүх шийдвэр, захиалга, алдааны бүртгэл
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS pending (symbol TEXT PRIMARY KEY, action TEXT, created TEXT,
            sl_dist REAL, bar_time TEXT);
        CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket INTEGER,
            symbol TEXT, virtual INTEGER, side INTEGER, lot REAL, entry REAL, sl REAL, sl_dist REAL,
            entry_time TEXT, entry_bar_time TEXT, open INTEGER DEFAULT 1, exit REAL, exit_time TEXT,
            r REAL, reason TEXT);
        CREATE TABLE IF NOT EXISTS journal (id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, level TEXT,
            symbol TEXT, event TEXT, details TEXT);
        """)
        self.db.commit()

    # ---- kv ----
    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value)))
        self.db.commit()

    # ---- journal ----
    def log(self, event: str, symbol: str = "", details: str = "", level: str = "INFO") -> None:
        self.db.execute("INSERT INTO journal (time, level, symbol, event, details) VALUES (?,?,?,?,?)",
                        (utcnow(), level, symbol, event, details))
        self.db.commit()

    # ---- pending ----
    def set_pending(self, symbol: str, action: str, sl_dist: float, bar_time: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO pending VALUES (?,?,?,?,?)",
                        (symbol, action, utcnow(), sl_dist, bar_time))
        self.db.commit()

    def get_pending(self, symbol: str):
        return self.db.execute("SELECT * FROM pending WHERE symbol=?", (symbol,)).fetchone()

    def clear_pending(self, symbol: str) -> None:
        self.db.execute("DELETE FROM pending WHERE symbol=?", (symbol,))
        self.db.commit()

    # ---- positions ----
    def open_positions(self, symbol: str | None = None, virtual: bool | None = None) -> list:
        q, a = "SELECT * FROM positions WHERE open=1", []
        if symbol:
            q += " AND symbol=?"
            a.append(symbol)
        if virtual is not None:
            q += " AND virtual=?"
            a.append(int(virtual))
        return self.db.execute(q, a).fetchall()

    def add_position(self, **kw) -> int:
        cols = ",".join(kw)
        cur = self.db.execute(f"INSERT INTO positions ({cols}) VALUES ({','.join('?' * len(kw))})",
                              tuple(kw.values()))
        self.db.commit()
        return cur.lastrowid

    def close_position(self, pid: int, exit_price: float, r: float, reason: str) -> None:
        self.db.execute("UPDATE positions SET open=0, exit=?, exit_time=?, r=?, reason=? WHERE id=?",
                        (exit_price, utcnow(), r, reason, pid))
        self.db.commit()

    def closed_positions(self) -> list:
        return self.db.execute("SELECT * FROM positions WHERE open=0 ORDER BY exit_time").fetchall()
