"""HTTP-сервер: раздаёт мини-апу, API для неё, картинки карточек и живую ленту (SSE)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from core.plates import COUNTRIES, Plate, country_list
from core.rarity import Evaluation

from .config import Config
from .game import Game, NoEnergy
from .render import render_card, render_cover
from .widget import widget_html

log = logging.getLogger("api")
WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"


# ------------------------------------------------------------ initData

def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict | None:
    """Проверка подписи initData мини-апы по алгоритму Telegram."""
    if not init_data:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        return None
    check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received):
        return None
    try:
        if time.time() - int(pairs.get("auth_date", "0")) > max_age:
            return None
        return json.loads(pairs["user"])
    except (ValueError, KeyError):
        return None


# ------------------------------------------------------------ лента

class Feed:
    """Каждую секунду генерирует номер мира и рассылает подписчикам (SSE)."""

    def __init__(self, game: Game, interval: float):
        self.game, self.interval = game, interval
        self.subs: set[asyncio.Queue] = set()
        self.last: list[dict] = []

    async def run(self):
        while True:
            plate, ev = self.game.random_world()
            item = {"plate": plate.to_dict(), "eval": ev.to_dict(), "t": time.time()}
            self.last = (self.last + [item])[-24:]
            dead = []
            for q in self.subs:
                try:
                    q.put_nowait(item)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self.subs.discard(q)
            await asyncio.sleep(self.interval)

    async def stream(self, request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache",
                                           "X-Accel-Buffering": "no"})
        await resp.prepare(request)
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        for item in self.last:
            q.put_nowait(item)
        self.subs.add(q)
        try:
            while True:
                item = await q.get()
                await resp.write(f"data: {json.dumps(item, ensure_ascii=False)}\n\n".encode())
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.subs.discard(q)
        return resp


# ------------------------------------------------------------ приложение

def create_app(config: Config, game: Game, feed: Feed, tg=None, ai=None) -> web.Application:
    app = web.Application(client_max_size=64 * 1024)
    storage = game.storage
    routes = web.RouteTableDef()

    def user_of(request: web.Request) -> dict:
        init = request.headers.get("X-Init-Data", "")
        user = validate_init_data(init, config.bot_token)
        if user is None:
            if config.dev_mode and not init:
                user = {"id": 1, "first_name": "Dev", "username": "dev"}
            else:
                raise web.HTTPUnauthorized(text=json.dumps({"error": "bad_init_data"}), content_type="application/json")
        storage.touch_user(user)
        return user

    def err(status: int, code: str, **extra):
        return web.json_response({"error": code, **extra}, status=status)

    def roll_payload(roll: dict) -> dict:
        return {k: roll[k] for k in ("id", "plate", "eval", "created", "expires", "saved", "forever")}

    @routes.get("/")
    async def index(request):
        return web.FileResponse(WEBAPP_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @routes.get("/api/bootstrap")
    async def bootstrap(request):
        user = user_of(request)
        uid = user["id"]
        last = storage.last_roll(uid)
        return web.json_response({
            "user": {"id": uid, "name": user.get("first_name", "")},
            "energy": storage.energy(uid),
            "settings": storage.settings(uid),
            "countries": country_list(),
            "garage": [roll_payload(r) for r in storage.garage(uid)],
            "stats": storage.stats(uid),
            "last": roll_payload(last) if last else None,
            "ai": bool(ai),
            "energy_packs": config.energy_packs,
        })

    @routes.get("/api/energy")
    async def energy(request):
        user = user_of(request)
        return web.json_response(storage.energy(user["id"]))

    @routes.post("/api/energy/buy")
    async def energy_buy(request):
        user = user_of(request)
        try:
            body = await request.json() if request.can_read_body else {}
        except ValueError:
            body = {}
        pack = config.energy_pack(body.get("pack")) if isinstance(body, dict) else None
        if not pack:
            return err(400, "Неизвестный набор энергии")
        if tg:
            try:
                url = await tg("createInvoiceLink", title=f"Энергия +{pack['amount']}",
                               description=f"{pack['amount']} бросков номера. Энергия сверх максимума не сгорает.",
                               payload=f"energy:{pack['id']}", currency="XTR",
                               prices=[{"label": f"Энергия +{pack['amount']}", "amount": pack["stars"]}])
            except Exception as e:  # noqa: BLE001
                log.warning("createInvoiceLink: %s", e)
                return err(502, "Не удалось создать счёт, попробуй позже")
            return web.json_response({"invoice_url": url})
        if config.dev_mode:
            # без бота оплатить нечем: в dev-режиме начисляем сразу, чтобы проверить интерфейс в браузере
            return web.json_response({"ok": True, "energy": storage.add_energy(user["id"], pack["amount"])})
        return err(503, "Покупка недоступна: бот не подключён")

    @routes.post("/api/spin")
    async def spin(request):
        user = user_of(request)
        body = await request.json() if request.can_read_body else {}
        try:
            roll = game.spin(user, "app", body.get("country"))
        except NoEnergy:
            return err(429, "no_energy", energy=storage.energy(user["id"]))
        payload = roll_payload(roll)
        payload["energy"] = storage.energy(user["id"])
        return web.json_response({"roll": payload})

    @routes.post("/api/save")
    async def save(request):
        user = user_of(request)
        body = await request.json()
        status, roll = storage.save_roll(int(body.get("roll_id", 0)), user["id"])
        if status == "missing":
            return err(404, "not_found")
        if status == "full":
            invoice_url = None
            if config.stars_forever and tg:
                try:
                    invoice_url = await tg("createInvoiceLink", title="Номер навсегда", description=f"Сохранить {roll['plate']['text']} в гараже без ограничений",
                                           payload=f"forever:{roll['id']}", currency="XTR",
                                           prices=[{"label": "Сохранить навсегда", "amount": config.stars_forever}])
                except Exception as e:  # noqa: BLE001
                    log.warning("createInvoiceLink: %s", e)
            return err(409, "garage_full", invoice_url=invoice_url, stars=config.stars_forever)
        garage = storage.garage(user["id"])
        return web.json_response({"ok": True, "roll": roll_payload(roll), "forever": roll["forever"],
                                  "garage": [roll_payload(r) for r in garage],
                                  "slots_left": max(0, storage.stats(user["id"])["slots"] - len(garage))})

    @routes.post("/api/settings")
    async def settings(request):
        user = user_of(request)
        body = await request.json()
        mode = body.get("mode") if body.get("mode") in ("ru", "world", "custom") else "ru"
        countries = [c for c in body.get("countries", []) if c in COUNTRIES][:len(COUNTRIES)]
        return web.json_response(storage.set_settings(user["id"], mode, countries))

    @routes.post("/api/estimate")
    async def estimate(request):
        user_of(request)
        body = await request.json()
        res = game.estimate(str(body.get("text", ""))[:16])
        if not res:
            return err(400, "Не похоже на российский номер. Формат: А777АА 777")
        plate, ev = res
        return web.json_response({"plate": plate.to_dict(), "eval": ev.to_dict()})

    @routes.post("/api/ai")
    async def ai_estimate(request):
        user = user_of(request)
        if not ai:
            return err(404, "ai_disabled")
        body = await request.json()
        roll = storage.get_roll(int(body.get("roll_id", 0)))
        if not roll or roll["user_id"] != user["id"]:
            return err(404, "not_found")
        plate, ev = game.roll_objects(roll)
        try:
            data = await ai.value(plate, ev, game.country_name(plate.country))
        except Exception as e:  # noqa: BLE001
            log.warning("ai: %s", e)
            return err(502, "Нейросеть не ответила, попробуй позже")
        return web.json_response(data)

    @routes.get("/api/top")
    async def top(request):
        return web.json_response(storage.top(10))

    @routes.post("/api/share")
    async def share(request):
        user = user_of(request)
        if not tg:
            return err(503, "Бот не подключён")
        body = await request.json()
        roll = storage.get_roll(int(body.get("roll_id", 0)))
        if not roll or roll["user_id"] != user["id"]:
            return err(404, "not_found")
        from .handlers import send_roll_card  # локальный импорт, чтобы не было цикла
        await send_roll_card(tg, game, config, user, roll)
        return web.json_response({"ok": True})

    @routes.get("/api/feed")
    async def feed_stream(request):
        return await feed.stream(request)

    @routes.get("/card/{roll_id:\\d+}.png")
    async def card(request):
        roll = storage.get_roll(int(request.match_info["roll_id"]))
        if not roll:
            raise web.HTTPNotFound()
        png = _card_png(roll["id"], json.dumps(roll["plate"], sort_keys=True), json.dumps(roll["eval"], sort_keys=True))
        return web.Response(body=png, content_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @lru_cache(maxsize=256)
    def _card_png(roll_id: int, plate_json: str, eval_json: str) -> bytes:
        roll = storage.get_roll(roll_id)
        user = storage.db.execute("SELECT first_name, username FROM users WHERE id=?", (roll["user_id"],)).fetchone()
        plate, ev = Plate(**json.loads(plate_json)), Evaluation(**json.loads(eval_json))
        name = (user["first_name"] or user["username"] or "Игрок") if user else "Игрок"
        return render_card(plate, ev, "Номер выпал", name, (tg.me.get("username") if tg else "") or "bot",
                           game.country_name(plate.country))

    @routes.get("/card/cover_{kind}.png")
    async def cover(request):
        kind = request.match_info["kind"]
        title = {"ru": "Бросок российского номера", "world": "Бросок номера мира"}.get(kind, "Бросок номера")
        return web.Response(body=_cover_png(title), content_type="image/png", headers={"Cache-Control": "public, max-age=86400"})

    @lru_cache(maxsize=4)
    def _cover_png(title: str) -> bytes:
        return render_cover((tg.me.get("username") if tg else "") or "bot", title)

    if config.dev_mode:
        @routes.get("/dev/widget")
        async def dev_widget(request):
            """Локальный предпросмотр виджета с заглушкой TelegramWidget."""
            from core.plates import generate
            from core.rarity import evaluate
            from .widget import chat_data
            plate = generate("RU")
            ev = evaluate(plate)
            cd = chat_data({"plate": plate.to_dict(), "eval": ev.to_dict()}, {"current": 7, "max": 10}, "Россия")
            mock = """<script>
            var TelegramWidget={chatData:%s,publicData:'{"a":"https://t.me"}',isPreview:false,
              request:function(d){return fetch('/dev/widget_roll').then(function(r){return r.text()}).then(function(t){return {result:t}})},
              onEvent:function(){},ready:function(){},openTelegramLink:function(u){window.open(u)},
              HapticFeedback:{impactOccurred:function(){}}};
            </script>""" % json.dumps(cd, ensure_ascii=False)
            page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                    "<body style='margin:0;background:#1f2a3a;padding:24px;display:flex;justify-content:center'>"
                    f"<div style='width:360px;height:{330}px'>{mock}{widget_html()}</div></body>")
            return web.Response(text=page, content_type="text/html")

        @routes.get("/dev/widget_roll")
        async def dev_widget_roll(request):
            from .widget import chat_data
            user = {"id": 1, "first_name": "Dev"}
            try:
                roll = game.spin(user, "widget")
            except NoEnergy:
                return web.Response(text=json.dumps({"err": "Энергия кончилась"}, ensure_ascii=False))
            return web.Response(text=chat_data(roll, storage.energy(1), game.country_name(roll["plate"]["country"])))

    app.add_routes(routes)
    app.router.add_static("/static/", WEBAPP_DIR, show_index=False)
    return app
