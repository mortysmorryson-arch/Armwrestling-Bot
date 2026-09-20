"""
Роутер для общих команд: /start, /help, /cancel.
"""
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import (
    get_or_create_user,
    is_user_blocked,
    get_invite_token,
    get_user_by_telegram_id,
)
from helpers import get_main_keyboard_async, is_admin
from state import (
    chat_sessions,
    send_workout_sessions,
    awaiting_student_message,
)
from config import ADMIN_ID
import logging

logger = logging.getLogger(__name__)

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработка /start с параметрами приглашения."""
    start_param = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else None
    is_blocked = await is_user_blocked(message.from_user.id)
    if is_blocked and message.from_user.id != ADMIN_ID:
        await message.answer(
            "🚫 *Ваш доступ к боту заблокирован.*\n\nОбратитесь к тренеру.",
            parse_mode="Markdown"
        )
        return
    invite_token = None
    source = 'direct'
    if start_param:
        if start_param.startswith('link_'):
            invite_token = start_param[5:]
            source = 'ссылка'
        elif start_param.startswith('qr_'):
            invite_token = start_param[3:]
            source = 'QR-код'
        else:
            invite_token = start_param
            source = 'прямая ссылка'
    if invite_token:
        invite = await get_invite_token(invite_token)
        if not invite:
            await message.answer(
                "❌ *Недействительная или неактивная ссылка.*\n\nОбратитесь к тренеру.",
                parse_mode="Markdown"
            )
            return
    await get_or_create_user(
        message.from_user.id,
        message.from_user.full_name,
        invite_token=invite_token,
        source=source
    )
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
            f"Чтобы пригласить ученика, нажми '🔗 Пригласить ученика'.",
            reply_markup=keyboard
        )
        return
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
            f"• Писать тренеру через кнопку '💬 Написать тренеру'\n\n"
            f"💪 Удачи на тренировках!"
        )
    await message.answer(welcome_text, reply_markup=keyboard, parse_mode="Markdown")
    if invite_token and message.from_user.id != ADMIN_ID:
        try:
            await message.bot.send_message(
                ADMIN_ID,
                f"🆕 *Новый ученик зарегистрировался!*\n\n"
                f"👤 Имя: {message.from_user.full_name}\n"
                f"Telegram ID: {message.from_user.id}\n"
                f"📩 Источник: *{source}*\n"
                f"Токен: `{invite_token}`",
                parse_mode="Markdown"
            )
            logger.info(f"🆕 Новый ученик: {message.from_user.full_name} (ID: {message.from_user.id}) по {source}")
        except Exception as e:
            logger.error(f"Не удалось уведомить админа: {e}")


@router.message(Command("help"))
@router.message(F.text.lower().contains("помощь"))
async def cmd_help(message: Message):
    """Справка по боту."""
    text = (
        "📋 Как пользоваться ботом:\n\n"
        "1. Жми '📝 Записать тренировку' или напиши упражнения через запятую:\n"
        "   Жим 20 3 10, Пронация 15 4 12\n"
        "2. Жми '📋 Последняя' — посмотреть/исправить/добавить заметку\n"
        "3. Жми '📊 Моя статистика' для отчета\n"
        "4. Жми '📈 Прогресс' для графика\n"
        "5. Жми '🔥 Серия' — узнать свою серию\n"
        "6. Жми '📅 По дате' — посмотреть тренировки за конкретный день\n"
        "7. Жми '🎯 Поставить цель' — интерактивная постановка цели\n"
        "8. Жми '🎯 Цели' — посмотреть активные цели\n"
        "9. Жми '⚙️ Управление' для удаления упражнений\n"
    )
    if is_admin(message):
        text += (
            "\n🔐 Админ-команды:\n"
            "10. '⏰ Напоминания' — настроить напоминания\n"
            "11. '💬 Чат с учеником' — написать ученику\n"
            "12. '🏋️ Тренировка ученику' — записать тренировку ученику\n"
            "13. '📬 Сообщения' — посмотреть непрочитанные\n"
            "14. '🔗 Пригласить ученика' — создать ссылку и QR-код\n"
            "15. '👥 Управление учениками' — блокировать/разблокировать\n"
            "16. '/students' — список всех учеников\n"
            "17. '/invites' — список всех приглашений\n"
            "18. '/revoke TOKEN' — деактивировать приглашение\n"
            "19. '/block USER_ID' — заблокировать ученика\n"
            "20. '/unblock USER_ID' — разблокировать ученика\n"
            "21. '/exit' — выйти из режима чата\n"
        )
    else:
        text += "\n📩 Для учеников:\n• '💬 Написать тренеру' — отправить сообщение тренеру\n"
    await message.answer(text, parse_mode=None)


@router.message(Command("cancel"))
@router.message(Command("exit"))
async def cmd_cancel(message: Message, state: FSMContext):
    user_id = message.from_user.id

    # Проверяем старые словари (если ещё используются)
    if user_id in chat_sessions:
        # pop удаляет ключ СРАЗУ и возвращает значение. Если ключа нет, вернет None.
        student_id = chat_sessions.pop(user_id, None) 
        student_info = await get_user_by_telegram_id(student_id) if student_id else None
        student_name = student_info[2] if student_info else "ученик"
        await message.answer(f"✅ Чат с {student_name} завершён.")
        await state.clear()
        return
        
    elif user_id in send_workout_sessions:
        student_id = send_workout_sessions.pop(user_id, None)
        student_info = await get_user_by_telegram_id(student_id) if student_id else None
        student_name = student_info[2] if student_info else "ученик"
        await message.answer(f"✅ Отмена отправки тренировки {student_name}.")
        await state.clear()
        return
        
    elif user_id in awaiting_student_message:
        # discard не падает с ошибкой, если элемента нет в множестве
        awaiting_student_message.discard(user_id) 
        await message.answer("❌ Отправка сообщения тренеру отменена.")
        await state.clear()
        return
    else:
        # Проверяем FSM состояние
        current_state = await state.get_state()
        if current_state is not None:
            await state.clear()
            await message.answer("❌ Действие отменено.")
        else:
            await message.answer("Ты ничего не редактируешь.")