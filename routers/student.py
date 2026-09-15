"""
Роутер для команд учеников: запись тренировок, статистика, прогресс, цели, управление.
"""
import asyncio 
import io
import logging
import re
from datetime import datetime, timedelta

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
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
    add_goal,
    add_workout,
    delete_exercise,
    delete_goal,
    delete_last_workout,
    get_current_max,
    get_exercise_progress,
    get_last_workout,
    get_user_exercises,
    get_user_goals,
    get_user_stats,
    get_user_streak,
    get_workouts_by_date,
    get_or_create_user,
)
from state import delete_exercise_cache
from constants import STICKER_RECORD, STICKER_STREAK
from utils import (
    parse_workouts,
    make_progress_bar,
    check_and_celebrate_goals,
)
from states import GoalStates, EditStates, NoteStates, DateStates

logger = logging.getLogger(__name__)
router = Router()


# ========== ЗАПИСЬ ТРЕНИРОВКИ ==========

@router.message(Command("log"))
@router.message(F.text.lower().contains("записать тренировку"))
async def cmd_log(message: Message):
    if message.text and "записать тренировку" in message.text.lower():
        return await message.answer("Напиши упражнения через запятую или с новой строки:\nЖим 20 3 10, Пронация 15 4 12")
    text = message.text.replace("/log ", "", 1).strip()
    workouts = parse_workouts(text)
    if not workouts:
        await message.answer("❌ Не понял формат. Напиши:\nЖим 20 3 10, Пронация 15 4 12")
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
                logger.error(f"Ошибка стикера рекорда: {e}")
        if streak >= 5:
            try:
                await message.answer_sticker(STICKER_STREAK)
            except Exception as e:
                logger.error(f"Ошибка стикера серии: {e}")


# ========== ПОСЛЕДНЯЯ ТРЕНИРОВКА ==========

@router.message(Command("last"))
@router.message(F.text.lower().contains("последняя"))
async def cmd_last(message: Message):
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    workout = await get_last_workout(user_id)
    if not workout:
        await message.answer("📭 У тебя ещё нет записей.")
        return
    w_id, date, exercise, weight, sets, reps, notes = workout
    note_text = f"\n📝 Заметка: {notes}" if notes else ""
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
async def edit_last_callback(callback_query: CallbackQuery, state: FSMContext):
    workout_id = int(callback_query.data.replace('edit_last_', ''))
    await state.update_data(workout_id=workout_id)
    await state.set_state(EditStates.waiting_for_new_data)
    await callback_query.message.answer("✏️ Напиши новые данные в формате:\nЖим 20 3 10\n\nИли /cancel чтобы отменить")
    await callback_query.answer()


@router.callback_query(lambda c: c.data.startswith('note_last_'))
async def note_last_callback(callback_query: CallbackQuery, state: FSMContext):
    workout_id = int(callback_query.data.replace('note_last_', ''))
    # Сохраняем ID тренировки в data состояния
    await state.update_data(workout_id=workout_id)
    await state.set_state(NoteStates.waiting_for_note)
    await callback_query.message.answer("📝 Напиши заметку к этой тренировке:\n\nИли /cancel чтобы отменить")
    await callback_query.answer()


@router.callback_query(lambda c: c.data.startswith('delete_last_'))
async def delete_last_callback(callback_query: CallbackQuery):
    user_id = await get_or_create_user(callback_query.from_user.id, callback_query.from_user.full_name)
    deleted = await delete_last_workout(user_id)
    if deleted:
        await callback_query.message.answer("🗑 Последняя тренировка удалена.")
    else:
        await callback_query.message.answer("📭 Нечего удалять.")
    await callback_query.answer()


# ========== СТАТИСТИКА И СЕРИЯ ==========

