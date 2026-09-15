import logging
import os
import re
import secrets
from datetime import datetime, timedelta

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "bot.db")

async def _ensure_column(db, table: str, column: str, coltype: str):
    """Добавляет колонку в таблицу, если её ещё нет (миграция старых баз)."""
    cursor = await db.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in await cursor.fetchall()]
    if column not in columns:
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        logger.info(f"Миграция: добавлена колонка {table}.{column}")


async def init_db():
    """
    Создаёт схему БД и мигрирует старые базы.

    ВАЖНО: схема здесь должна совпадать с реальной bot.db (прод),
    иначе код работает только на старой базе, а на свежей падает
    (нет records, другие имена колонок в messages и т.д.).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # WAL-режим: запись не блокирует чтение, устойчивее к сбоям питания.
        # busy_timeout: ждать освобождение БД вместо мгновенного "database is locked"
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA busy_timeout=5000")

        # Таблица пользователей
        await db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            name TEXT,
            role TEXT DEFAULT 'student',
            is_blocked INTEGER DEFAULT 0,
            invite_token TEXT,
            source TEXT,
            registered_at TEXT
        )
        ''')

        # Таблица тренировок
        await db.execute('''
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            exercise TEXT,
            weight REAL,
            sets INTEGER,
            reps TEXT,
            notes TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        ''')

        # Таблица личных рекордов (раньше не создавалась вовсе — фикс)
        await db.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            exercise TEXT,
            max_weight REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        ''')

        # Таблица целей
        await db.execute('''
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            exercise TEXT,
            target_weight REAL,
            target_date TEXT,
            created_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        ''')

        # Таблица приглашений (схема как в продовой базе: usage_count
        # нигде не используется — количество применений считается через LEFT JOIN)
        await db.execute('''
        CREATE TABLE IF NOT EXISTS invites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT UNIQUE,
            created_at TEXT,
            created_by INTEGER,
            is_active INTEGER DEFAULT 1
        )
        ''')

        # Таблица сообщений чата — имена колонок как в продовой базе
        await db.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_telegram_id INTEGER,
            receiver_telegram_id INTEGER,
            text TEXT,
            timestamp TEXT,
            is_read INTEGER DEFAULT 0
        )
        ''')

        # Таблица напоминаний
        await db.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            days TEXT,
            time TEXT,
            text TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        ''')

        # === МИГРАЦИИ СТАРЫХ БАЗ ===

        # Базы, созданные старым init_db: колонки users.registered_at и
        # goals.created_at использовались кодом, но в схеме отсутствовали.
        await _ensure_column(db, "users", "registered_at", "TEXT")
        await _ensure_column(db, "goals", "celebrated", "INTEGER DEFAULT 0")
        await _ensure_column(db, "goals", "created_at", "TEXT")
        await _ensure_column(db, "reminders", "text", "TEXT")

        # Старые имена колонок messages (sender_id/recipient_id) → продовые
        cursor = await db.execute("PRAGMA table_info(messages)")
        msg_columns = [row[1] for row in await cursor.fetchall()]
        if msg_columns and "sender_telegram_id" not in msg_columns:
            if "sender_id" in msg_columns:
                await db.execute(
                    "ALTER TABLE messages RENAME COLUMN sender_id TO sender_telegram_id"
                )
                logger.info("Миграция: messages.sender_id → sender_telegram_id")
            if "recipient_id" in msg_columns:
                await db.execute(
                    "ALTER TABLE messages RENAME COLUMN recipient_id TO receiver_telegram_id"
                )
                logger.info("Миграция: messages.recipient_id → receiver_telegram_id")

        await db.commit()

async def get_unread_count_from_sender(sender_telegram_id: int, receiver_telegram_id: int) -> int:
    """Считает непрочитанные сообщения от конкретного отправителя для получателя."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE sender_telegram_id = ? AND receiver_telegram_id = ? AND is_read = 0",
            (sender_telegram_id, receiver_telegram_id)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

