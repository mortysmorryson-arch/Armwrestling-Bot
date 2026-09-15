"""
Роутер для админ-команд: приглашения, блокировки, статистика, рейтинг, напоминания (FSM) и т.д.
"""
import csv
import io
from pathlib import Path
import logging
import re
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import (
    block_user,
    create_invite_token,
    deactivate_invite,
    delete_all_reminders,
    export_all_workouts,
    get_all_invites,
    get_all_users_stats,
    get_lazy_users,
    get_monthly_rating,
    get_reminders,
    get_user_by_telegram_id,
    get_users_without_workout_today,
    set_reminder,
    unblock_user,
    get_or_create_user,
)
from helpers import is_admin, is_admin_by_id
from states import ReminderStates  # импортируем состояния

logger = logging.getLogger(__name__)

router = Router()


# ========== ПРИГЛАШЕНИЯ ==========

@router.message(Command("invite"))
@router.message(F.text.lower().contains("пригласить ученика"))
async def cmd_invite(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    token = await create_invite_token(message.from_user.id)
    bot_username = (await message.bot.get_me()).username
    link_url = f"https://t.me/{bot_username}?start=link_{token}"
    qr_url = f"https://t.me/{bot_username}?start=qr_{token}"
    await message.answer(
        f"🔗 Приглашение создано!\n\n"
        f"🔑 Токен: {token}\n\n"
        f"📩 Ссылка для рассылки:\n{link_url}\n\n"
        f"📱 Ссылка для QR-кода:\n{qr_url}\n\n"
        f"Обе ссылки ведут на один токен. Ниже — QR-код для печати."
    )
    try:
        import qrcode
        qr_img = qrcode.make(qr_url)
        buf = io.BytesIO()
        qr_img.save(buf, format='PNG')
        buf.seek(0)
        qr_photo = BufferedInputFile(buf.getvalue(), filename=f"invite_{token}.png")
        await message.answer_photo(qr_photo, caption=f"📱 QR-код для приглашения\nТокен: {token}")
    except ImportError:
        await message.answer("⚠️ Библиотека qrcode не установлена.\nУстанови: pip install qrcode[pil]")


@router.message(Command("invites"))
async def cmd_invites(message: Message):
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
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Использование: `/revoke TOKEN`", parse_mode="Markdown")
    token = args[1]
    await deactivate_invite(token)
    await message.answer(f"✅ Приглашение `{token}` деактивировано.", parse_mode="Markdown")


# ========== БЛОКИРОВКИ ==========

@router.message(Command("block"))
async def cmd_block(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Использование: `/block USER_ID`", parse_mode="Markdown")
    try:
        user_id = int(args[1])
    except ValueError:
        return await message.answer("❌ Неверный USER_ID.")
    await block_user(user_id)
    user_info = await get_user_by_telegram_id(user_id)
    user_name = user_info[2] if user_info else "неизвестный"
    await message.answer(f"🚫 Пользователь *{user_name}* (ID: {user_id}) заблокирован.", parse_mode="Markdown")
    try:
        await message.bot.send_message(user_id, "🚫 *Ваш доступ к боту заблокирован.*\n\nОбратитесь к тренеру.", parse_mode="Markdown")
    except Exception:
        pass


@router.message(Command("unblock"))
async def cmd_unblock(message: Message):
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
    user_name = user_info[2] if user_info else "неизвестный"
    await message.answer(f"✅ Пользователь *{user_name}* (ID: {user_id}) разблокирован.", parse_mode="Markdown")
    try:
        await message.bot.send_message(user_id, "✅ *Ваш доступ восстановлен!*", parse_mode="Markdown")
    except Exception:
        pass


@router.message(Command("manage_students"))
@router.message(F.text.lower().contains("управление учениками"))
async def cmd_manage_students(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    import aiosqlite
    from database import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT telegram_id, name, is_blocked FROM users WHERE telegram_id IS NOT NULL ORDER BY name")
        users = await cursor.fetchall()
    if not users:
        return await message.answer("📭 Нет пользователей.")
    text = "👥 *Управление учениками:*\n\n"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for telegram_id, name, is_blocked in users:
        if telegram_id == message.from_user.id:  # admin
            continue
        status = "🚫" if is_blocked else "✅"
        text += f"{status} {name} (ID: {telegram_id})\n"
        action = "unblock" if is_blocked else "block"
        action_text = "Разблокировать" if is_blocked else "Заблокировать"
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=f"{action_text} {name}", callback_data=f"{action}_student_{telegram_id}")
        ])
    keyboard.inline_keyboard.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="close_manage")])
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
        await callback_query.bot.send_message(student_id, "🚫 *Ваш доступ к боту заблокирован.*", parse_mode="Markdown")
    except Exception:
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
        await callback_query.bot.send_message(student_id, "✅ *Ваш доступ восстановлен!*", parse_mode="Markdown")
    except Exception:
        pass
    await callback_query.answer()


