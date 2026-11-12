"""Обработчики апдейтов Telegram: команды, кнопки, inline-режим, Stars."""
from __future__ import annotations

import logging
from pathlib import Path

from core.cars import BY_ID, CARS, fmt_money
from core.rarity import format_price

from .config import Config
from .game import Game, NoEnergy
from .render import render_card, in_thread
from .tg import Telegram, TelegramError, btn, esc, kb

log = logging.getLogger("handlers")


BRAND = Path(__file__).resolve().parent.parent / "assets" / "brand"
BANNER = BRAND / "banner_1280.png"
SPIN_ANIM = BRAND / "spin.mp4"


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


def sell_buttons(config: Config, roll: dict, short: bool = False) -> list[dict]:
    """Кнопки продажи: за прокруты (если бот выкупает) и за деньги (всегда, пока номер не продан)."""
    out = []
    price, money = config.sell_price(roll), config.money_price(roll)
    if price:
        out.append(btn(f"⚡ За {price} прокрутов" if not short else f"⚡ {price}", f"sell:{roll['id']}"))
    if money:
        out.append(btn(f"💰 За {fmt_money(money)}" if not short else f"💰 {fmt_money(money)}", f"sellm:{roll['id']}"))
    return out


def roll_keyboard(config: Config, tg: Telegram, roll: dict) -> dict:
    rows = []
    if not roll.get("sold"):
        if not roll["saved"]:
            rows.append([btn("⭐ Сохранить в гараж", f"save:{roll['id']}", style="primary")])
        sb = sell_buttons(config, roll)
        if sb:
            rows.append(sb)
    rows.append([btn("⚡ Крутить ещё", "roll"), btn("📤 Поделиться", switch_inline_query=f"{roll['id']}")])
    ab = app_button(config, tg)
    if ab:
        rows.append([ab])
    return kb(rows)


async def send_roll_card(tg: Telegram, game: Game, config: Config, user: dict, roll: dict, chat_id: int | None = None) -> dict:
    plate, ev = game.roll_objects(roll)
    png = await in_thread(render_card, plate, ev, "Номер выпал", user.get("first_name") or "Игрок",
                          tg.me.get("username", "bot"), game.country_name(plate.country), "",
                          BY_ID.get(game.storage.car_of(user["id"]) or ""))
    return await tg("sendPhoto", files={"photo": ("card.png", png)}, chat_id=chat_id or user["id"],
                    caption=roll_caption(game, roll), parse_mode="HTML", reply_markup=roll_keyboard(config, tg, roll))


