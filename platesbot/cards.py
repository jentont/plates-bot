"""Склад картинок: превращает нарисованную карточку в file_id — как в mogbattle.

Инлайн-сообщения не умеют загружать файл: им нужна ссылка или file_id уже
загруженного фото. Ссылка заставляет Telegram скачивать картинку с нашего
сервера — это медленно и ломается, если сервер недоступен снаружи. Поэтому
бот отправляет карточку в чат-склад (приватный канал или группа, где бот
админ) и дальше использует её file_id.

Склад задаётся в админке или переменной STORAGE_CHAT. Без склада всё
работает как раньше — по ссылке на PUBLIC_URL.
"""
from __future__ import annotations

import logging

from .render import render_card, render_cover, in_thread
from .tg import TelegramError

log = logging.getLogger("cards")


def variants(raw: int) -> list[int]:
    """Боты-подсказчики показывают id канала без «-100» — пробуем оба варианта."""
    out = [raw]
    if raw < 0 and not str(raw).startswith("-100"):
        out.append(int(f"-100{abs(raw)}"))
    elif raw > 0:
        out += [-raw, int(f"-100{raw}")]
    return out


class CardStore:
    def __init__(self, tg, storage, game, config):
        self.tg, self.storage, self.game, self.config = tg, storage, game, config
        self._ids: dict[int, str] = {}         # roll_id → file_id карточки

    def chat_id(self) -> int | None:
        raw = self.storage.get_setting("storage_chat") or self.config.storage_chat
        try:
            return int(raw) if raw else None
        except ValueError:
            return None

    async def upload(self, png: bytes, caption: str = "") -> str | None:
        """Положить картинку на склад, вернуть file_id. None — склада нет или он не отвечает."""
        chat = self.chat_id()
        if not chat or self.tg is None:
            return None
        try:
            sent = await self.tg.raw("sendPhoto", files={"photo": ("card.png", png)}, chat_id=chat,
                                     caption=caption[:200], disable_notification=True)
            return sent["photo"][-1]["file_id"]
        except (TelegramError, KeyError, IndexError) as e:
            log.warning("склад %s не принял картинку: %s", chat, e)
            return None

    async def card_id(self, roll: dict, user_name: str = "Игрок") -> str | None:
        if roll["id"] in self._ids:
            return self._ids[roll["id"]]
        plate, ev = self.game.roll_objects(roll)
        from core.cars import BY_ID
        png = await in_thread(render_card, plate, ev, "Номер выпал", user_name,
                              self.tg.me.get("username", "bot"), self.game.country_name(plate.country), "",
                              BY_ID.get(self.storage.car_of(roll["user_id"]) or ""))
        file_id = await self.upload(png, f"#{roll['id']} {plate.text}")
        if file_id:
            if len(self._ids) > 5000:
                self._ids.clear()
            self._ids[roll["id"]] = file_id
        return file_id

    def remember(self, roll_id: int, file_id: str) -> None:
        """Карточка уже ушла пользователю — её file_id тоже годится для инлайна."""
        self._ids[roll_id] = file_id

    async def cover_id(self, kind: str) -> str | None:
        key = f"cover_file_{kind}"
        cached = self.storage.get_setting(key)
        if cached:
            return cached
        title = {"ru": "Бросок российского номера", "world": "Бросок номера мира"}.get(kind, "Бросок номера")
        png = await in_thread(render_cover, self.tg.me.get("username", "bot"), title)
        file_id = await self.upload(png, f"cover {kind}")
        if file_id:
            self.storage.set_setting(key, file_id)
        return file_id

    async def set_chat(self, raw: int) -> tuple[int | None, str]:
        """Проверить склад отправкой пробной картинки. Вернёт рабочий id и пояснение."""
        from PIL import Image, ImageDraw
        import io
        img = Image.new("RGB", (320, 120), (14, 15, 17))
        ImageDraw.Draw(img).text((16, 52), "Nomera storage probe", fill=(220, 220, 220))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        last = ""
        for chat in variants(raw):
            try:
                sent = await self.tg.raw("sendPhoto", files={"photo": ("probe.png", buf.getvalue())}, chat_id=chat,
                                         caption="Склад картинок подключён", disable_notification=True)
                self.storage.set_setting("storage_chat", str(chat))
                for kind in ("ru", "world"):            # обложки перезальём уже в новый склад
                    self.storage.set_setting(f"cover_file_{kind}", "")
                self._ids.clear()
                title = (sent.get("chat") or {}).get("title") or str(chat)
                return chat, title
            except TelegramError as e:
                last = e.description
        return None, last or "чат не найден"