@router.callback_query(lambda c: c.data == 'close_manage')
async def close_manage_callback(callback_query: CallbackQuery):
    await callback_query.message.answer("👥 Закрыто.")
    await callback_query.answer()


# ========== СТАТИСТИКА И ЭКСПОРТ ==========

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
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, count) in enumerate(rating):
        medal = medals[i] if i < 3 else "🏅"
        word = "тренировка" if count == 1 else "тренировки" if count < 5 else "тренировок"
        text += f"{medal} {name}: {count} {word}\n"
    await message.answer(text)


# ========== НАПОМИНАНИЯ (FSM) ==========

@router.message(Command("reminder"))
@router.message(F.text.lower().contains("напоминания"))
async def cmd_reminder(message: Message, state: FSMContext):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    reminders = await get_reminders()
    if reminders:
        text = "⏰ Текущие напоминания:\n\n"
        day_names = {'1': 'Пн', '2': 'Вт', '3': 'Ср', '4': 'Чт', '5': 'Пт', '6': 'Сб', '7': 'Вс'}
        for user_id, days, time, reminder_text in reminders:
            days_text = ', '.join([day_names.get(d, d) for d in days.split(',')])
            text += f"📅 {days_text} в {time}"
            if reminder_text:
                text += f" — {reminder_text}"
            text += "\n"
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
    if not is_admin_by_id(callback_query.from_user.id):
        await callback_query.answer("🔒 Только для админа.", show_alert=True)
        return
    reminders = await get_reminders()
    if not reminders:
        await callback_query.answer("Напоминания и так не настроены.", show_alert=True)
        return
    await delete_all_reminders()
    await callback_query.message.answer("🗑 Напоминания успешно удалены.")
    await callback_query.answer()


# --- Настройка напоминаний (FSM) ---

@router.callback_query(lambda c: c.data == 'setup_reminder')
async def setup_reminder_callback(callback_query: CallbackQuery, state: FSMContext):
    if not is_admin_by_id(callback_query.from_user.id):
        await callback_query.answer("🔒 Только для админа.", show_alert=True)
        return
    await state.set_state(ReminderStates.choosing_days)
    await state.update_data(days=[])
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пн", callback_data="rem_day_1"),
         InlineKeyboardButton(text="Вт", callback_data="rem_day_2"),
         InlineKeyboardButton(text="Ср", callback_data="rem_day_3")],
        [InlineKeyboardButton(text="Чт", callback_data="rem_day_4"),
         InlineKeyboardButton(text="Пт", callback_data="rem_day_5"),
         InlineKeyboardButton(text="Сб", callback_data="rem_day_6")],
        [InlineKeyboardButton(text="Вс", callback_data="rem_day_7")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="rem_days_done")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reminder")]
    ])
    await callback_query.message.answer("⏰ *Настройка напоминаний*\n\nВыбери дни недели (можно несколько):", reply_markup=keyboard, parse_mode="Markdown")
    await callback_query.answer()