@router.message(Command("stats"))
@router.message(F.text.lower().contains("моя статистика"))
async def cmd_stats(message: Message):
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    workouts = await get_user_stats(user_id)
    if not workouts:
        await message.answer("📭 Тренировок пока нет.")
        return
    streak = await get_user_streak(user_id)
    streak_text = f"🔥 Текущая серия: {streak} {'дней' if streak > 4 else 'дня' if streak > 1 else 'день'}\n\n" if streak > 0 else ""
    text = f"📊 Твоя статистика (последние 10):\n\n{streak_text}"
    for w in workouts[:10]:
        note = f" ({w[5]})" if w[5] else ""
        text += f"🏋️ {w[0]} | {w[1]}: {w[2]}кг × {w[3]}×{w[4]}{note}\n"
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

def build_progress_chart(dates, weights, exercise):
    """Рисует график прогресса. Вызывается в отдельном потоке."""
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
    return buf.getvalue()

# ========== ПРОГРЕСС ==========

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
            await callback_query.message.answer("📭 Нет данных")
            await callback_query.answer()
            return
        dates = [row[0] for row in progress]
        weights = [row[1] for row in progress]
        # Рисуем график в отдельном потоке — бот не фризит
        image_bytes = await asyncio.to_thread(build_progress_chart, dates, weights, exercise)
        photo = BufferedInputFile(image_bytes, filename="progress.png")
        await callback_query.message.answer_photo(photo, caption="📈 Твой прогресс")
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await callback_query.message.answer(f"❌ Ошибка: {e}")
        await callback_query.answer()


# ========== ПО ДАТЕ ==========

@router.message(Command("date"))
@router.message(F.text.lower().contains("по дате"))
async def cmd_date_prompt(message: Message, state: FSMContext):
    if message.text.lower() in ["📅 по дате", "/date"]:
        await state.set_state(DateStates.waiting_for_date)
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
                return await message.answer(f"📭 Тренировок {day:02d}.{month:02d} не было.")
            text_msg = f"📅 Тренировки за {day:02d}.{month:02d}:\n\n"
            for w in workouts:
                note = f" ({w[5]})" if w[5] else ""
                text_msg += f"🏋️ {w[1]}: {w[2]}кг × {w[3]}×{w[4]}{note}\n"
            return await message.answer(text_msg)
    await state.set_state(DateStates.waiting_for_date)
    await message.answer("Введите дату в формате ДД.ММ (например, 12.06)\nИли /cancel")


# ========== УПРАВЛЕНИЕ УПРАЖНЕНИЯМИ ==========

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
    delete_exercise_cache.pop(short_id, None)
    await callback_query.message.answer(f"✅ Удалено записей: {deleted_count}")
    await callback_query.answer()


@router.callback_query(lambda c: c.data == 'cancel_delete')
async def cancel_delete_callback(callback_query: CallbackQuery):
    await callback_query.message.answer("❌ Отменено")
    await callback_query.answer()


# ========== ЦЕЛИ (FSM) ==========

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
        text += f"🎯 {exercise} → {target_weight}кг (до {target_date})\n{bar}\n{status}\n\n"
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=f"❌ Удалить цель: {exercise}", callback_data=f"delete_goal_{g_id}")])
    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(lambda c: c.data.startswith('delete_goal_'))
async def delete_goal_callback(callback_query: CallbackQuery):
    goal_id = int(callback_query.data.replace('delete_goal_', ''))
    await delete_goal(goal_id)
    await callback_query.message.answer("🗑 Цель удалена.")
    await callback_query.answer()


# ========== ПОСТАНОВКА ЦЕЛИ (FSM) ==========

@router.message(Command("set_goal"))
@router.message(F.text.lower().contains("поставить цель"))
async def cmd_set_goal_start(message: Message, state: FSMContext):
    user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    exercises = await get_user_exercises(user_id)
    if not exercises:
        return await message.answer("📭 У тебя пока нет упражнений. Сначала запиши тренировку.")
    # Сбрасываем состояние (на случай, если предыдущий диалог завис)
    await state.set_state(GoalStates.choosing_exercise)
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


