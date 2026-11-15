"""Самопроверка игровой логики без Telegram: python tools/selfcheck.py

Временная база, один игрок. Проверяет поэтапную цену, коллекцию, задания, достижения,
кейсы, улучшения и автопродажу, включая защиту от двойных наград и покупок в долг.
"""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.cars import plate_money  # noqa: E402
from core.plates import COUNTRIES, generate, parse_ru  # noqa: E402
from core.rarity import Evaluation, catalog, evaluate, reveal_len  # noqa: E402
from platesbot.progress import CASES, SLOT_LEVELS, Progress, slot_price  # noqa: E402
from platesbot.storage import Storage  # noqa: E402

fails = 0


def check(cond: bool, what: str) -> None:
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += 0 if cond else 1


def main() -> None:
    # --- оценка: шаги цены
    rng = random.Random(5)
    for code in COUNTRIES:
        for _ in range(200):
            p = generate(code, rng)
            ev = evaluate(p)
            prices = [s[0] for s in ev.steps]
            assert len(ev.steps) == reveal_len(p), (p.text, len(ev.steps))
            assert prices == sorted(prices), (p.text, prices)
            assert ev.steps[-1] == [ev.price_rub, ev.tier], p.text
    check(True, "шаги цены: длина = число символов, цена не падает, последний шаг = итог (все страны)")
    ev = evaluate(parse_ru("А777АА 777"))
    check(ev.steps[3][0] > 0 and ev.steps[2][0] == 0, "А777АА 777: цена появляется на третьей цифре")
    check(ev.tier == "mythic" and "c:jackpot" in ev.keys and ev.fact, "А777АА 777: мифический, джекпот в коллекции, есть справка")
    check(all(c["key"] in evaluate(parse_ru(c["example"])).keys for c in catalog()), "каждый пример каталога даёт свою редкость")
    old = {k: v for k, v in ev.to_dict().items() if k not in ("steps", "keys", "fact")}
    check(Evaluation(**old).steps == [], "старые броски без новых полей читаются")

    with tempfile.TemporaryDirectory() as tmp:
        st = Storage(Path(tmp) / "t.db", 30, 90, 5, 86400)
        uid = 1
        st.touch_user({"id": uid, "first_name": "Тест"})
        pr = Progress(st, random.Random(3))

        # --- броски наполняют коллекцию и задания
        for text in ["А777АА 777", "В559МР 77", "Р676НУ 96"] + ["К418ВТ 52"] * 17:
            st.consume_energy(uid)
            st.add_roll(uid, parse_ru(text), evaluate(parse_ru(text)), "app")
        coll = pr.collection(uid)
        check(coll["found"] >= 6 and coll["total"] == len(catalog()), f"коллекция: найдено {coll['found']} из {coll['total']}")
        tasks = {t["id"]: t for t in pr.tasks(uid)["items"]}
        check(tasks["spin20"]["done"] and tasks["rare"]["done"] and not tasks["spin100"]["done"], "задания: 20 прокрутов и редкий выполнены, 100 — нет")

        # --- награда только один раз
        money0 = st.wallet(uid)["money"]
        s1, r1 = pr.claim(uid, "task", "spin20")
        s2, _ = pr.claim(uid, "task", "spin20")
        check(s1 == "ok" and s2 == "claimed" and st.wallet(uid)["money"] == money0 + r1["amount"], "задание: награда выдаётся один раз")
        check(pr.claim(uid, "task", "spin100")[0] == "not_done", "невыполненное задание не забрать")
        en0 = st.energy(uid)["current"]
        pr.st.db.execute("UPDATE users SET spins=100 WHERE id=?", (uid,))
        check(pr.claim(uid, "ach", "spins100")[0] == "ok" and pr.claim(uid, "ach", "spins100")[0] == "claimed", "достижение: один раз")
        check(st.energy(uid)["current"] == en0, "достижения энергию не дают")

        # --- покупки в долг невозможны
        st.db.execute("UPDATE users SET money=0 WHERE id=?", (uid,))
        st.db.commit()
        check(pr.open_case(uid, "silver")[0] == "poor", "кейс без денег не открыть")
        check(pr.buy_upgrade(uid, "auto") == "poor", "улучшение без денег не купить")
        check(st.wallet(uid)["money"] == 0, "деньги не ушли в минус")

        # --- кейсы дают номер не хуже порога
        st.db.execute("UPDATE users SET money=100000000 WHERE id=?", (uid,))
        st.db.commit()
        for case in CASES:
            before = st.wallet(uid)["money"]
            status, roll = pr.open_case(uid, case["id"])
            check(status == "ok" and roll["eval"]["score"] >= case["min"] and st.wallet(uid)["money"] == before - case["price"],
                  f"{case['id']}: {roll['plate']['text']} ({roll['eval']['score']} очков), списано {case['price']}")
        check(pr.tasks(uid)["items"][-1]["done"], "задание «открой кейс» засчиталось")

        # --- улучшения
        slots0 = st.stats(uid)["slots"]
        check(pr.buy_upgrade(uid, "slots") == "ok" and st.stats(uid)["slots"] == slots0 + 5, "гараж +5 мест")
        check(pr.upgrades(uid)["slots"]["price"] == slot_price(1), "следующий уровень гаража дороже")
        st.db.execute("UPDATE users SET extra_slots=? WHERE id=?", (5 * SLOT_LEVELS, uid))
        st.db.commit()
        check(pr.buy_upgrade(uid, "slots") == "max", "гараж: выше максимума не купить")
        check(pr.buy_upgrade(uid, "auto") == "ok" and pr.buy_upgrade(uid, "auto") == "owned", "автопрокрутка покупается один раз")
        check(not pr.set_autosell(uid, "rare"), "автопродажу нельзя включить без покупки")
        check(pr.buy_upgrade(uid, "autosell") == "ok" and pr.upgrades(uid)["autosell"]["below"] == "uncommon", "автопродажа куплена и сразу продаёт обычные")

        # --- автопродажа
        money = st.wallet(uid)["money"]
        common = st.add_roll(uid, parse_ru("К418ВТ 52"), evaluate(parse_ru("К418ВТ 52")), "app")
        gain = pr.autosell_after_spin(uid, common, plate_money)
        check(gain == 1000 and st.get_roll(common["id"])["sold"] and st.wallet(uid)["money"] == money + 1000, "обычный номер продан за 1 000 ₽")
        rare = st.add_roll(uid, parse_ru("В559МР 77"), evaluate(parse_ru("В559МР 77")), "app")
        check(pr.autosell_after_spin(uid, rare, plate_money) == 0 and not st.get_roll(rare["id"])["sold"], "редкий номер не продаётся")
        pr.set_autosell(uid, "")
        common2 = st.add_roll(uid, parse_ru("К418ВТ 52"), evaluate(parse_ru("К418ВТ 52")), "app")
        check(pr.autosell_after_spin(uid, common2, plate_money) == 0, "выключенная автопродажа ничего не продаёт")

        stats = pr.stats(uid)
        check(stats["sold"] >= 1 and stats["earned"] >= 1000 and sum(t["count"] for t in stats["tiers"]) >= 20, "статистика считает продажи и редкости")
        st.db.close()

    print("\nВсё в порядке" if not fails else f"\nОшибок: {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
