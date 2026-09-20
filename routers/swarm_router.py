"""
Роутер роя: команда /swarm — вопрос совету нейросетей.
Автоподстановка данных ученика из БД + RAG-поиск по базе знаний.
Использует ModelRegistry для динамического выбора моделей и прокси.
"""
import asyncio
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from model_registry import get_registry

from helpers import is_admin
from swarm_engine import Swarm
from prompts import SYSTEM_CONTEXT
from telegram_render import render_for_telegram
from rag import retrieve
from database import (
    get_user_stats,
    get_current_max,
    get_user_goals,
    get_all_students,
    get_last_workout,
    get_user_exercises,
)

logger = logging.getLogger(__name__)
router = Router()

# Жёсткий потолок промпта: у части моделей лимит ~8000 токенов/запрос (Groq TPM),
# а промпт судьи включает ещё и ответы всех экспертов. ~24000 символов ≈ 6000-7000
# токенов — безопасный размер с запасом на ответ экспертов.
MAX_PROMPT_CHARS = 24000


def split_message(text: str, limit: int = 4096) -> list:
    """Режет текст на куски под лимит Telegram."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    chunks.append(text)
    return chunks


async def get_student_data_by_name(name: str):
    """Ищет ученика по имени в БД и возвращает его данные для подстановки в промпт."""
    students = await get_all_students()
    name_lower = name.lower()
    for user_db_id, telegram_id, student_name in students:
        if name_lower in student_name.lower():
            stats = await get_user_stats(user_db_id)
            maxes_data = []
            exercises = await get_user_exercises(user_db_id)
            for ex in exercises:
                current_max = await get_current_max(user_db_id, ex)
                if current_max:
                    maxes_data.append(f"{ex}: {current_max}кг")
            goals = await get_user_goals(user_db_id)
            goals_text = "\n".join([f"{g[1]} → {g[2]}кг к {g[3]}" for g in goals]) if goals else "нет активных целей"
            last_workout = await get_last_workout(user_db_id)
            last_workout_text = f"{last_workout[2]}: {last_workout[3]}кг × {last_workout[4]}×{last_workout[5]}" if last_workout else "нет данных"
            return {
                "found": True,
                "telegram_id": telegram_id,
                "name": student_name,
                "stats": stats[:5] if stats else [],
                "maxes": maxes_data,
                "goals": goals_text,
                "last_workout": last_workout_text,
            }
    return {"found": False}


async def build_context_prompt(user_prompt: str) -> str:
    """
    Проверяет, есть ли в запросе упоминание ученика.
    Если есть — подставляет его данные.
    """
    words = user_prompt.split()
    if words:
        first_word = words[0]
        if not first_word.isdigit() and first_word not in ["ученик", "программа", "план"]:
            student_data = await get_student_data_by_name(first_word)
            if student_data["found"]:
                context = f"""
=== ДАННЫЕ УЧЕНИКА (из БД) ===
Имя: {student_data['name']}
Текущие максимумы:
{chr(10).join(student_data['maxes']) if student_data['maxes'] else 'нет данных'}
Цели:
{student_data['goals']}
Последняя тренировка:
{student_data['last_workout']}

=== ЗАПРОС ТРЕНЕРА (остальная часть) ===
{' '.join(words[1:]) if len(words) > 1 else ''}
"""
                return context
    return user_prompt


@router.message(Command("swarm"))
async def cmd_swarm(message: Message):
    if not is_admin(message):
        await message.answer("🚫 Команда доступна только тренеру.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🤖 Использование:\n/swarm @username или /swarm Имя\n\n"
            "Пример:\n/swarm Иван программа 4 недели\n\n"
            "Если ученик найден в БД, его данные подставятся автоматически."
        )
        return

    user_prompt = parts[1]

    # 1. Автоподстановка данных ученика
    enhanced_prompt = await build_context_prompt(user_prompt)

    # 2. RAG-поиск по базе знаний
    # Щедрый ретривал: база маленькая, отдаём 6 чанков (лимит промпта защищает от 413)
    chunks = await retrieve(user_prompt, top_n=6)

    # 3. Формируем полный промпт
    full_prompt = SYSTEM_CONTEXT

    if chunks:
        knowledge_text = "\n\n".join(
            f"--- {c['source']} (тип: {c['source_type']}) ---\n{c['text']}"
            for c in chunks
        )
        full_prompt += f"\n\n=== БАЗА ЗНАНИЙ ===\n{knowledge_text}"

    full_prompt += f"\n\nЗАПРОС ТРЕНЕРА:\n{enhanced_prompt}"

    # Защита от 413: если промпт раздут — отрезаем базу знаний с конца,
    # пока не влезет в лимит (системный контекст и данные ученика не трогаем)
    if len(full_prompt) > MAX_PROMPT_CHARS and chunks:
        dropped = 0
        while chunks and len(full_prompt) > MAX_PROMPT_CHARS:
            chunks.pop()
            dropped += 1
            knowledge_text = "\n\n".join(
                f"--- {c['source']} (тип: {c['source_type']}) ---\n{c['text']}"
                for c in chunks
            )
            full_prompt = (
                SYSTEM_CONTEXT
                + f"\n\n=== БАЗА ЗНАНИЙ ===\n{knowledge_text}"
                + f"\n\nЗАПРОС ТРЕНЕРА:\n{enhanced_prompt}"
            )
        if dropped:
            logger.warning(f"Промпт превышал лимит, отброшено чанков базы знаний: {dropped}")
        if len(full_prompt) > MAX_PROMPT_CHARS:
            # База знаний кончилась, а промпт всё ещё большой — режем хвост запроса
            full_prompt = full_prompt[:MAX_PROMPT_CHARS] + "\n…(запрос обрезан)"

    # 4. Получаем реестр из dp
    registry = get_registry()
    if not registry:
        await message.answer("❌ Ошибка: реестр моделей не инициализирован.")
        return

    # 5. Создаём экземпляр Swarm с реестром
    swarm = Swarm(registry=registry, overall_timeout=120)

    await message.answer("🐝 Рой думает... (10–60 секунд)")

    try:
        answers, verdict = await asyncio.to_thread(swarm.run, full_prompt)
    except Exception as e:
        await message.answer(f"❌ Ошибка роя: {e}")
        return

    # Сводка с выводом текста ошибок
    summary = "🤖 <b>Мнения роя:</b>\n\n"
    for a in answers:
        is_ok = not a["text"].startswith("❌")
        status = "✅" if is_ok else "❌"
        proxy_info = f" через {a.get('proxy', 'direct')}" if 'proxy' in a else ""
        line = f"{status} <b>{a['provider'].upper()}</b> ({a['model']}){proxy_info} — <i>{a['time']:.1f}с</i>\n"
        if not is_ok:
            err_text = a["text"].replace("<", "&lt;").replace(">", "&gt;")[:200]
            line += f"<code>{err_text}</code>\n"
        summary += line
    await message.answer(summary, parse_mode="HTML")

    # Вердикт
    if verdict and verdict["provider"] == "error":
        await message.answer(verdict["text"])
        return

    if verdict and not verdict["text"].startswith("❌"):
        header = f"⚖️ <b>ВЕРДИКТ ПРЕДСЕДАТЕЛЯ</b> <i>({verdict['model']})</i>\n\n"
        body = render_for_telegram(verdict["text"])
        for chunk in split_message(header + body, limit=4096):
            await message.answer(chunk, parse_mode="HTML")
    else:
        err = verdict["text"][:200] if verdict else "неизвестная ошибка"
        await message.answer(f"⚠️ Председатель не смог вынести вердикт.\n<code>{err}</code>", parse_mode="HTML")