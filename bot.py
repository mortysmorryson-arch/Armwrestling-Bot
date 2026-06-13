import os
import re
import asyncio
import logging
import io
import csv
from datetime import datetime, timedelta

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, 
    BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton
)
from dotenv import load_dotenv

from database import (
    init_db, get_or_create_user, add_workout, get_user_stats, 
    get_all_users_stats, get_lazy_users, get_user_exercises, get_exercise_progress,
    delete_exercise, get_last_workout, update_workout, delete_last_workout,
    get_user_streak, add_note_to_workout, export_all_workouts, get_workouts_by_date,
    get_monthly_rating, add_goal, get_user_goals, get_current_max, delete_goal,
    set_reminder, get_reminders, delete_reminder, delete_all_reminders, get_users_without_workout_today,
    get_all_students, get_user_by_telegram_id,
    save_message, get_unread_count, get_unread_count_from_sender, get_chat_history, mark_as_read,
    is_user_blocked, block_user, unblock_user,
    create_invite_token, get_invite_token, get_all_invites, deactivate_invite,
    get_inactive_users
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
PROXY_URL = os.getenv("PROXY_URL", "").strip() 

dp = Dispatcher()
router = Router()
dp.include_router(router)

editing_users = {}
adding_note_users = {}
awaiting_date_users = set()
goal_steps = {}
celebrated_goals = set()
reminder_steps = {}
last_reminder_sent_date = None
chat_sessions = {}
send_workout_sessions = {}
awaiting_student_message = set()
delete_exercise_cache = {}

STICKER_RECORD = "CAACAgIAAxkBAAIBh2oizjGk4UwbQQXQ5mh1ncOqa1QjAAJomgACPP4pS7Apz8oKLfG2OwQ"
STICKER_STREAK = "CAACAgIAAxkBAAIBiGoi2d7_WcVV7_u1drlAIMpNSMafAAJ6XwACyq0oSaCtAAGRoSMCYDsE"
STICKER_GOAL = "CAACAgIAAxkBAAIBiWoi2iRIIM_khRiA94ItAmKaK6xZAAJIlQAC1R8gSxDvBZotMHQKOwQ"
STICKER_REMINDER = "CAACAgIAAxkBAAIBimoi2oGIKEyTiZkVCXyyNkKH_NVSAAKJUwACM2BBSQdCqXz63ZQDOwQ"
STICKER_MOTIVATION = "CAACAgIAAxkBAAIBi2oi2q9k9iE9NTN9Puc5cMvH7lyLAALrYQACEDSASc-bH-cMP33AOwQ"

MENU_BUTTONS = {
    "📝 Записать тренировку", "📋 Последняя", "📊 Моя статистика", 
    "📈 Прогресс", "🔥 Серия", "📅 По дате", "⚙️ Управление", "❓ Помощь", 
    "🔐 Все ученики", "😴 Кто ленится", "📥 Экспорт CSV", "🏆 Рейтинг", "🎯 Цели",
    "🎯 Поставить цель", "⏰ Напоминания", "💬 Чат с учеником", "🏋️ Тренировка ученику",
    "📬 Сообщения", "💬 Написать тренеру", "🔗 Пригласить ученика", "👥 Управление учениками"
}

def is_admin(message: Message) -> bool:
    return message.from_user.id == ADMIN_ID

def is_admin_by_id(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def get_unread_badge() -> str:
    count = await get_unread_count(ADMIN_ID)
    return f" ({count})" if count > 0 else ""

async def get_main_keyboard_async(admin: bool = False) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="📝 Записать тренировку"), KeyboardButton(text="📋 Последняя")],
        [KeyboardButton(text="📊 Моя статистика"), KeyboardButton(text="📈 Прогресс")],
        [KeyboardButton(text="🔥 Серия"), KeyboardButton(text="📅 По дате")],
        [KeyboardButton(text="⚙️ Управление"), KeyboardButton(text="🎯 Цели")],
        [KeyboardButton(text="🎯 Поставить цель"), KeyboardButton(text="❓ Помощь")]
    ]
    if admin:
        unread_badge = await get_unread_badge()
        kb.append([
            KeyboardButton(text="🔐 Все ученики"), 
            KeyboardButton(text="😴 Кто ленится"),
            KeyboardButton(text="📥 Экспорт CSV")
        ])
        kb.append([
            KeyboardButton(text="🏆 Рейтинг"),
            KeyboardButton(text="⏰ Напоминания")
        ])
        kb.append([
            KeyboardButton(text="💬 Чат с учеником"),
            KeyboardButton(text="🏋️ Тренировка ученику")
        ])
        kb.append([KeyboardButton(text=f"📬 Сообщения{unread_badge}")])
        kb.append([
            KeyboardButton(text="🔗 Пригласить ученика"),
            KeyboardButton(text=" Управление учениками")
        ])
    else:
        kb.append([KeyboardButton(text="💬 Написать тренеру")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

import re
import logging

logger = logging.getLogger(__name__)

def clean_exercise_name(name: str) -> str:
    name = name.rstrip(' ,.-')
    name = re.sub(r'\b(кг|килограмм|килограммов)\b', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'[:;,.!?]+$', '', name).strip()
    return name.capitalize()

def parse_exercise_line(line: str):
    print(f"[DEBUG] Парсим строку: {repr(line)}")
    if not line or not line.strip():
        return None
    
    # 1. Удаляем нумерацию
    line = re.sub(r'^\s*\d+[\.\)]\s*', '', line).strip()
    
    # 2. Извлекаем вес из скобок
    weight = 0.0
    weight_match = re.search(r'[\(\（]([\d\.,]+)[\)\）]', line)
    if weight_match:
        try:
            weight = float(weight_match.group(1).replace(',', '.'))
        except ValueError:
            pass
        line = line[:weight_match.start()] + line[weight_match.end():]
        line = line.strip()
    
    # 3. Ищем числовой хвост
    tail_match = re.search(r'(\d+(?:\s*[xх/]\s*\d+)*)\s*(.*)$', line)
    
    if tail_match:
        tail_nums = tail_match.group(1)
        tail_rest = tail_match.group(2).strip()
        
        # Разделяем хвост по слэшам или иксам
        parts = re.split(r'\s*[xх/]\s*', tail_nums)
        parts = [p for p in parts if p] # убираем пустые элементы
        
        if not parts:
            return None
            
        # ЛОГИКА РАЗДЕЛЕНИЯ:
        if len(parts) == 2 and not tail_rest:
            # Формат "4/8" -> подходы=4, повторения=8
            sets = int(parts[0])
            reps = parts[1]
        else:
            # Формат "15/13/9/9" или "4 10 сек"
            sets = int(parts[0]) # Первое число всегда подходы
            reps = tail_rest if tail_rest else tail_nums.strip()
            
        ex_name = line[:tail_match.start()].strip()
        
        # Очистка имени упражнения
        ex_name = ex_name.rstrip(' ,.-')
        ex_name = re.sub(r'\b(кг|килограмм|килограммов)\b', '', ex_name, flags=re.IGNORECASE).strip()
        ex_name = re.sub(r'[:;,.!?]+$', '', ex_name).strip()
        ex_name = ex_name.capitalize()
        
        result = (ex_name, weight, sets, reps)
        print(f"[DEBUG] Успех: name='{ex_name}', weight={weight}, sets={sets}, reps='{reps}'")
        return result
        
    print(f"[DEBUG] Провал: не найдено числового хвоста")
    return None


def parse_workouts(text: str):
    # КРИТИЧЕСКИ ВАЖНО: заменяем десятичные запятые на точки ДО сплита, 
    # чтобы "17,5" не разорвало строку на две части
    text = re.sub(r'(\d),(\d)', r'\1.\2', text)
    
    workouts = []
    for line in re.split(r'[\n,]+', text):
        line = line.strip()
        if not line:
            continue
        parsed = parse_exercise_line(line)
        if parsed:
            workouts.append(parsed)
    return workouts


def parse_workouts_with_notes(text: str):
    # КРИТИЧЕСКИ ВАЖНО: заменяем десятичные запятые на точки
    text = re.sub(r'(\d),(\d)', r'\1.\2', text)
    
    workouts = []
    notes = []
    for line in re.split(r'[\n,]+', text):
        line = line.strip()
        if not line:
            continue
        
        parsed = parse_exercise_line(line)
        if parsed:
            workouts.append(parsed)
        else:
            notes.append(line)
            
    return workouts, notes

def make_progress_bar(percent: float) -> str:
    percent = min(100.0, max(0.0, percent))
    filled = int(percent / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {percent:.0f}%"

async def check_and_celebrate_goals(message: Message, user_id: int) -> bool:
    goals = await get_user_goals(user_id)
    goal_achieved = False
    for g_id, exercise, target_weight, target_date in goals:
        if g_id in celebrated_goals:
            continue
        current_max = await get_current_max(user_id, exercise)
        percent = (current_max / target_weight) * 100 if target_weight > 0 else 0
        if percent >= 100:
            try:
                await message.answer_sticker(STICKER_GOAL)
                await message.answer(f"🎉 ЦЕЛЬ ДОСТИГНУТА!\n\n{exercise} → {target_weight}кг\nТы сделал это! Devon Larratt гордится тобой! ")
                celebrated_goals.add(g_id)
                goal_achieved = True
            except Exception as e:
                logger.error(f"Ошибка отправки стикера цели: {e}")
    return goal_achieved

async def build_students_keyboard(action_prefix: str) -> InlineKeyboardMarkup:
    students = await get_all_students()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for user_db_id, telegram_id, name in students:
        if telegram_id == ADMIN_ID:
            continue
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=name, callback_data=f"{action_prefix}{telegram_id}")
        ])
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_student_select")
    ])
    return keyboard