async def get_or_create_user(telegram_id: int, name: str, invite_token: str | None = None, source: str = 'direct') -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
        row = await cursor.fetchone()
        if row:
            if invite_token:
                await db.execute(
                    "UPDATE users SET name = ?, invite_token = ?, source = ? WHERE telegram_id = ?",
                    (name, invite_token, source, telegram_id)
                )
            else:
                await db.execute("UPDATE users SET name = ? WHERE telegram_id = ?", (name, telegram_id))
            await db.commit()
            return row[0]

        registered_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = await db.execute(
            "INSERT INTO users (telegram_id, name, invite_token, source, registered_at) VALUES (?, ?, ?, ?, ?)",
            (telegram_id, name, invite_token, source, registered_at)
        )
        await db.commit()
        return cursor.lastrowid

async def is_user_blocked(telegram_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT is_blocked FROM users WHERE telegram_id = ?", (telegram_id,))
        row = await cursor.fetchone()
        return row[0] == 1 if row else False

async def block_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_blocked = 1 WHERE telegram_id = ?", (telegram_id,))
        await db.commit()

async def unblock_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_blocked = 0 WHERE telegram_id = ?", (telegram_id,))
        await db.commit()

# ИЗМЕНЕНО: reps теперь имеет тип str
async def add_workout(user_id: int, exercise: str, weight: float, sets: int, reps: str, notes: str = "") -> str:
    """
    Добавляет новую тренировку в БД и проверяет рекорды.

    :param user_id: ID пользователя в БД
    :param exercise: Название упражнения
    :param weight: Вес (кг)
    :param sets: Количество подходов
    :param reps: Количество повторений (строка, т.к. может быть "10 сек")
    :param notes: Примечание к упражнению
    :return: Строку с поздравлением, если установлен новый рекорд, иначе пустую строку
    """
    date_str = datetime.now().strftime("%Y-%m-%d")

    exercise = re.sub(r'[:;,.!?]+$', '', exercise).strip()
    record_msg = ""

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO workouts (user_id, date, exercise, weight, sets, reps, notes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, date_str, exercise, weight, sets, reps, notes)
        )

        cursor = await db.execute(
            "SELECT max_weight FROM records WHERE user_id = ? AND exercise = ?",
            (user_id, exercise)
        )
        row = await cursor.fetchone()

        if not row or weight > row[0]:
            if row:
                await db.execute(
                    "UPDATE records SET max_weight = ? WHERE user_id = ? AND exercise = ?",
                    (weight, user_id, exercise)
                )
            else:
                await db.execute(
                    "INSERT INTO records (user_id, exercise, max_weight) VALUES (?, ?, ?)",
                    (user_id, exercise, weight)
                )
            record_msg = f"\n🏆 Новый личный рекорд в упражнении '{exercise}': {weight}кг!"

        await db.commit()
    return record_msg

async def get_user_stats(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT date, exercise, weight, sets, reps, notes FROM workouts WHERE user_id = ? ORDER BY date DESC",
            (user_id,)
        )
        return await cursor.fetchall()

async def get_all_users_stats() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT u.name, w.date, w.exercise, w.weight, w.sets, w.reps, w.notes
            FROM users u
            JOIN workouts w ON u.id = w.user_id
            ORDER BY w.date DESC
        """)
        rows = await cursor.fetchall()
        if not rows:
            return "📭 Тренировок пока нет ни у кого."

        text = "📊 Общая статистика:\n\n"
        for r in rows[:15]:
            note_text = f" ({r[6]})" if r[6] else ""
            text += f"👤 {r[0]} | 📅 {r[1]} | {r[2]}: {r[3]}кг × {r[4]}×{r[5]}{note_text}\n"
        return text

async def export_all_workouts() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT w.date, u.name, w.exercise, w.weight, w.sets, w.reps, w.notes
            FROM workouts w
            JOIN users u ON w.user_id = u.id
            ORDER BY w.date DESC
        """)
        return await cursor.fetchall()

