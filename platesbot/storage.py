"""SQLite-хранилище: пользователи, энергия, прокрутки, гараж, настройки."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from core.plates import Plate
from core.rarity import Evaluation

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT, first_name TEXT,
    energy INTEGER NOT NULL, energy_ts REAL NOT NULL,
    spins INTEGER NOT NULL DEFAULT 0,
    best_score INTEGER NOT NULL DEFAULT 0,
    extra_slots INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'ru', countries TEXT NOT NULL DEFAULT '[]',
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS rolls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    country TEXT NOT NULL, text TEXT NOT NULL,
    plate TEXT NOT NULL, eval TEXT NOT NULL,
    score INTEGER NOT NULL, price_rub INTEGER NOT NULL,
    source TEXT NOT NULL,
    created REAL NOT NULL, expires REAL NOT NULL,
    saved INTEGER NOT NULL DEFAULT 0, forever INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS rolls_user ON rolls(user_id, created);
CREATE TABLE IF NOT EXISTS ai_cache (text TEXT PRIMARY KEY, data TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY, title TEXT NOT NULL, active INTEGER NOT NULL, added REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sponsors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER, title TEXT NOT NULL, username TEXT, link TEXT NOT NULL DEFAULT '',
    goal INTEGER NOT NULL DEFAULT 0, joined INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sponsor_joins (
    sponsor_id INTEGER NOT NULL, user_id INTEGER NOT NULL, ts REAL NOT NULL,
    PRIMARY KEY (sponsor_id, user_id)
);
"""


