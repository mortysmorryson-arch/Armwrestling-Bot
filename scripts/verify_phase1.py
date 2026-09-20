#!/usr/bin/env python3
"""
Автопроверка фазы 1 (критические фиксы).

Проверяет:
  1. Парсер тренировок (примеры из README, десятичная запятая, краевые случаи)
  2. Свежую БД: схема создаётся правильной, все функции БД работают
  3. Миграцию: старая bot.db migrирует без потери данных
  4. Планировщик напоминаний: несколько времён в один день срабатывают,
     повторной отправки нет, админ не получает напоминания
  5. Импорт bot.py целиком (все зависимости на месте)

Запуск:  python scripts/verify_phase1.py
Код возврата: 0 — всё ок, 1 — есть провалы.
"""
import asyncio
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
os.chdir(PROJECT)

RESULTS: list[tuple[str, bool]] = []


def check(name: str, cond, extra: str = ""):
    ok = bool(cond)
    RESULTS.append((name, ok))
    mark = "✅" if ok else "❌"
    suffix = f"  ({extra})" if extra and not ok else ""
    print(f"{mark} {name}{suffix}")


def section(title: str):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# =====================================================================
section("1. ПАРСЕР ТРЕНИРОВОК (parsers.py)")
import parsers  # noqa: E402

check("README: 'Жим 20 3 10, Пронация 15 4 12'",
      parsers.parse_workouts("Жим 20 3 10, Пронация 15 4 12") == [
          ("Жим", 20.0, 3, "10"), ("Пронация", 15.0, 4, "12")])

check("Десятичная запятая: 'Сгибание 17,5 3 10' → 17.5 (раньше терялось)",
      parsers.parse_workouts("Сгибание 17,5 3 10") == [("Сгибание", 17.5, 3, "10")])

check("Десятичная точка: 'Сгибание 17.5 3 10'",
      parsers.parse_workouts("Сгибание 17.5 3 10") == [("Сгибание", 17.5, 3, "10")])

check("Вес в скобках: 'Жим (15) 4 12'",
      parsers.parse_workouts("Жим (15) 4 12") == [("Жим", 15.0, 4, "12")])

check("Формат x: 'Подъём на бицепс 25 3x12'",
      parsers.parse_workouts("Подъём на бицепс 25 3x12") == [("Подъём на бицепс", 25.0, 3, "12")])

check("Только вес: 'Жим 20' → 1×1 (раньше терялось)",
      parsers.parse_workouts("Жим 20") == [("Жим", 20.0, 1, "1")])

check("Вес+подходы: 'Тяга 40 3' → 3×1 (раньше было 3×'3')",
      parsers.parse_workouts("Тяга 40 3") == [("Тяга", 40.0, 3, "1")])

check("Нумерация: '1. Жим 20 3 10'",
      parsers.parse_workouts("1. Жим 20 3 10") == [("Жим", 20.0, 3, "10")])

w, n = parsers.parse_workouts_with_notes("Жим 20 3 10\nНе забывай разминать запястье!")
check("Примечания отделяются от упражнений",
      w == [("Жим", 20.0, 3, "10")] and n == ["Не забывай разминать запястье!"])

check("Мусор игнорируется: parse_workouts('привет') == []",
      parsers.parse_workouts("привет") == [])

check("utils.py переиспользует parsers.py (единственная реализация)",
      __import__("utils").parse_workouts is parsers.parse_workouts)

# =====================================================================
section("2. СВЕЖАЯ БАЗА: схема и все функции database.py")
import database  # noqa: E402

tmpdir = Path(tempfile.mkdtemp(prefix="armbot_verify_"))
fresh_db = tmpdir / "fresh.db"
database.DB_PATH = str(fresh_db)
asyncio.run(database.init_db())

EXPECTED_TABLES = {"users", "workouts", "records", "goals", "invites", "messages", "reminders"}


def schema_of(path: Path) -> dict[str, set[str]]:
    con = sqlite3.connect(path)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result = {}
    for t in tables & EXPECTED_TABLES:
        result[t] = {row[1] for row in con.execute(f"PRAGMA table_info({t})")}
    con.close()
    return result


fresh_schema = schema_of(fresh_db)
check("Все 7 таблиц созданы", set(fresh_schema) == EXPECTED_TABLES, str(sorted(fresh_schema)))
check("Таблица records создана (раньше отсутствовала — падение на чистой базе)",
      "records" in fresh_schema)
check("messages: правильные имена колонок",
      fresh_schema.get("messages") == {"id", "sender_telegram_id", "receiver_telegram_id",
                                       "text", "timestamp", "is_read"})
check("users: есть registered_at", "registered_at" in fresh_schema.get("users", set()))
check("goals: есть created_at", "created_at" in fresh_schema.get("goals", set()))


