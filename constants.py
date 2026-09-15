"""
Константы бота: стикеры, названия кнопок и другие неизменяемые значения.
Вынесены в отдельный модуль для соблюдения принципа Single Responsibility.
"""

# === СТИКЕРЫ ===
# File ID стикеров из Telegram. Можно получить командой /sticker
STICKER_RECORD = "CAACAgIAAxkBAAIBh2oizjGk4UwbQQXQ5mh1ncOqa1QjAAJomgACPP4pS7Apz8oKLfG2OwQ"
STICKER_STREAK = "CAACAgIAAxkBAAIBiGoi2d7_WcVV7_u1drlAIMpNSMafAAJ6XwACyq0oSaCtAAGRoSMCYDsE"
STICKER_GOAL = "CAACAgIAAxkBAAIBiWoi2iRIIM_khRiA94ItAmKaK6xZAAJIlQAC1R8gSxDvBZotMHQKOwQ"
# ВНИМАНИЕ: в старом коде было два разных file_id для этого стикера (…KJUw… и …KJUg…).
# Оставлен вариант из bot.py (…KJUw…), который реально использовался в проде.
# Если стикер напоминания не отправляется — перешли нужный стикер боту и обнови ID.
STICKER_REMINDER = "CAACAgIAAxkBAAIBimoi2oGIKEyTiZkVCXyyNkKH_NVSAAKJUwACM2BBSQdCqXz63ZQDOwQ"
STICKER_MOTIVATION = "CAACAgIAAxkBAAIBi2oi2q9k9iE9NTN9Puc5cMvH7lyLAALrYQACEDSASc-bH-cMP33AOwQ"

# === НАЗВАНИЯ КНОПОК МЕНЮ ===
# Множество (set), чтобы быстро проверять: "это кнопка меню или текст пользователя?"
MENU_BUTTONS = {
    "📝 Записать тренировку",
    "📋 Последняя",
    "📊 Моя статистика",
    "📈 Прогресс",
    "🔥 Серия",
    "📅 По дате",
    "⚙️ Управление",
    "❓ Помощь",
    "🔐 Все ученики",
    "😴 Кто ленится",
    "📥 Экспорт CSV",
    "🏆 Рейтинг",
    "🎯 Цели",
    "🎯 Поставить цель",
    "⏰ Напоминания",
    "💬 Чат с учеником",
    "🏋️ Тренировка ученику",
    "📬 Сообщения",
    "💬 Написать тренеру",
    "🔗 Пригласить ученика",
    "👥 Управление учениками",
}