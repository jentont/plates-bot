"""Бот в группах: быстрые команды прокрутки, приветствие и напоминание.

* `.ролл`, `.спин`, `.номер` (и `.roll`, `.spin`, `/roll`) — бросок прямо в чат,
  карточка приходит ответом на сообщение игрока;
* бота добавили в группу — приветствие с анимацией прокрутки;
* раз в GROUP_NUDGE_EVERY сообщений бот отвечает кому-нибудь: «напиши .ролл».

Чтобы бот видел сообщения с точкой и считал сообщения, в @BotFather нужно
выключить privacy mode (/setprivacy → Disable) и заново добавить бота в группу.
Команды вида /roll приходят и без этого.
"""
from __future__ import annotations

import logging
import random
import time

from core.rarity import format_price

from .game import NoEnergy
from .render import render_card, in_thread
from .tg import TelegramError, btn, esc, kb

log = logging.getLogger("groups")

TRIGGERS = {".ролл", ".спин", ".номер", ".roll", ".spin", "/roll", "/spin", "/nomer"}
ANONYMOUS = 1087968824          # GroupAnonymousBot: от имени группы бросать некому

NUDGES = (
    "⚡ {name}, напиши <code>.ролл</code> и получи классный номер",
    "🌟 {name}, а ты знаешь, какой номер выпадет тебе? Напиши <code>.ролл</code>",
    "👑 {name}, кто-то здесь уже выбил мифический номер. Твоя очередь: <code>.ролл</code>",
    "✨ {name}, проверь удачу — напиши <code>.спин</code> и узнай цену своего номера",
    "⭐ {name}, три семёрки ждут. Напиши <code>.номер</code>",
)


def mention(user: dict) -> str:
    name = esc((user.get("first_name") or user.get("username") or "Игрок")[:32])
    return f'<a href="tg://user?id={user["id"]}">{name}</a>'


