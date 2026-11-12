"""Админ-панель /admin — по образцу «Итогов года» и mogbattle.

Спонсоры (обязательная подписка), статистика, рассылка, премиум-эмодзи и
баннер главного меню. Доступна только тем, кто перечислен в ADMIN_IDS.
Состояния ввода (ждём канал, ссылку, цель, пост) живут в памяти: после
перезапуска админ просто откроет /admin заново.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re

from . import emoji
from .tg import Telegram, TelegramError, btn, kb

log = logging.getLogger("admin")

PANEL = "⚙️ <b>Админка «Номера»</b>\n\nВыбери раздел."


def B(text: str, data: str, **kw) -> dict:
    return btn(text, data, **kw)


BACK = [B("⬅️ Назад", "a:main")]


def panel_kb() -> dict:
    return kb([
        [B("📢 Спонсоры", "a:sp")],
        [B("📊 Статистика", "a:stats"), B("📨 Рассылка", "a:post")],
        [B("✨ Премиум-эмодзи", "a:pack"), B("🖼 Баннер меню", "a:ban")],
        [B("🗄 Склад картинок", "a:store")],
    ])


class Admin:
    def __init__(self, tg: Telegram, storage, sponsors, config):
        self.tg, self.storage, self.sponsors, self.config = tg, storage, sponsors, config
        self.state: dict[int, tuple[str, dict]] = {}
        self.cards = None          # CardStore, подключается в main после создания обработчиков

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.config.admin_ids

    # ------------------------------------------------------------ вход

    async def on_message(self, m: dict) -> bool:
        """True — сообщение обработала админка."""
        user = m.get("from") or {}
        if not self.is_admin(user.get("id", 0)) or m["chat"]["type"] != "private":
            return False
        text = (m.get("text") or "").strip()
        if text.split("@")[0] in ("/admin", "/panel"):
            self.state.pop(user["id"], None)
            await self.send(user["id"], PANEL, panel_kb())
            return True
        st = self.state.get(user["id"])
        if not st:
            return False
        name, data = st
        handler = {"channel": self._got_channel, "link": self._got_link, "goal": self._got_goal,
                   "post": self._got_post, "pack": self._got_pack, "banner": self._got_banner,
                   "store": self._got_store}.get(name)
        if handler:
            await handler(user["id"], m, data)
            return True
        return False

    async def on_callback(self, cq: dict) -> bool:
        data = cq.get("data", "")
        user = cq["from"]
        if not data.startswith("a:"):
            return False
        if not self.is_admin(user["id"]):
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
            return True
        await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
        uid, msg = user["id"], cq.get("message") or {}
        parts = data.split(":")
        action = parts[1]
        if action == "main":
            self.state.pop(uid, None)
            await self.edit(msg, PANEL, panel_kb())
        elif action == "stats":
            await self.edit(msg, self._stats_text(), kb([[B("📊 Отчёт по спонсорам", "a:report")], BACK]))
        elif action == "report":
            await self.edit(msg, self.sponsors.report_text(), kb([[B("⬅️ Назад", "a:stats")]]))
        elif action == "sp":
            self.state.pop(uid, None)
            await self.edit(msg, *self._sponsors_screen())
        elif action == "s":
            await self.edit(msg, *self._sponsor_card(int(parts[2])))
        elif action == "tog":
            sid = int(parts[2])
            row = self.storage.sponsor(sid)
            if row:
                self.storage.set_sponsor(sid, active=0 if row["active"] else 1)
                self.sponsors.forget()
            await self.edit(msg, *self._sponsor_card(sid))
        elif action == "del":
            sid = int(parts[2])
            await self.edit(msg, "Точно удалить спонсора?",
                            kb([[B("🗑 Да, удалить", f"a:del!:{sid}", style="danger"), B("⬅️ Нет", f"a:s:{sid}")]]))
        elif action == "del!":
            self.storage.drop_sponsor(int(parts[2]))
            self.sponsors.forget()
            text, markup = self._sponsors_screen()
            await self.edit(msg, "✅ Удалил.\n\n" + text, markup)
        elif action == "goal":
            self.state[uid] = ("goal", {"sid": int(parts[2])})
            await self.edit(msg, "🎯 Сколько вступлений набрать? Пришли число, 0 — без цели.\n"
                                 "Когда цель наберётся, бот сам снимет канал и напишет тебе.",
                            kb([[B("⬅️ Отмена", "a:sp")]]))
        elif action == "add":
            self.state[uid] = ("channel", {})
            await self.edit(msg, (
                "➕ <b>Новый канал-спонсор</b>\n\n"
                "Сначала сделай бота админом в канале. Потом пришли сюда одно из:\n"
                "• любой пост из канала (переслать)\n"
                "• @юзернейм или ссылку t.me/…\n"
                "• id канала (-100…)\n\n"
                "Можно добавить цель через пробел: <code>@channel 5000</code>"), kb([[B("⬅️ Отмена", "a:sp")]]))
        elif action == "addlink":
            self.state[uid] = ("link", {})
            await self.edit(msg, ("➕ <b>Спонсор-ссылка</b> (бот, сайт — без проверки подписки)\n\n"
                                  "Пришли в формате:\n<code>Название | https://t.me/somebot?start=ref</code>"),
                            kb([[B("⬅️ Отмена", "a:sp")]]))
        elif action == "post":
            self.state[uid] = ("post", {})
            await self.edit(msg, "📨 Пришли сообщение для рассылки — текст, фото, видео, что угодно. "
                                 "Кнопки и премиум-эмодзи сохранятся.", kb([[B("⬅️ Отмена", "a:main")]]))
        elif action == "post!":
            st = self.state.pop(uid, None)
            if not st or st[0] != "post_ready":
                await self.send(uid, "Сообщение потерялось, начни заново.", kb([BACK]))
                return True
            status = await self.send(uid, "📨 Рассылаю…")
            asyncio.create_task(self._broadcast(st[1]["chat"], st[1]["msg"], uid, status))
        elif action == "pack":
            await self.edit(msg, self._pack_text(), kb([
                [B("📤 Пак по ссылке", "a:ipk"), B("🔄 Перечитать", "a:rl")], BACK]))
        elif action == "ipk":
            self.state[uid] = ("pack", {})
            await self.edit(msg, "Пришли ссылки на паки эмодзи, например <code>https://t.me/addemoji/tgiosicons</code>.\n"
                                 "Можно несколько через пробел — первый главнее. Применится сразу.",
                            kb([[B("❌ Отмена", "a:pack")]]))
        elif action == "rl":
            await emoji.load(self.tg, self.packs())
            await self.edit(msg, self._pack_text(), kb([
                [B("📤 Пак по ссылке", "a:ipk"), B("🔄 Перечитать", "a:rl")], BACK]))
        elif action == "ban":
            self.state[uid] = ("banner", {})
            custom = bool(self.storage.get_setting("menu_banner"))
            rows = [[B("✅ Вернуть стандартный", "a:ban0")]] if custom else []
            await self.edit(msg, "🖼 <b>Баннер главного меню</b>\n\n"
                                 f"Сейчас: {'свой' if custom else 'стандартный — анимация прокрутки А777АА 777'}.\n"
                                 "Пришли картинку, GIF или видео без звука, чтобы поставить своё. Лучше всего 1280×720.",
                            kb(rows + [BACK]))
        elif action == "store":
            self.state[uid] = ("store", {})
            chat = self.cards.chat_id() if self.cards else None
            await self.edit(msg, (
                "🗄 <b>Склад картинок</b>\n\n"
                f"Сейчас: {f'<code>{chat}</code>' if chat else 'не задан — инлайн берёт картинки по ссылке PUBLIC_URL'}\n\n"
                "Склад — приватный канал или группа, куда бот складывает карточки номеров и берёт их file_id. "
                "С ним инлайн-броски грузятся быстрее и не зависят от того, видит ли Telegram наш сервер.\n\n"
                "Сделай бота админом канала и пришли сюда любой пост оттуда (переслать) или id канала (-100…)."),
                kb(([[B("❌ Отключить склад", "a:store0")]] if chat else []) + [BACK]))
        elif action == "store0":
            self.state.pop(uid, None)
            self.storage.set_setting("storage_chat", "0")
            await self.edit(msg, "✅ Склад отключён, инлайн снова берёт картинки по ссылке.", kb([BACK]))
        elif action == "ban0":
            self.state.pop(uid, None)
            self.storage.set_setting("menu_banner", "")
            await self.edit(msg, "✅ Вернул стандартный баннер.", kb([BACK]))
        return True

    # ------------------------------------------------------------ отправка

    async def send(self, chat_id: int, text: str, markup: dict | None = None) -> dict:
        return await self.tg("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
                             reply_markup=markup, link_preview_options={"is_disabled": True})

    async def edit(self, msg: dict, text: str, markup: dict | None = None) -> None:
        try:
            await self.tg("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"], text=text,
                          parse_mode="HTML", reply_markup=markup, link_preview_options={"is_disabled": True})
        except (TelegramError, KeyError) as error:
            if "not modified" in str(error):
                return
            # Сообщение с картинкой или старое — шлём новое.
            if msg.get("chat"):
                await self.send(msg["chat"]["id"], text, markup)

    # ------------------------------------------------------------ экраны

    def _stats_text(self) -> str:
        s = self.storage.global_stats()
        return ("📊 <b>Статистика</b>\n\n"
                f"👥 Всего: <b>{s['users']}</b> (+{s['today']} за сутки)\n"
                f"⚡ Активны за сутки: <b>{s['active']}</b>\n"
                f"🎯 Бросков: <b>{s['rolls']}</b> (+{s['rolls_today']} за сутки)\n"
                f"📤 Инлайн-бросков: <b>{s['inline']}</b>\n"
                f"👥 Групп с ботом: <b>{s['groups']}</b>, бросков в группах: <b>{s['group_rolls']}</b>\n"
                f"💰 Продано номеров: <b>{s['sold']}</b> за <b>{s['sold_for']}</b> прокрутов и <b>{s['sold_money']:,}</b> ₽\n"
                f"🚀 Куплено машин: <b>{s['cars']}</b>\n"
                f"⭐ Сохранено в гаражи: <b>{s['saved']}</b>\n"
                f"👑 Мифических номеров: <b>{s['mythic']}</b>\n"
                f"❌ Заблокировали бота: <b>{s['blocked']}</b>")

    def _sponsors_screen(self) -> tuple[str, dict]:
        rows = self.storage.sponsors(active_only=False)
        lines, buttons = ["📢 <b>Спонсоры</b>", ""], []
        if not rows:
            lines.append("Пока пусто — бот открыт без подписки.")
        for r in rows:
            mark = "✅" if r["active"] else "💤"
            kind = "канал" if r["chat_id"] else "ссылка"
            goal = f" · {r['joined']}/{r['goal']}" if r["goal"] else f" · {r['joined']}"
            lines.append(f"{mark} <b>{html.escape(r['title'])}</b> — {kind}{goal}")
            buttons.append([B(f"{mark} {r['title']}", f"a:s:{r['id']}")])
        lines += ["", "Бот должен быть <b>админом</b> в канале, иначе подписку не проверить."]
        buttons.append([B("➕ Канал", "a:add"), B("➕ Ссылка", "a:addlink")])
        buttons.append(BACK)
        return "\n".join(lines), kb(buttons)

    def _sponsor_card(self, sid: int) -> tuple[str, dict]:
        r = self.storage.sponsor(sid)
        if not r:
            return self._sponsors_screen()
        text = (f"📢 <b>{html.escape(r['title'])}</b>\n\n"
                f"Ссылка: {html.escape(self.sponsors.link_of(r) or '—')}\n"
                f"Тип: {'канал/чат, подписка проверяется' if r['chat_id'] else 'ссылка без проверки'}\n"
                f"Статус: {'активен' if r['active'] else 'на паузе'}\n"
                f"Вступили через бота: <b>{r['joined']}</b> (за сутки +{self.storage.sponsor_today(sid)})\n"
                f"Цель: <b>{r['goal'] or 'нет'}</b>")
        toggle = "💤 Пауза" if r["active"] else "✅ Включить"
        return text, kb([
            [B("🎯 Цель", f"a:goal:{sid}"), B(toggle, f"a:tog:{sid}")],
            [B("🗑 Удалить", f"a:del:{sid}", style="danger")],
            [B("⬅️ Назад", "a:sp")],
        ])

    def packs(self) -> list[str]:
        raw = self.storage.get_setting("icon_packs")
        return [x for x in raw.split(",") if x] if raw else list(self.config.icon_packs)

    def _pack_text(self) -> str:
        have, miss = emoji.covered()
        links = ", ".join(f"<a href='https://t.me/addemoji/{p}'>{html.escape(p)}</a>" for p in self.packs())
        return ("✨ <b>Премиум-эмодзи</b>\n\n"
                f"Паки: {links or '—'}\n{html.escape(emoji.status())}\n\n"
                f"Есть в паке: {' '.join(have) or '—'}\n"
                + (f"Нет в паке (останется обычный): {' '.join(miss)}\n" if miss else "")
                + "\nПремиум-эмодзи ставятся в тексты, на кнопки и в инлайн-сообщения. "
                  "Если Telegram не пустит их у этого бота, бот сам откатится на обычные эмодзи.")

    # ------------------------------------------------------------ ввод

    @staticmethod
    def _target(m: dict) -> tuple[str | int | None, int]:
        origin = m.get("forward_origin") or {}
        chat = origin.get("chat") or m.get("forward_from_chat")
        if chat:
            return chat["id"], 0
        raw, goal = (m.get("text") or "").strip(), 0
        parts = raw.split()
        if len(parts) > 1 and parts[-1].isdigit():
            goal, raw = int(parts[-1]), " ".join(parts[:-1])
        found = re.search(r"(?:t\.me/|telegram\.me/|@)([A-Za-z0-9_]{4,})", raw)
        if found and found.group(1) not in ("joinchat", "c"):
            return "@" + found.group(1), goal
        if raw.lstrip("-").isdigit():
            return int(raw), goal
        return None, goal

    async def _got_channel(self, uid: int, m: dict, data: dict) -> None:
        target, goal = self._target(m)
        if target is None:
            await self.send(uid, "Не понял, что это за канал. Перешли пост или пришли @юзернейм.")
            return
        try:
            chat = await self.tg.raw("getChat", chat_id=target)
        except TelegramError as error:
            await self.send(uid, f"Telegram не отдал канал: {html.escape(error.description)}\nБот добавлен в канал?")
            return
        warn = ""
        try:
            me = await self.tg.raw("getChatMember", chat_id=chat["id"], user_id=self.tg.me.get("id"))
            if me.get("status") not in ("administrator", "creator"):
                warn = "\n❗ Бот не админ в канале — подписку проверить не получится."
        except TelegramError:
            warn = "\n❗ Бот не видит канал — сделай его админом."
        link = f"https://t.me/{chat['username']}" if chat.get("username") else (chat.get("invite_link") or "")
        if not link:
            try:
                invite = await self.tg.raw("createChatInviteLink", chat_id=chat["id"], name="Номера")
                link = invite["invite_link"]
            except TelegramError:
                warn += "\n❗ У канала нет юзернейма, а ссылку-приглашение бот создать не смог."
        title = chat.get("title") or chat.get("username") or str(chat["id"])
        self.storage.add_sponsor(chat["id"], title, chat.get("username"), link, goal)
        self.sponsors.forget()
        self.state.pop(uid, None)
        text, markup = self._sponsors_screen()
        await self.send(uid, f"✅ Добавил <b>{html.escape(title)}</b>{warn}\n\n" + text, markup)

    async def _got_link(self, uid: int, m: dict, data: dict) -> None:
        raw = m.get("text") or ""
        if "|" not in raw:
            await self.send(uid, "Нужно «Название | ссылка».")
            return
        title, link = (p.strip() for p in raw.split("|", 1))
        if not link.startswith(("https://", "http://", "tg://")):
            await self.send(uid, "Ссылка должна начинаться с https://")
            return
        self.storage.add_sponsor(None, title[:64], None, link)
        self.sponsors.forget()
        self.state.pop(uid, None)
        text, markup = self._sponsors_screen()
        await self.send(uid, "✅ Ссылка добавлена\n\n" + text, markup)

    async def _got_goal(self, uid: int, m: dict, data: dict) -> None:
        raw = (m.get("text") or "").strip().replace(" ", "")
        if not raw.isdigit():
            await self.send(uid, "Нужно число, например 5000.")
            return
        self.storage.set_sponsor(data["sid"], goal=int(raw))
        self.state.pop(uid, None)
        await self.send(uid, *self._sponsor_card(data["sid"]))

    async def _got_post(self, uid: int, m: dict, data: dict) -> None:
        self.state[uid] = ("post_ready", {"chat": m["chat"]["id"], "msg": m["message_id"]})
        n = len(self.storage.audience())
        await self.send(uid, f"Отправить это сообщение <b>{n}</b> людям?",
                        kb([[B("🚀 Отправить", "a:post!", style="success"), B("⬅️ Отмена", "a:main")]]))

    async def _got_pack(self, uid: int, m: dict, data: dict) -> None:
        names = re.findall(r"(?:addemoji/|^|\s)([A-Za-z0-9_]{5,64})(?=\s|$)", m.get("text") or "")
        names = [n for n in names if n.lower() not in ("https", "addemoji")]
        if not names:
            await self.send(uid, "Не вижу ссылок вида t.me/addemoji/ИМЯ — пришли ещё раз.")
            return
        count = await emoji.load(self.tg, names)
        if not count:
            await self.send(uid, "Эти паки не прочитались — проверь ссылки.")
            return
        self.storage.set_setting("icon_packs", ",".join(names))
        self.state.pop(uid, None)
        await self.send(uid, "✅ Готово, эмодзи уже применяются.\n\n" + self._pack_text(), kb([[B("⬅️ Назад", "a:pack")]]))

    async def _got_store(self, uid: int, m: dict, data: dict) -> None:
        origin = m.get("forward_origin") or {}
        chat = origin.get("chat") or m.get("forward_from_chat")
        raw = chat["id"] if chat else (m.get("text") or "").strip()
        try:
            raw = int(raw)
        except (TypeError, ValueError):
            await self.send(uid, "Перешли пост из канала-склада или пришли его id, например <code>-1001234567890</code>.")
            return
        chat_id, note = await self.cards.set_chat(raw)
        if not chat_id:
            await self.send(uid, f"❗ Склад не отвечает: {html.escape(note)}\nБот добавлен в канал админом?")
            return
        self.state.pop(uid, None)
        await self.send(uid, f"✅ Склад подключён: <b>{html.escape(note)}</b> (<code>{chat_id}</code>). "
                             "Там уже лежит пробная картинка.", kb([BACK]))

    async def _got_banner(self, uid: int, m: dict, data: dict) -> None:
        photos = m.get("photo") or []
        anim = m.get("animation") or m.get("video")
        if anim:
            value = "anim:" + anim["file_id"]
        elif photos:
            value = "photo:" + photos[-1]["file_id"]
        else:
            await self.send(uid, "Нужна картинка, GIF или видео — пришли ещё раз.")
            return
        self.storage.set_setting("menu_banner", value)
        self.state.pop(uid, None)
        await self.send(uid, "✅ Баннер меню обновлён. Проверь: /start", kb([BACK]))

    # ------------------------------------------------------------ рассылка

    async def _broadcast(self, from_chat: int, msg_id: int, admin_id: int, status: dict) -> None:
        users = self.storage.audience()
        ok = fail = 0
        for i, user_id in enumerate(users, 1):
            try:
                await self.tg.raw("copyMessage", chat_id=user_id, from_chat_id=from_chat, message_id=msg_id)
                ok += 1
            except TelegramError as error:
                fail += 1
                if error.code == 403:
                    self.storage.mark_blocked(user_id)
                elif error.code == 429:
                    await asyncio.sleep(5)
            if i % 25 == 0:
                await asyncio.sleep(1)       # не больше ~25 сообщений в секунду
            if i % 200 == 0:
                try:
                    await self.tg("editMessageText", chat_id=admin_id, message_id=status["message_id"],
                                  text=f"📨 Рассылаю… {i} из {len(users)}")
                except TelegramError:
                    pass
        await self.send(admin_id, f"✅ Рассылка готова: доставлено <b>{ok}</b>, не дошло <b>{fail}</b>.", kb([BACK]))