class Handlers:
    def __init__(self, tg: Telegram, game: Game, config: Config, sponsors=None, admin=None):
        self.tg, self.game, self.config = tg, game, config
        self.sponsors, self.admin = sponsors, admin
        self._inline_busy: set[str] = set()   # инлайн-сообщения, где бросок уже идёт (двойное нажатие)
        self._inline_done: set[str] = set()   # уже брошенные: запоздалое второе нажатие не перебрасывает номер
        self.storage = game.storage
        from .cards import CardStore
        self.cards = CardStore(tg, self.storage, game, config)
        from .groups import Groups
        self.groups = Groups(self)

    # ------------------------------------------------------------ dispatch

    async def handle(self, upd: dict) -> None:
        try:
            if "message" in upd:
                if upd["message"]["chat"]["type"] in ("group", "supergroup"):
                    await self.groups.on_message(upd["message"])
                    return
                if self.admin and await self.admin.on_message(upd["message"]):
                    return
                await self.on_message(upd["message"])
            elif "my_chat_member" in upd:
                await self.groups.on_my_chat_member(upd["my_chat_member"])
            elif "callback_query" in upd:
                if self.admin and await self.admin.on_callback(upd["callback_query"]):
                    return
                if await self.groups.on_callback(upd["callback_query"]):
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
        if cmd == "/start" and text.split()[-1] == "energy":
            await self.cmd_energy(user)
        elif cmd == "/start":
            await self.cmd_start(user)
        elif cmd in ("/roll", "/spin"):
            await self.do_roll(user, "chat")
        elif cmd == "/garage":
            await self.cmd_garage(user)
        elif cmd == "/top":
            await self.cmd_top(user)
        elif cmd == "/energy":
            await self.cmd_energy(user)
        elif cmd in ("/cars", "/salon", "/car"):
            await self.cmd_cars(user)
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
        rows.append([btn("🚀 Автосалон", "cars"), btn("📤 В любой чат", switch_inline_query="")])
        if self.admin and self.admin.is_admin(user["id"]):
            rows.append([btn("⚙️ Админка", "a:main")])
        return kb(rows)

    def menu_text(self, user: dict) -> str:
        return (f"✨ Привет, <b>{esc(user.get('first_name') or 'водитель')}</b>.\n\n"
                "Крути номера — российские и со всего мира. За каждый бросок получаешь номер и его оценку: "
                "редкость, очки, цена на рынке. Лучшие сохраняй в гараж.\n\n"
                f"⚡ Энергия: {self.config.energy_max} бросков, +1 каждые {regen_text(self.config.energy_regen_sec)}. "
                "Докупить: /energy\n"
                "💰 Номера продаются за прокруты или за деньги, на деньги покупаются машины: /cars\n"
                "🌟 Напиши свой номер, например <code>А777АА 777</code>, — оценю.")

    async def _send_media(self, kind: str, file_id: str, chat_id: int, caption: str, markup: dict) -> bool:
        method, field = ("sendAnimation", "animation") if kind == "anim" else ("sendPhoto", "photo")
        try:
            await self.tg(method, chat_id=chat_id, caption=caption, parse_mode="HTML", reply_markup=markup,
                          **{field: file_id})
            return True
        except TelegramError as e:
            log.warning("баннер %s не ушёл: %s", kind, e)
            return False

    async def send_banner(self, chat_id: int, caption: str, markup: dict) -> None:
        """Главное меню с баннером: свой из админки (фото или анимация), иначе анимация прокрутки
        А777АА 777, иначе картинка. file_id кэшируется после первой загрузки."""
        custom = self.storage.get_setting("menu_banner")
        if custom:
            kind, _, file_id = custom.partition(":") if custom.startswith(("anim:", "photo:")) else ("photo", "", custom)
            if await self._send_media(kind, file_id, chat_id, caption, markup):
                return
        cached = self.storage.get_setting("menu_anim_default")
        if cached and await self._send_media("anim", cached, chat_id, caption, markup):
            return
        if SPIN_ANIM.exists():
            try:
                sent = await self.tg("sendAnimation", files={"animation": ("spin.mp4", SPIN_ANIM.read_bytes())},
                                     chat_id=chat_id, caption=caption, parse_mode="HTML", reply_markup=markup)
                media = sent.get("animation") or sent.get("document") or {}
                if media.get("file_id"):
                    self.storage.set_setting("menu_anim_default", media["file_id"])
                return
            except TelegramError as e:
                log.warning("анимация меню не ушла: %s", e)
        cached = self.storage.get_setting("menu_banner_default")
        if cached and await self._send_media("photo", cached, chat_id, caption, markup):
            return
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
        await self.tg("sendMessage", chat_id=user["id"], parse_mode="HTML", text=self.garage_text(garage, stats),
                      reply_markup=self.garage_keyboard(garage))

    def garage_text(self, garage: list[dict], stats: dict) -> str:
        if not garage:
            return "⭐ Гараж пуст. Брось номер и сохрани его."
        lines = []
        for r in garage:
            plate, ev = self.game.roll_objects(r)
            lines.append(f"<b>{esc(plate.text)}</b> · {esc(ev.tier_name)} · {esc(format_price(ev, plate.country))}"
                         + (" · навсегда" if r["forever"] else ""))
        return (f"⭐ <b>Гараж</b> {len(garage)}/{stats['slots']}\n\n" + "\n".join(lines)
                + "\n\n🗑 — убрать номер, ⚡ — продать за прокруты, 💰 — продать за деньги. Машины: /cars")

    def garage_keyboard(self, garage: list[dict], confirm: int | None = None) -> dict | None:
        """По строке на номер: удалить и, если бот его выкупает, продать. confirm — номер, который ждёт «Да»."""
        rows = []
        for r in garage[:12]:
            if r["id"] == confirm:
                rows.append([btn(f"🗑 Удалить {r['plate']['text']}?", "noop"),
                             btn("✅ Да", f"del!:{r['id']}", style="danger"), btn("❌ Нет", "del0")])
                continue
            row = [btn(f"🗑 {r['plate']['text']}", f"del:{r['id']}")]
            price, money = self.config.sell_price(r), self.config.money_price(r)
            if price:
                row.append(btn(f"⚡ {price}", f"sell:{r['id']}:g"))
            if money:
                row.append(btn(f"💰 {fmt_money(money)}", f"sellm:{r['id']}:g"))
            rows.append(row)
        return kb(rows) if rows else None

    async def on_garage_delete(self, cq: dict, data: str) -> None:
        user, msg = cq["from"], cq.get("message") or {}
        action, _, raw = data.partition(":")
        if action == "del!":
            roll = self.storage.drop_from_garage(int(raw), user["id"]) if raw.isdigit() else None
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"],
                          text=f"Удалил {roll['plate']['text']} из гаража" if roll else "Номера уже нет в гараже")
            confirm = None
        else:
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
            confirm = int(raw) if action == "del" and raw.isdigit() else None
        if not msg:
            return
        garage = self.storage.garage(user["id"])
        stats = self.storage.stats(user["id"])
        try:
            if action == "del!":     # список номеров в тексте тоже поменялся
                await self.tg("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                              parse_mode="HTML", text=self.garage_text(garage, stats),
                              reply_markup=self.garage_keyboard(garage))
            else:
                await self.tg("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                              reply_markup=self.garage_keyboard(garage, confirm))
        except TelegramError:
            pass

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
        sent = await send_roll_card(self.tg, self.game, self.config, user, roll)
        self.remember_card(roll, sent)

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
        if data.startswith(("sell:", "sellm:")):
            await self.on_sell(cq, data)
            return
        if data.startswith("car:"):
            await self.on_car(cq, data)
            return
        if data.startswith(("del:", "del!:")) or data == "del0":
            await self.on_garage_delete(cq, data)
            return
        if data == "cars":
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
            await self.cmd_cars(user)
            return
        if data == "noop":
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
            return
        if data.startswith("save:"):
            msg = cq.get("message") or {}
            in_group = (msg.get("chat") or {}).get("type") in ("group", "supergroup")
            status, roll = self.storage.save_roll(int(data[5:]), user["id"])
            if status == "missing" and in_group:
                await self.tg("answerCallbackQuery", callback_query_id=cq["id"], show_alert=True,
                              text="Это чужой номер. Напиши .ролл, чтобы выбить свой")
                return
            if status == "sold":
                await self.tg("answerCallbackQuery", callback_query_id=cq["id"], text="Этот номер уже продан")
                return
            if status == "ok":
                await self.tg("answerCallbackQuery", callback_query_id=cq["id"], text="Сохранено в гараж")
                if msg:
                    markup = self.groups.card_keyboard(roll) if in_group else roll_keyboard(self.config, self.tg, roll)
                    try:
                        await self.tg("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                                      reply_markup=markup)
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

    # ------------------------------------------------------------ автосалон

    def cars_screen(self, user_id: int) -> tuple[str, dict]:
        w = self.storage.wallet(user_id)
        lines = ["🚀 <b>Автосалон</b>", f"💰 На счету: <b>{fmt_money(w['money'])}</b>", ""]
        rows = []
        for c in CARS:
            if c["id"] == w["car"]:
                lines.append(f"✅ <b>{esc(c['name'])}</b> — за рулём")
            elif c["id"] in w["owned"]:
                lines.append(f"⭐ <b>{esc(c['name'])}</b> — в гараже")
                rows.append([btn(f"🔑 Сесть в {c['name']}", f"car:use:{c['id']}")])
            else:
                lines.append(f"🔒 {esc(c['name'])} — {fmt_money(c['price'])}")
                if w["money"] >= c["price"]:
                    rows.append([btn(f"💰 Купить {c['name']}", f"car:buy:{c['id']}", style="success")])
        lines += ["", "Продавай номера за деньги и покупай машины. Машина, в которой ты за рулём, появляется на карточках твоих номеров."]
        return "\n".join(lines), kb(rows)

    async def cmd_cars(self, user: dict) -> None:
        text, markup = self.cars_screen(user["id"])
        await self.tg("sendMessage", chat_id=user["id"], parse_mode="HTML", text=text, reply_markup=markup)

    async def on_car(self, cq: dict, data: str) -> None:
        user, msg = cq["from"], cq.get("message") or {}
        _, action, car_id = (data.split(":") + ["", ""])[:3]
        car = BY_ID.get(car_id)
        if not car:
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
            return
        if action == "buy":
            status = self.storage.buy_car(user["id"], car_id, car["price"])
            note = {"ok": f"Поздравляю, {car['name']} твоя", "owned": "Эта машина у тебя уже есть",
                    "poor": f"Не хватает денег: нужно {fmt_money(car['price'])}"}[status]
        else:
            note = f"Ты за рулём {car['name']}" if self.storage.use_car(user["id"], car_id) else "Сначала купи эту машину"
        await self.tg("answerCallbackQuery", callback_query_id=cq["id"], text=note)
        if msg:
            text, markup = self.cars_screen(user["id"])
            try:
                await self.tg("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                              parse_mode="HTML", text=text, reply_markup=markup)
            except TelegramError:
                pass

    def remember_card(self, roll: dict, sent) -> None:
        try:
            self.cards.remember(roll["id"], sent["photo"][-1]["file_id"])
        except (KeyError, IndexError, TypeError):
            pass

    async def on_sell(self, cq: dict, data: str) -> None:
        """Продажа номера боту за прокруты: из карточки (личка и группа) и из гаража."""
        user, msg = cq["from"], cq.get("message") or {}
        parts = data.split(":")
        try:
            roll_id = int(parts[1])
        except (IndexError, ValueError):
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"])
            return
        in_group = (msg.get("chat") or {}).get("type") in ("group", "supergroup")
        money = parts[0] == "sellm"
        status, roll, gain = self.storage.sell_roll(roll_id, user["id"],
                                                    self.config.money_price if money else self.config.sell_price, money)
        texts = {
            "missing": "Это чужой номер. Напиши .ролл, чтобы выбить свой" if in_group else "Номер не найден",
            "sold": "Этот номер уже продан",
            "expired": "Номер сгорел: несохранённые номера живут 24 часа",
            "cheap": "Обычные номера бот не выкупает",
        }
        if status != "ok":
            await self.tg("answerCallbackQuery", callback_query_id=cq["id"], text=texts[status], show_alert=status == "missing")
            return
        if money:
            done = f"Продано за {fmt_money(gain)}. На счету: {fmt_money(self.storage.wallet(user['id'])['money'])}"
        else:
            done = f"Продано за {gain} прокрутов. Энергия: {self.storage.energy(user['id'])['current']}"
        await self.tg("answerCallbackQuery", callback_query_id=cq["id"], text=done)
        if not msg:
            return
        chat_id, mid = msg["chat"]["id"], msg["message_id"]
        try:
            if len(parts) > 2 and parts[2] == "g":          # из гаража: обновить список
                garage = self.storage.garage(user["id"])
                await self.tg("editMessageText", chat_id=chat_id, message_id=mid, parse_mode="HTML",
                              text=self.garage_text(garage, self.storage.stats(user["id"])),
                              reply_markup=self.garage_keyboard(garage))
            elif in_group:
                await self.tg("editMessageReplyMarkup", chat_id=chat_id, message_id=mid,
                              reply_markup=self.groups.card_keyboard(roll))
            else:
                await self.tg("editMessageReplyMarkup", chat_id=chat_id, message_id=mid,
                              reply_markup=roll_keyboard(self.config, self.tg, roll))
        except TelegramError:
            pass
        if in_group and money and gain >= 1_000_000:
            from .groups import mention
            try:
                await self.tg("sendMessage", chat_id=chat_id, parse_mode="HTML",
                              reply_parameters={"message_id": mid, "allow_sending_without_reply": True},
                              text=f"💰 {mention(user)} продал <b>{esc(roll['plate']['text'])}</b> за {fmt_money(gain)}")
            except TelegramError:
                pass
        if in_group and not money and gain >= 10:         # громкие продажи видно всему чату
            from .groups import mention
            try:
                await self.tg("sendMessage", chat_id=chat_id, parse_mode="HTML",
                              reply_parameters={"message_id": mid, "allow_sending_without_reply": True},
                              text=f"💰 {mention(user)} продал <b>{esc(roll['plate']['text'])}</b> за {gain} прокрутов ⚡")
            except TelegramError:
                pass

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
            cover = await self.cards.cover_id(kind)
            if cover:
                results.append({
                    "type": "photo", "id": f"roll_{kind}", "photo_file_id": cover,
                    "title": title, "description": desc, "caption": caption, "parse_mode": "HTML", "reply_markup": markup,
                })
            elif self.config.public_url:
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
                card = await self.cards.card_id(roll, user.get("first_name") or "Игрок")
                if card:
                    results.insert(0, {
                        "type": "photo", "id": f"share_{roll['id']}", "photo_file_id": card,
                        "title": f"Мой номер {roll['plate']['text']}",
                        "caption": roll_caption(self.game, roll), "parse_mode": "HTML",
                        "reply_markup": kb([[btn("⚡ Крутить свой", url=app_link(self.config, self.tg))]]),
                    })
                elif self.config.public_url:
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
            card = await self.cards.card_id(roll, user.get("first_name") or "Игрок")
            media = card or (f"{self.config.public_url}/card/{roll['id']}.png" if self.config.public_url else None)
            try:
                if not media:
                    raise TelegramError("editMessageMedia", 0, "нет ни склада, ни PUBLIC_URL")
                await self.tg("editMessageMedia", inline_message_id=imid, reply_markup=markup,
                              media={"type": "photo", "media": media,
                                     "caption": roll_caption(self.game, roll), "parse_mode": "HTML"})
            except TelegramError as e:     # заготовка была текстом или картинка не скачалась — хотя бы текст
                log.info("инлайн-карточка картинкой не встала: %s", e)
                await self.tg("editMessageText", inline_message_id=imid, parse_mode="HTML",
                              text=roll_caption(self.game, roll), reply_markup=markup)
        finally:
            self._inline_busy.discard(imid)