class Groups:
    def __init__(self, handlers):
        self.h = handlers
        self.tg, self.game, self.config, self.storage = handlers.tg, handlers.game, handlers.config, handlers.storage
        self._count: dict[int, int] = {}          # сообщений с последнего напоминания
        self._last_roll: dict[int, float] = {}    # chat_id → когда был последний бросок
        self._last_user: dict[tuple[int, int], float] = {}

    def bot_link(self, start: str = "") -> str:
        return f"https://t.me/{self.tg.me.get('username', '')}" + (f"?start={start}" if start else "")

    def card_keyboard(self, roll: dict) -> dict:
        rows = []
        from .handlers import sell_buttons
        if not roll["saved"] and not roll.get("sold"):
            rows.append([btn("⭐ В гараж", f"save:{roll['id']}", style="primary")])
        sb = sell_buttons(self.config, roll)
        if sb:
            rows.append(sb)
        rows.append([btn("⚡ Крутить свой", "groll", style="primary")])
        rows.append([btn("✨ Открыть бота", url=self.bot_link("g"))])
        return kb(rows)

    # ------------------------------------------------------------ сообщения

    async def on_message(self, m: dict) -> None:
        user = m.get("from") or {}
        chat = m["chat"]
        if not user or user.get("is_bot") or user.get("id") == ANONYMOUS:
            return
        text = (m.get("text") or "").strip()
        word = text.split()[0].lower() if text else ""
        bot = self.tg.me.get("username", "").lower()
        if "@" in word:                      # /roll@nomera_spin_bot — только если это нам
            word, _, to = word.partition("@")
            if to != bot:
                return
        if word in TRIGGERS:
            await self.roll(chat, user, m["message_id"])
            return
        await self.maybe_nudge(chat, user, m)

    async def maybe_nudge(self, chat: dict, user: dict, m: dict) -> None:
        every = self.config.group_nudge_every
        if not every or not (m.get("text") or m.get("caption") or m.get("sticker") or m.get("photo")):
            return
        n = self._count.get(chat["id"], 0) + 1
        if n < every:
            self._count[chat["id"]] = n
            return
        self._count[chat["id"]] = 0
        try:
            await self.tg("sendMessage", chat_id=chat["id"], parse_mode="HTML",
                          text=random.choice(NUDGES).format(name=mention(user)),
                          reply_parameters={"message_id": m["message_id"], "allow_sending_without_reply": True})
        except TelegramError as e:
            log.info("напоминание в %s не ушло: %s", chat["id"], e)

    async def roll(self, chat: dict, user: dict, reply_to: int | None) -> None:
        now = time.time()
        # Лимит Telegram — ~20 сообщений в минуту на группу; не даём забить его одним игроком.
        if now - self._last_roll.get(chat["id"], 0) < 3 or now - self._last_user.get((chat["id"], user["id"]), 0) < 8:
            return
        self._last_roll[chat["id"]] = now
        self._last_user[(chat["id"], user["id"])] = now
        reply = {"message_id": reply_to, "allow_sending_without_reply": True} if reply_to else None
        self.storage.touch_user(user)
        if self.h.sponsors and await self.h.sponsors.missing(user["id"]):
            await self.tg("sendMessage", chat_id=chat["id"], parse_mode="HTML", reply_parameters=reply,
                          text=f"🔒 {mention(user)}, чтобы крутить номера, подпишись на спонсоров в боте",
                          reply_markup=kb([[btn("✅ Подписаться", url=self.bot_link("sub"), style="success")]]))
            return
        try:
            roll = self.game.spin(user, "group")
        except NoEnergy:
            en = self.storage.energy(user["id"])
            await self.tg("sendMessage", chat_id=chat["id"], parse_mode="HTML", reply_parameters=reply,
                          text=f"⌛ {mention(user)}, энергия кончилась. +1 через {en['next_in'] // 60} мин {en['next_in'] % 60} с",
                          reply_markup=kb([[btn("⚡ Пополнить энергию", url=self.bot_link("energy"))]]))
            return
        plate, ev = self.game.roll_objects(roll)
        from core.cars import BY_ID
        png = await in_thread(render_card, plate, ev, "Номер выпал", user.get("first_name") or "Игрок",
                              self.tg.me.get("username", "bot"), self.game.country_name(plate.country), "",
                              BY_ID.get(self.storage.car_of(user["id"]) or ""))
        where = self.game.country_name(plate.country) + (f", {plate.region_name}" if plate.region_name else "")
        caption = (f"⚡ {mention(user)} выбил номер <b>{esc(plate.text)}</b>\n"
                   f"🌟 {esc(where)}\n"
                   f"👑 {esc(ev.tier_name)} · 💰 <b>{esc(format_price(ev, plate.country))}</b>")
        sent = await self.tg("sendPhoto", files={"photo": ("card.png", png)}, chat_id=chat["id"], caption=caption,
                             parse_mode="HTML", reply_parameters=reply, reply_markup=self.card_keyboard(roll))
        self.h.remember_card(roll, sent)

    # ------------------------------------------------------------ кнопки

    async def on_callback(self, cq: dict) -> bool:
        """Кнопки под групповой карточкой. True — обработано."""
        msg = cq.get("message") or {}
        if cq.get("data") != "groll" or not msg:
            return False
        await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
        await self.roll(msg["chat"], cq["from"], msg.get("message_id"))
        return True

    # ------------------------------------------------------------ добавили в группу

    async def on_my_chat_member(self, upd: dict) -> None:
        chat = upd["chat"]
        if chat["type"] not in ("group", "supergroup"):
            return
        old, new = upd["old_chat_member"]["status"], upd["new_chat_member"]["status"]
        joined = new in ("member", "administrator") and old in ("left", "kicked")
        left = new in ("left", "kicked")
        self.storage.track_chat(chat["id"], chat.get("title") or "", active=not left)
        if not joined:
            return
        bot = self.tg.me.get("username", "")
        caption = ("✨ <b>Привет, чат! Я Номера</b>\n\n"
                   "Кручу автомобильные номера России и ещё 19 стран, считаю их редкость и цену. "
                   "Три семёрки, зеркальные цифры, блатные серии — посмотрим, кому повезёт.\n\n"
                   "⚡ Чтобы бросить номер, напишите в чат:\n"
                   "<code>.ролл</code>  ·  <code>.спин</code>  ·  <code>.номер</code>\n\n"
                   f"⭐ Гараж, топ игроков и приложение — в @{esc(bot)}")
        markup = kb([[btn("⚡ Бросить номер", "groll", style="primary")],
                     [btn("✨ Открыть бота", url=self.bot_link("g"))]])
        try:
            await self.h.send_banner(chat["id"], caption, markup)
        except TelegramError as e:
            log.info("приветствие в %s не ушло: %s", chat["id"], e)
