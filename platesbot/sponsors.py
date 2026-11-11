"""Обязательная подписка на спонсоров — как в «Итогах года» и mogbattle.

Спонсоры правятся в админке и живут в базе. Бывают двух видов:

* канал или чат (есть chat_id) — подписку проверяем через getChatMember.
  Бот должен быть админом в канале. Если Telegram не отвечает, канал
  считаем пройденным: не держим людей за дверью из-за своей настройки;
* простая ссылка (бот, сайт) — проверить нельзя, просто показываем кнопку.

Пройденную проверку помним SUBSCRIBE_TTL секунд: лимиты Bot API общие на бота.
"""
from __future__ import annotations

import asyncio
import html
import logging
import time

from .tg import Telegram, TelegramError

log = logging.getLogger("sponsors")

INSIDE = ("member", "administrator", "creator", "restricted")


class Sponsors:
    def __init__(self, tg: Telegram | None, storage, config):
        self.tg, self.storage, self.config = tg, storage, config
        self._passed: dict[int, float] = {}

    def forget(self, user_id: int | None = None) -> None:
        if user_id is None:
            self._passed.clear()
        else:
            self._passed.pop(user_id, None)

    @staticmethod
    def link_of(row: dict) -> str:
        if row.get("link"):
            return row["link"]
        return f"https://t.me/{row['username']}" if row.get("username") else ""

    async def missing(self, user_id: int, fresh: bool = False) -> list[dict]:
        """Спонсоры, на которых человек не подписан. Пусто — можно играть."""
        if self.tg is None or user_id in self.config.admin_ids:
            return []
        if not fresh and self._passed.get(user_id, 0) > time.time():
            return []
        rows = self.storage.sponsors()
        if not rows:
            return []
        out: list[dict] = []
        for row in rows:
            if not row["chat_id"]:
                continue
            try:
                member = await self.tg.raw("getChatMember", chat_id=row["chat_id"], user_id=user_id)
            except TelegramError as error:
                log.warning("не проверить подписку на %s: %s", row["title"], error)
                continue
            if member.get("status") in INSIDE or member.get("is_member"):
                if self.storage.sponsor_joined(row["id"], user_id):
                    await self._check_goal(row["id"])
            else:
                out.append(row)
        if out:
            # Непроверяемые ссылки показываем вместе с каналами.
            return out + [r for r in rows if not r["chat_id"]]
        self._passed[user_id] = time.time() + self.config.subscribe_ttl
        return []

    async def _check_goal(self, sponsor_id: int) -> None:
        row = self.storage.sponsor(sponsor_id)
        if not row or not row["goal"] or row["joined"] < row["goal"]:
            return
        self.storage.set_sponsor(sponsor_id, active=0)
        self.forget()
        await self.tell_admins(f"🎯 Спонсор <b>{html.escape(row['title'])}</b> набрал цель: "
                               f"{row['joined']} из {row['goal']}. Снял его из подписки.")

    async def tell_admins(self, text: str) -> None:
        for admin_id in self.config.admin_ids:
            try:
                await self.tg("sendMessage", chat_id=admin_id, text=text, parse_mode="HTML")
            except TelegramError as error:
                log.warning("админу %s не отправить: %s", admin_id, error)

    def report_text(self) -> str:
        rows = self.storage.sponsors(active_only=False)
        if not rows:
            return "📊 <b>Спонсоры</b>\n\nСпонсоров пока нет."
        lines = ["📊 <b>Спонсоры за сутки</b>", ""]
        for row in rows:
            goal = f" / цель {row['goal']}" if row["goal"] else ""
            state = "" if row["active"] else " · снят"
            kind = "" if row["chat_id"] else " · ссылка"
            lines.append(f"• <b>{html.escape(row['title'])}</b>{kind}{state}\n"
                         f"   за сутки +{self.storage.sponsor_today(row['id'])}, всего {row['joined']}{goal}")
        return "\n".join(lines)

    async def report_loop(self) -> None:
        """Раз в сутки в REPORT_HOUR по Москве прислать отчёт админам."""
        while True:
            try:
                now = time.gmtime(time.time() + 3 * 3600)
                today = time.strftime("%Y-%m-%d", now)
                if now.tm_hour >= self.config.report_hour and self.storage.get_setting("report_day") != today:
                    self.storage.set_setting("report_day", today)
                    if self.storage.sponsors(active_only=False):
                        await self.tell_admins(self.report_text())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("отчёт не ушёл")
            await asyncio.sleep(300)
