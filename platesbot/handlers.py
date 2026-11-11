"""Обработчики апдейтов Telegram: команды, кнопки, inline-режим, Stars."""
from __future__ import annotations

import logging
from pathlib import Path

from core.rarity import format_price

from .config import Config
from .game import Game, NoEnergy
from .render import render_card
from .tg import Telegram, TelegramError, btn, esc, kb

log = logging.getLogger("handlers")


BANNER = Path(__file__).resolve().parent.parent / "assets" / "brand" / "banner_1280.png"


def app_button(config: Config, tg: Telegram, text: str = "✨ Открыть приложение") -> dict | None:
    if not config.webapp_url:
        return None
    return btn(text, web_app=config.webapp_url, style="primary")


def app_link(config: Config, tg: Telegram) -> str:
    return f"https://t.me/{tg.me.get('username', '')}?startapp" if config.webapp_url else f"https://t.me/{tg.me.get('username', '')}"


def energy_keyboard(config: Config) -> dict | None:
    """Кнопки покупки энергии за Stars: по одной на набор."""
    if not config.energy_packs:
        return None
    return kb([[btn(f"⚡ +{p['amount']} энергии за {p['stars']} Stars", f"buy:{p['id']}")] for p in config.energy_packs])


def regen_text(sec: int) -> str:
    return f"{sec // 60} мин" if sec % 60 == 0 else f"{sec} с"


def roll_caption(game: Game, roll: dict) -> str:
    plate, ev = game.roll_objects(roll)
    price = format_price(ev, plate.country)
    top = f"топ {ev.percentile}%" if ev.percentile <= 50 else f"{ev.score} очков"
    reasons = ", ".join(r["title"].lower() for r in ev.reasons if r["points"]) or "без особых признаков"
    where = game.country_name(plate.country) + (f", {plate.region_name}" if plate.region_name else "")
    return (f"🌟 <b>{esc(plate.text)}</b> — {esc(where)}\n"
            f"👑 {esc(ev.tier_name)} · {top}\n"
            f"💰 Оценка: <b>{esc(price)}</b>\n"
            f"<i>{esc(reasons)}</i>")


def roll_keyboard(config: Config, tg: Telegram, roll: dict) -> dict:
    rows = []
    if not roll["saved"]:
        rows.append([btn("⭐ Сохранить в гараж", f"save:{roll['id']}", style="primary")])
    rows.append([btn("⚡ Крутить ещё", "roll"), btn("📤 Поделиться", switch_inline_query=f"{roll['id']}")])
    ab = app_button(config, tg)
    if ab:
        rows.append([ab])
    return kb(rows)


async def send_roll_card(tg: Telegram, game: Game, config: Config, user: dict, roll: dict, chat_id: int | None = None) -> None:
    plate, ev = game.roll_objects(roll)
    png = render_card(plate, ev, "Номер выпал", user.get("first_name") or "Игрок", tg.me.get("username", "bot"),
                      game.country_name(plate.country))
    await tg("sendPhoto", files={"photo": ("card.png", png)}, chat_id=chat_id or user["id"],
             caption=roll_caption(game, roll), parse_mode="HTML", reply_markup=roll_keyboard(config, tg, roll))


