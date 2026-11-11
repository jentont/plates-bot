"""Точка входа: запускает HTTP-сервер мини-апы и long polling бота в одном процессе.

    python -m bot.main            # бот + сервер
    DEV_MODE=1 python -m bot.main # сервер без токена: мини-апа открывается в браузере
"""
from __future__ import annotations

import asyncio
import logging
import sys

import aiohttp
from aiohttp import web

from .api import Feed, create_app
from .config import config
from .game import Game
from .storage import Storage
from .tg import Telegram, TelegramError

log = logging.getLogger("main")

ALLOWED_UPDATES = ["message", "callback_query", "inline_query", "chosen_inline_result", "widget_query", "pre_checkout_query"]


async def setup_bot(tg: Telegram) -> None:
    tg.me = await tg("getMe")
    log.info("bot: @%s", tg.me.get("username"))
    await tg("setMyCommands", commands=[
        {"command": "roll", "description": "Бросить номер"},
        {"command": "energy", "description": "Энергия и покупка за Stars"},
        {"command": "garage", "description": "Мой гараж"},
        {"command": "top", "description": "Лучшие игроки"},
        {"command": "widget", "description": "Живой виджет в чате"},
        {"command": "help", "description": "Как играть"},
    ])
    if config.webapp_url:
        try:
            await tg("setChatMenuButton", menu_button={"type": "web_app", "text": "Крутить", "web_app": {"url": config.webapp_url}})
        except TelegramError as e:
            log.warning("setChatMenuButton: %s", e)


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    storage = Storage(config.db_path, config.energy_max, config.energy_regen_sec, config.garage_free_slots, config.roll_ttl_sec)
    storage.purge()
    game = Game(storage, config)
    feed = Feed(game, config.feed_interval)

    ai = None
    if config.ai_enabled:
        from .ai import AIValuer
        ai = AIValuer(config.anthropic_api_key, config.ai_model, storage)
        log.info("AI valuation: %s", config.ai_model)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=70)) as session:
        tg = Telegram(config.bot_token, session) if config.bot_token else None
        app = create_app(config, game, feed, tg=tg, ai=ai)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, config.host, config.port)
        await site.start()
        log.info("web: http://%s:%d  (public: %s)", config.host, config.port, config.public_url or "не задан")

        tasks = [asyncio.create_task(feed.run())]
        if tg:
            from .handlers import Handlers
            await setup_bot(tg)
            handlers = Handlers(tg, game, config)

            async def polling():
                async for upd in tg.poll(ALLOWED_UPDATES):
                    asyncio.create_task(handlers.handle(upd))

            tasks.append(asyncio.create_task(polling()))
        elif not config.dev_mode:
            log.error("BOT_TOKEN не задан. Для запуска только сервера поставь DEV_MODE=1.")
            sys.exit(1)
        else:
            log.info("DEV_MODE: бот выключен, мини-апа доступна без Telegram")
        try:
            await asyncio.gather(*tasks)
        finally:
            await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
