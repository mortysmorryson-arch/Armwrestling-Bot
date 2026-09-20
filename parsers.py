"""
Парсеры для разбора текста тренировок.
Чистая бизнес-логика, не зависящая от Telegram.
"""
import re
import logging

logger = logging.getLogger(__name__)

# Число с необязательной десятичной частью (17, 17.5, 17,5)
_NUM = r'\d+(?:[.,]\d+)?'
# Числовой хвост: "20 3 10", "25 3x12", "40/8" и т.п.
_TAIL_RE = re.compile(rf'({_NUM}(?:\s*[xх/]\s*{_NUM}|\s+{_NUM})*)\s*(.*)$')


def clean_exercise_name(name: str) -> str:
    """Очищает название упражнения от мусора и приводит к единому виду."""
    name = name.rstrip(' ,.-')
    name = re.sub(r'\b(кг|килограмм|килограммов)\b', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'[:;,.!?]+$', '', name).strip()
    return name.capitalize()


def parse_exercise_line(line: str):
    """
    Парсит одну строку тренировки.
    Примеры:
        "Жим 20 3 10" -> ("Жим", 20.0, 3, "10")
        "Пронация (15) 4 12" -> ("Пронация", 15.0, 4, "12")
        "Сгибание 17,5 3 10" -> ("Сгибание", 17.5, 3, "10")
        "Подъём 25 3x12" -> ("Подъём", 25.0, 3, "12")
        "Жим 20" -> ("Жим", 20.0, 1, "1")          # вес без подходов
        "Тяга 40 3" -> ("Тяга", 40.0, 3, "1")      # вес + подходы
    Возвращает кортеж (название, вес, подходы, повторения) или None.
    """
    logger.debug(f"Парсим строку: {line!r}")
    if not line or not line.strip():
        return None

    # 1. Удаляем нумерацию (1. Жим, 2) Жим)
    line = re.sub(r'^\s*\d+[\.\)]\s*', '', line).strip()

    # 2. Извлекаем вес из скобок (если есть)
    weight = 0.0
    weight_match = re.search(r'[\(\（]([\d\.,]+)[\)\）]', line)
    if weight_match:
        try:
            weight = float(weight_match.group(1).replace(',', '.'))
        except ValueError:
            pass
        line = line[:weight_match.start()] + line[weight_match.end():]
        line = line.strip()

    # 3. Ищем числовой хвост (числа через пробел, x, х, /)
    tail_match = _TAIL_RE.search(line)

    if not tail_match:
        logger.debug("Провал: не найдено числового хвоста")
        return None

    tail_nums = tail_match.group(1)
    tail_rest = tail_match.group(2).strip()

    # Разделяем хвост по пробелам, x, х, /
    parts = [p for p in re.split(r'\s*[xх/]\s*|\s+', tail_nums) if p]

    if not parts:
        return None

    ex_name = clean_exercise_name(line[:tail_match.start()].strip())
    if not ex_name:
        # Упражнение без названия ("20 3 10" отдельной строкой) — не запись
        logger.debug("Провал: пустое название упражнения")
        return None

    def _num(value: str) -> float:
        return float(value.replace(',', '.'))

    def _int(value: str) -> int:
        return int(float(value.replace(',', '.')))

    # === ЛОГИКА ОПРЕДЕЛЕНИЯ ВЕСА, ПОДХОДОВ, ПОВТОРЕНИЙ ===
    if weight > 0:
        # Вес уже задан в скобках
        if len(parts) >= 2:
            sets = _int(parts[0])
            reps = parts[1] if len(parts) == 2 else ' '.join(parts[1:])
        else:
            sets = _int(parts[0])
            reps = tail_rest or str(sets)
    elif len(parts) == 1:
        # Только вес → 1 подход, 1 повторение
        weight = _num(parts[0])
        sets = 1
        reps = "1"
    else:
        # Первое число = вес, второе = подходы, остальное = повторения
        weight = _num(parts[0])
        sets = _int(parts[1])
        reps = ' '.join(parts[2:]) if len(parts) > 2 else (tail_rest or "1")

    logger.debug(f"Успех: name='{ex_name}', weight={weight}, sets={sets}, reps='{reps}'")
    return (ex_name, float(weight), int(sets), str(reps))


def _split_lines(text: str) -> list:
    """
    Делит текст на строки-кандидаты по переводам строк и запятым.

    Хитрость: «Жим лёжа, 20 3 10» — запятая здесь НЕ разделитель упражнений,
    а часть строки. Если кусок без чисел, а следующий начинается с числа —
    склеиваем их обратно (иначе имя упражнения теряется).
    """
    chunks = [c.strip() for c in re.split(r'[\n,]+', text) if c.strip()]
    merged: list = []
    for chunk in chunks:
        prev = merged[-1] if merged else None
        if prev is not None and not any(ch.isdigit() for ch in prev) and chunk[:1].isdigit():
            merged[-1] = f"{prev} {chunk}"
        else:
            merged.append(chunk)
    return merged


def parse_workouts(text: str) -> list:
    """
    Парсит весь текст тренировки (несколько упражнений через запятую или с новой строки).
    Возвращает список кортежей: [(название, вес, подходы, повторения), ...]
    """
    # КРИТИЧЕСКИ ВАЖНО: заменяем десятичные запятые на точки ДО сплита,
    # чтобы "17,5" не разорвало строку на две части
    text = re.sub(r'(\d),(\d)', r'\1.\2', text)
    workouts = []
    for line in _split_lines(text):
        parsed = parse_exercise_line(line)
        if parsed:
            workouts.append(parsed)
    return workouts


def parse_workouts_with_notes(text: str) -> tuple:
    """
    Парсит текст тренировки с примечаниями.
    Возвращает кортеж (workouts, notes), где:
        - workouts: список упражнений
        - notes: список строк, которые не распознали как упражнения
    """
    # КРИТИЧЕСКИ ВАЖНО: заменяем десятичные запятые на точки
    text = re.sub(r'(\d),(\d)', r'\1.\2', text)
    workouts = []
    notes = []
    for line in _split_lines(text):
        parsed = parse_exercise_line(line)
        if parsed:
            workouts.append(parsed)
        else:
            notes.append(line)

    return workouts, notes


def make_progress_bar(percent: float) -> str:
    """Создаёт текстовый прогресс-бар для целей."""
    percent = min(100.0, max(0.0, percent))
    filled = int(percent / 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {percent:.0f}%"