@router.callback_query(StateFilter(ReminderStates.choosing_days), lambda c: c.data.startswith('rem_day_'))
async def rem_day_callback(callback_query: CallbackQuery, state: FSMContext):
    day = callback_query.data.replace('rem_day_', '')
    data = await state.get_data()
    days = data.get('days', [])
    if day in days:
        days.remove(day)
    else:
        days.append(day)
    await state.update_data(days=days)
    day_names = {'1': 'Пн', '2': 'Вт', '3': 'Ср', '4': 'Чт', '5': 'Пт', '6': 'Сб', '7': 'Вс'}
    selected = [day_names[d] for d in sorted(days)]
    selected_text = ', '.join(selected) if selected else 'не выбрано'
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Пн" if '1' in days else "Пн", callback_data="rem_day_1"),
         InlineKeyboardButton(text="✅ Вт" if '2' in days else "Вт", callback_data="rem_day_2"),
         InlineKeyboardButton(text="✅ Ср" if '3' in days else "Ср", callback_data="rem_day_3")],
        [InlineKeyboardButton(text="✅ Чт" if '4' in days else "Чт", callback_data="rem_day_4"),
         InlineKeyboardButton(text="✅ Пт" if '5' in days else "Пт", callback_data="rem_day_5"),
         InlineKeyboardButton(text="✅ Сб" if '6' in days else "Сб", callback_data="rem_day_6")],
        [InlineKeyboardButton(text="✅ Вс" if '7' in days else "Вс", callback_data="rem_day_7")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="rem_days_done")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reminder")]
    ])
    await callback_query.message.edit_text(
        f"⏰ *Настройка напоминаний*\n\nВыбраны дни: *{selected_text}*\n\nНажми '✅ Готово' для продолжения:",
        reply_markup=keyboard, parse_mode="Markdown"
    )
    await callback_query.answer()


