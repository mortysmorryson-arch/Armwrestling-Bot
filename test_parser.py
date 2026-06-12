import re
import pytest

def clean_exercise_name(name: str) -> str:
    name = name.rstrip(' ,.-')
    name = re.sub(r'\b(кг|килограмм|килограммов)\b', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'[:;,.!?]+$', '', name).strip()
    return name.capitalize()

def parse_exercise_line(line: str):
    if not line or not line.strip():
        return None
    
    line = re.sub(r'^\s*\d+[\.\)]\s*', '', line).strip()
    
    weight = 0.0
    has_paren_weight = False
    weight_match = re.search(r'\(([\d\.,]+)\)', line)
    
    if weight_match:
        try:
            weight = float(weight_match.group(1).replace(',', '.'))
            has_paren_weight = True
        except ValueError:
            pass
        line = line[:weight_match.start()] + line[weight_match.end():]
        line = line.strip()
    
    if not has_paren_weight:
        match_3_nums = re.search(r'^(.*?)\s+(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d+)?)\s*$', line)
        if match_3_nums:
            ex_name = match_3_nums.group(1).strip()
            w = float(match_3_nums.group(2).replace(',', '.'))
            s = int(float(match_3_nums.group(3)))
            r = match_3_nums.group(4).strip()
            return clean_exercise_name(ex_name), w, s, r
    
    tail_match = re.search(r'(\d+(?:\s*[xх/]\s*\d+)*)\s*(.*)$', line)
    
    if tail_match:
        tail_nums = tail_match.group(1)
        tail_rest = tail_match.group(2).strip()
        
        first_num_match = re.search(r'\d+', tail_nums)
        if not first_num_match:
            return None
            
        sets = int(first_num_match.group())
        reps = tail_rest if tail_rest else tail_nums.strip()
        ex_name = line[:tail_match.start()].strip()
        
        return clean_exercise_name(ex_name), weight, sets, reps
        
    return None

def parse_workouts(text: str):
    workouts = []
    for line in re.split(r'[\n,]+', text):
        parsed = parse_exercise_line(line)
        if parsed:
            workouts.append(parsed)
    return workouts

def parse_workouts_with_notes(text: str):
    workouts = []
    notes = []
    for line in re.split(r'[\n,]+', text):
        line = line.strip()
        if not line:
            continue
        parsed = parse_exercise_line(line)
        if parsed:
            workouts.append(parsed)
        else:
            notes.append(line)
    return workouts, notes


# ==========================================
# 7 ОТДЕЛЬНЫХ ТЕСТОВ ДЛЯ PYTEST
# ==========================================

@pytest.mark.parametrize("input_str, expected", [
    # 1. Стандартный формат из 3 чисел
    ("Жим 20 3 10", ("Жим", 20.0, 3, "10")),
    # 2. Список повторений через слэш (без веса)
    ("1)Подтягивание 15/13/9/9", ("Подтягивание", 0.0, 15, "15/13/9/9")),
    # 3. Вес в скобках, прилепленный к подходам (ГЛАВНЫЙ КЕЙС)
    ("2)Луч через фаланги (17,5)4/8", ("Луч через фаланги", 17.5, 4, "4/8")),
    # 4. Вес в скобках без пробела перед названием
    ("8)Пальцы гриф(70)4/10", ("Пальцы гриф", 70.0, 4, "4/10")),
    # 5. Подходы и текстовые повторения
    ("Статика в Скотте 4 10 сек", ("Статика в скотте", 0.0, 4, "10 сек")),
])
def test_parse_exercise_line_cases(input_str, expected):
    assert parse_exercise_line(input_str) == expected

# 6. Разделение через запятую
def test_parse_workouts_comma_separated():
    assert parse_workouts("Жим 20 3 10, Пронация 15 4 12") == [
        ("Жим", 20.0, 3, "10"), 
        ("Пронация", 15.0, 4, "12")
    ]

# 7. Корректное разделение на упражнения и заметки
def test_parse_workouts_with_notes():
    workouts, notes = parse_workouts_with_notes("Жим 20 3 10\nЗавтра будет тяжелее")
    assert workouts == [("Жим", 20.0, 3, "10")]
    assert notes == ["Завтра будет тяжелее"]

if __name__ == "__main__":
    pytest.main([__file__, "-v"])