"""
Роутер для чата и сообщений: чат с учеником, отправка тренировки, сообщения от учеников.
"""
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import (
    get_all_students,
    get_chat_history,
    get_unread_count_from_sender,
    get_user_by_telegram_id,
    mark_as_read,
)
from helpers import is_admin, is_admin_by_id, build_students_keyboard
from state import chat_sessions, send_workout_sessions, awaiting_student_message
from config import ADMIN_ID

logger = logging.getLogger(__name__)

router = Router()


# ========== ЧАТ С УЧЕНИКОМ ==========

@router.message(Command("chat"))
@router.message(F.text.lower().contains("чат с учеником"))
async def cmd_chat_start(message: Message):
    if not is_admin(message):
        return await message.answer("🔒 Только для админа.")
    keyboard = await build_students_keyboard("chat_")
    if not keyboard.inline_keyboard or len(keyboard.inline_keyboard) <= 1:
        return await message.answer("📭 Нет учеников для чата.")
    await message.answer("💬 *Чат с учеником*\n\nВыбери ученика:", reply_markup=keyboard, parse_mode="Markdown")


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
        f"💬 Чат с *{student_name}* начат.\n\nПиши сообщения — они будут пересылаться ученику.\nЧтобы выйти, напиши /exit",
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


# ========== СООБЩЕНИЯ ОТ УЧЕНИКОВ ==========

@router.message(F.text.lower().contains("написать тренеру"))
async def cmd_write_to_coach(message: Message):
    if is_admin(message):
        return
    awaiting_student_message.add(message.from_user.id)
    await message.answer(
        "✏️ *Напиши сообщение тренеру:*\n\nПросто напиши текст — он будет переслан тренеру.\nЧтобы отменить, напиши /cancel",
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
        await callback_query.answer("🔒 Только для админа.", show_alert=True)
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
        [InlineKeyboardButton(text="🔙 Назад к сообщениям", callback_data="back_messages")]
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