class Handlers:
    def __init__(self, tg: Telegram, game: Game, config: Config, sponsors=None, admin=None):
        self.tg, self.game, self.config = tg, game, config
        self.sponsors, self.admin = sponsors, admin
        self._inline_busy: set[str] = set()   # инлайн-сообщения, где бросок уже идёт (двойное нажатие)
        self._inline_done: set[str] = set()   # уже брошенные: запоздалое второе нажатие не перебрасывает номер
        self.storage = game.storage

    # ------------------------------------------------------------ dispatch

    async def handle(self, upd: dict) -> None:
        try:
            if "message" in upd:
                if self.admin and await self.admin.on_message(upd["message"]):
                    return
                await self.on_message(upd["message"])
            elif "callback_query" in upd:
                if self.admin and await self.admin.on_callback(upd["callback_query"]):
                    return
                await self.on_callback(upd["callback_query"])
            elif "inline_query" in upd:
                await self.on_inline(upd["inline_query"])
            elif "pre_checkout_query" in upd:
                await self.tg("answerPreCheckoutQuery", pre_checkout_query_id=upd["pre_checkout_query"]["id"], ok=True)
        except TelegramError as e:
            log.warning("telegram error: %s", e)
        except Exception:  # noqa: BLE001
            log.exception("handler failed")

    # ------------------------------------------------------------ messages

    async def on_message(self, m: dict) -> None:
        user = m.get("from")
        if not user or m["chat"]["type"] != "private":
            return
        self.storage.touch_user(user)
        if "successful_payment" in m:
            await self.on_payment(user, m["successful_payment"])
            return
        text = (m.get("text") or "").strip()
        cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if not await self.gate(user):
            return
        if cmd == "/start":
            await self.cmd_start(user)
        elif cmd in ("/roll", "/spin"):
            await self.do_roll(user, "chat")
        elif cmd == "/garage":
            await self.cmd_garage(user)
        elif cmd == "/top":
            await self.cmd_top(user)
        elif cmd == "/energy":
            await self.cmd_energy(user)
        elif cmd in ("/app", "/help"):
            await self.cmd_help(user)
        elif text:
            res = self.game.estimate(text)
            if res:
                plate, ev = res
                price = format_price(ev, "RU")
                reasons = "\n".join(f"· {r['title']} +{r['points']}" for r in ev.reasons if r["points"]) or "· без особых признаков"
                await self.tg("sendMessage", chat_id=user["id"], parse_mode="HTML",
                              text=f"🌟 <b>{esc(plate.text)}</b> — {esc(plate.region_name or '')}\n👑 {esc(ev.tier_name)} · {ev.score} очков · топ {ev.percentile}%\n💰 Оценка: <b>{esc(price)}</b>\n{esc(reasons)}")
            else:
                await self.cmd_help(user)

    def menu_keyboard(self, user: dict) -> dict:
        rows = []
        ab = app_button(self.config, self.tg)
        if ab:
            rows.append([ab])
        rows.append([btn("⚡ Бросить номер", "roll")])
        rows.append([btn("📤 В любой чат", switch_inline_query="")])
        if self.admin and self.admin.is_admin(user["id"]):
            rows.append([btn("⚙️ Админка", "a:main")])
        return kb(rows)

    def menu_text(self, user: dict) -> str:
        return (f"✨ Привет, <b>{esc(user.get('first_name') or 'водитель')}</b>.\n\n"
                "Крути номера — российские и со всего мира. За каждый бросок получаешь номер и его оценку: "
                "редкость, очки, цена на рынке. Лучшие сохраняй в гараж.\n\n"
                f"⚡ Энергия: {self.config.energy_max} бросков, +1 каждые {regen_text(self.config.energy_regen_sec)}. "
                "Докупить: /energy\n"
                "🌟 Напиши свой номер, например <code>А777АА 777</code>, — оценю.")

    async def send_banner(self, chat_id: int, caption: str, markup: dict) -> None:
        """Сообщение с баннером: свой из админки, иначе стандартный (file_id кэшируется после первой загрузки)."""
        file_id = self.storage.get_setting("menu_banner") or self.storage.get_setting("menu_banner_default")
        if file_id:
            try:
                await self.tg("sendPhoto", chat_id=chat_id, photo=file_id, caption=caption, parse_mode="HTML",
                              reply_markup=markup)
                return
            except TelegramError as e:
                log.warning("баннер по file_id не ушёл: %s", e)
        if BANNER.exists():
            sent = await self.tg("sendPhoto", files={"photo": ("banner.png", BANNER.read_bytes())}, chat_id=chat_id,
                                 caption=caption, parse_mode="HTML", reply_markup=markup)
            try:
                self.storage.set_setting("menu_banner_default", sent["photo"][-1]["file_id"])
            except (KeyError, IndexError, TypeError):
                pass
            return
        await self.tg("sendMessage", chat_id=chat_id, text=caption, parse_mode="HTML", reply_markup=markup)

    async def cmd_start(self, user: dict) -> None:
        await self.send_banner(user["id"], self.menu_text(user), self.menu_keyboard(user))

    # ------------------------------------------------------------ обязательная подписка

    def gate_markup(self, rows: list[dict]) -> dict:
        buttons = []
        for row in rows:
            link = self.sponsors.link_of(row)
            if link:
                buttons.append([btn(f"📢 {row['title']}", url=link)])
        buttons.append([btn("✅ Проверить подписку", "check", style="success")])
        return kb(buttons)

    async def gate(self, user: dict, notify: bool = True) -> bool:
        """True — можно играть. Иначе шлёт просьбу подписаться на спонсоров."""
        if not self.sponsors:
            return True
        need = await self.sponsors.missing(user["id"])
        if not need:
            return True
        if notify:
            await self.send_banner(user["id"],
                                   f"🔒 <b>{esc(user.get('first_name') or 'Водитель')}</b>, чтобы крутить номера, "
                                   "подпишись на каналы спонсоров. Потом нажми «Проверить подписку».",
                                   self.gate_markup(need))
        return False

    async def cmd_help(self, user: dict) -> None:
        await self.tg("sendMessage", chat_id=user["id"], parse_mode="HTML", reply_markup=self.menu_keyboard(user),
                      text="⚡ /roll — бросить номер\n⭐ /garage — гараж\n👑 /top — лучшие игроки\n💰 /energy — энергия и покупка за Stars\n"
                           "📤 В любом чате: напиши @" + esc(self.tg.me.get("username", "")) + " и выбери бросок.")

    async def cmd_garage(self, user: dict) -> None:
        garage = self.storage.garage(user["id"])
        stats = self.storage.stats(user["id"])
        if not garage:
            text = "⭐ Гараж пуст. Брось номер и сохрани его."
        else:
            lines = []
            for r in garage:
                plate, ev = self.game.roll_objects(r)
                lines.append(f"<b>{esc(plate.text)}</b> · {esc(ev.tier_name)} · {esc(format_price(ev, plate.country))}" + (" · навсегда" if r["forever"] else ""))
            text = f"⭐ <b>Гараж</b> {len(garage)}/{stats['slots']}\n\n" + "\n".join(lines)
        await self.tg("sendMessage", chat_id=user["id"], parse_mode="HTML", text=text)

    async def cmd_top(self, user: dict) -> None:
        top = self.storage.top(10)
        if not top:
            text = "👑 Пока никто не крутил. Будь первым: /roll"
        else:
            text = "👑 <b>Лучшие номера</b>\n\n" + "\n".join(f"{i + 1}. {esc(t['name'])} — <b>{esc(t['plate_text'])}</b> · {t['score']} очков" for i, t in enumerate(top))
        await self.tg("sendMessage", chat_id=user["id"], parse_mode="HTML", text=text)

    async def cmd_energy(self, user: dict) -> None:
        en = self.storage.energy(user["id"])
        text = f"⚡ Энергия: <b>{en['current']}</b> из {en['max']}."
        if en["current"] < en["max"]:
            text += f"\n+1 через {en['next_in'] // 60} мин {en['next_in'] % 60} с (каждые {regen_text(self.config.energy_regen_sec)})."
        elif en["current"] > en["max"]:
            text += "\nКупленная энергия не сгорает, восстановление начнётся, когда запас опустится ниже максимума."
        params = {}
        markup = energy_keyboard(self.config)
        if markup:
            text += "\n\nМожно докупить за Stars:"
            params["reply_markup"] = markup
        await self.tg("sendMessage", chat_id=user["id"], parse_mode="HTML", text=text, **params)

    async def send_energy_invoice(self, user: dict, pack: dict) -> None:
        await self.tg("sendInvoice", chat_id=user["id"], title=f"Энергия +{pack['amount']}",
                      description=f"{pack['amount']} бросков номера. Энергия сверх максимума не сгорает.",
                      payload=f"energy:{pack['id']}", currency="XTR",
                      prices=[{"label": f"Энергия +{pack['amount']}", "amount": pack["stars"]}])

    async def do_roll(self, user: dict, source: str) -> None:
        try:
            roll = self.game.spin(user, source)
        except NoEnergy:
            en = self.storage.energy(user["id"])
            params = {}
            markup = energy_keyboard(self.config)
            text = f"⌛ Энергия кончилась. Следующий бросок через {en['next_in'] // 60} мин {en['next_in'] % 60} с."
            if markup:
                text += "\nИли докупи энергию за Stars:"
                params["reply_markup"] = markup
            await self.tg("sendMessage", chat_id=user["id"], text=text, parse_mode="HTML", **params)
            return
        await send_roll_card(self.tg, self.game, self.config, user, roll)

    # ------------------------------------------------------------ callbacks

    async def on_callback(self, cq: dict) -> None:
        user = cq["from"]
        data = cq.get("data", "")
        self.storage.touch_user(user)
        if data == "check":
            need = await self.sponsors.missing(user["id"], fresh=True) if self.sponsors else []
            if need:
                await self.tg("answerCallbackQuery", callback_query_id=cq["id"], show_alert=True,
                              text="Ещё не на всех подписан. Подпишись и нажми ещё раз.")
                msg = cq.get("message")
                if msg:
                    try:
                        await self.tg("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                                      reply_markup=self.gate_markup(need))
                    except TelegramError:
                        pass
                return
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"], text="Готово, можно крутить")
            msg = cq.get("message")
            if msg:
                try:
                    await self.tg("deleteMessage", chat_id=msg["chat"]["id"], message_id=msg["message_id"])
                except TelegramError:
                    pass
            await self.cmd_start(user)
            return
        if data == "roll" or data.startswith(("save:", "buy:")):
            if not await self.gate(user):
                await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
                return
        if data == "roll":
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
            await self.do_roll(user, "chat")
            return
        if data.startswith("ir:"):
            try:
                _, kind, owner = data.split(":")
                owner_id = int(owner)
            except ValueError:
                await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
                return
            await self.on_inline_roll(cq, kind, owner_id)
            return
        if data.startswith("buy:"):
            pack = self.config.energy_pack(data[4:])
            if not pack:
                await self.tg("answerCallbackQuery", callback_query_id=cq["id"], text="Набор не найден")
                return
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
            await self.send_energy_invoice(user, pack)
            return
        if data.startswith("save:"):
            status, roll = self.storage.save_roll(int(data[5:]), user["id"])
            if status == "ok":
                await self.tg("answerCallbackQuery", callback_query_id=cq["id"], text="Сохранено в гараж")
                msg = cq.get("message")
                if msg:
                    try:
                        await self.tg("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                                      reply_markup=roll_keyboard(self.config, self.tg, roll))
                    except TelegramError:
                        pass
            elif status == "full":
                await self.tg("answerCallbackQuery", callback_query_id=cq["id"], text="Гараж полон", show_alert=False)
                if self.config.stars_forever:
                    await self.tg("sendInvoice", chat_id=user["id"], title="Номер навсегда",
                                  description=f"Сохранить {roll['plate']['text']} в гараже без ограничений по местам",
                                  payload=f"forever:{roll['id']}", currency="XTR",
                                  prices=[{"label": "Сохранить навсегда", "amount": self.config.stars_forever}])
                else:
                    await self.tg("sendMessage", chat_id=user["id"], text="⭐ Гараж полон. Освободи место: /garage", parse_mode="HTML")
            else:
                await self.tg("answerCallbackQuery", callback_query_id=cq["id"], text="Номер не найден")
            return
        await self.tg("answerCallbackQuery", callback_query_id=cq["id"])

    async def on_payment(self, user: dict, payment: dict) -> None:
        payload = payment.get("invoice_payload", "")
        if payload.startswith("forever:"):
            status, roll = self.storage.save_roll(int(payload[8:]), user["id"], forever=True)
            if status == "ok":
                await self.tg("sendMessage", chat_id=user["id"], text=f"{roll['plate']['text']} теперь в гараже навсегда.")
        elif payload.startswith("energy:"):
            pack = self.config.energy_pack(payload[7:])
            if not pack:
                log.error("оплачен неизвестный набор энергии: %s (user %s)", payload, user["id"])
                await self.tg("sendMessage", chat_id=user["id"], text="Оплата получена, но набор не найден. Напиши в поддержку, энергию начислим.")
                return
            en = self.storage.add_energy(user["id"], pack["amount"])
            await self.tg("sendMessage", chat_id=user["id"], text=f"Начислено +{pack['amount']} энергии. Теперь у тебя {en['current']}.")

    # ------------------------------------------------------------ inline

    async def on_inline(self, q: dict) -> None:
        user = q["from"]
        self.storage.touch_user(user)
        query = (q.get("query") or "").strip()
        results = []
        # Бросок в любом чате: картинка-заготовка и кнопка «Крутить». Номер падает по нажатию,
        # поэтому не нужен inline feedback в BotFather (chosen_inline_result).
        name = esc(user.get("first_name") or "Игрок")
        for kind, title, desc in (("ru", "Бросить российский номер", "Нажми «Крутить» — номер упадёт в чат"),
                                  ("world", "Бросить номер мира", "Любая из 19 стран")):
            markup = kb([[btn("Крутить", f"ir:{kind}:{user['id']}", style="primary")]])
            caption = f"⚡ <b>{name}</b> бросает номер. Нажми «Крутить»"
            if self.config.public_url:
                results.append({
                    "type": "photo", "id": f"roll_{kind}",
                    "photo_url": f"{self.config.public_url}/card/cover_{kind}.png?v=2",
                    "thumbnail_url": f"{self.config.public_url}/card/cover_{kind}.png?v=2",
                    "photo_width": 1200, "photo_height": 675,
                    "title": title, "description": desc, "caption": caption, "parse_mode": "HTML", "reply_markup": markup,
                })
            else:
                results.append({
                    "type": "article", "id": f"roll_{kind}", "title": title, "description": desc,
                    "input_message_content": {"message_text": caption, "parse_mode": "HTML"}, "reply_markup": markup,
                })
        # поделиться конкретной прокруткой (кнопка «Поделиться» под карточкой передаёт её id)
        if query.isdigit():
            roll = self.storage.get_roll(int(query))
            if roll and roll["user_id"] == user["id"]:
                if self.config.public_url:
                    results.insert(0, {
                        "type": "photo", "id": f"share_{roll['id']}",
                        "photo_url": f"{self.config.public_url}/card/{roll['id']}.png",
                        "thumbnail_url": f"{self.config.public_url}/card/{roll['id']}.png",
                        "photo_width": 1200, "photo_height": 675,
                        "title": f"Мой номер {roll['plate']['text']}",
                        "caption": roll_caption(self.game, roll), "parse_mode": "HTML",
                        "reply_markup": kb([[btn("Крутить свой", url=app_link(self.config, self.tg))]]),
                    })
                else:
                    results.insert(0, {
                        "type": "article", "id": f"share_{roll['id']}", "title": f"Мой номер {roll['plate']['text']}",
                        "input_message_content": {"message_text": roll_caption(self.game, roll), "parse_mode": "HTML"},
                        "reply_markup": kb([[btn("Крутить свой", url=app_link(self.config, self.tg))]]),
                    })
        else:
            res = self.game.estimate(query) if query else None
            if res:
                plate, ev = res
                results.insert(0, {
                    "type": "article", "id": "est", "title": f"Оценить {plate.text}",
                    "description": f"{ev.tier_name} · {format_price(ev, 'RU')}",
                    "input_message_content": {"parse_mode": "HTML", "message_text":
                        f"<b>{esc(plate.text)}</b> — {esc(ev.tier_name)}, {ev.score} очков, топ {ev.percentile}%\nОценка: <b>{esc(format_price(ev, 'RU'))}</b>"},
                })
        await self.tg("answerInlineQuery", inline_query_id=q["id"], results=results, cache_time=0, is_personal=True)

    async def on_inline_roll(self, cq: dict, kind: str, owner_id: int) -> None:
        """Кнопка «Крутить» под инлайн-сообщением: бросок и замена картинки на карточку номера."""
        user, imid = cq["from"], cq.get("inline_message_id")
        bot = self.tg.me.get("username", "")
        if not imid:
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
            return
        if user["id"] != owner_id:
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"], show_alert=True,
                          text=f"Это чужой бросок. Чтобы бросить свой номер, напиши @{bot} в этом чате")
            return
        if imid in self._inline_busy or imid in self._inline_done:
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"], text="Номер уже брошен")
            return
        if self.sponsors and await self.sponsors.missing(user["id"]):
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"], show_alert=True,
                          text=f"Сначала подпишись на спонсоров: открой @{bot} и нажми «Проверить подписку»")
            return
        self._inline_busy.add(imid)
        try:
            try:
                roll = self.game.spin(user, "inline", "WORLD" if kind == "world" else "RU")
            except NoEnergy:
                en = self.storage.energy(user["id"])
                await self.tg("answerCallbackQuery", callback_query_id=cq["id"], show_alert=True,
                              text=f"Энергия кончилась. +1 через {en['next_in'] // 60} мин {en['next_in'] % 60} с. Пополнить: /energy в @{bot}")
                return
            if len(self._inline_done) > 20000:
                self._inline_done.clear()
            self._inline_done.add(imid)
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
            markup = kb([[btn("⚡ Крутить свой", switch_inline_query_current_chat="", style="primary")],
                         [btn("✨ Открыть бота", url=app_link(self.config, self.tg))]])
            if self.config.public_url:
                await self.tg("editMessageMedia", inline_message_id=imid, reply_markup=markup,
                              media={"type": "photo", "media": f"{self.config.public_url}/card/{roll['id']}.png",
                                     "caption": roll_caption(self.game, roll), "parse_mode": "HTML"})
            else:
                await self.tg("editMessageText", inline_message_id=imid, parse_mode="HTML",
                              text=roll_caption(self.game, roll), reply_markup=markup)
        finally:
            self._inline_busy.discard(imid)

