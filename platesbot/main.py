"""Точка входа: запускает HTTP-сервер мини-апы и long polling бота в одном процессе.

    python run.py            # бот + сервер
    python run.py --dev          # сервер без токена: мини-апа открывается в браузере
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

ALLOWED_UPDATES = ["message", "callback_query", "inline_query", "pre_checkout_query", "my_chat_member"]


async def setup_bot(tg: Telegram) -> None:
    tg.me = await tg("getMe")
    log.info("bot: @%s", tg.me.get("username"))
    await tg("setMyCommands", commands=[
        {"command": "roll", "description": "Бросить номер"},
        {"command": "energy", "description": "Энергия и покупка за Stars"},
        {"command": "garage", "description": "Мой гараж"},
        {"command": "top", "description": "Лучшие игроки"},
        {"command": "help", "description": "Как играть"},
    ])
    try:                                   # в группах — только бросок
        await tg("setMyCommands", scope={"type": "all_group_chats"}, commands=[
            {"command": "roll", "description": "Бросить номер (или .ролл)"},
        ])
    except TelegramError as e:
        log.warning("команды для групп: %s", e)
    for admin_id in config.admin_ids:      # админам — ещё и /admin в меню команд
        try:
            await tg("setMyCommands", scope={"type": "chat", "chat_id": admin_id}, commands=[
                {"command": "admin", "description": "Админ-панель"},
                {"command": "roll", "description": "Бросить номер"},
                {"command": "energy", "description": "Энергия и покупка за Stars"},
                {"command": "garage", "description": "Мой гараж"},
                {"command": "top", "description": "Лучшие игроки"},
            ])
        except TelegramError as e:
            log.warning("команды админа %s: %s", admin_id, e)
    from . import texts
    try:
        for lang, short, full in (("", texts.SHORT_DESCRIPTION, texts.DESCRIPTION),
                                  ("ru", texts.SHORT_DESCRIPTION, texts.DESCRIPTION),
                                  ("en", texts.SHORT_DESCRIPTION_EN, texts.DESCRIPTION_EN)):
            await tg("setMyShortDescription", short_description=short, language_code=lang or None)
            await tg("setMyDescription", description=full, language_code=lang or None)
    except TelegramError as e:
        log.warning("setMyDescription: %s", e)
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
        from .sponsors import Sponsors
        sponsors = Sponsors(tg, storage, config)
        app = create_app(config, game, feed, tg=tg, ai=ai, sponsors=sponsors)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, config.host, config.port)
        await site.start()
        log.info("web: http://%s:%d  (public: %s)", config.host, config.port, config.public_url or "не задан")

        tasks = [asyncio.create_task(feed.run())]
        if tg:
            from . import emoji
            from .admin import Admin
            from .handlers import Handlers
            await setup_bot(tg)
            admin = Admin(tg, storage, sponsors, config)
            # Премиум-эмодзи: паки из админки, иначе ICON_PACKS (по умолчанию tgiosicons)
            await emoji.load(tg, admin.packs())
            handlers = Handlers(tg, game, config, sponsors=sponsors, admin=admin)
            tasks.append(asyncio.create_task(sponsors.report_loop()))

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