@router.callback_query(lambda c: c.data.startswith('goal_exercise_'), StateFilter(GoalStates.choosing_exercise))
async def goal_exercise_callback(callback_query: CallbackQuery, state: FSMContext):
    exercise = callback_query.data.replace('goal_exercise_', '')
    await state.update_data(exercise=exercise)
    db_user_id = await get_or_create_user(callback_query.from_user.id, callback_query.from_user.full_name)
    current_max = await get_current_max(db_user_id, exercise)
    await state.set_state(GoalStates.entering_weight)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_goal")]])
    await callback_query.message.answer(
        f"🏋️ Выбрано: *{exercise}*\nТекущий максимум: {current_max}кг\n\nВведи целевой вес (например: 30 или 30.5):",
        reply_markup=keyboard, parse_mode="Markdown")
    await callback_query.answer()


# Обработчик ввода веса
@router.message(StateFilter(GoalStates.entering_weight), F.text)
async def goal_enter_weight(message: Message, state: FSMContext):
    text = message.text.strip()
    try:
        weight = float(text.replace(',', '.'))
        if weight <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Неверный вес. Введи число (например: 30 или 30.5)\nИли /cancel")
        return
    await state.update_data(weight=weight)
    await state.set_state(GoalStates.choosing_deadline)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 месяц", callback_data="goal_months_1"),
         InlineKeyboardButton(text="3 месяца", callback_data="goal_months_3")],
        [InlineKeyboardButton(text="6 месяцев", callback_data="goal_months_6"),
         InlineKeyboardButton(text="Своя дата", callback_data="goal_custom_date")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_goal")]
    ])
    await message.answer(f"⚖️ Целевой вес: {weight}кг\n\nВыбери срок:", reply_markup=keyboard)


@router.callback_query(StateFilter(GoalStates.choosing_deadline), lambda c: c.data.startswith('goal_months_'))
async def goal_months_callback(callback_query: CallbackQuery, state: FSMContext):
    months = int(callback_query.data.replace('goal_months_', ''))
    user_data = await state.get_data()
    exercise = user_data.get('exercise')
    weight = user_data.get('weight')
    if not exercise or not weight:
        await callback_query.message.answer("❌ Ошибка: не хватает данных. Начни заново.")
        await state.clear()
        await callback_query.answer()
        return
    target_date = (datetime.now() + timedelta(days=30 * months)).strftime("%d.%m.%Y")
    db_user_id = await get_or_create_user(callback_query.from_user.id, callback_query.from_user.full_name)
    await add_goal(db_user_id, exercise, weight, target_date)
    await state.clear()
    await callback_query.message.answer(f"🎯 Цель поставлена:\n{exercise} → {weight}кг к {target_date}")
    await callback_query.answer()


@router.callback_query(StateFilter(GoalStates.choosing_deadline), lambda c: c.data == 'goal_custom_date')
async def goal_custom_date_callback(callback_query: CallbackQuery, state: FSMContext):
    await state.set_state(GoalStates.entering_custom_date)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_goal")]])
    await callback_query.message.answer("Введи дату в формате ДД.ММ.ГГГГ (например, 01.12.2026):", reply_markup=keyboard)
    await callback_query.answer()


@router.message(StateFilter(GoalStates.entering_custom_date), F.text)
async def goal_enter_custom_date(message: Message, state: FSMContext):
    text = message.text.strip()
    match = re.match(r'^(\d{1,2})[./](\d{1,2})[./](\d{4})$', text)
    if not match:
        await message.answer("❌ Неверный формат. Напиши ДД.ММ.ГГГГ (например, 01.12.2026)\nИли /cancel")
        return
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if day > 31 or month > 12:
        await message.answer("❌ Неверная дата.")
        return
    target_date = f"{day:02d}.{month:02d}.{year}"
    user_data = await state.get_data()
    exercise = user_data.get('exercise')
    weight = user_data.get('weight')
    if not exercise or not weight:
        await message.answer("❌ Ошибка: не хватает данных. Начни заново.")
        await state.clear()
        return
    db_user_id = await get_or_create_user(message.from_user.id, message.from_user.full_name)
    await add_goal(db_user_id, exercise, weight, target_date)
    await state.clear()
    await message.answer(f"🎯 Цель поставлена:\n{exercise} → {weight}кг к {target_date}")


@router.callback_query(lambda c: c.data == 'cancel_goal')
async def cancel_goal_callback(callback_query: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback_query.message.answer("❌ Постановка цели отменена.")
    await callback_query.answer()