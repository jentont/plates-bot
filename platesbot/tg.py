"""Тонкий клиент Bot API поверх aiohttp.

Написан сам, без сторонних библиотек: так проще поддерживать свежие методы
Bot API. Любой метод вызывается как `await tg("methodName", param=value)`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

log = logging.getLogger("tg")


class TelegramError(Exception):
    def __init__(self, method: str, code: int, description: str):
        super().__init__(f"{method}: [{code}] {description}")
        self.method, self.code, self.description = method, code, description


class Telegram:
    def __init__(self, token: str, session: aiohttp.ClientSession):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.session = session
        self.me: dict = {}

    async def __call__(self, method: str, files: dict[str, tuple[str, bytes]] | None = None, **params: Any) -> Any:
        """Вызов с премиум-эмодзи и цветными кнопками; на отказе Telegram — без украшений."""
        from . import emoji
        params = {k: v for k, v in params.items() if v is not None}
        sent = emoji.dress_request(method, params)
        for _ in range(3):
            try:
                return await self.raw(method, files, **sent)
            except TelegramError as e:
                if e.code != 400:
                    raise
                fixed = emoji.undress_request(method, sent, e.description)
                if fixed is None:
                    raise
                sent = fixed
        return await self.raw(method, files, **sent)

    async def raw(self, method: str, files: dict[str, tuple[str, bytes]] | None = None, **params: Any) -> Any:
        """files: {"photo": ("card.png", b"...")} — отправляется multipart; остальное — JSON."""
        params = {k: v for k, v in params.items() if v is not None}
        if files:
            form = aiohttp.FormData()
            for k, v in params.items():
                form.add_field(k, v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
            for k, (name, data) in files.items():
                form.add_field(k, data, filename=name, content_type="application/octet-stream")
            resp = await self.session.post(self.base + method, data=form)
        else:
            resp = await self.session.post(self.base + method, json=params)
        async with resp:
            body = await resp.json(content_type=None)
        if not body.get("ok"):
            raise TelegramError(method, body.get("error_code", 0), body.get("description", "unknown"))
        return body["result"]

    async def poll(self, allowed_updates: list[str], timeout: int = 30):
        """Генератор апдейтов long polling."""
        offset = None
        await self.raw("deleteWebhook", drop_pending_updates=False)
        while True:
            try:
                updates = await self.raw("getUpdates", offset=offset, timeout=timeout, allowed_updates=allowed_updates)
            except (aiohttp.ClientError, asyncio.TimeoutError, TelegramError) as e:
                log.warning("getUpdates failed: %s", e)
                await asyncio.sleep(3)
                continue
            for upd in updates:
                offset = upd["update_id"] + 1
                yield upd


# ------------------------------------------------------------ helpers

def kb(rows: list[list[dict]]) -> dict:
    return {"inline_keyboard": rows}


def btn(text: str, callback_data: str | None = None, url: str | None = None, web_app: str | None = None,
        switch_inline_query: str | None = None, switch_inline_query_current_chat: str | None = None,
        style: str | None = None) -> dict:
    """style: "primary" — синяя, "success" — зелёная, "danger" — красная (Bot API 9.4)."""
    b: dict[str, Any] = {"text": text}
    if callback_data is not None:
        b["callback_data"] = callback_data
    if url:
        b["url"] = url
    if web_app:
        b["web_app"] = {"url": web_app}
    if switch_inline_query is not None:
        b["switch_inline_query"] = switch_inline_query
    if switch_inline_query_current_chat is not None:
        b["switch_inline_query_current_chat"] = switch_inline_query_current_chat
    if style:
        b["style"] = style
    return b


def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