async def get_lazy_users(days: int = 7) -> str:
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT u.name FROM users u
            WHERE u.id NOT IN (SELECT user_id FROM workouts WHERE date >= ?)
            AND u.is_blocked = 0
        """, (cutoff_date,))
        rows = await cursor.fetchall()
        if not rows:
            return f"✅ За последние {days} дней все тренились!"
        return f"😴 Не тренировались {days} дней:\n" + "\n".join([f"- {r[0]}" for r in rows])

async def set_reminder(user_id: int, days: str, time: str, text: str = ""):
    """Одна настройка напоминаний на пользователя: новая заменяет старую."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Раньше INSERT OR REPLACE без UNIQUE-констрейнта плодил дубли строк
        await db.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
        await db.execute(
            "INSERT INTO reminders (user_id, days, time, text) VALUES (?, ?, ?, ?)",
            (user_id, days, time, text)
        )
        await db.commit()

async def get_reminders():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT user_id, days, time, text FROM reminders")
        rows = await cursor.fetchall()
    return rows

async def delete_reminder(user_id: int):
    """Удаляет все напоминания для конкретного пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM reminders WHERE user_id = ?", (user_id,))
        await db.commit()

async def delete_all_reminders():
    """Удаляет все настройки напоминаний из базы данных."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM reminders")
        await db.commit()