async def functional_sweep() -> list[str]:
    """Прогоняем все ключевые функции БД на свежей базе. Возвращаем список провалов."""
    errors: list[str] = []

    def expect(name, cond):
        if not cond:
            errors.append(name)

    uid = await database.get_or_create_user(111, "Тест Ученик")
    expect("get_or_create_user", uid > 0)

    msg1 = await database.add_workout(uid, "Жим", 20, 3, "10")
    expect("первый add_workout даёт рекорд", "рекорд" in msg1)
    msg2 = await database.add_workout(uid, "Жим", 25, 3, "10")
    expect("второй add_workout обновляет рекорд", "рекорд" in msg2)
    expect("get_current_max = 25", await database.get_current_max(uid, "жим") == 25.0)

    last = await database.get_last_workout(uid)
    expect("get_last_workout", last is not None and last[2] == "Жим")
    await database.update_workout(last[0], "Жим", 30, 4, "12")
    expect("update_workout", (await database.get_last_workout(uid))[3] == 30)
    expect("рекорд после update = 30", await database.get_current_max(uid, "жим") == 30.0)

    today = datetime.now()
    rows = await database.get_workouts_by_date(uid, today.day, today.month)
    expect("get_workouts_by_date", len(rows) >= 2)

    expect("get_user_streak >= 1", await database.get_user_streak(uid) >= 1)
    stats = await database.get_user_stats(uid)
    expect("get_user_stats", len(stats) >= 2)

    await database.save_message(111, 999, "привет")
    expect("get_unread_count", await database.get_unread_count(999) == 1)
    expect("get_unread_count_from_sender", await database.get_unread_count_from_sender(111, 999) == 1)
    hist = await database.get_chat_history(111, 999)
    expect("get_chat_history", len(hist) == 1)
    await database.mark_as_read(111, 999)
    expect("mark_as_read", await database.get_unread_count(999) == 0)

    await database.add_goal(uid, "Жим", 40, "01.12.2026")
    goals = await database.get_user_goals(uid)
    expect("add_goal/get_user_goals", len(goals) == 1)

    await database.set_reminder(uid, "1,3,5", "18:00", "тренировка!")
    await database.set_reminder(uid, "2,4", "19:00", "замена")  # повторная установка
    reminders = await database.get_reminders()
    expect("set_reminder заменяет, а не дублирует", len(reminders) == 1)
    expect("get_reminders возвращает 4 колонки", all(len(r) == 4 for r in reminders))
    # Тот же unpack, что в /reminder_status и reminder_task:
    for _uid, days, time, rtext in reminders:
        pass
    expect("unpack 4 колонок без ValueError", True)

    token = await database.create_invite_token(999)
    inv = await database.get_invite_token(token)
    expect("create/get_invite_token", inv is not None)
    await database.deactivate_invite(token)
    expect("deactivate_invite", await database.get_invite_token(token) is None)
    await database.get_all_invites()  # GROUP BY i.id — не должно падать

    expect("delete_exercise > 0", await database.delete_exercise(uid, "жим") > 0)
    expect("рекорд удалён вместе с упражнением", await database.get_current_max(uid, "жим") == 0.0)

    await database.add_workout(uid, "Становая", 100, 3, "8")
    expect("get_monthly_rating", len(await database.get_monthly_rating()) >= 1)
    expect("get_inactive_users пуст (тренировался сегодня)",
           await database.get_inactive_users(14) == [])
    expect("get_users_without_workout_today пуст",
           await database.get_users_without_workout_today() == [])
    expect("get_lazy_users строка", isinstance(await database.get_lazy_users(7), str))
    expect("get_all_students", len(await database.get_all_students()) >= 1)
    await database.block_user(111)
    expect("block_user", await database.is_user_blocked(111) is True)
    await database.unblock_user(111)
    expect("unblock_user", await database.is_user_blocked(111) is False)
    await database.delete_all_reminders()
    expect("delete_all_reminders", await database.get_reminders() == [])
    return errors


sweep_errors = asyncio.run(functional_sweep())
check("Функциональный прогон БД (35+ операций)", not sweep_errors, "; ".join(sweep_errors))