@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработка /start с параметрами приглашения."""
    # Получаем параметр start (может быть None)
    start_param = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else None
    
    # Проверяем, заблокирован ли пользователь
    is_blocked = await is_user_blocked(message.from_user.id)
    
    if is_blocked and message.from_user.id != ADMIN_ID:
        await message.answer(
            "🚫 *Ваш доступ к боту заблокирован.*\n\n"
            "Обратитесь к тренеру для восстановления доступа.",
            parse_mode="Markdown"
        )
        return
    
    # Если есть параметр start — пытаемся зарегистрировать по приглашению
    invite_token = None
    source = 'direct'
    
    if start_param:
        # Форматы: link_XXX, qr_XXX, invite (старый формат)
        if start_param.startswith('link_'):
            invite_token = start_param[5:]  # Убираем префикс "link_"
            source = 'ссылка'
        elif start_param.startswith('qr_'):
            invite_token = start_param[3:]  # Убираем префикс "qr_"
            source = 'QR-код'
        elif start_param == 'invite':
            source = 'прямая ссылка (старый формат)'
        else:
            # Возможно, это просто токен без префикса
            invite_token = start_param
            source = 'неизвестно'
    
    # Проверяем токен, если есть
    if invite_token:
        invite = await get_invite_token(invite_token)
        if not invite:
            await message.answer(
                "❌ *Недействительная или неактивная ссылка-приглашение.*\n\n"
                "Обратитесь к тренеру за новой ссылкой.",
                parse_mode="Markdown"
            )
            return
    
    # Регистрируем пользователя
    user_id = await get_or_create_user(
        message.from_user.id, 
        message.from_user.full_name,
        invite_token=invite_token,
        source=source
    )
    
    # Если это админ
    if is_admin(message):
        keyboard = await get_main_keyboard_async(True)
        await message.answer(
            f"👋 Привет, {message.from_user.full_name}! Ты — тренер.\n\n"
            f"🔧 Что ты можешь:\n"
            f"• Записывать тренировки себе и ученикам\n"
            f"• Писать ученикам и получать от них сообщения\n"
            f"• Смотреть статистику и рейтинги\n"
            f"• Настраивать напоминания\n"
            f"• Управлять учениками (блокировать/разблокировать)\n"
            f"• Создавать приглашения (ссылки и QR-коды)\n\n"
            f" Чтобы пригласить ученика, нажми '🔗 Пригласить ученика'.",
            reply_markup=keyboard
        )
        return
    
    # Если это ученик — приветствие
    keyboard = await get_main_keyboard_async(False)
    
    if invite_token:
        welcome_text = (
            f"👋 Привет, {message.from_user.full_name}! Ты зарегистрирован в боте тренера.\n\n"
            f"📩 Ты перешёл по *{source}*.\n\n"
            f"🔧 Что ты можешь:\n"
            f"• Записывать свои тренировки (просто напиши: Жим 20 3 10)\n"
            f"• Смотреть свою статистику и прогресс\n"
            f"• Ставить цели и отслеживать прогресс\n"
            f"• Писать тренеру через кнопку '💬 Написать тренеру'\n\n"
            f"💪 Удачи на тренировках!"
        )
    else:
        welcome_text = (
            f"👋 Привет, {message.from_user.full_name}!\n\n"
            f"🔧 Что ты можешь:\n"
            f"• Записывать свои тренировки (просто напиши: Жим 20 3 10)\n"
            f"• Смотреть свою статистику и прогресс\n"
            f"• Писать тренеру через кнопку ' Написать тренеру'\n\n"
            f"💪 Удачи на тренировках!"
        )
    
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")
    
    # Уведомляем админа о новом ученике (если это новая регистрация по приглашению)
    if invite_token and message.from_user.id != ADMIN_ID:
        try:
            await bot.send_message(
                ADMIN_ID,
                f"🆕 *Новый ученик зарегистрировался!*\n\n"
                f"👤 Имя: {message.from_user.full_name}\n"
                f" Telegram ID: {message.from_user.id}\n"
                f"📩 Источник: *{source}*\n"
                f" Токен приглашения: `{invite_token}`\n\n"
                f"Теперь ты можешь писать ему через '💬 Чат с учеником'.",
                parse_mode="Markdown"
            )
            logger.info(f"🆕 Новый ученик: {message.from_user.full_name} (ID: {message.from_user.id}) по {source}")
        except Exception as e:
            logger.error(f"Не удалось уведомить админа о новом ученике: {e}")

@router.message(Command("invite"))
@router.message(F.text.lower().contains("пригласить ученика"))
async def cmd_invite(message: Message):
    """Создание приглашения: ссылка + QR-код."""
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    
    # Создаём токен
    token = await create_invite_token(message.from_user.id)
    
    # Две ссылки: для рассылки и для QR
    bot_username = (await bot.get_me()).username
    link_url = f"https://t.me/{bot_username}?start=link_{token}"
    qr_url = f"https://t.me/{bot_username}?start=qr_{token}"
    
    # Отправляем ссылки БЕЗ Markdown (чтобы подчёркивания не пропадали)
    await message.answer(
        f"🔗 Приглашение создано!\n\n"
        f"🔑 Токен: {token}\n\n"
        f"📩 Ссылка для рассылки:\n{link_url}\n\n"
        f"📱 Ссылка для QR-кода:\n{qr_url}\n\n"
        f"Обе ссылки ведут на один токен. Ниже — QR-код для печати."
    )
    
    # Генерируем QR-код
    try:
        import qrcode
        qr_img = qrcode.make(qr_url)
        buf = io.BytesIO()
        qr_img.save(buf, format='PNG')
        buf.seek(0)
        qr_photo = BufferedInputFile(buf.getvalue(), filename=f"invite_{token}.png")
    except ImportError:
        qr_photo = None
        logger.warning("Библиотека qrcode не установлена.")
    
    if qr_photo:
        await message.answer_photo(
            qr_photo,
            caption=f"📱 QR-код для приглашения\nТокен: {token}"
        )
    else:
        await message.answer(
            "⚠️ Библиотека qrcode не установлена.\n"
            "Установи: pip install qrcode[pil]"
        )

@router.message(Command("invites"))
async def cmd_invites(message: Message):
    """Список всех приглашений."""
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    
    invites = await get_all_invites()
    if not invites:
        return await message.answer("📭 Приглашений ещё не создавалось.")
    
    text = "🔗 *Все приглашения:*\n\n"
    for token, created_at, is_active, usage_count in invites:
        status = "✅ активно" if is_active else "❌ неактивно"
        text += f"• `{token}` — {status}, использовано: {usage_count} раз\n"
        text += f"  Создано: {created_at}\n\n"
    
    await message.answer(text, parse_mode="Markdown")

@router.message(Command("revoke"))
async def cmd_revoke(message: Message):
    """Деактивация приглашения: /revoke TOKEN"""
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Использование: `/revoke TOKEN`", parse_mode="Markdown")
    
    token = args[1]
    await deactivate_invite(token)
    await message.answer(f"✅ Приглашение `{token}` деактивировано. Новые регистрации по нему невозможны.", parse_mode="Markdown")

@router.message(Command("block"))
async def cmd_block(message: Message):
    """Блокировка ученика: /block @username или /block USER_ID"""
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    
    args = message.text.split()
    if len(args) < 2:
        return await message.answer(
            "Использование: `/block USER_ID`\n\n"
            "USER_ID — telegram_id ученика (можно посмотреть через /students или /debug_users)",
            parse_mode="Markdown"
        )
    
    try:
        user_id = int(args[1])
    except ValueError:
        return await message.answer("❌ Неверный USER_ID. Должно быть число.")
    
    await block_user(user_id)
    
    user_info = await get_user_by_telegram_id(user_id)
    user_name = user_info[2] if user_info else "неизвестный пользователь"
    
    await message.answer(f"🚫 Пользователь *{user_name}* (ID: {user_id}) заблокирован.", parse_mode="Markdown")
    
    # Уведомляем заблокированного
    try:
        await bot.send_message(
            user_id,
            "🚫 *Ваш доступ к боту заблокирован.*\n\n"
            "Обратитесь к тренеру для восстановления доступа.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id} о блокировке: {e}")

@router.message(Command("unblock"))
async def cmd_unblock(message: Message):
    """Разблокировка ученика: /unblock USER_ID"""
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Использование: `/unblock USER_ID`", parse_mode="Markdown")
    
    try:
        user_id = int(args[1])
    except ValueError:
        return await message.answer("❌ Неверный USER_ID.")
    
    await unblock_user(user_id)
    
    user_info = await get_user_by_telegram_id(user_id)
    user_name = user_info[2] if user_info else "неизвестный пользователь"
    
    await message.answer(f"✅ Пользователь *{user_name}* (ID: {user_id}) разблокирован.", parse_mode="Markdown")
    
    # Уведомляем разблокированного
    try:
        await bot.send_message(
            user_id,
            "✅ *Ваш доступ к боту восстановлен!*\n\n"
            "Теперь вы можете снова пользоваться ботом.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить пользователя {user_id} о разблокировке: {e}")

@router.message(Command("manage_students"))
@router.message(F.text.lower().contains("управление учениками"))
async def cmd_manage_students(message: Message):
    """Список учеников с кнопками блокировки."""
    if not is_admin(message):
        return await message.answer(" Только для админа.")
    
    import aiosqlite
    from database import DB_PATH
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT telegram_id, name, is_blocked FROM users WHERE telegram_id IS NOT NULL ORDER BY name")
        users = await cursor.fetchall()
    
    if not users:
        return await message.answer(" Нет пользователей.")
    
    text = "👥 *Управление учениками:*\n\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    
    for telegram_id, name, is_blocked in users:
        if telegram_id == ADMIN_ID:
            continue
        status = "🚫" if is_blocked else "✅"
        text += f"{status} {name} (ID: {telegram_id})\n"
        
        action = "unblock" if is_blocked else "block"
        action_text = "Разблокировать" if is_blocked else "Заблокировать"
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=f"{action_text} {name}", callback_data=f"{action}_student_{telegram_id}")
        ])
    
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="❌ Закрыть", callback_data="close_manage")
    ])
    
    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")

@router.callback_query(lambda c: c.data.startswith('block_student_'))
async def block_student_callback(callback_query: CallbackQuery):
    if not is_admin_by_id(callback_query.from_user.id):
        await callback_query.answer("🔒 Только для админа.", show_alert=True)
        return
    
    student_id = int(callback_query.data.replace('block_student_', ''))
    await block_user(student_id)
    
    user_info = await get_user_by_telegram_id(student_id)
    user_name = user_info[2] if user_info else "неизвестный"
    
    await callback_query.message.answer(f"🚫 {user_name} заблокирован.")
    
    try:
        await bot.send_message(
            student_id,
            "🚫 *Ваш доступ к боту заблокирован.*\n\nОбратитесь к тренеру.",
            parse_mode="Markdown"
        )
    except:
        pass
    
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith('unblock_student_'))
async def unblock_student_callback(callback_query: CallbackQuery):
    if not is_admin_by_id(callback_query.from_user.id):
        await callback_query.answer("🔒 Только для админа.", show_alert=True)
        return
    
    student_id = int(callback_query.data.replace('unblock_student_', ''))
    await unblock_user(student_id)
    
    user_info = await get_user_by_telegram_id(student_id)
    user_name = user_info[2] if user_info else "неизвестный"
    
    await callback_query.message.answer(f"✅ {user_name} разблокирован.")
    
    try:
        await bot.send_message(
            student_id,
            "✅ *Ваш доступ восстановлен!*",
            parse_mode="Markdown"
        )
    except:
        pass
    
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'close_manage')
async def close_manage_callback(callback_query: CallbackQuery):
    await callback_query.message.answer("👥 Закрыто.")
    await callback_query.answer()

@router.message(Command("help"))
@router.message(F.text.lower().contains("помощь"))
async def cmd_help(message: Message):
    text = (
        "📋 Как пользоваться ботом:\n\n"
        "1. Жми '📝 Записать тренировку' или напиши упражнения через запятую:\n"
        "   Жим 20 3 10, Пронация 15 4 12\n"
        "2. Жми '📋 Последняя' — посмотреть/исправить/добавить заметку\n"
        "3. Жми '📊 Моя статистика' для отчета\n"
        "4. Жми '📈 Прогресс' для графика\n"
        "5. Жми '🔥 Серия' — узнать свою серию тренировок\n"
        "6. Жми ' По дате' — посмотреть тренировки за конкретный день\n"
        "7. Жми ' Поставить цель' — интерактивная постановка цели\n"
        "8. Жми '🎯 Цели' — посмотреть активные цели\n"
        "9. Жми '⚙️ Управление' для удаления упражнений\n"
    )
    if is_admin(message):
        text += "\n🔐 Админ-команды:\n"
        text += "10. Жми ' Напоминания' — настроить напоминания\n"
        text += "11. Жми '💬 Чат с учеником' — написать ученику\n"
        text += "12. Жми '🏋️ Тренировка ученику' — записать тренировку ученику\n"
        text += "13. Жми '📬 Сообщения' — посмотреть непрочитанные\n"
        text += "14. Жми '🔗 Пригласить ученика' — создать ссылку и QR-код\n"
        text += "15. Жми ' Управление учениками' — блокировать/разблокировать\n"
        text += "16. '/students' — список всех учеников\n"
        text += "17. '/invites' — список всех приглашений\n"
        text += "18. '/revoke TOKEN' — деактивировать приглашение\n"
        text += "19. '/block USER_ID' — заблокировать ученика\n"
        text += "20. '/unblock USER_ID' — разблокировать ученика\n"
        text += "21. '/exit' — выйти из режима чата\n"
    else:
        text += "\n📩 Для учеников:\n"
        text += "• Жми '💬 Написать тренеру' — отправить сообщение тренеру\n"
    await message.answer(text, parse_mode=None)

@router.message(Command("log"))
@router.message(F.text.lower().contains("записать тренировку"))
async def cmd_log(message: Message):
    if message.text and "записать тренировку" in message.text.lower():
        return await message.answer("Напиши упражнения через запятую или с новой строки:\nЖим 20 3 10, Пронация 15 4 12")
    text = message.text.replace("/log", "", 1).strip()
    workouts = parse_workouts(text)
    if not workouts:
        await message.answer("❌ Не понял формат. Напиши:\nЖим 20 3 10, Пронация 15 4 12")
        return
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    for exercise, weight, sets, reps in workouts:
        record_msg = await add_workout(user_id, exercise, weight, sets, reps)
        streak = await get_user_streak(user_id)
        streak_msg = f"\n🔥 Серия: {streak} {'дней' if streak > 4 else 'дня' if streak > 1 else 'день'}!" if streak > 0 else ""
        await message.answer(f"✅ Записано:\n️ {exercise}: {weight}кг × {sets}×{reps}{record_msg}{streak_msg}")
        goal_achieved = await check_and_celebrate_goals(message, user_id)
        if not goal_achieved and record_msg:
            try:
                await message.answer_sticker(STICKER_RECORD)
            except Exception as e:
                logger.error(f"Ошибка отправки стикера рекорда: {e}")
        if streak >= 5:
            try:
                await message.answer_sticker(STICKER_STREAK)
            except Exception as e:
                logger.error(f"Ошибка отправки стикера серии: {e}")

@router.message(Command("last"))
@router.message(F.text.lower().contains("последняя"))
async def cmd_last(message: Message):
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    workout = await get_last_workout(user_id)
    if not workout:
        await message.answer("📭 У тебя ещё нет записей.")
        return
    w_id, date, exercise, weight, sets, reps, notes = workout
    note_text = f"\n Заметка: {notes}" if notes else ""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Исправить", callback_data=f"edit_last_{w_id}"),
         InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_last_{w_id}")],
        [InlineKeyboardButton(text="📝 Заметка", callback_data=f"note_last_{w_id}")]
    ])
    await message.answer(
        f"📋 Твоя последняя тренировка:\n\n📅 {date}\n🏋️ {exercise}: {weight}кг × {sets}×{reps}{note_text}",
        reply_markup=keyboard
    )

@router.callback_query(lambda c: c.data.startswith('edit_last_'))
async def edit_last_callback(callback_query: CallbackQuery):
    workout_id = int(callback_query.data.replace('edit_last_', ''))
    editing_users[callback_query.from_user.id] = workout_id
    await callback_query.message.answer("✏️ Напиши новые данные в формате:\nЖим 20 3 10\n\nИли /cancel чтобы отменить")
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith('note_last_'))
async def note_last_callback(callback_query: CallbackQuery):
    workout_id = int(callback_query.data.replace('note_last_', ''))
    adding_note_users[callback_query.from_user.id] = workout_id
    await callback_query.message.answer("📝 Напиши заметку к этой тренировке:\n\nИли /cancel чтобы отменить")
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith('delete_last_'))
async def delete_last_callback(callback_query: CallbackQuery):
    user_id = await get_or_create_user(callback_query.from_user.id, callback_query.from_user.full_name)
    deleted = await delete_last_workout(user_id)
    if deleted:
        await callback_query.message.answer("🗑 Последняя тренировка удалена.")
    else:
        await callback_query.message.answer(" Нечего удалять.")
    await callback_query.answer()

@router.message(Command("cancel"))
@router.message(Command("exit"))
async def cmd_cancel(message: Message):
    user_id = message.from_user.id
    if user_id in editing_users:
        del editing_users[user_id]
        await message.answer("❌ Редактирование отменено.")
    elif user_id in adding_note_users:
        del adding_note_users[user_id]
        await message.answer(" Добавление заметки отменено.")
    elif user_id in awaiting_date_users:
        awaiting_date_users.remove(user_id)
        await message.answer("❌ Просмотр по дате отменен.")
    elif user_id in goal_steps:
        del goal_steps[user_id]
        await message.answer("❌ Постановка цели отменена.")
    elif user_id in reminder_steps:
        del reminder_steps[user_id]
        await message.answer("❌ Настройка напоминаний отменена.")
    elif user_id in chat_sessions:
        student_id = chat_sessions[user_id]
        student_info = await get_user_by_telegram_id(student_id)
        student_name = student_info[2] if student_info else "ученик"
        del chat_sessions[user_id]
        await message.answer(f"✅ Чат с {student_name} завершён.")
    elif user_id in send_workout_sessions:
        student_id = send_workout_sessions[user_id]
        student_info = await get_user_by_telegram_id(student_id)
        student_name = student_info[2] if student_info else "ученик"
        del send_workout_sessions[user_id]
        await message.answer(f"✅ Отмена отправки тренировки {student_name}.")
    elif user_id in awaiting_student_message:
        awaiting_student_message.remove(user_id)
        await message.answer("❌ Отправка сообщения тренеру отменена.")
    else:
        await message.answer("Ты ничего не редактируешь.")

@router.message(Command("stats"))
@router.message(F.text.lower().contains("моя статистика"))
async def cmd_stats(message: Message):
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    workouts = await get_user_stats(user_id)
    if not workouts:
        await message.answer(" Тренировок пока нет.")
        return
    streak = await get_user_streak(user_id)
    streak_text = f"🔥 Текущая серия: {streak} {'дней' if streak > 4 else 'дня' if streak > 1 else 'день'}\n\n" if streak > 0 else ""
    text = f" Твоя статистика (последние 10):\n\n{streak_text}"
    for w in workouts[:10]:
        note = f" ({w[5]})" if w[5] else ""
        text += f" {w[0]} | {w[1]}: {w[2]}кг × {w[3]}×{w[4]}{note}\n"
    await message.answer(text)

@router.message(Command("streak"))
@router.message(F.text.lower().contains("серия"))
async def cmd_streak(message: Message):
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    streak = await get_user_streak(user_id)
    if streak == 0:
        await message.answer("🔥 Серия: 0 дней\nНачни тренироваться, чтобы зажечь серию!")
    else:
        days_word = 'дней' if streak > 4 else 'дня' if streak > 1 else 'день'
        await message.answer(f"🔥 Твоя серия: {streak} {days_word}!\nПродолжай в том же духе! 💪")

@router.message(Command("progress"))
@router.message(F.text.lower().contains("прогресс"))
async def cmd_progress(message: Message):
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    exercises = await get_user_exercises(user_id)
    if not exercises:
        await message.answer("📭 У тебя пока нет тренировок.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for ex in exercises:
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=ex, callback_data=f"show_progress_{ex}")])
    await message.answer("📊 Выбери упражнение:", reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith('show_progress_'))
async def process_progress_callback(callback_query: CallbackQuery):
    try:
        exercise = callback_query.data.replace('show_progress_', '')
        user_id = await get_or_create_user(callback_query.from_user.id, callback_query.from_user.full_name)
        progress = await get_exercise_progress(user_id, exercise)
        if not progress:
            await callback_query.message.answer(f"📭 Нет данных")
            await callback_query.answer()
            return
        dates = [row[0] for row in progress]
        weights = [row[1] for row in progress]
        plt.figure(figsize=(10, 6))
        plt.plot(dates, weights, marker='o', linewidth=2, markersize=8, color='#4CAF50')
        plt.title(f'Прогресс: {exercise}', fontsize=16, fontweight='bold')
        plt.xlabel('Дата', fontsize=12)
        plt.ylabel('Вес (кг)', fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()
        photo = BufferedInputFile(buf.getvalue(), filename="progress.png")
        await callback_query.message.answer_photo(photo, caption=f"📈 Твой прогресс")
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await callback_query.message.answer(f"❌ Ошибка: {e}")
        await callback_query.answer()

@router.message(Command("date"))
@router.message(F.text.lower().contains("по дате"))
async def cmd_date_prompt(message: Message):
    if message.text.lower() in ["📅 по дате", "/date"]:
        awaiting_date_users.add(message.from_user.id)
        return await message.answer("Введите дату в формате ДД.ММ (например, 12.06)\nИли /cancel")
    args = message.text.split()
    if len(args) == 2:
        match = re.match(r'^(\d{1,2})[./](\d{1,2})$', args[1])
        if match:
            day, month = int(match.group(1)), int(match.group(2))
            if day > 31 or month > 12:
                return await message.answer("❌ Неверная дата.")
            user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
            workouts = await get_workouts_by_date(user_id, day, month)
            if not workouts:
                return await message.answer(f" Тренировок {day:02d}.{month:02d} не было.")
            text_msg = f"📅 Тренировки за {day:02d}.{month:02d}:\n\n"
            for w in workouts:
                note = f" ({w[5]})" if w[5] else ""
                text_msg += f"🏋️ {w[1]}: {w[2]}кг × {w[3]}×{w[4]}{note}\n"
            return await message.answer(text_msg)
    awaiting_date_users.add(message.from_user.id)
    await message.answer("Введите дату в формате ДД.ММ (например, 12.06)\nИли /cancel")

@router.message(Command("manage"))
@router.message(F.text.lower().contains("управление"))
async def cmd_manage(message: Message):
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    exercises = await get_user_exercises(user_id)
    
    if not exercises:
        await message.answer("📭 У тебя пока нет записанных упражнений для удаления.")
        return
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for i, ex in enumerate(exercises):
        # Используем короткий ID (user_id + индекс), чтобы не превысить лимит Telegram в 64 байта
        short_id = f"{user_id}_{i}"
        delete_exercise_cache[short_id] = ex
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"🗑 Удалить {ex}", callback_data=f"delete_exercise_{short_id}")])
    
    await message.answer("⚙️ Выбери упражнение для удаления:", reply_markup=keyboard)

@router.callback_query(lambda c: c.data.startswith('delete_exercise_'))
async def confirm_delete_callback(callback_query: CallbackQuery):
    short_id = callback_query.data.replace('delete_exercise_', '')
    exercise = delete_exercise_cache.get(short_id, "Неизвестное упражнение")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_delete_{short_id}"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_delete")]
    ])
    await callback_query.message.answer(f"⚠️ Удалить все записи упражнения '{exercise}'?", reply_markup=keyboard)
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith('confirm_delete_'))
async def process_delete_callback(callback_query: CallbackQuery):
    short_id = callback_query.data.replace('confirm_delete_', '')
    exercise = delete_exercise_cache.get(short_id)
    
    if not exercise:
        await callback_query.message.answer("❌ Сессия удаления истекла. Начни заново через меню 'Управление'.")
        await callback_query.answer()
        return
        
    user_id = await get_or_create_user(callback_query.from_user.id, callback_query.from_user.full_name)
    deleted_count = await delete_exercise(user_id, exercise)
    
    # Очищаем кэш после использования
    if short_id in delete_exercise_cache:
        del delete_exercise_cache[short_id]
        
    await callback_query.message.answer(f"✅ Удалено записей: {deleted_count}")
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'cancel_delete')
async def cancel_delete_callback(callback_query: CallbackQuery):
    await callback_query.message.answer("❌ Отменено")
    await callback_query.answer()

@router.message(Command("all_stats"))
@router.message(F.text.lower().contains("все ученики"))
async def cmd_all_stats(message: Message):
    if not is_admin(message):
        return
    await message.answer(await get_all_users_stats())

@router.message(Command("lazy"))
@router.message(F.text.lower().contains("ленится"))
async def cmd_lazy(message: Message):
    if not is_admin(message):
        return
    await message.answer(await get_lazy_users(7))

@router.message(Command("export"))
@router.message(F.text.lower().contains("экспорт csv"))
async def cmd_export(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    rows = await export_all_workouts()
    if not rows:
        return await message.answer("📭 Нет данных для экспорта.")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Дата", "Ученик", "Упражнение", "Вес (кг)", "Подходы", "Повторения", "Заметка"])
    for row in rows:
        writer.writerow(row)
    csv_bytes = output.getvalue().encode('utf-8-sig')
    doc = BufferedInputFile(csv_bytes, filename="workouts.csv")
    await message.answer_document(doc, caption=f"📥 Выгружено тренировок: {len(rows)}")

@router.message(Command("rating"))
@router.message(F.text.lower().contains("рейтинг"))
async def cmd_rating(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    rating = await get_monthly_rating()
    if not rating:
        return await message.answer("📭 В этом месяце тренировок пока не было.")
    text = "🏆 Рейтинг учеников за этот месяц:\n\n"
    medals = ["🥇", "🥈", ""]
    for i, (name, count) in enumerate(rating):
        medal = medals[i] if i < 3 else "🏅"
        word = "тренировка" if count == 1 else "тренировки" if count < 5 else "тренировок"
        text += f"{medal} {name}: {count} {word}\n"
    await message.answer(text)

@router.message(Command("goals"))
@router.message(F.text.lower().contains("цели"))
async def cmd_goals(message: Message):
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    goals = await get_user_goals(user_id)
    if not goals:
        return await message.answer("📭 У тебя пока нет активных целей.\nНажми '🎯 Поставить цель' чтобы создать.")
    text = "🎯 Твои цели:\n\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for g_id, exercise, target_weight, target_date in goals:
        current_max = await get_current_max(user_id, exercise)
        percent = (current_max / target_weight) * 100 if target_weight > 0 else 0
        bar = make_progress_bar(percent)
        status = "✅ Выполнено!" if percent >= 100 else f"Текущий макс: {current_max}кг"
        text += f"️ *{exercise}* → {target_weight}кг (до {target_date})\n{bar}\n{status}\n\n"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"❌ Удалить цель: {exercise}", callback_data=f"delete_goal_{g_id}")])
    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")

@router.callback_query(lambda c: c.data.startswith('delete_goal_'))
async def delete_goal_callback(callback_query: CallbackQuery):
    goal_id = int(callback_query.data.replace('delete_goal_', ''))
    await delete_goal(goal_id)
    if goal_id in celebrated_goals:
        celebrated_goals.remove(goal_id)
    await callback_query.message.answer("🗑 Цель удалена.")
    await callback_query.answer()

@router.message(Command("set_goal"))
@router.message(F.text.lower().contains("поставить цель"))
async def cmd_set_goal_start(message: Message):
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    exercises = await get_user_exercises(user_id)
    if not exercises:
        return await message.answer("📭 У тебя пока нет упражнений. Сначала запиши тренировку.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    row = []
    for ex in exercises:
        row.append(InlineKeyboardButton(text=ex, callback_data=f"goal_exercise_{ex}"))
        if len(row) == 2:
            keyboard.inline_keyboard.append(row)
            row = []
    if row:
        keyboard.inline_keyboard.append(row)
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_goal")])
    await message.answer("🎯 *Постановка цели*\n\nВыбери упражнение:", reply_markup=keyboard, parse_mode="Markdown")

@router.callback_query(lambda c: c.data.startswith('goal_exercise_'))
async def goal_exercise_callback(callback_query: CallbackQuery):
    exercise = callback_query.data.replace('goal_exercise_', '')
    user_id = callback_query.from_user.id
    goal_steps[user_id] = {"exercise": exercise}
    db_user_id = await get_or_create_user(callback_query.from_user.id, callback_query.from_user.full_name)
    current_max = await get_current_max(db_user_id, exercise)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_goal")]])
    await callback_query.message.answer(
        f"🏋️ Выбрано: *{exercise}*\nТекущий максимум: {current_max}кг\n\nВведи целевой вес (например: 30 или 30.5):",
        reply_markup=keyboard, parse_mode="Markdown")
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'cancel_goal')
async def cancel_goal_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id in goal_steps:
        del goal_steps[callback_query.from_user.id]
    await callback_query.message.answer("❌ Постановка цели отменена.")
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith('goal_months_'))
async def goal_months_callback(callback_query: CallbackQuery):
    months = int(callback_query.data.replace('goal_months_', ''))
    user_id = callback_query.from_user.id
    if user_id not in goal_steps:
        await callback_query.message.answer("❌ Сессия истекла. Начни заново.")
        await callback_query.answer()
        return
    target_date = (datetime.now() + timedelta(days=30 * months)).strftime("%d.%m.%Y")
    exercise = goal_steps[user_id]["exercise"]
    weight = goal_steps[user_id]["weight"]
    del goal_steps[user_id]
    db_user_id = await get_or_create_user(callback_query.from_user.id, callback_query.from_user.full_name)
    await add_goal(db_user_id, exercise, weight, target_date)
    await callback_query.message.answer(f"🎯 Цель поставлена:\n{exercise} → {weight}кг к {target_date}")
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'goal_custom_date')
async def goal_custom_date_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in goal_steps:
        await callback_query.message.answer("❌ Сессия истекла. Начни заново.")
        await callback_query.answer()
        return
    goal_steps[user_id]["custom_date"] = True
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_goal")]])
    await callback_query.message.answer("Введи дату в формате ДД.ММ.ГГГГ (например, 01.12.2026):", reply_markup=keyboard)
    await callback_query.answer()

@router.message(Command("reminder"))
@router.message(F.text.lower().contains("напоминания"))
async def cmd_reminder(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    reminders = await get_reminders()
    if reminders:
        text = "⏰ Текущие напоминания:\n\n"
        day_names = {'1': 'Пн', '2': 'Вт', '3': 'Ср', '4': 'Чт', '5': 'Пт', '6': 'Сб', '7': 'Вс'}
        for user_id, days, time in reminders:
            days_text = ', '.join([day_names.get(d, d) for d in days.split(',')])
            text += f"📅 {days_text} в {time}\n"
        text += "\nЧтобы изменить, нажми кнопку ниже:"
    else:
        text = "⏰ Напоминания не настроены.\n\nНажми кнопку ниже:"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Настроить напоминания", callback_data="setup_reminder")],
        [InlineKeyboardButton(text="🗑 Удалить напоминание", callback_data="delete_reminder_confirm")]
    ])
    await message.answer(text, reply_markup=keyboard)

@router.callback_query(lambda c: c.data == 'delete_reminder_confirm')
async def delete_reminder_callback(callback_query: CallbackQuery):
    # Страховка: проверяем, что нажал админ
    if not is_admin_by_id(callback_query.from_user.id):
        await callback_query.answer("🔒 Только для админа.", show_alert=True)
        return
    
    reminders = await get_reminders()
    
    # Если напоминаний нет, честно говорим об этом
    if not reminders:
        await callback_query.answer("Напоминания и так не настроены.", show_alert=True)
        return
        
    # Удаляем все напоминания без привязки к ID
    await delete_all_reminders()
    
    await callback_query.message.answer("🗑 Напоминания успешно удалены. Бот больше не будет их присылать.")
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'setup_reminder')
async def setup_reminder_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    reminder_steps[user_id] = {"days": []}
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пн", callback_data="rem_day_1"), InlineKeyboardButton(text="Вт", callback_data="rem_day_2"), InlineKeyboardButton(text="Ср", callback_data="rem_day_3")],
        [InlineKeyboardButton(text="Чт", callback_data="rem_day_4"), InlineKeyboardButton(text="Пт", callback_data="rem_day_5"), InlineKeyboardButton(text="Сб", callback_data="rem_day_6")],
        [InlineKeyboardButton(text="Вс", callback_data="rem_day_7")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="rem_days_done")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reminder")]
    ])
    await callback_query.message.answer("⏰ *Настройка напоминаний*\n\nВыбери дни недели для напоминаний:\n(можно выбрать несколько)", reply_markup=keyboard, parse_mode="Markdown")
    await callback_query.answer()

@router.callback_query(lambda c: c.data.startswith('rem_day_'))
async def rem_day_callback(callback_query: CallbackQuery):
    day = callback_query.data.replace('rem_day_', '')
    user_id = callback_query.from_user.id
    if user_id not in reminder_steps:
        reminder_steps[user_id] = {"days": []}
    days = reminder_steps[user_id]["days"]
    if day in days:
        days.remove(day)
    else:
        days.append(day)
    day_names = {'1': 'Пн', '2': 'Вт', '3': 'Ср', '4': 'Чт', '5': 'Пт', '6': 'Сб', '7': 'Вс'}
    selected = [day_names[d] for d in sorted(days)]
    selected_text = ', '.join(selected) if selected else 'не выбрано'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Пн" if '1' in days else "Пн", callback_data="rem_day_1"), InlineKeyboardButton(text="✅ Вт" if '2' in days else "Вт", callback_data="rem_day_2"), InlineKeyboardButton(text="✅ Ср" if '3' in days else "Ср", callback_data="rem_day_3")],
        [InlineKeyboardButton(text="✅ Чт" if '4' in days else "Чт", callback_data="rem_day_4"), InlineKeyboardButton(text="✅ Пт" if '5' in days else "Пт", callback_data="rem_day_5"), InlineKeyboardButton(text="✅ Сб" if '6' in days else "Сб", callback_data="rem_day_6")],
        [InlineKeyboardButton(text="✅ Вс" if '7' in days else "Вс", callback_data="rem_day_7")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="rem_days_done")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reminder")]
    ])
    await callback_query.message.edit_text(f"⏰ *Настройка напоминаний*\n\nВыбраны дни: *{selected_text}*\n\nНажми '✅ Готово', когда закончишь выбор:", reply_markup=keyboard, parse_mode="Markdown")
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'rem_days_done')
async def rem_days_done_callback(callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    if user_id not in reminder_steps or not reminder_steps[user_id]["days"]:
        await callback_query.message.answer(" Выбери хотя бы один день!")
        await callback_query.answer()
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reminder")]])
    await callback_query.message.answer("⏰ Отлично! Теперь введи время напоминания:\n\nНапример: `18:00` или `20:30`", reply_markup=keyboard, parse_mode="Markdown")
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'cancel_reminder')
async def cancel_reminder_callback(callback_query: CallbackQuery):
    if callback_query.from_user.id in reminder_steps:
        del reminder_steps[callback_query.from_user.id]
    await callback_query.message.answer("❌ Настройка напоминаний отменена.")
    await callback_query.answer()

@router.message(Command("test_reminder"))
async def cmd_test_reminder(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    logger.info(" Тест напоминаний запущен")
    lazy_users = await get_users_without_workout_today()
    logger.info(f"🧪 Найдено ленивых пользователей: {len(lazy_users)}")
    if not lazy_users:
        return await message.answer("📭 Нет пользователей для напоминания")
    sent_count = 0
    for telegram_id, name in lazy_users:
        if telegram_id == ADMIN_ID:
            continue
        try:
            await bot.send_sticker(telegram_id, STICKER_REMINDER)
            await bot.send_message(telegram_id, f"👋 {name}, тренировка! Devon Larratt ждёт тебя! 💪\n\n(Это тестовое напоминание)")
            sent_count += 1
        except Exception as e:
            logger.error(f"❌ Ошибка отправки {telegram_id}: {e}")
    await message.answer(f"🧪 Тест завершён. Отправлено: {sent_count} из {len(lazy_users)}")

@router.message(Command("debug_users"))
async def cmd_debug_users(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    import aiosqlite
    from database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, telegram_id, name, role, is_blocked FROM users")
        users = await cursor.fetchall()
        today = datetime.now().strftime("%Y-%m-%d")
        cursor2 = await db.execute("SELECT user_id FROM workouts WHERE date = ?", (today,))
        trained_today = set(row[0] for row in await cursor2.fetchall())
    text = "👥 Все пользователи:\n\n"
    text += f"🔑 Твой ID: {message.from_user.id}\n🔑 ADMIN_ID в .env: {ADMIN_ID}\n\n"
    for u_id, tg_id, name, role, is_blocked in users:
        trained = "✅ тренировался" if u_id in trained_today else "❌ не тренировался"
        has_tg = f"telegram_id={tg_id}" if tg_id else " нет telegram_id"
        blocked = " заблокирован" if is_blocked else ""
        text += f"• {name} (id={u_id}, {has_tg}, роль={role}) — {trained} {blocked}\n"
    await message.answer(text)

@router.message(Command("reminder_status"))
async def cmd_reminder_status(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    current_day = str(now.weekday() + 1)
    day_names = {'1': 'Пн', '2': 'Вт', '3': 'Ср', '4': 'Чт', '5': 'Пт', '6': 'Сб', '7': 'Вс'}
    reminders = await get_reminders()
    text = f"⏰ **Статус напоминаний**\n\n🕐 Текущее время: **{current_time}**\n📅 Сегодня: **{day_names.get(current_day, current_day)}**\n\n"
    if not reminders:
        text += "⏸️ Напоминания не настроены"
    else:
        text += f"📋 Настроено напоминаний: **{len(reminders)}**\n\n"
        for user_id, days, time in reminders:
            days_text = ', '.join([day_names.get(d, d) for d in days.split(',')])
            is_today = current_day in days.split(',')
            status = "✅ сегодня" if is_today else "⏸️ не сегодня"
            text += f"• {days_text} в {time} — {status}\n"
    await message.answer(text, parse_mode="Markdown")

# ==================== СООБЩЕНИЯ И ЧАТ ====================

@router.message(Command("students"))
async def cmd_students(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    students = await get_all_students()
    if not students:
        return await message.answer("📭 В базе нет пользователей.")
    text = "👥 Список учеников:\n\n"
    for user_db_id, telegram_id, name in students:
        is_admin_mark = " " if telegram_id == ADMIN_ID else ""
        unread = await get_unread_count(telegram_id)
        unread_mark = f" ({unread} непрочит.)" if unread > 0 else ""
        text += f"• {name} (id: {telegram_id}){is_admin_mark}{unread_mark}\n"
    await message.answer(text)

@router.message(Command("chat"))
@router.message(F.text.lower().contains("чат с учеником"))
async def cmd_chat_start(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    keyboard = await build_students_keyboard("chat_")
    if not keyboard.inline_keyboard or len(keyboard.inline_keyboard) <= 1:
        return await message.answer("📭 Нет учеников для чата.")
    await message.answer(" *Чат с учеником*\n\nВыбери ученика, которому хочешь написать:", reply_markup=keyboard, parse_mode="Markdown")

@router.callback_query(lambda c: c.data.startswith('chat_'))
async def chat_select_callback(callback_query: CallbackQuery):
    if not is_admin_by_id(callback_query.from_user.id):
        await callback_query.answer("🔒 Только для админа.", show_alert=True)
        return
    student_id = int(callback_query.data.replace('chat_', ''))
    student_info = await get_user_by_telegram_id(student_id)
    if not student_info:
        await callback_query.message.answer("❌ Ученик не найден.")
        await callback_query.answer()
        return
    student_name = student_info[2]
    chat_sessions[callback_query.from_user.id] = student_id
    await mark_as_read(student_id, ADMIN_ID)
    await callback_query.message.answer(
        f"💬 Чат с *{student_name}* начат.\n\nТеперь пиши сообщения — они будут пересылаться ученику.\nЧтобы выйти, напиши /exit",
        parse_mode="Markdown")
    await callback_query.answer()

@router.message(Command("send_workout"))
@router.message(F.text.lower().contains("тренировка ученику"))
async def cmd_send_workout_start(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    keyboard = await build_students_keyboard("send_")
    if not keyboard.inline_keyboard or len(keyboard.inline_keyboard) <= 1:
        return await message.answer("📭 Нет учеников.")
    await message.answer("🏋️ *Отправка тренировки ученику*\n\nВыбери ученика:", reply_markup=keyboard, parse_mode="Markdown")

@router.callback_query(lambda c: c.data.startswith('send_'))
async def send_workout_select_callback(callback_query: CallbackQuery):
    if not is_admin_by_id(callback_query.from_user.id):
        await callback_query.answer("🔒 Только для админа.", show_alert=True)
        return
    student_id = int(callback_query.data.replace('send_', ''))
    student_info = await get_user_by_telegram_id(student_id)
    if not student_info:
        await callback_query.message.answer("❌ Ученик не найден.")
        await callback_query.answer()
        return
    student_name = student_info[2]
    send_workout_sessions[callback_query.from_user.id] = student_id
    await callback_query.message.answer(
        f"🏋️ Запись тренировки для *{student_name}*.\n\nНапиши упражнения и примечания:\n`Жим 20 3 10, Пронация 15 4 12`\n`Не забывай разминать запястье!`\n\nЧтобы отменить, напиши /exit",
        parse_mode="Markdown")
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'cancel_student_select')
async def cancel_student_select_callback(callback_query: CallbackQuery):
    await callback_query.message.answer("❌ Выбор ученика отменён.")
    await callback_query.answer()

@router.message(F.text.lower().contains("написать тренеру"))
async def cmd_write_to_coach(message: Message):
    if is_admin(message):
        return
    awaiting_student_message.add(message.from_user.id)
    await message.answer(
        "✏️ *Напиши сообщение тренеру:*\n\n"
        "Просто напиши текст — он будет переслан тренеру.\n"
        "Чтобы отменить, напиши /cancel",
        parse_mode="Markdown"
    )

@router.message(Command("messages"))
@router.message(F.text.lower().contains("сообщения"))
async def cmd_messages(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    
    students = await get_all_students()
    if not students:
        return await message.answer("📭 Нет учеников.")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    has_unread = False
    
    for user_db_id, telegram_id, name in students:
        if telegram_id == ADMIN_ID:
            continue
        
        # ИСПРАВЛЕНО: считаем непрочитанные ИМЕННО от этого ученика для админа
        unread = await get_unread_count_from_sender(telegram_id, ADMIN_ID)
        badge = f" ({unread})" if unread > 0 else ""
        
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"{name}{badge}", callback_data=f"view_chat_{telegram_id}")])
        if unread > 0:
            has_unread = True
            
    if not has_unread:
        keyboard.inline_keyboard.insert(0, [InlineKeyboardButton(text="✅ Непрочитанных нет", callback_data="noop")])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="close_messages")])
    
    await message.answer("📬 Сообщения от учеников\n\nВыбери ученика:", reply_markup=keyboard, parse_mode="Markdown")

@router.callback_query(lambda c: c.data.startswith('view_chat_'))
async def view_chat_callback(callback_query: CallbackQuery):
    if not is_admin_by_id(callback_query.from_user.id):
        await callback_query.answer(" Только для админа.", show_alert=True)
        return
    student_id = int(callback_query.data.replace('view_chat_', ''))
    student_info = await get_user_by_telegram_id(student_id)
    if not student_info:
        await callback_query.message.answer("❌ Ученик не найден.")
        await callback_query.answer()
        return
    student_name = student_info[2]
    await mark_as_read(student_id, ADMIN_ID)
    history = await get_chat_history(ADMIN_ID, student_id, limit=30)
    if not history:
        text = f"📭 История переписки с *{student_name}* пуста."
    else:
        text = f"💬 *Переписка с {student_name}* (последние 30):\n\n"
        for sender_id, msg_text, timestamp, is_read in reversed(history):
            sender_mark = "👨‍🏫" if sender_id == ADMIN_ID else "👤"
            display_text = msg_text if len(msg_text) <= 100 else msg_text[:100] + "..."
            display_text = display_text.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
            text += f"{sender_mark} [{timestamp}]: {display_text}\n\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Написать", callback_data=f"chat_{student_id}")],
        [InlineKeyboardButton(text="🏋️ Записать тренировку", callback_data=f"send_{student_id}")],
        [InlineKeyboardButton(text=" Назад к сообщениям", callback_data="back_messages")]
    ])
    await callback_query.message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'back_messages')
async def back_messages_callback(callback_query: CallbackQuery):
    if not is_admin_by_id(callback_query.from_user.id):
        await callback_query.answer("🔒 Только для админа.", show_alert=True)
        return
    students = await get_all_students()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for user_db_id, telegram_id, name in students:
        if telegram_id == ADMIN_ID:
            continue
        # ИСПРАВЛЕНО: правильный подсчет при возврате назад
        unread = await get_unread_count_from_sender(telegram_id, ADMIN_ID)
        badge = f" ({unread})" if unread > 0 else ""
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"{name}{badge}", callback_data=f"view_chat_{telegram_id}")])
    await callback_query.message.edit_text("📬 *Сообщения от учеников*\n\nВыбери ученика:", reply_markup=keyboard, parse_mode="Markdown")
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'close_messages')
async def close_messages_callback(callback_query: CallbackQuery):
    await callback_query.message.answer("📬 Закрыто.")
    await callback_query.answer()

@router.callback_query(lambda c: c.data == 'noop')
async def noop_callback(callback_query: CallbackQuery):
    await callback_query.answer()

@router.message(F.sticker)
async def handle_sticker(message: Message):
    # Если заблокирован — игнорируем
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
async def handle_any_text(message: Message):
    text = message.text
    if text.startswith('/'):
        return
    if text.strip() in {btn.strip() for btn in MENU_BUTTONS}:
        return
    
    # === ПРОВЕРКА БЛОКИРОВКИ ===
    if message.from_user.id != ADMIN_ID:
        if await is_user_blocked(message.from_user.id):
            logger.info(f"🚫 Заблокированный пользователь {message.from_user.id} попытался написать: {text}")
            return  # Просто игнорируем сообщения от заблокированных
    
    # === АДМИН В РЕЖИМЕ ЧАТА С УЧЕНИКОМ ===
    if message.from_user.id in chat_sessions:
        student_id = chat_sessions[message.from_user.id]
        student_info = await get_user_by_telegram_id(student_id)
        student_name = student_info[2] if student_info else "ученик"
        
        await save_message(ADMIN_ID, student_id, text)
        
        try:
            await bot.send_message(
                student_id,
                f"👨‍🏫 *Сообщение от тренера:*\n\n{text}",
                parse_mode="Markdown"
            )
            await message.answer(f"✅ Сообщение отправлено {student_name}.")
        except Exception as e:
            logger.error(f"Ошибка отправки ученику {student_id}: {e}")
            await message.answer(f"❌ Не удалось отправить сообщение: {e}")
        return
    
    # === АДМИН В РЕЖИМЕ ОТПРАВКИ ТРЕНИРОВКИ УЧЕНИКУ ===
    if message.from_user.id in send_workout_sessions:
        student_id = send_workout_sessions[message.from_user.id]
        student_info = await get_user_by_telegram_id(student_id)
        student_name = student_info[2] if student_info else "ученик"
        
        workouts, notes = parse_workouts_with_notes(text)
        
        if not workouts and not notes:
            await message.answer(
                "❌ Не понял, что записать. Напиши упражнения и/или примечания.\n\n"
                "Или /exit чтобы отменить."
            )
            return
        
        student_db_id = await get_or_create_user(student_id, student_name)
        
        results = []
        for exercise, weight, sets, reps in workouts:
            record_msg = await add_workout(student_db_id, exercise, weight, sets, reps)
            results.append(f"️ {exercise}: {weight}кг × {sets}×{reps}")
        
        summary_parts = []
        if results:
            summary_parts.append("📋 *Упражнения:*\n" + "\n".join(results))
        if notes:
            summary_parts.append("📝 *Примечания:*\n" + "\n".join(notes))
        
        summary = "\n\n".join(summary_parts)
        await message.answer(
            f"✅ Тренировка записана для *{student_name}*:\n\n{summary}",
            parse_mode="Markdown"
        )
        
        if notes:
            notes_text = "\n".join(notes)
            await save_message(ADMIN_ID, student_id, f"[Тренировка] {notes_text}")
        
        try:
            student_message = f"‍🏫 *Тренер записал тебе тренировку:*\n\n"
            if results:
                student_message += "📋 *Упражнения:*\n" + "\n".join(results) + "\n\n"
            if notes:
                student_message += "📝 *Примечания от тренера:*\n" + "\n".join(notes) + "\n\n"
            student_message += "💪 Удачи на тренировке!"
            
            await bot.send_message(student_id, student_message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Не удалось уведомить ученика {student_id}: {e}")
        
        del send_workout_sessions[message.from_user.id]
        return
    
    # === УЧЕНИК ПИШЕТ СООБЩЕНИЕ (СВОБОДНЫЙ ЧАТ) ===
    if message.from_user.id != ADMIN_ID:
        student_id = message.from_user.id
        student_name = message.from_user.full_name
        
        # 1. Проверяем, похоже ли на тренировку
        workouts = parse_workouts(text)
        if workouts:
            user_id = await get_or_create_user(student_id, student_name)
            for exercise, weight, sets, reps in workouts:
                record_msg = await add_workout(user_id, exercise, weight, sets, reps)
                streak = await get_user_streak(user_id)
                streak_msg = f"\n🔥 Серия: {streak} {'дней' if streak > 4 else 'дня' if streak > 1 else 'день'}!" if streak > 0 else ""
                await message.answer(f"✅ Записано:\n🏋️ {exercise}: {weight}кг × {sets}×{reps}{record_msg}{streak_msg}")
                
                goal_achieved = await check_and_celebrate_goals(message, user_id)
                if not goal_achieved and record_msg:
                    try:
                        await message.answer_sticker(STICKER_RECORD)
                    except Exception as e:
                        logger.error(f"Ошибка отправки стикера рекорда: {e}")
                if streak >= 5:
                    try:
                        await message.answer_sticker(STICKER_STREAK)
                    except Exception as e:
                        logger.error(f"Ошибка отправки стикера серии: {e}")
            
            # Уведомляем админа о тренировке
            await save_message(student_id, ADMIN_ID, text)
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"🏋️ *{student_name} записал тренировку:*\n\n{text}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить админа о тренировке: {e}")
            return
        
        # 2. Не тренировка — это сообщение тренеру
        await save_message(student_id, ADMIN_ID, text)
        
        try:
            await bot.send_message(
                ADMIN_ID,
                f" *Новое сообщение от {student_name}:*\n\n{text}",
                parse_mode="Markdown"
            )
            logger.info(f"💬 Сообщение от ученика {student_id} ({student_name}) переслано админу")
        except Exception as e:
            logger.error(f"Ошибка пересылки сообщения ученика: {e}")
            await message.answer("❌ Не удалось доставить сообщение тренеру.")
        
        await message.answer("✅ Сообщение отправлено тренеру.")
        
        if student_id in awaiting_student_message:
            awaiting_student_message.remove(student_id)
        return
    
    # === ШАГ НАСТРОЙКИ НАПОМИНАНИЙ ===
    if message.from_user.id in reminder_steps and "days" in reminder_steps[message.from_user.id] and "time" not in reminder_steps[message.from_user.id]:
        match = re.match(r'^(\d{1,2}):(\d{2})$', text.strip())
        if not match:
            return await message.answer(" Неверный формат времени. Напиши ЧЧ:ММ (например, 18:00)\nИли /cancel")
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            return await message.answer(" Неверное время.")
        time_str = f"{hour:02d}:{minute:02d}"
        reminder_steps[message.from_user.id]["time"] = time_str
        user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
        days = ','.join(sorted(reminder_steps[message.from_user.id]["days"]))
        await set_reminder(user_id, days, time_str)
        day_names = {'1': 'Пн', '2': 'Вт', '3': 'Ср', '4': 'Чт', '5': 'Пт', '6': 'Сб', '7': 'Вс'}
        days_text = ', '.join([day_names[d] for d in sorted(reminder_steps[message.from_user.id]["days"])])
        del reminder_steps[message.from_user.id]
        await message.answer(f"✅ Напоминания настроены:\n {days_text} в {time_str}")
        return
    
    # === ШАГ ПОСТАНОВКИ ЦЕЛИ: ввод веса ===
    if message.from_user.id in goal_steps and "exercise" in goal_steps[message.from_user.id] and "weight" not in goal_steps[message.from_user.id]:
        try:
            weight = float(text.replace(',', '.'))
            if weight <= 0:
                raise ValueError
        except ValueError:
            return await message.answer(" Неверный вес. Введи число (например: 30 или 30.5)\nИли /cancel")
        goal_steps[message.from_user.id]["weight"] = weight
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 месяц", callback_data="goal_months_1"), InlineKeyboardButton(text="3 месяца", callback_data="goal_months_3")],
            [InlineKeyboardButton(text="6 месяцев", callback_data="goal_months_6"), InlineKeyboardButton(text="Своя дата", callback_data="goal_custom_date")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_goal")]
        ])
        await message.answer(f"⚖️ Целевой вес: {weight}кг\n\nВыбери срок достижения цели:", reply_markup=keyboard)
        return
    
    # === ШАГ ПОСТАНОВКИ ЦЕЛИ: ввод своей даты ===
    if message.from_user.id in goal_steps and "custom_date" in goal_steps[message.from_user.id]:
        del goal_steps[message.from_user.id]["custom_date"]
        match = re.match(r'^(\d{1,2})[./](\d{1,2})[./](\d{4})$', text.strip())
        if not match:
            return await message.answer("❌ Неверный формат. Напиши ДД.ММ.ГГГГ (например, 01.12.2026)\nИли /cancel")
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if day > 31 or month > 12:
            return await message.answer(" Неверная дата.")
        target_date = f"{day:02d}.{month:02d}.{year}"
        user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
        exercise = goal_steps[message.from_user.id]["exercise"]
        weight = goal_steps[message.from_user.id]["weight"]
        del goal_steps[message.from_user.id]
        await add_goal(user_id, exercise, weight, target_date)
        await message.answer(f"🎯 Цель поставлена:\n{exercise} → {weight}кг к {target_date}")
        return
    
    # Режим просмотра по дате
    if message.from_user.id in awaiting_date_users:
        awaiting_date_users.remove(message.from_user.id)
        match = re.match(r'^(\d{1,2})[./](\d{1,2})$', text.strip())
        if not match:
            return await message.answer("❌ Неверный формат. Напиши ДД.ММ (например, 12.06)")
        day, month = int(match.group(1)), int(match.group(2))
        if day > 31 or month > 12:
            return await message.answer("❌ Неверная дата.")
        user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
        workouts = await get_workouts_by_date(user_id, day, month)
        if not workouts:
            return await message.answer(f"📭 Тренировок {day:02d}.{month:02d} не было.")
        text_msg = f"📅 Тренировки за {day:02d}.{month:02d}:\n\n"
        for w in workouts:
            note = f" ({w[5]})" if w[5] else ""
            text_msg += f"️ {w[1]}: {w[2]}кг × {w[3]}×{w[4]}{note}\n"
        return await message.answer(text_msg)

    # Режим добавления заметки
    if message.from_user.id in adding_note_users:
        workout_id = adding_note_users[message.from_user.id]
        await add_note_to_workout(workout_id, text)
        del adding_note_users[message.from_user.id]
        await message.answer("✅ Заметка сохранена!")
        return
    
    # Режим редактирования
    if message.from_user.id in editing_users:
        workout_id = editing_users[message.from_user.id]
        workouts = parse_workouts(text)
        if not workouts:
            await message.answer("❌ Не понял. Напиши: Жим 20 3 10\nИли /cancel")
            return
        for exercise, weight, sets, reps in workouts:
            await update_workout(workout_id, exercise, weight, sets, reps)
        del editing_users[message.from_user.id]
        user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
        streak = await get_user_streak(user_id)
        streak_msg = f"\n🔥 Серия: {streak} {'дней' if streak > 4 else 'дня' if streak > 1 else 'день'}!" if streak > 0 else ""
        await message.answer(f"✅ Запись обновлена:\n🏋️ {workouts[0][0]}: {workouts[0][1]}кг × {workouts[0][2]}×{workouts[0][3]}{streak_msg}")
        return
    
    # Обычный режим — новая тренировка (для админа)
    workouts = parse_workouts(text)
    if not workouts:
        return
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    for exercise, weight, sets, reps in workouts:
        record_msg = await add_workout(user_id, exercise, weight, sets, reps)
        streak = await get_user_streak(user_id)
        streak_msg = f"\n🔥 Серия: {streak} {'дней' if streak > 4 else 'дня' if streak > 1 else 'день'}!" if streak > 0 else ""
        await message.answer(f"✅ Записано:\n🏋️ {exercise}: {weight}кг × {sets}×{reps}{record_msg}{streak_msg}")
        goal_achieved = await check_and_celebrate_goals(message, user_id)
        if not goal_achieved and record_msg:
            try:
                await message.answer_sticker(STICKER_RECORD)
            except Exception as e:
                logger.error(f"Ошибка отправки стикера рекорда: {e}")
        if streak >= 5:
            try:
                await message.answer_sticker(STICKER_STREAK)
            except Exception as e:
                logger.error(f"Ошибка отправки стикера серии: {e}")

# ==================== ФОНОВЫЕ ЗАДАЧИ ====================

last_reminder_sent_date = None

async def reminder_task():
    global last_reminder_sent_date
    logger.info("⏰ reminder_task запущен")
    while True:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            current_day = str(now.weekday() + 1)
            today_date = now.strftime("%Y-%m-%d")
            reminders = await get_reminders()
            for reminder_user_id, days, time in reminders:
                if current_day not in days.split(','):
                    continue
                if current_time != time:
                    continue
                if last_reminder_sent_date == today_date:
                    logger.info(f"⏰ Напоминание уже отправлено сегодня ({today_date}), пропускаем")
                    continue
                logger.info(f"⏰ ✅ Время совпало! Отправка напоминаний...")
                lazy_users = await get_users_without_workout_today()
                logger.info(f"⏰ Найдено ленивых пользователей: {len(lazy_users)}")
                sent_count = 0
                for telegram_id, name in lazy_users:
                    if telegram_id == ADMIN_ID:
                        continue
                    try:
                        await bot.send_sticker(telegram_id, STICKER_REMINDER)
                        await bot.send_message(telegram_id, f"👋 {name}, тренировка! Devon Larratt ждёт тебя! 💪")
                        sent_count += 1
                    except Exception as e:
                        logger.error(f"⏰ ❌ Ошибка отправки {telegram_id}: {e}")
                last_reminder_sent_date = today_date
                logger.info(f"⏰ Отправлено напоминаний: {sent_count}")
        except Exception as e:
            logger.error(f"⏰ Ошибка в reminder_task: {e}")
        await asyncio.sleep(30)

last_inactive_report_date = None

async def inactive_users_task():
    """Отчет о неактивных учениках (14 дней без тренировок)"""
    global last_inactive_report_date
    logger.info("📉 inactive_users_task запущен")
    while True:
        try:
            now = datetime.now()
            today_date = now.strftime("%Y-%m-%d")
            
            # Отправляем отчет один раз в день в 10:00 утра
            if now.hour == 10 and now.minute < 5:
                if last_inactive_report_date != today_date:
                    inactive_list = await get_inactive_users(days=14)
                    if inactive_list:
                        text = "⚠️ *Отчет о неактивных учениках (14+ дней без тренировок):*\n\n"
                        for telegram_id, name, last_workout in inactive_list:
                            last_date_str = last_workout if last_workout else "никогда"
                            text += f"• {name} (последняя: {last_date_str})\n"
                        try:
                            await bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
                            logger.info("📉 Отчет о неактивных отправлен админу")
                        except Exception as e:
                            logger.error(f"Ошибка отчета о неактивных: {e}")
                    last_inactive_report_date = today_date
        except Exception as e:
            logger.error(f"Ошибка в inactive_users_task: {e}")
        await asyncio.sleep(3600)  # Проверка каждый час

async def main():
    global bot  # Разрешаем изменять глобальную переменную bot
    await init_db()
    
    # --- БЛОК ИНИЦИАЛИЗАЦИИ БОТА С ПРОКСИ ---
    if PROXY_URL:
        from aiohttp_socks import ProxyConnector
        from aiohttp import ClientSession, ClientTimeout
        from aiogram.client.session.aiohttp import AiohttpSession
        logger.info(f"🌐 Подключаемся через прокси...")
        
        # Увеличиваем таймауты, чтобы бот не падал при временных обрывах связи
        timeout = ClientTimeout(
            total=60,        # Общий таймаут запроса: 60 секунд
            connect=30,      # Таймаут установки соединения: 30 секунд
            sock_connect=30, # Таймаут подключения к сокету: 30 секунд
            sock_read=60     # Таймаут чтения ответа: 60 секунд
        )
        
        connector = ProxyConnector.from_url(PROXY_URL)
        aiohttp_session = ClientSession(connector=connector, timeout=timeout)
        
        session = AiohttpSession()
        session._session = aiohttp_session
        
        bot = Bot(token=BOT_TOKEN, session=session)
    else:
        logger.info("🌐 Прокси не указан, подключаемся напрямую")
        bot = Bot(token=BOT_TOKEN)
    # ----------------------------------------

    logger.info(f"🤖 Бот запущен... ADMIN_ID={ADMIN_ID}")
    
    asyncio.create_task(reminder_task())
    asyncio.create_task(inactive_users_task())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())