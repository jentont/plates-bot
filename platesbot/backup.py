"""Бэкап базы в Telegram и восстановление после передеплоя.

Хостинг пересоздаёт контейнер при каждом обновлении, и файл SQLite внутри него
пропадает. Поэтому бот сам держит копию базы в Telegram:

* раз в BACKUP_EVERY секунд, если в базе что-то поменялось, отправляет сжатую
  копию документом в чат-хранилище и закрепляет её;
* при запуске, если база пустая (0 игроков), берёт закреплённую копию и
  восстанавливается из неё — до того, как бот начнёт отвечать.

Куда складывать: BACKUP_CHAT (id приватного канала, где бот админ с правом
закреплять), иначе личка первого админа из ADMIN_IDS. Оба варианта заданы в
переменных окружения, поэтому переживают потерю базы — в отличие от настроек
из админки, которые живут в самой базе.
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import re
import sqlite3
import tempfile
import time
from pathlib import Path

import aiohttp

from .tg import TelegramError

log = logging.getLogger("backup")
API = "https://api.telegram.org"          # переопределяется в тестах


def target(config) -> int | None:
    if config.backup_chat:
        try:
            return int(config.backup_chat)
        except ValueError:
            log.warning("BACKUP_CHAT не число: %s", config.backup_chat)
    return config.admin_ids[0] if config.admin_ids else None


def _counts(path: Path) -> tuple[int, int]:
    """(игроков, бросков) в файле базы; (0, 0), если файла нет или он пустой."""
    if not path.exists():
        return 0, 0
    try:
        con = sqlite3.connect(str(path))
        try:
            users = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            rolls = con.execute("SELECT COUNT(*) FROM rolls").fetchone()[0]
            return users, rolls
        finally:
            con.close()
    except sqlite3.Error:
        return 0, 0


PLAYERS_RE = re.compile(r"Игроков (\d+)")


def is_backup(doc: dict | None) -> bool:
    return bool(doc) and str(doc.get("file_name", "")).startswith("plates-backup")


async def download(token: str, file_id: str) -> Path:
    """Скачать файл бэкапа из Telegram и распаковать во временный .db. Бросает RuntimeError с понятным текстом."""
    base = f"{API}/bot{token}/"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as s:
        async with s.post(base + "getFile", json={"file_id": file_id}) as r:
            path = ((await r.json(content_type=None)).get("result") or {}).get("file_path")
        if not path:
            raise RuntimeError("Telegram не отдал файл (больше 20 МБ?)")
        async with s.get(f"{API}/file/bot{token}/{path}") as r:
            blob = await r.read()
    try:
        raw = gzip.decompress(blob)
    except OSError as e:
        raise RuntimeError(f"бэкап повреждён: {e}") from e
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        tmp.write(raw)
    path = Path(tmp.name)
    if not _counts(path)[0]:
        path.unlink(missing_ok=True)
        raise RuntimeError("в бэкапе нет игроков")
    return path


async def pinned(token: str, chat: int) -> dict:
    """Закреплённое сообщение в чате бэкапов (или {})."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
        async with s.post(f"{API}/bot{token}/getChat", json={"chat_id": chat}) as r:
            info = await r.json(content_type=None)
    if not info.get("ok"):
        log.warning("getChat %s: %s", chat, info.get("description"))
    return (info.get("result") or {}).get("pinned_message") or {}


async def restore_if_empty(config) -> str:
    """Вызывается до открытия базы. Восстанавливает закреплённую копию, если своя база пустая
    или почти пустая (меньше 10 игроков), а в копии игроков заметно больше. Возвращает строку для лога."""
    chat = target(config)
    if not config.bot_token or not chat:
        return "бэкап не настроен: нет BOT_TOKEN или ADMIN_IDS/BACKUP_CHAT"
    users, _ = _counts(config.db_path)
    if users >= 10:
        return f"база на месте ({users} игроков), восстановление не нужно"
    doc = (await pinned(config.bot_token, chat)).get("document")
    if not is_backup(doc):
        return f"база почти пустая ({users} игроков), а закреплённого бэкапа в {chat} нет — начинаем так"
    try:
        tmp = await download(config.bot_token, doc["file_id"])
    except RuntimeError as e:
        return f"бэкап не восстановлен: {e}"
    restored = _counts(tmp)
    if restored[0] <= users * 2:
        tmp.unlink(missing_ok=True)
        return f"в закреплённом бэкапе {restored[0]} игроков, у нас {users} — оставляю свою базу"
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    for extra in ("-wal", "-shm", "-journal"):
        Path(str(config.db_path) + extra).unlink(missing_ok=True)
    tmp.replace(config.db_path)
    return f"база восстановлена из бэкапа: {restored[0]} игроков, {restored[1]} бросков"