@router.callback_query(StateFilter(ReminderStates.choosing_days), lambda c: c.data == 'rem_days_done')
async def rem_days_done_callback(callback_query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    days = data.get('days', [])
    if not days:
        await callback_query.message.answer("❌ Выбери хотя бы один день!")
        await callback_query.answer()
        return
    await state.set_state(ReminderStates.entering_time)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_reminder")]])
    await callback_query.message.answer(
        "⏰ Отлично! Теперь напиши время в формате ЧЧ:ММ. Можешь добавить любой текст, главное чтобы время было указано, например:\n"
        "`18:00` или `в 18:00` или `завтра в 18:00`",
        reply_markup=keyboard, parse_mode="Markdown"
    )
    await callback_query.answer()


@router.message(StateFilter(ReminderStates.entering_time), F.text)
async def rem_enter_time(message: Message, state: FSMContext):
    full_text = message.text.strip()
    match = re.search(r'(\d{1,2}):(\d{2})', full_text)
    if not match:
        await message.answer("❌ Не удалось найти время в формате ЧЧ:ММ. Напиши, например:\n`18:00` или `в 18:00`\nИли /cancel чтобы отменить.")
        return
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        await message.answer("❌ Неверное время.")
        return
    time_str = f"{hour:02d}:{minute:02d}"
    data = await state.get_data()
    days = data.get('days', [])
    if not days:
        await message.answer("❌ Ошибка: не выбраны дни. Начни заново.")
        await state.clear()
        return
    days_str = ','.join(sorted(days))
    db_user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    await set_reminder(db_user_id, days_str, time_str, full_text)
    day_names = {'1': 'Пн', '2': 'Вт', '3': 'Ср', '4': 'Чт', '5': 'Пт', '6': 'Сб', '7': 'Вс'}
    days_text = ', '.join([day_names[d] for d in sorted(days)])
    await state.clear()
    await message.answer(f"✅ Напоминания настроены:\n📅 {days_text} в {time_str}\n📝 Текст: {full_text}")


@router.callback_query(lambda c: c.data == 'cancel_reminder')
async def cancel_reminder_callback(callback_query: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback_query.message.answer("❌ Настройка напоминаний отменена.")
    await callback_query.answer()


# ========== ТЕСТОВЫЕ И ОТЛАДОЧНЫЕ ==========

@router.message(Command("test_reminder"))
async def cmd_test_reminder(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    lazy_users = await get_users_without_workout_today()
    if not lazy_users:
        return await message.answer("📭 Нет пользователей для напоминания")
    sent_count = 0
    for telegram_id, name in lazy_users:
        if telegram_id == message.from_user.id:
            continue
        try:
            await message.bot.send_message(telegram_id, f"👋 {name}, тренировка! 💪\n\n(Тестовое)")
            sent_count += 1
        except Exception as e:
            logger.error(f"Ошибка отправки {telegram_id}: {e}")
    await message.answer(f"🧪 Тест завершён. Отправлено: {sent_count}")


@router.message(Command("debug_users"))
async def cmd_debug_users(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    import aiosqlite
    from database import DB_PATH
    from config import ADMIN_ID
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, telegram_id, name, role, is_blocked FROM users")
        users = await cursor.fetchall()
        today = datetime.now().strftime("%Y-%m-%d")
        cursor2 = await db.execute("SELECT user_id FROM workouts WHERE date = ?", (today,))
        trained_today = set(row[0] for row in await cursor2.fetchall())
    text = "👥 Все пользователи:\n\n"
    text += f"🔑 Твой ID: {message.from_user.id}\n🔑 ADMIN_ID: {ADMIN_ID}\n\n"
    for u_id, tg_id, name, role, is_blocked in users:
        trained = "✅ тренировался" if u_id in trained_today else "❌ не тренировался"
        has_tg = f"telegram_id={tg_id}" if tg_id else "нет telegram_id"
        blocked = " заблокирован" if is_blocked else ""
        text += f"• {name} (id={u_id}, {has_tg}, роль={role}) — {trained}{blocked}\n"
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
        for _user_id, days, time, _rtext in reminders:
            days_text = ', '.join([day_names.get(d, d) for d in days.split(',')])
            is_today = current_day in days.split(',')
            status = "✅ сегодня" if is_today else "⏸️ не сегодня"
            text += f"• {days_text} в {time} — {status}\n"
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("students"))
async def cmd_students(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    from database import get_all_students, get_unread_count_from_sender
    students = await get_all_students()
    if not students:
        return await message.answer("📭 В базе нет пользователей.")
    text = "👥 Список учеников:\n\n"
    for user_db_id, telegram_id, name in students:
        if telegram_id == message.from_user.id:
            continue
        unread = await get_unread_count_from_sender(telegram_id, message.from_user.id)
        unread_mark = f" ({unread} непрочит.)" if unread > 0 else ""
        text += f"• {name} (id: {telegram_id}){unread_mark}\n"
    await message.answer(text)

# ========== ЗДОРОВЬЕ БОТА (observability) ==========

@router.message(Command("health"))
async def cmd_health(message: Message):
    """Статус компонентов: модели, БД, индекс базы знаний."""
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    from database import DB_PATH, get_reminders
    from model_registry import get_registry

    lines = ["🩺 <b>Состояние бота</b>\n"]

    reg = get_registry()
    if reg:
        alive = [m for m in reg.models if m.available]
        lines.append(f"🤖 Модели: {len(alive)}/{len(reg.models)} живых")
        for m in reg.models:
            status = "✅" if m.available else "❌"
            lat = f" ({m.latency:.2f}с)" if m.available else ""
            lines.append(f"   {status} {m.name}{lat}")
    else:
        lines.append("🤖 Модели: реестр не инициализирован")

    lines.append("")
    import os
    if os.path.exists(DB_PATH):
        size_mb = os.path.getsize(DB_PATH) / 1024 / 1024
        lines.append(f"🗄 БД: {DB_PATH} ({size_mb:.1f} МБ)")
    reminders = await get_reminders()
    lines.append(f"⏰ Напоминаний настроено: {len(reminders)}")

    chroma_meta = Path("chroma_db")
    if chroma_meta.exists():
        total = sum(f.stat().st_size for f in chroma_meta.rglob("*") if f.is_file())
        lines.append(f"📚 Индекс БЗ: {total / 1024:.0f} КБ")

    await message.answer("\n".join(lines), parse_mode="HTML")

@router.message(Command("backup"))
async def cmd_backup(message: Message):
    """Отправляет админу консистентную копию БД (через sqlite backup API).
    Ступенька к домашке про cron-бэкапы: тут тот же механизм, что будет в скрипте."""
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    import aiosqlite
    from database import DB_PATH
    if not Path(DB_PATH).exists():
        return await message.answer("📭 База данных не найдена.")
    backup_path = f"{DB_PATH}.bak"
    import sqlite3
    target = sqlite3.connect(backup_path)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.backup(target)  # консистентный снапшот даже при работающем боте
    target.close()
    doc = BufferedInputFile(Path(backup_path).read_bytes(), filename=f"bot_backup_{datetime.now():%Y-%m-%d_%H-%M}.db")
    await message.answer_document(doc, caption="🗄 Бэкап базы данных")
    Path(backup_path).unlink(missing_ok=True)
