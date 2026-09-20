"""
Общие утилиты: парсеры тренировок (переиспользуются из parsers.py — единая
реализация, раньше тут была расходящаяся копия) и проверка целей.
"""
import logging

from aiogram.types import Message

from constants import STICKER_GOAL
from database import (
    get_current_max,
    get_uncelenrated_goals,
    mark_goal_celebrated,
)

# Единая реализация парсеров живёт в parsers.py
from parsers import (  # noqa: F401 — реэкспорт для обратной совместимости
    clean_exercise_name,
    make_progress_bar,
    parse_exercise_line,
    parse_workouts,
    parse_workouts_with_notes,
)

logger = logging.getLogger(__name__)


async def check_and_celebrate_goals(message: Message, user_id: int) -> bool:
    """
    Проверяет достижение непразднованных целей и отправляет поздравление.
    Отпразднованные цели хранятся в БД (goals.celebrated), поэтому после
    рестарта бота поздравления не повторяются (раньше был set в памяти).
    """
    goals = await get_uncelenrated_goals(user_id)
    goal_achieved = False
    for g_id, exercise, target_weight in goals:
        current_max = await get_current_max(user_id, exercise)
        percent = (current_max / target_weight) * 100 if target_weight > 0 else 0
        if percent >= 100:
            try:
                await message.answer_sticker(STICKER_GOAL)
                await message.answer(f"🎉 ЦЕЛЬ ДОСТИГНУТА!\n\n{exercise} → {target_weight}кг\nТы сделал это! Devon Larratt гордится тобой!")
                await mark_goal_celebrated(g_id)
                goal_achieved = True
            except Exception as e:
                logger.error(f"Ошибка отправки стикера цели: {e}")
    return goal_achieved
