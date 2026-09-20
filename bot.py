"""
Точка входа: запуск бота, фоновые задачи, catch-all обработчик текста.

ВАЖНО (фаза 1 рефакторинга):
- Состояния (чат, отправка тренировок, цели) берутся из state.py — раньше здесь
  были локальные копии, из-за чего «Чат с учеником» и «Тренировка ученику» не работали.
- Стикеры и кнопки меню — из constants.py (раньше дублировались в 4 файлах).
- Парсеры — из parsers.py (раньше в utils.py была расходящаяся копия).
"""
import asyncio
import logging
import re
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiohttp import ClientError

from config import ADMIN_ID, BOT_TOKEN, PROXY_URL
from constants import MENU_BUTTONS, STICKER_RECORD, STICKER_REMINDER, STICKER_STREAK
from database import (
    add_note_to_workout,
    add_workout,
    get_inactive_users,
    get_or_create_user,
    get_reminders,
    get_user_by_telegram_id,
    get_user_streak,
    get_users_without_workout_today,
    get_workouts_by_date,
    init_db,
    is_user_blocked,
    save_message,
    update_workout,
)
from helpers import escape_md
from model_registry import init_registry
from parsers import parse_workouts, parse_workouts_with_notes
from routers import admin, chat, student, swarm_router
from routers.common import router as common_router
from state import (
    awaiting_student_message,
    chat_sessions,
    send_workout_sessions,
    sent_reminders,
)
from states import DateStates, EditStates, NoteStates
from utils import check_and_celebrate_goals

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot: Bot | None = None

dp = Dispatcher()
router = Router()

# === РЕЕСТР МОДЕЛЕЙ ===
registry = init_registry()


def _parse_proxy_list(raw: str) -> list:
    """
    Разбирает PROXY_URL. Можно указать НЕСКОЛЬКО вариантов через запятую
    или точку с запятой — бот будет перебирать их при сбоях по кругу.

    Элемент «direct» (или «none») означает прямое подключение без прокси.

    Пример:
        PROXY_URL=socks5://127.0.0.1:10808, http://127.0.0.1:10809, direct
    """
    result: list = []
    for part in re.split(r"[,;]+", raw):
        part = part.strip()
        if not part:
            continue
        if part.lower() in {"direct", "none", "no", "-"}:
            result.append(None)
        elif "://" in part:
            result.append(part)
        else:
            logger.warning(f"Пропускаю некорректный элемент PROXY_URL: {part!r}")
    return result


def _make_session(proxy: str | None) -> AiohttpSession:
    """Создаёт сессию aiogram: с прокси (нативная поддержка) или без."""
    return AiohttpSession(proxy=proxy) if proxy else AiohttpSession()


@dp.startup()
async def on_startup():
    await registry.start_healthcheck()


# Подключаем роутеры (catch-all роутер этого файла — ВСЕГДА последним)
dp.include_router(common_router)
dp.include_router(chat.router)
dp.include_router(admin.router)
dp.include_router(student.router)
dp.include_router(swarm_router.router)
dp.include_router(router)


@router.message(Command("ping"))
async def ping(message: Message):
    await message.answer("pong")


# ========== ОБРАБОТЧИК ЛЮБОГО ТЕКСТА (catch-all) ==========

@router.message(F.sticker)
async def handle_sticker(message: Message):
    if message.from_user.id != ADMIN_ID and await is_user_blocked(message.from_user.id):
        return
    sticker = message.sticker
    logger.info(f"📦 СТИКЕР: file_id={sticker.file_id}")
    await message.answer(
        f"📋 Информация о стикере:\n\n"
        f"🎴 File ID:\n`{sticker.file_id}`\n\n"
        f"📦 Пак: `{sticker.set_name}`\n"
        f"Эмодзи: {sticker.emoji}",
        parse_mode="Markdown"
    )


