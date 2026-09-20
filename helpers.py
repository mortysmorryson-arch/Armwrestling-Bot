"""
Вспомогательные функции: клавиатуры, проверка прав, экранирование Markdown.

Про escape_md: Telegram Markdown ломается, если в имени пользователя есть
`*`, `_`, `` ` ``, `[` — сообщение не отправится или отрендерится криво
(Markdown-инъекция). Все имена из Telegram перед вставкой в сообщения
с parse_mode нужно прогонять через escape_md.
"""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from config import ADMIN_ID
from database import get_all_students, get_unread_count


def escape_md(text) -> str:
    """Экранирует спецсимволы MarkdownV1/HTML-опасные конструкции в тексте."""
    s = str(text)
    return s.replace("\\", "\\\\").replace("*", "\\*").replace("_", "\\_").replace("`", "\\`").replace("[", "\\[")


def is_admin(message: Message) -> bool:
    """Проверяет, является ли отправитель админом."""
    return message.from_user.id == ADMIN_ID


def is_admin_by_id(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом по его ID."""
    return user_id == ADMIN_ID


async def get_unread_badge() -> str:
    """Возвращает строку с бейджем непрочитанных сообщений для админа."""
    count = await get_unread_count(ADMIN_ID)
    return f" ({count})" if count > 0 else ""


async def get_main_keyboard_async(admin: bool = False) -> ReplyKeyboardMarkup:
    """
    Создаёт главное меню с кнопками.
    Если admin=True — добавляет админ-кнопки.
    """
    kb = [
        [KeyboardButton(text="📝 Записать тренировку"), KeyboardButton(text="📋 Последняя")],
        [KeyboardButton(text="📊 Моя статистика"), KeyboardButton(text="📈 Прогресс")],
        [KeyboardButton(text="🔥 Серия"), KeyboardButton(text="📅 По дате")],
        [KeyboardButton(text="⚙️ Управление"), KeyboardButton(text="🎯 Цели")],
        [KeyboardButton(text="🎯 Поставить цель"), KeyboardButton(text="❓ Помощь")],
    ]

    if admin:
        unread_badge = await get_unread_badge()
        kb.append([
            KeyboardButton(text="🔐 Все ученики"),
            KeyboardButton(text="😴 Кто ленится"),
            KeyboardButton(text="📥 Экспорт CSV"),
        ])
        kb.append([
            KeyboardButton(text="🏆 Рейтинг"),
            KeyboardButton(text="⏰ Напоминания"),
        ])
        kb.append([
            KeyboardButton(text="💬 Чат с учеником"),
            KeyboardButton(text="🏋️ Тренировка ученику"),
        ])
        kb.append([KeyboardButton(text=f"📬 Сообщения{unread_badge}")])
        kb.append([
            KeyboardButton(text="🔗 Пригласить ученика"),
            KeyboardButton(text="👥 Управление учениками"),
        ])
    else:
        kb.append([KeyboardButton(text="💬 Написать тренеру")])

    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


async def build_students_keyboard(action_prefix: str) -> InlineKeyboardMarkup:
    """
    Создаёт инлайн-клавиатуру со списком учеников (кроме админа).
    action_prefix — префикс для callback_data (например, 'chat_' или 'send_').
    """
    students = await get_all_students()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for user_db_id, telegram_id, name in students:
        if telegram_id == ADMIN_ID:
            continue
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(
                text=name,
                callback_data=f"{action_prefix}{telegram_id}"
            )
        ])
    keyboard.inline_keyboard.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_student_select")
    ])
    return keyboard