async def get_users_without_workout_today() -> list:
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT u.telegram_id, u.name FROM users u
            WHERE u.telegram_id IS NOT NULL
            AND u.id NOT IN (SELECT user_id FROM workouts WHERE date = ?)
            AND u.is_blocked = 0
        """, (today,))
        return await cursor.fetchall()

async def get_exercise_progress(user_id: int, exercise: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT date, exercise, weight FROM workouts WHERE user_id = ? ORDER BY date",
            (user_id,)
        )
        # SQLite LOWER() не работает с кириллицей — сопоставление в Python
        target = exercise.strip().casefold()
        return [(row[0], row[2]) for row in await cursor.fetchall()
                if str(row[1]).strip().casefold() == target]

async def get_user_exercises(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT DISTINCT LOWER(exercise) FROM workouts WHERE user_id = ?",
            (user_id,)
        )
        exercises = []
        for row in await cursor.fetchall():
            clean_ex = re.sub(r'[:;,.!?]+$', '', row[0]).strip()
            exercises.append(clean_ex.capitalize())
        return exercises

async def delete_exercise(user_id: int, exercise: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT exercise FROM workouts WHERE user_id = ?",
            (user_id,)
        )
        # SQLite LOWER() не работает с кириллицей — сопоставление в Python
        target = exercise.strip().casefold()
        matches = [row[0] for row in await cursor.fetchall()
                   if str(row[0]).strip().casefold() == target]
        deleted = 0
        for ex in matches:
            cursor = await db.execute(
                "DELETE FROM workouts WHERE user_id = ? AND exercise = ?",
                (user_id, ex)
            )
            deleted += cursor.rowcount
            await db.execute(
                "DELETE FROM records WHERE user_id = ? AND exercise = ?",
                (user_id, ex)
            )
        await db.commit()
        return deleted

async def get_last_workout(user_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, date, exercise, weight, sets, reps, notes FROM workouts WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        return await cursor.fetchone()

# ИЗМЕНЕНО: reps теперь имеет тип str
async def update_workout(workout_id: int, exercise: str, weight: float, sets: int, reps: str):
    exercise = re.sub(r'[:;,.!?]+$', '', exercise).strip()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE workouts SET exercise = ?, weight = ?, sets = ?, reps = ? WHERE id = ?",
            (exercise, weight, sets, reps, workout_id)
        )
        cursor = await db.execute(
            "SELECT user_id FROM workouts WHERE id = ?", (workout_id,)
        )
        row = await cursor.fetchone()
        if row:
            user_id = row[0]
            cursor = await db.execute(
                "SELECT max_weight FROM records WHERE user_id = ? AND exercise = ?",
                (user_id, exercise)
            )
            rec = await cursor.fetchone()
            if not rec or weight > rec[0]:
                if rec:
                    await db.execute(
                        "UPDATE records SET max_weight = ? WHERE user_id = ? AND exercise = ?",
                        (weight, user_id, exercise)
                    )
                else:
                    await db.execute(
                        "INSERT INTO records (user_id, exercise, max_weight) VALUES (?, ?, ?)",
                        (user_id, exercise, weight)
                    )
        await db.commit()

async def delete_last_workout(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id FROM workouts WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,)
        )
        row = await cursor.fetchone()
        if row:
            await db.execute("DELETE FROM workouts WHERE id = ?", (row[0],))
            await db.commit()
            await recalc_record(user_id, "ALL")
            return True
        return False

async def add_note_to_workout(workout_id: int, note: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE workouts SET notes = ? WHERE id = ?", (note, workout_id))
        await db.commit()

async def recalc_record(user_id: int, exercise: str):
    """Пересчитывает рекорд по фактическим тренировкам.
    exercise="ALL" — пересчитать все упражнения пользователя.
    Нужен, потому что при удалении записи рекорд мог держаться именно на ней."""
    async with aiosqlite.connect(DB_PATH) as db:
        if exercise == "ALL":
            cursor = await db.execute(
                "SELECT DISTINCT exercise FROM workouts WHERE user_id = ?", (user_id,))
            exercises = [r[0] for r in await cursor.fetchall()]
        else:
            exercises = [exercise]
        for ex in exercises:
            cursor = await db.execute(
                "SELECT MAX(weight) FROM workouts WHERE user_id = ? AND exercise = ?",
                (user_id, ex))
            max_w = cursor.fetchone()[0]
            cursor = await db.execute(
                "SELECT id FROM records WHERE user_id = ? AND exercise = ?", (user_id, ex))
            rec_row = await cursor.fetchone()
            if max_w is None:
                if rec_row:
                    await db.execute("DELETE FROM records WHERE id = ?", (rec_row[0],))
            elif rec_row:
                await db.execute(
                    "UPDATE records SET max_weight = ? WHERE id = ?", (max_w, rec_row[0]))
            else:
                await db.execute(
                    "INSERT INTO records (user_id, exercise, max_weight) VALUES (?, ?, ?)",
                    (user_id, ex, max_w))
        await db.commit()


async def get_user_streak(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT DISTINCT date FROM workouts WHERE user_id = ? ORDER BY date DESC",
            (user_id,)
        )
        rows = await cursor.fetchall()

        if not rows:
            return 0

        streak = 1
        today = datetime.now().date()

        last_date = datetime.strptime(rows[0][0], "%Y-%m-%d").date()
        if (today - last_date).days > 1:
            return 0

        for i in range(1, len(rows)):
            current_date = datetime.strptime(rows[i][0], "%Y-%m-%d").date()
            prev_date = datetime.strptime(rows[i-1][0], "%Y-%m-%d").date()

            if (prev_date - current_date).days == 1:
                streak += 1
            else:
                break

        return streak

async def get_workouts_by_date(user_id: int, day: int, month: int) -> list:
    day_str = f"{day:02d}"
    month_str = f"{month:02d}"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT date, exercise, weight, sets, reps, notes FROM workouts WHERE user_id = ? AND strftime('%d', date) = ? AND strftime('%m', date) = ? ORDER BY date DESC",
            (user_id, day_str, month_str)
        )
        return await cursor.fetchall()

async def get_monthly_rating() -> list:
    current_month = datetime.now().strftime("%Y-%m")
    async with aiosqlite.connect(DB_PATH) as db:
        # ИСПРАВЛЕНО: COUNT(DISTINCT w.date) считает уникальные дни тренировок, а не количество упражнений
        cursor = await db.execute("""
            SELECT u.name, COUNT(DISTINCT w.date) as count
            FROM users u
            JOIN workouts w ON u.id = w.user_id
            WHERE w.date LIKE ? || '%' AND u.role = 'student' AND u.is_blocked = 0
            GROUP BY u.id
            ORDER BY count DESC
        """, (current_month,))
        return await cursor.fetchall()

async def add_goal(user_id: int, exercise: str, target_weight: float, target_date: str):
    exercise = re.sub(r'[:;,.!?]+$', '', exercise).strip().capitalize()
    created_at = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO goals (user_id, exercise, target_weight, target_date, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, exercise, target_weight, target_date, created_at)
        )
        await db.commit()

async def get_user_goals(user_id: int) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, exercise, target_weight, target_date FROM goals WHERE user_id = ? ORDER BY id DESC",
            (user_id,)
        )
        return await cursor.fetchall()


async def get_uncelenrated_goals(user_id: int) -> list:
    """Цели, которые ещё не праздновались (для check_and_celebrate_goals)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, exercise, target_weight FROM goals "
            "WHERE user_id = ? AND COALESCE(celebrated, 0) = 0",
            (user_id,)
        )
        return await cursor.fetchall()