@router.message(F.text)
async def handle_any_text(message: Message, state: FSMContext):
    text = message.text
    if text.startswith('/'):
        return
    if text.strip() in {btn.strip() for btn in MENU_BUTTONS}:
        return

    # === ПРОВЕРКА БЛОКИРОВКИ ===
    if message.from_user.id != ADMIN_ID and await is_user_blocked(message.from_user.id):
        logger.info(f"🚫 Заблокированный {message.from_user.id} попытался написать: {text}")
        return

    user_id = message.from_user.id

    # === АДМИН В РЕЖИМЕ ЧАТА ===
    if user_id in chat_sessions:
        student_id = chat_sessions[user_id]
        student_info = await get_user_by_telegram_id(student_id)
        student_name = student_info[2] if student_info else "ученик"
        await save_message(ADMIN_ID, student_id, text)
        try:
            await bot.send_message(student_id, f"👨‍🏫 *Сообщение от тренера:*\n\n{text}", parse_mode="Markdown")
            await message.answer(f"✅ Сообщение отправлено {student_name}.")
        except Exception as e:
            logger.error(f"Ошибка отправки ученику {student_id}: {e}")
            await message.answer(f"❌ Не удалось отправить: {e}")
        return

    # === АДМИН В РЕЖИМЕ ОТПРАВКИ ТРЕНИРОВКИ ===
    if user_id in send_workout_sessions:
        student_id = send_workout_sessions[user_id]
        student_info = await get_user_by_telegram_id(student_id)
        student_name = student_info[2] if student_info else "ученик"
        workouts, notes = parse_workouts_with_notes(text)
        if not workouts and not notes:
            await message.answer("❌ Не понял. Напиши упражнения и/или примечания.\nИли /exit")
            return
        student_db_id = await get_or_create_user(student_id, student_name)
        results = []
        for exercise, weight, sets, reps in workouts:
            record_msg = await add_workout(student_db_id, exercise, weight, sets, reps)
            results.append(f"🏋️ {exercise}: {weight}кг × {sets}×{reps}")
        summary_parts = []
        if results:
            summary_parts.append("📋 *Упражнения:*\n" + "\n".join(results))
        if notes:
            summary_parts.append("📝 *Примечания:*\n" + "\n".join(notes))
        summary = "\n\n".join(summary_parts)
        await message.answer(f"✅ Тренировка записана для *{escape_md(student_name)}*:\n\n{summary}", parse_mode="Markdown")
        if notes:
            await save_message(ADMIN_ID, student_id, "[Тренировка] " + "\n".join(notes))
        try:
            student_message = "🏫 *Тренер записал тебе тренировку:*\n\n"
            if results:
                student_message += "📋 *Упражнения:*\n" + "\n".join(results) + "\n\n"
            if notes:
                student_message += "📝 *Примечания от тренера:*\n" + "\n".join(notes) + "\n\n"
            student_message += "💪 Удачи!"
            await bot.send_message(student_id, student_message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Не удалось уведомить ученика {student_id}: {e}")
        send_workout_sessions.pop(user_id, None)
        return

    # === УЧЕНИК ПИШЕТ СООБЩЕНИЕ (ТРЕНИРОВКА ИЛИ ЧАТ) ===
    if user_id != ADMIN_ID:
        student_id = user_id
        student_name = message.from_user.full_name
        workouts = parse_workouts(text)
        if workouts:
            db_user_id = await get_or_create_user(student_id, student_name)
            for exercise, weight, sets, reps in workouts:
                record_msg = await add_workout(db_user_id, exercise, weight, sets, reps)
                streak = await get_user_streak(db_user_id)
                streak_msg = f"\n🔥 Серия: {streak} {'дней' if streak > 4 else 'дня' if streak > 1 else 'день'}!" if streak > 0 else ""
                await message.answer(f"✅ Записано:\n🏋️ {exercise}: {weight}кг × {sets}×{reps}{record_msg}{streak_msg}")
                goal_achieved = await check_and_celebrate_goals(message, db_user_id)
                if not goal_achieved and record_msg:
                    try: await message.answer_sticker(STICKER_RECORD)
                    except Exception as e: logger.warning(f"Стикер не ушел: {e}")
                if streak >= 5:
                    try: await message.answer_sticker(STICKER_STREAK)
                    except Exception as e: logger.warning(f"Стикер не ушел: {e}")
            await save_message(student_id, ADMIN_ID, text)
            try:
                await bot.send_message(ADMIN_ID, f"🏋️ *{escape_md(student_name)} записал тренировку:*\n\n{text}", parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"Не удалось уведомить админа: {e}")
            return
        # не тренировка — сообщение тренеру
        await save_message(student_id, ADMIN_ID, text)
        try:
            await bot.send_message(ADMIN_ID, f"💬 *Новое сообщение от {escape_md(student_name)}:*\n\n{text}", parse_mode="Markdown")
            await message.answer("✅ Сообщение отправлено тренеру.")
        except Exception as e:
            logger.error(f"Ошибка пересылки: {e}")
            await message.answer("❌ Не удалось доставить сообщение.")
        if student_id in awaiting_student_message:
            awaiting_student_message.remove(student_id)
        return

    # === FSM-СОСТОЯНИЯ (просмотр по дате, заметка, редактирование) ===
    current_state = await state.get_state()

    if current_state == DateStates.waiting_for_date:
        match = re.match(r'^(\d{1,2})[./](\d{1,2})$', text.strip())
        if not match:
            await message.answer("❌ Неверный формат. Напиши ДД.ММ (например, 12.06)")
            return
        day, month = int(match.group(1)), int(match.group(2))
        if day > 31 or month > 12:
            await message.answer("❌ Неверная дата.")
            return
        db_user_id = await get_or_create_user(user_id, message.from_user.full_name)
        workouts = await get_workouts_by_date(db_user_id, day, month)
        if not workouts:
            await message.answer(f"📭 Тренировок {day:02d}.{month:02d} не было.")
        else:
            text_msg = f"📅 Тренировки за {day:02d}.{month:02d}:\n\n"
            for w in workouts:
                note = f" ({w[5]})" if w[5] else ""
                text_msg += f"🏋️ {w[1]}: {w[2]}кг × {w[3]}×{w[4]}{note}\n"
            await message.answer(text_msg)
        await state.clear()
        return

    if current_state == NoteStates.waiting_for_note:
        data = await state.get_data()
        workout_id = data.get('workout_id')
        if not workout_id:
            await message.answer("❌ Ошибка: не найдена тренировка. Попробуй снова.")
            await state.clear()
            return
        await add_note_to_workout(workout_id, text)
        await state.clear()
        await message.answer("✅ Заметка сохранена!")
        return

    if current_state == EditStates.waiting_for_new_data:
        data = await state.get_data()
        workout_id = data.get('workout_id')
        if not workout_id:
            await message.answer("❌ Ошибка: не найдена тренировка. Попробуй снова.")
            await state.clear()
            return
        workouts = parse_workouts(text)
        if not workouts:
            await message.answer("❌ Не понял. Напиши: Жим 20 3 10\nИли /cancel")
            return
        for exercise, weight, sets, reps in workouts:
            await update_workout(workout_id, exercise, weight, sets, reps)
        await state.clear()
        await message.answer(f"✅ Запись обновлена:\n🏋️ {workouts[0][0]}: {workouts[0][1]}кг × {workouts[0][2]}×{workouts[0][3]}")
        return

    # === ДЛЯ АДМИНА: если ничего не подошло, пробуем распарсить как тренировку ===
    if user_id == ADMIN_ID:
        workouts = parse_workouts(text)
        if workouts:
            db_user_id = await get_or_create_user(user_id, message.from_user.full_name)
            for exercise, weight, sets, reps in workouts:
                record_msg = await add_workout(db_user_id, exercise, weight, sets, reps)
                streak = await get_user_streak(db_user_id)
                streak_msg = f"\n🔥 Серия: {streak} {'дней' if streak > 4 else 'дня' if streak > 1 else 'день'}!" if streak > 0 else ""
                await message.answer(f"✅ Записано:\n🏋️ {exercise}: {weight}кг × {sets}×{reps}{record_msg}{streak_msg}")
                goal_achieved = await check_and_celebrate_goals(message, db_user_id)
                if not goal_achieved and record_msg:
                    try: await message.answer_sticker(STICKER_RECORD)
                    except Exception as e: logger.warning(f"Стикер не ушел: {e}")
                if streak >= 5:
                    try: await message.answer_sticker(STICKER_STREAK)
                    except Exception as e: logger.warning(f"Стикер не ушел: {e}")
            return

    # === ВСЁ ОСТАЛЬНОЕ — ИГНОРИРУЕМ ===
    logger.info(f"Неизвестное текстовое сообщение от {user_id}: {text[:50]}")


# ========== ФОНОВЫЕ ЗАДАЧИ ==========

async def reminder_task():
    """
    Отправка напоминаний.

    ФИКС: раньше был один общий флаг «уже отправляли сегодня» — после первого
    сработавшего напоминания все остальные времена дня молча пропускались.
    Теперь каждое время дня отслеживается отдельным ключом sent_reminders.
    """
    logger.info("⏰ reminder_task запущен")
    while True:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            current_day = str(now.weekday() + 1)
            today_date = now.strftime("%Y-%m-%d")
            reminders = await get_reminders()
            for reminder_user_id, days, time, text in reminders:
                if current_day not in days.split(','):
                    continue
                if current_time != time:
                    continue
                sent_key = f"{today_date}_{time}"
                if sent_key in sent_reminders:
                    continue
                lazy_users = await get_users_without_workout_today()
                sent_count = 0
                for telegram_id, name in lazy_users:
                    if telegram_id == ADMIN_ID:
                        continue
                    try:
                        await bot.send_sticker(telegram_id, STICKER_REMINDER)
                        if text:
                            await bot.send_message(telegram_id, f"👋 {name}, {text}")
                        else:
                            await bot.send_message(telegram_id, f"👋 {name}, тренировка! 💪")
                        sent_count += 1
                    except Exception as e:
                        logger.error(f"Ошибка отправки {telegram_id}: {e}")
                # Помечаем время как отработанное даже если ленивых не нашлось,
                # чтобы не спамить проверками каждые 30 секунд в течение минуты
                sent_reminders.add(sent_key)
                if sent_count > 0:
                    logger.info(f"⏰ Отправлено напоминаний: {sent_count}")
        except Exception as e:
            logger.error(f"Ошибка в reminder_task: {e}")
        await asyncio.sleep(30)

async def inactive_users_task():
    global last_inactive_report_date
    last_inactive_report_date = None
    logger.info("📉 inactive_users_task запущен")
    while True:
        try:
            now = datetime.now()
            today_date = now.strftime("%Y-%m-%d")
            if now.hour == 10 and now.minute < 5:
                if last_inactive_report_date != today_date:
                    inactive_list = await get_inactive_users(days=14)
                    if inactive_list:
                        text = "⚠️ *Отчет о неактивных учениках (14+ дней):*\n\n"
                        for telegram_id, name, last_workout in inactive_list:
                            last_date_str = last_workout if last_workout else "никогда"
                            text += f"• {name} (последняя: {last_date_str})\n"
                        try:
                            await bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
                            logger.info("📉 Отчет отправлен")
                        except Exception as e:
                            logger.error(f"Ошибка отчета: {e}")
                    last_inactive_report_date = today_date
        except Exception as e:
            logger.error(f"Ошибка в inactive_users_task: {e}")
        await asyncio.sleep(3600)

@dp.error()
async def on_error(event, exception):
    """Глобальный обработчик ошибок (DevOps: observability).
    Необработанное исключение в хендлере: в лог — трейсбек, пользователю —
    аккуратное сообщение без технических деталей."""
    logger.exception("Необработанная ошибка в хендлере", exc_info=exception)
    try:
        msg = getattr(event.update, "message", None) or getattr(event.update, "callback_query", None)
        if msg is not None:
            await msg.answer("⚠️ Внутренняя ошибка. Попробуй ещё раз или позже.")
    except Exception:
        pass
    return True


async def main():
    global bot
    # Fail-fast: падаем сразу с понятным сообщением, а не загадочной ошибкой
    # где-нибудь на первом запросе (конфигурация проверяется при старте)
    if not BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN не задан. Заполни .env (шаблон — .env.example)")
    if not ADMIN_ID:
        logger.warning("⚠️ ADMIN_ID не задан — админ-функции будут недоступны")
    await init_db()

    # Список способов подключения (прокси и/или прямое). Первый рабочий
    # используется; при сбоях бот переключается на следующий по кругу.
    proxies = _parse_proxy_list(PROXY_URL) if PROXY_URL else []
    if proxies:
        pretty = ["напрямую" if p is None else p for p in proxies]
        logger.info(f"🌐 Варианты подключения: {pretty}")
        bot = Bot(token=BOT_TOKEN, session=_make_session(proxies[0]))
    else:
        logger.info("🌐 Подключаемся напрямую (PROXY_URL пуст)")
        bot = Bot(token=BOT_TOKEN)

    logger.info(f"🤖 Бот запущен... ADMIN_ID={ADMIN_ID}")
    # Ссылки на задачи сохраняем (иначе ruff RUF006 и нет graceful shutdown)
    tasks = [
        asyncio.create_task(reminder_task()),
        asyncio.create_task(inactive_users_task()),
    ]

    # Ретрай-цикл: если прокси/VPN временно недоступен (Happ перезапускается,
    # меняется сервер) — бот не падает, а переподключается с бэкоффом,
    # по кругу переключаясь между вариантами из PROXY_URL.
    #
    # Хитрость: у python_socks и aiohttp_socks СВОИ иерархии исключений
    # (ProxyConnectionError из aiohttp_socks — не наследник python_socks.ProxyError
    # и даже не OSError), поэтому собираем все Exception-классы обоих модулей.
    retry_exceptions: list = [TelegramNetworkError, ClientError, OSError]
    import importlib
    for mod_name in ("python_socks", "aiohttp_socks"):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        for attr in dir(mod):
            obj = getattr(mod, attr)
            if isinstance(obj, type) and issubclass(obj, Exception):
                retry_exceptions.append(obj)
    retry_exceptions = tuple(dict.fromkeys(retry_exceptions))

    retry_delay = 5
    proxy_idx = 0
    while True:
        try:
            await dp.start_polling(bot)
            # Штатное завершение (Ctrl+C): гасим фоновые задачи (graceful shutdown)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await bot.session.close()
            return
        except retry_exceptions as e:
            if proxies:
                proxy_idx = (proxy_idx + 1) % len(proxies)
                next_proxy = proxies[proxy_idx]
                logger.error(
                    f"🌐 Нет связи с Telegram ({type(e).__name__}). "
                    f"Переключаюсь на: {'напрямую' if next_proxy is None else next_proxy}"
                )
                bot.session = _make_session(next_proxy)
            else:
                logger.error(
                    f"🌐 Нет связи с Telegram ({type(e).__name__}). "
                    f"Повтор через {retry_delay} с..."
                )
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # бэкофф до 1 минуты


if __name__ == "__main__":
    asyncio.run(main())
