"""
Состояния для aiogram FSM.
"""
from aiogram.fsm.state import State, StatesGroup


class GoalStates(StatesGroup):
    choosing_exercise = State()
    entering_weight = State()
    choosing_deadline = State()
    entering_custom_date = State()


class ReminderStates(StatesGroup):
    choosing_days = State()
    entering_time = State()


class EditStates(StatesGroup):
    waiting_for_new_data = State()


class NoteStates(StatesGroup):
    """Состояние для добавления заметки к тренировке."""
    waiting_for_note = State()


class DateStates(StatesGroup):
    """Состояние для просмотра тренировок по дате."""
    waiting_for_date = State()