# =====================================================================
section("3. МИГРАЦИЯ: старая bot.db без потери данных")
real_db = PROJECT / "bot.db"
if real_db.exists():
    migrated = tmpdir / "migrated.db"
    shutil.copy(real_db, migrated)

    con = sqlite3.connect(migrated)
    before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("users", "workouts", "records", "goals", "messages", "invites")}
    con.close()

    database.DB_PATH = str(migrated)
    asyncio.run(database.init_db())

    con = sqlite3.connect(migrated)
    after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("users", "workouts", "records", "goals", "messages", "invites")}
    con.close()

    check("Количество строк во всех таблицах не изменилось", before == after,
          f"было {before}, стало {after}")

    migrated_schema = schema_of(migrated)
    diffs = [t for t in EXPECTED_TABLES if migrated_schema.get(t) != fresh_schema.get(t)]
    check("Схема мигрированной базы == схеме свежей базы", not diffs,
          f"различия: {diffs}")

    database.DB_PATH = str(migrated)
    reminders = asyncio.run(database.get_reminders())
    ok_unpack = True
    for _uid, days, time, rtext in reminders:
        pass
    check("reminder_status/reminder_task unpack на продовых данных", ok_unpack)
else:
    print("ℹ️ bot.db не найден — миграционный тест пропущен")

# =====================================================================
section("4. ПЛАНИРОВЩИК НАПОМИНАНИЙ (reminder_task)")
import bot as bot_module  # noqa: E402
from config import ADMIN_ID  # noqa: E402


class FakeBot:
    def __init__(self):
        self.stickers = []
        self.messages = []

    async def send_sticker(self, chat_id, sticker):
        self.stickers.append(chat_id)

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text))


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 13, 18, 0, 0)  # воскресенье (weekday 6 → день "7")


async def run_one_iteration():
    try:
        await asyncio.wait_for(bot_module.reminder_task(), timeout=2)
    except asyncio.TimeoutError:
        pass  # норм: вечный цикл, мы забрали одну итерацию


bot_module.datetime = FixedDatetime
bot_module.get_users_without_workout_today = lambda: asyncio.sleep(0, result=[
    (555, "Вася"), (ADMIN_ID, "Тренер"), (666, "Заблокированный")])


async def reminder_scenario():
    # Сценарий: два напоминания в один день — 18:00 и 19:00
    rows_18 = [(1, "7", "18:00", "пора на тренировку")]
    rows_19 = [(1, "7", "19:00", "второй заход")]

    fake = FakeBot()
    bot_module.bot = fake
    bot_module.get_reminders = lambda: asyncio.sleep(0, result=rows_18)
    bot_module.sent_reminders.clear()
    await run_one_iteration()

    check("Напоминание 18:00 отправлено", len(fake.messages) == 2)  # стикер + текст
    check("Админ не получает напоминания", all(cid != ADMIN_ID for cid, _ in fake.messages))
    check("Стикер отправлен", len(fake.stickers) == 2)

    # Та же минута/день: повторной отправки быть не должно
    fake2 = FakeBot()
    bot_module.bot = fake2
    await run_one_iteration()
    check("Повторной отправки в то же время нет", len(fake2.messages) == 0)

    # 19:00 того же дня — РАНЬШЕ ГЛОХЛО ОБЩИМ ФЛАГОМ, теперь работает
    class FixedDatetime19(FixedDatetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 13, 19, 0, 0)

    bot_module.datetime = FixedDatetime19
    bot_module.get_reminders = lambda: asyncio.sleep(0, result=rows_19)
    fake3 = FakeBot()
    bot_module.bot = fake3
    await run_one_iteration()
    check("ВТОРОЕ напоминание в тот же день срабатывает (ключевой фикс)",
          len(fake3.messages) == 2)

    # Другой день — снова работает
    class FixedDatetimeNextDay(FixedDatetime19):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 9, 14, 18, 0, 0)  # понедельник → день "1"

    bot_module.datetime = FixedDatetimeNextDay
    bot_module.get_reminders = lambda: asyncio.sleep(0, result=[(1, "1", "18:00", "новый день")])
    fake4 = FakeBot()
    bot_module.bot = fake4
    await run_one_iteration()
    check("На следующий день напоминание снова срабатывает", len(fake4.messages) == 2)


asyncio.run(reminder_scenario())

# =====================================================================
section("5. ИМПОРТ bot.py (все зависимости на месте)")
env = dict(os.environ, DB_PATH=str(tmpdir / "import_test.db"))
proc = subprocess.run([sys.executable, "-c", "import bot"], cwd=PROJECT, env=env,
                      capture_output=True, text=True, timeout=120)
check("import bot без ошибок", proc.returncode == 0, proc.stderr[-500:] if proc.returncode else "")

# =====================================================================
shutil.rmtree(tmpdir, ignore_errors=True)
failed = [name for name, ok in RESULTS if not ok]
print(f"\n{'=' * 60}")
print(f"ИТОГО: {len(RESULTS) - len(failed)}/{len(RESULTS)} проверок пройдено")
if failed:
    print("ПРОВАЛЫ:")
    for name in failed:
        print(f"  ❌ {name}")
    sys.exit(1)
print("🎉 ФАЗА 1 ПОЛНОСТЬЮ ПРОВЕРЕНА")