class Backup:
    def __init__(self, tg, storage, config):
        self.tg, self.storage, self.config = tg, storage, config
        self.last_sig: tuple | None = None
        self.last_users = 0
        self.last_at = 0.0
        self.last_msg: int | None = None
        self.last_day = ""
        self.status = "ещё не делали"

    def _signature(self) -> tuple:
        db = self.storage.db
        one = lambda sql: db.execute(sql).fetchone()[0]  # noqa: E731
        return (one("SELECT COUNT(*) FROM users"), one("SELECT COALESCE(MAX(id), 0) FROM rolls"),
                one("SELECT COALESCE(SUM(saved + sold + forever), 0) FROM rolls"),
                one("SELECT COALESCE(SUM(energy + money), 0) FROM users"),
                one("SELECT COUNT(*) FROM user_cars"), one("SELECT COUNT(*) FROM sponsors"),
                one("SELECT COUNT(*) FROM settings"))

    def _dump(self) -> bytes:
        """Согласованная копия через sqlite backup API, сжатая gzip."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy.db"
            with self.storage.lock:
                dst = sqlite3.connect(str(path))
                self.storage.db.backup(dst)
                dst.close()
            return gzip.compress(path.read_bytes(), 9)

    async def run_once(self, force: bool = False) -> str:
        chat = target(self.config)
        if not chat:
            self.status = "некуда сохранять: задай ADMIN_IDS или BACKUP_CHAT"
            return self.status
        sig = self._signature()
        if not force and sig == self.last_sig:
            return self.status
        users = sig[0]
        if not self.last_users:
            # после перезапуска сверяемся с уже закреплённой копией: сколько в ней игроков
            try:
                cap = (await pinned(self.config.bot_token, chat)).get("caption") or ""
                found = PLAYERS_RE.search(cap)
                self.last_users = int(found.group(1)) if found else 0
            except Exception:  # noqa: BLE001
                log.warning("не прочитал закреплённый бэкап", exc_info=True)
        # Защита от затирания: внезапно пустая база не должна вытеснить нормальный бэкап
        if self.last_users >= 10 and users < self.last_users // 2:
            warn = not self.status.startswith("пропустил")
            self.status = (f"пропустил: игроков стало {users} вместо {self.last_users} — похоже на потерю базы. "
                           "Ответь на файл нормального бэкапа командой /restore")
            log.warning(self.status)
            if warn:
                try:
                    await self.tg("sendMessage", chat_id=chat, text=(
                        f"⚠️ В базе {users} игроков, а в закреплённом бэкапе {self.last_users}. "
                        "Похоже, база потерялась при передеплое. Новый бэкап не закрепляю.\n\n"
                        "Чтобы вернуть игроков, ответь на сообщение с нужным файлом plates-backup командой /restore"))
                except TelegramError:
                    pass
            return self.status
        blob = await asyncio.to_thread(self._dump)
        stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 3 * 3600))
        try:
            sent = await self.tg.raw("sendDocument", chat_id=chat, disable_notification=True,
                                     files={"document": (f"plates-backup-{stamp.replace(' ', '_').replace(':', '-')}.db.gz", blob)},
                                     caption=f"💾 Бэкап базы «Номера» · {stamp} МСК\nИгроков {users}, бросков {sig[1]}")
            await self.tg.raw("pinChatMessage", chat_id=chat, message_id=sent["message_id"], disable_notification=True)
        except TelegramError as e:
            self.status = f"не отправился в {chat}: {e.description}"
            log.warning(self.status)
            return self.status
        # Первая копия за сутки остаётся навсегда (для отката), промежуточные за день заменяют друг друга
        day = stamp[:10]
        if day != self.last_day:
            self.last_day, self.last_msg = day, None
        else:
            if self.last_msg:
                try:
                    await self.tg.raw("deleteMessage", chat_id=chat, message_id=self.last_msg)
                except TelegramError:
                    pass
            self.last_msg = sent["message_id"]
        self.last_sig, self.last_users, self.last_at = sig, users, time.time()
        self.status = f"последний: {stamp} МСК, {len(blob) // 1024} КБ, игроков {users}"
        log.info("бэкап: %s", self.status)
        return self.status

    async def restore(self, file_id: str) -> tuple[int, int]:
        """Вернуть базу из присланного файла бэкапа прямо в работающего бота. Потом сразу свежий бэкап с закрепом."""
        tmp = await download(self.config.bot_token, file_id)
        try:
            users, rolls = _counts(tmp)
            await asyncio.to_thread(self.storage.restore_from, tmp)
        finally:
            tmp.unlink(missing_ok=True)
        self.last_users, self.last_sig, self.status = users, None, "восстановлено, делаю свежую копию"
        await self.run_once(force=True)
        return users, rolls

    async def loop(self) -> None:
        await asyncio.sleep(60)               # дать боту подняться
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("бэкап упал")
            await asyncio.sleep(max(120, self.config.backup_every))
