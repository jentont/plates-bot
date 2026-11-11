"""Премиум-эмодзи и цветные кнопки — прослойка в клиенте Bot API.

Работает как в «Итогах года 2026»:

* обычный эмодзи в HTML-тексте (text, caption, инлайн-результаты) превращается
  в `<tg-emoji emoji-id="…">` из подключённого пака, например tgiosicons;
* эмодзи в начале подписи кнопки уезжает в icon_custom_emoji_id — иконку
  перед текстом. У кнопок самих инлайн-результатов Telegram иконки молча
  выбрасывает, поэтому там эмодзи остаётся в подписи;
* если Telegram отказывает (премиум-эмодзи или цвет кнопок недоступны боту),
  запрос уходит заново без украшений, а украшение выключается до перезапуска.
  Сломаться из-за украшения бот не должен.

Паки задаются ссылками t.me/addemoji/ИМЯ в админке и применяются сразу.
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Any

log = logging.getLogger("emoji")

#: Эмодзи бота, которых нет в паке → похожий, который там есть (подобрано под tgiosicons).
ALIAS: dict[str, str] = {
    "🦆": "🌟", "🏆": "👑", "👇": "⬇️", "🔥": "⚡", "😱": "😨", "📨": "📤", "📩": "📥",
    "📱": "📞", "🔑": "🔓", "🕵️": "👁", "😎": "👓", "🚀": "⚡", "🟢": "✅", "⏳": "⌛",
    "⏸": "💤", "⚠️": "❗", "✖️": "❌", "👀": "👁", "💀": "😨", "😂": "😝", "😢": "🙁",
    "🙈": "🫥", "❄️": "✨", "🙏": "👏", "☔": "💧", "😭": "🙁", "😈": "😡",
    "🎲": "⚡", "🚗": "⚡", "💎": "🌟", "💰": "🌟", "🏁": "✅", "🔄": "⌛", "▶️": "✅",
    "⬅️": "⬇️", "🗑": "❌", "📢": "📤", "📊": "👁", "📈": "👁", "⚙️": "👁", "🎯": "✅",
}
#: Эмодзи, которые бот использует: по ним админка показывает, что покрыто паком.
USED = ("✨", "⚡", "⭐", "🌟", "👑", "📤", "✅", "❌", "⬅️", "➕", "🎁", "🔒", "📢", "📊",
        "🗑", "🔄", "🎯", "💰", "⚙️", "👥", "📨", "🚀", "❗", "⌛", "💤")

ICONS: dict[str, str] = {}        # обычный эмодзи → custom_emoji_id
_aliased: set[str] = set()
_pattern: re.Pattern | None = None
_allowed = True                   # Telegram пускает премиум-эмодзи
_styles = True                    # Telegram принимает цвет кнопок
_status = "пак ещё не читали"
packs: list[str] = []

TAG = '<tg-emoji emoji-id="{id}">{emoji}</tg-emoji>'
UNTAG = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', re.S)
VS = "️"


def _forms(plain: str) -> set[str]:
    base = plain.replace(VS, "")
    return {plain, base, base + VS} if len(base) == 1 else {plain, base}


def on() -> bool:
    return _allowed and bool(ICONS)


def status() -> str:
    state = "включены" if on() else ("выключены: Telegram не пускает их у этого бота" if not _allowed else "выключены")
    return f"{_status}\nПремиум-эмодзи: {state}\nЦветные кнопки: {'включены' if _styles else 'выключены Telegram'}"


def covered() -> tuple[list[str], list[str]]:
    have = [e for e in USED if any(f in ICONS for f in _forms(e))]
    return have, [e for e in USED if e not in have]


async def load(tg: Any, names: list[str]) -> int:
    """Прочитать паки у Telegram. Первый в списке главнее. Вернёт, сколько эмодзи покрыто."""
    global _pattern, _status
    found: dict[str, str] = {}
    read = []
    for name in names:
        try:
            got = await tg.raw("getStickerSet", name=name)
        except Exception as error:  # noqa: BLE001
            log.info("пак «%s» не прочитать: %s", name, error)
            continue
        read.append(f"{name} ({len(got.get('stickers') or [])} шт.)")
        for one in got.get("stickers") or []:
            if one.get("custom_emoji_id") and one.get("emoji"):
                for form in _forms(one["emoji"]):
                    found.setdefault(form, one["custom_emoji_id"])
    _aliased.clear()
    for src, dst in ALIAS.items():
        target = next((found[f] for f in _forms(dst) if f in found), None)
        if target and not any(f in found for f in _forms(src)):
            for form in _forms(src):
                found[form] = target
                _aliased.add(form)
    if found or not names:
        ICONS.clear()
        ICONS.update(found)
        packs[:] = names
    _pattern = None
    _status = ("Паки: " + ", ".join(read)) if read else "Паки не прочитались"
    log.info(_status)
    return len(found)


def _regex() -> re.Pattern | None:
    global _pattern
    if _pattern is None and ICONS:
        _pattern = re.compile("|".join(re.escape(k) for k in sorted(ICONS, key=len, reverse=True)))
    return _pattern


def dress(text: str) -> str:
    if not on() or "<tg-emoji" in text:
        return text
    rx = _regex()
    return rx.sub(lambda m: TAG.format(id=ICONS[m.group(0)], emoji=m.group(0)), text) if rx else text


def strip(text: str) -> str:
    return UNTAG.sub(r"\1", text)


# ------------------------------------------------------------ обход запроса

def _texts(method: str, params: dict) -> list[tuple[dict, str]]:
    """Пары (контейнер, поле) с HTML-текстом: сам запрос, media, инлайн-результаты."""
    out: list[tuple[dict, str]] = []

    def take(holder: dict, field: str, mode_holder: dict | None = None) -> None:
        if isinstance(holder.get(field), str) and (mode_holder or holder).get("parse_mode") == "HTML":
            out.append((holder, field))

    take(params, "text")
    take(params, "caption")
    media = params.get("media")
    for one in media if isinstance(media, list) else [media] if isinstance(media, dict) else []:
        take(one, "caption")
    for res in params.get("results") or []:
        if isinstance(res, dict):
            take(res, "caption")
            imc = res.get("input_message_content")
            if isinstance(imc, dict):
                take(imc, "message_text")
    return out


def _buttons(method: str, params: dict, everywhere: bool = False) -> list[dict]:
    markups = [params.get("reply_markup")]
    if everywhere:     # для снятия цвета смотрим и клавиатуры инлайн-результатов
        markups += [r.get("reply_markup") for r in params.get("results") or [] if isinstance(r, dict)]
    out = []
    for markup in markups:
        if isinstance(markup, dict):
            out += [b for row in markup.get("inline_keyboard") or [] for b in row if isinstance(b, dict)]
    return out


def dress_request(method: str, params: dict) -> dict:
    """Копия параметров с премиум-эмодзи и иконками кнопок."""
    if not on() and _styles:
        return params
    params = copy.deepcopy(params)
    if on():
        for holder, field in _texts(method, params):
            holder[field] = dress(holder[field])
        if method != "answerInlineQuery":
            keys = sorted(ICONS, key=len, reverse=True)
            for b in _buttons(method, params):
                text = b.get("text")
                if not isinstance(text, str) or b.get("icon_custom_emoji_id"):
                    continue
                for plain in keys:
                    if text.startswith(plain) and text[len(plain):].strip():
                        b["text"] = text[len(plain):].lstrip()
                        b["icon_custom_emoji_id"] = ICONS[plain]
                        break
    if not _styles:
        for b in _buttons(method, params, everywhere=True):
            b.pop("style", None)
    return params


def undress_request(method: str, params: dict, error_text: str) -> dict | None:
    """Снять то, на что ругается Telegram. None — ругань не про украшения."""
    global _allowed, _styles
    text = error_text.lower()
    if "style" in text:
        if not _styles:
            return None
        _styles = False
        log.warning("Telegram не принимает цвет кнопок (%s) — выключаю", error_text)
        params = copy.deepcopy(params)
        for b in _buttons(method, params, everywhere=True):
            b.pop("style", None)
        return params
    if not any(k in text for k in ("custom emoji", "custom_emoji", "emoji_id", "tg-emoji", "document_invalid")):
        return None
    if not _allowed:
        return None
    _allowed = False
    log.warning("Telegram не пускает премиум-эмодзи (%s) — выключаю до перезапуска", error_text)
    params = copy.deepcopy(params)
    # Обратно в подпись — самую короткую форму эмодзи (без невидимого символа-варианта)
    back: dict[str, str] = {}
    for k in sorted(ICONS, key=len, reverse=True):
        if k not in _aliased:
            back[ICONS[k]] = k
    for holder, field in _texts(method, params):
        holder[field] = strip(holder[field])
    for b in _buttons(method, params):
        icon_id = b.pop("icon_custom_emoji_id", None)
        if icon_id:
            b["text"] = f"{back.get(icon_id, '')} {b.get('text', '')}".strip()
    return params