async def mark_goal_celebrated(goal_id: int):
    """Помечает цель достигнутой и отпразднованной (в БД, а не в памяти:
    раньше после рестарта бота поздравление прилетало повторно)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE goals SET celebrated = 1 WHERE id = ?", (goal_id,))
        await db.commit()

async def get_current_max(user_id: int, exercise: str) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT exercise, max_weight FROM records WHERE user_id = ?",
            (user_id,)
        )
        # SQLite LOWER() не работает с кириллицей, поэтому сравнение в Python
        target = exercise.strip().casefold()
        for row in await cursor.fetchall():
            if str(row[0]).strip().casefold() == target:
                return row[1]
        return 0.0

async def delete_goal(goal_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        await db.commit()

async def get_all_students() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, telegram_id, name FROM users WHERE telegram_id IS NOT NULL AND is_blocked = 0 ORDER BY name"
        )
        return await cursor.fetchall()

async def get_user_by_telegram_id(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, telegram_id, name, role FROM users WHERE telegram_id = ?",
            (telegram_id,)
        )
        return await cursor.fetchone()

async def save_message(sender_telegram_id: int, receiver_telegram_id: int, text: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (sender_telegram_id, receiver_telegram_id, text, timestamp) VALUES (?, ?, ?, ?)",
            (sender_telegram_id, receiver_telegram_id, text, timestamp)
        )
        await db.commit()

async def get_unread_count(user_telegram_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM messages WHERE receiver_telegram_id = ? AND is_read = 0",
            (user_telegram_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

async def get_chat_history(user1_telegram_id: int, user2_telegram_id: int, limit: int = 50) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT sender_telegram_id, text, timestamp, is_read
            FROM messages
            WHERE (sender_telegram_id = ? AND receiver_telegram_id = ?)
               OR (sender_telegram_id = ? AND receiver_telegram_id = ?)
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user1_telegram_id, user2_telegram_id, user2_telegram_id, user1_telegram_id, limit))
        rows = await cursor.fetchall()
        return rows

async def mark_as_read(sender_telegram_id: int, receiver_telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE messages SET is_read = 1 WHERE sender_telegram_id = ? AND receiver_telegram_id = ? AND is_read = 0",
            (sender_telegram_id, receiver_telegram_id)
        )
        await db.commit()

# === ФУНКЦИИ ДЛЯ ПРИГЛАШЕНИЙ ===

async def create_invite_token(created_by: int) -> str:
    token = secrets.token_urlsafe(8)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO invites (token, created_at, created_by) VALUES (?, ?, ?)",
            (token, created_at, created_by)
        )
        await db.commit()
    return token

async def get_invite_token(token: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, token, created_at, created_by, is_active FROM invites WHERE token = ? AND is_active = 1",
            (token,)
        )
        return await cursor.fetchone()

async def get_all_invites() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT i.token, i.created_at, i.is_active, COUNT(u.id) as usage_count
            FROM invites i
            LEFT JOIN users u ON u.invite_token = i.token
            GROUP BY i.id
            ORDER BY i.created_at DESC
        """)
        return await cursor.fetchall()

async def deactivate_invite(token: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE invites SET is_active = 0 WHERE token = ?", (token,))
        await db.commit()

async def get_inactive_users(days: int = 14) -> list:
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT u.telegram_id, u.name, MAX(w.date) as last_workout
            FROM users u
            LEFT JOIN workouts w ON u.id = w.user_id
            WHERE u.telegram_id IS NOT NULL AND u.is_blocked = 0
            GROUP BY u.id
            HAVING last_workout IS NULL OR last_workout < ?
        """, (cutoff_date,))
        return await cursor.fetchall()