class Storage:
    def __init__(self, path: Path, energy_max: int, regen_sec: int, free_slots: int, ttl_sec: int):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(users)")}
        if "blocked" not in cols:     # старые базы: отметка «заблокировал бота» для рассылки и статистики
            self.db.execute("ALTER TABLE users ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")
            self.db.commit()
        if "sold" not in {r["name"] for r in self.db.execute("PRAGMA table_info(rolls)")}:   # выкуп за прокруты
            self.db.execute("ALTER TABLE rolls ADD COLUMN sold INTEGER NOT NULL DEFAULT 0")
            self.db.execute("ALTER TABLE rolls ADD COLUMN sold_for INTEGER NOT NULL DEFAULT 0")
            self.db.commit()
        self.lock = threading.Lock()
        self.energy_max, self.regen_sec, self.free_slots, self.ttl = energy_max, regen_sec, free_slots, ttl_sec

    # ------------------------------------------------------------ users / energy

    def touch_user(self, tg_user: dict) -> sqlite3.Row:
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE id=?", (tg_user["id"],)).fetchone()
            now = time.time()
            if row is None:
                self.db.execute(
                    "INSERT INTO users(id, username, first_name, energy, energy_ts, created) VALUES (?,?,?,?,?,?)",
                    (tg_user["id"], tg_user.get("username"), tg_user.get("first_name", ""), self.energy_max, now, now))
            else:
                self.db.execute("UPDATE users SET username=?, first_name=?, blocked=0 WHERE id=?",
                                (tg_user.get("username"), tg_user.get("first_name", ""), tg_user["id"]))
            self.db.commit()
            return self.db.execute("SELECT * FROM users WHERE id=?", (tg_user["id"],)).fetchone()

    def _energy_now(self, row: sqlite3.Row) -> tuple[int, float]:
        """Текущая энергия с учётом регенерации и отметка времени последнего начисления.

        Купленная энергия может быть выше максимума: она не срезается, а регенерация
        идёт только пока энергии меньше максимума.
        """
        energy, ts = row["energy"], row["energy_ts"]
        now = time.time()
        if energy >= self.energy_max:
            return energy, now
        gained = int((now - ts) // self.regen_sec)
        if gained > 0:
            energy = min(self.energy_max, energy + gained)
            ts = now if energy >= self.energy_max else ts + gained * self.regen_sec
        return energy, ts

    def _energy_dict(self, energy: int, ts: float) -> dict:
        next_in = 0 if energy >= self.energy_max else max(0, int(ts + self.regen_sec - time.time()))
        return {"current": energy, "max": self.energy_max, "next_in": next_in}

    def energy(self, user_id: int) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            energy, ts = self._energy_now(row)
            self.db.execute("UPDATE users SET energy=?, energy_ts=? WHERE id=?", (energy, ts, user_id))
            self.db.commit()
        return self._energy_dict(energy, ts)

    def add_energy(self, user_id: int, amount: int) -> dict:
        """Начисляет купленную энергию (может превысить максимум). Возвращает то же, что energy()."""
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            energy, ts = self._energy_now(row)
            energy += max(0, int(amount))
            if energy >= self.energy_max:
                ts = time.time()
            self.db.execute("UPDATE users SET energy=?, energy_ts=? WHERE id=?", (energy, ts, user_id))
            self.db.commit()
        return self._energy_dict(energy, ts)

    def consume_energy(self, user_id: int) -> bool:
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            energy, ts = self._energy_now(row)
            if energy <= 0:
                self.db.execute("UPDATE users SET energy=?, energy_ts=? WHERE id=?", (energy, ts, user_id))
                self.db.commit()
                return False
            if energy >= self.energy_max:   # таймер регенерации стартует, когда энергия опускается ниже максимума
                ts = time.time()
            self.db.execute("UPDATE users SET energy=?, energy_ts=?, spins=spins+1 WHERE id=?", (energy - 1, ts, user_id))
            self.db.commit()
            return True

    def settings(self, user_id: int) -> dict:
        row = self.db.execute("SELECT mode, countries FROM users WHERE id=?", (user_id,)).fetchone()
        return {"mode": row["mode"], "countries": json.loads(row["countries"])}

    def set_settings(self, user_id: int, mode: str, countries: list[str]) -> dict:
        with self.lock:
            self.db.execute("UPDATE users SET mode=?, countries=? WHERE id=?", (mode, json.dumps(countries), user_id))
            self.db.commit()
        return self.settings(user_id)

    def stats(self, user_id: int) -> dict:
        row = self.db.execute("SELECT spins, best_score, extra_slots FROM users WHERE id=?", (user_id,)).fetchone()
        return {"spins": row["spins"], "best_score": row["best_score"], "slots": self.free_slots + row["extra_slots"]}

    # ------------------------------------------------------------ rolls

    def add_roll(self, user_id: int, plate: Plate, ev: Evaluation, source: str) -> dict:
        now = time.time()
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO rolls(user_id, country, text, plate, eval, score, price_rub, source, created, expires) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (user_id, plate.country, plate.text, json.dumps(plate.to_dict(), ensure_ascii=False),
                 json.dumps(ev.to_dict(), ensure_ascii=False), ev.score, ev.price_rub, source, now, now + self.ttl))
            self.db.execute("UPDATE users SET best_score=MAX(best_score, ?) WHERE id=?", (ev.score, user_id))
            self.db.commit()
            return self.get_roll(cur.lastrowid)

    def get_roll(self, roll_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM rolls WHERE id=?", (roll_id,)).fetchone()
        return self._roll(row) if row else None

    def last_roll(self, user_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM rolls WHERE user_id=? AND expires>? ORDER BY id DESC LIMIT 1",
                              (user_id, time.time())).fetchone()
        return self._roll(row) if row else None

    def garage(self, user_id: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM rolls WHERE user_id=? AND saved=1 AND sold=0 AND (forever=1 OR expires>?) ORDER BY score DESC, id DESC",
            (user_id, time.time())).fetchall()
        return [self._roll(r) for r in rows]

    def save_roll(self, roll_id: int, user_id: int, forever: bool = False) -> tuple[str, dict | None]:
        """Возвращает ('ok'|'full'|'missing', roll)."""
        with self.lock:
            row = self.db.execute("SELECT * FROM rolls WHERE id=? AND user_id=?", (roll_id, user_id)).fetchone()
            if not row:
                return "missing", None
            if row["sold"]:
                return "sold", self._roll(row)
            if row["saved"] and (row["forever"] or not forever):
                return "ok", self._roll(row)
            slots = self.stats(user_id)["slots"]
            used = self.db.execute("SELECT COUNT(*) FROM rolls WHERE user_id=? AND saved=1 AND sold=0 AND (forever=1 OR expires>?)",
                                   (user_id, time.time())).fetchone()[0]
            if not row["saved"] and used >= slots and not forever:
                return "full", self._roll(row)
            self.db.execute("UPDATE rolls SET saved=1, forever=? WHERE id=?", (1 if forever else row["forever"], roll_id))
            self.db.commit()
            return "ok", self.get_roll(roll_id)

    def sell_roll(self, roll_id: int, user_id: int, price_of) -> tuple[str, dict | None, int]:
        """Продать номер боту. Возвращает ('ok'|'missing'|'sold'|'expired'|'cheap', roll, сколько прокрутов дали).

        Одна транзакция: «sold=0» в условии UPDATE не даёт продать номер дважды при двойном нажатии.
        """
        with self.lock:
            row = self.db.execute("SELECT * FROM rolls WHERE id=? AND user_id=?", (roll_id, user_id)).fetchone()
            if not row:
                return "missing", None, 0
            roll = self._roll(row)
            if roll["sold"]:
                return "sold", roll, 0
            if not roll["saved"] and roll["expires"] < time.time():
                return "expired", roll, 0
            gain = price_of(roll)
            if gain <= 0:
                return "cheap", roll, 0
            cur = self.db.execute("UPDATE rolls SET sold=1, sold_for=?, saved=0 WHERE id=? AND sold=0", (gain, roll_id))
            if not cur.rowcount:
                return "sold", roll, 0
            self.db.commit()
        self.add_energy(user_id, gain)
        return "ok", self.get_roll(roll_id), gain

    def drop_from_garage(self, roll_id: int, user_id: int) -> dict | None:
        """Убрать номер из гаража насовсем: место освобождается, вернуть нельзя."""
        with self.lock:
            cur = self.db.execute("UPDATE rolls SET saved=0, forever=0, expires=0 WHERE id=? AND user_id=? AND saved=1",
                                  (roll_id, user_id))
            self.db.commit()
        return self.get_roll(roll_id) if cur.rowcount else None

    def top(self, limit: int = 10) -> list[dict]:
        rows = self.db.execute(
            "SELECT r.text, r.score, r.price_rub, r.country, u.first_name, u.username "
            "FROM rolls r JOIN users u ON u.id=r.user_id "
            "WHERE r.id IN (SELECT id FROM rolls r2 WHERE r2.user_id=r.user_id ORDER BY score DESC, id DESC LIMIT 1) "
            "ORDER BY r.score DESC, r.id ASC LIMIT ?", (limit,)).fetchall()
        return [{"name": r["first_name"] or ("@" + r["username"] if r["username"] else "Игрок"),
                 "plate_text": r["text"], "score": r["score"], "price_rub": r["price_rub"], "country": r["country"]}
                for r in rows]

    def purge(self) -> None:
        with self.lock:
            self.db.execute("DELETE FROM rolls WHERE saved=0 AND expires<?", (time.time() - 7 * 86400,))
            self.db.commit()

    @staticmethod
    def _roll(row: sqlite3.Row) -> dict:
        return {"id": row["id"], "user_id": row["user_id"], "plate": json.loads(row["plate"]), "eval": json.loads(row["eval"]),
                "created": row["created"], "expires": row["expires"], "saved": bool(row["saved"]),
                "forever": bool(row["forever"]), "source": row["source"],
                "sold": bool(row["sold"]) if "sold" in row.keys() else False}

    # ------------------------------------------------------------ ai cache

    def ai_get(self, text: str) -> dict | None:
        row = self.db.execute("SELECT data FROM ai_cache WHERE text=?", (text,)).fetchone()
        return json.loads(row["data"]) if row else None

    def ai_put(self, text: str, data: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO ai_cache(text, data, created) VALUES (?,?,?)",
                            (text, json.dumps(data, ensure_ascii=False), time.time()))
            self.db.commit()

    # ------------------------------------------------------------ settings

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?,?)", (key, value))
            self.db.commit()

    # ------------------------------------------------------------ sponsors

    def sponsors(self, active_only: bool = True) -> list[dict]:
        sql = "SELECT * FROM sponsors" + (" WHERE active=1" if active_only else "") + " ORDER BY id"
        return [dict(r) for r in self.db.execute(sql)]

    def sponsor(self, sponsor_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM sponsors WHERE id=?", (sponsor_id,)).fetchone()
        return dict(row) if row else None

    def add_sponsor(self, chat_id: int | None, title: str, username: str | None, link: str, goal: int = 0) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO sponsors(chat_id, title, username, link, goal, created) VALUES (?,?,?,?,?,?)",
                                  (chat_id, title, username, link, goal, time.time()))
            self.db.commit()
            return cur.lastrowid

    def set_sponsor(self, sponsor_id: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("title", "link", "goal", "active")}
        if not allowed:
            return
        with self.lock:
            self.db.execute("UPDATE sponsors SET " + ", ".join(f"{k}=?" for k in allowed) + " WHERE id=?",
                            (*allowed.values(), sponsor_id))
            self.db.commit()

    def drop_sponsor(self, sponsor_id: int) -> None:
        with self.lock:
            self.db.execute("DELETE FROM sponsors WHERE id=?", (sponsor_id,))
            self.db.execute("DELETE FROM sponsor_joins WHERE sponsor_id=?", (sponsor_id,))
            self.db.commit()

    def sponsor_joined(self, sponsor_id: int, user_id: int) -> bool:
        """Засчитать вступление через бота. True — новое."""
        with self.lock:
            cur = self.db.execute("INSERT OR IGNORE INTO sponsor_joins(sponsor_id, user_id, ts) VALUES (?,?,?)",
                                  (sponsor_id, user_id, time.time()))
            if cur.rowcount:
                self.db.execute("UPDATE sponsors SET joined=joined+1 WHERE id=?", (sponsor_id,))
            self.db.commit()
            return bool(cur.rowcount)

    def sponsor_today(self, sponsor_id: int) -> int:
        return self.db.execute("SELECT COUNT(*) FROM sponsor_joins WHERE sponsor_id=? AND ts>?",
                               (sponsor_id, time.time() - 86400)).fetchone()[0]

    # ------------------------------------------------------------ admin

    def audience(self) -> list[int]:
        return [r[0] for r in self.db.execute("SELECT id FROM users WHERE blocked=0")]

    def mark_blocked(self, user_id: int) -> None:
        with self.lock:
            self.db.execute("UPDATE users SET blocked=1 WHERE id=?", (user_id,))
            self.db.commit()

    def track_chat(self, chat_id: int, title: str, active: bool) -> None:
        with self.lock:
            self.db.execute("INSERT INTO chats(id, title, active, added) VALUES (?,?,?,?) "
                            "ON CONFLICT(id) DO UPDATE SET title=excluded.title, active=excluded.active",
                            (chat_id, title, 1 if active else 0, time.time()))
            self.db.commit()

    def global_stats(self) -> dict:
        day = time.time() - 86400
        one = lambda sql, *a: self.db.execute(sql, a).fetchone()[0]  # noqa: E731
        return {
            "users": one("SELECT COUNT(*) FROM users"),
            "today": one("SELECT COUNT(*) FROM users WHERE created>?", day),
            "blocked": one("SELECT COUNT(*) FROM users WHERE blocked=1"),
            "active": one("SELECT COUNT(DISTINCT user_id) FROM rolls WHERE created>?", day),
            "rolls": one("SELECT COUNT(*) FROM rolls"),
            "rolls_today": one("SELECT COUNT(*) FROM rolls WHERE created>?", day),
            "saved": one("SELECT COUNT(*) FROM rolls WHERE saved=1"),
            "inline": one("SELECT COUNT(*) FROM rolls WHERE source='inline'"),
            "mythic": one("SELECT COUNT(*) FROM rolls WHERE score>=80"),
            "groups": one("SELECT COUNT(*) FROM chats WHERE active=1"),
            "sold": one("SELECT COUNT(*) FROM rolls WHERE sold=1"),
            "sold_for": one("SELECT COALESCE(SUM(sold_for), 0) FROM rolls WHERE sold=1"),
            "group_rolls": one("SELECT COUNT(*) FROM rolls WHERE source='group'"),
        }
