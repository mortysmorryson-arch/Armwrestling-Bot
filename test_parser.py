"""
Тесты ПАРСЕРА из parsers.py (реального модуля — раньше тесты проверяли
собственную копию логики и пропускали баги).

Запуск: pytest test_parser.py -v
"""

from parsers import (
    clean_exercise_name,
    make_progress_bar,
    parse_workouts,
    parse_workouts_with_notes,
)


class TestParseWorkouts:
    """Основные сценарии из README и реальной практики."""

    def test_readme_example(self):
        """Пример из README: два упражнения через запятую."""
        assert parse_workouts("Жим 20 3 10, Пронация 15 4 12") == [
            ("Жим", 20.0, 3, "10"),
            ("Пронация", 15.0, 4, "12"),
        ]

    def test_decimal_comma(self):
        """Десятичная запятая не должна терять упражнение (баг фазы 1)."""
        assert parse_workouts("Сгибание 17,5 3 10") == [("Сгибание", 17.5, 3, "10")]

    def test_decimal_dot(self):
        assert parse_workouts("Сгибание 17.5 3 10") == [("Сгибание", 17.5, 3, "10")]

    def test_paren_weight(self):
        assert parse_workouts("Жим (15) 4 12") == [("Жим", 15.0, 4, "12")]

    def test_x_format(self):
        assert parse_workouts("Подъём на бицепс 25 3x12") == [
            ("Подъём на бицепс", 25.0, 3, "12")
        ]

    def test_slash_format(self):
        assert parse_workouts("Тяга 30/3/10") == [("Тяга", 30.0, 3, "10")]

    def test_weight_only(self):
        """Только вес → 1 подход, 1 повторение (не терять запись)."""
        assert parse_workouts("Жим 20") == [("Жим", 20.0, 1, "1")]

    def test_weight_and_sets(self):
        """Вес + подходы → повторения по умолчанию 1."""
        assert parse_workouts("Тяга 40 3") == [("Тяга", 40.0, 3, "1")]

    def test_numbering_stripped(self):
        assert parse_workouts("1. Жим 20 3 10\n2) Пронация 15 4 12") == [
            ("Жим", 20.0, 3, "10"),
            ("Пронация", 15.0, 4, "12"),
        ]

    def test_multiline(self):
        text = "Жим 20 3 10\nПронация 15 4 12\nСгибание 17,5 3 10"
        result = parse_workouts(text)
        assert len(result) == 3
        assert result[2] == ("Сгибание", 17.5, 3, "10")

    def test_name_trailing_punctuation(self):
        result = parse_workouts("Жим лёжа, 20 3 10")
        assert result == [("Жим лёжа", 20.0, 3, "10")]

    def test_junk_ignored(self):
        """Строки без чисел не должны попадать в тренировки."""
        assert parse_workouts("привет") == []
        assert parse_workouts("") == []

    def test_kg_word_in_name(self):
        result = parse_workouts("Жим кг 20 3 10")
        assert result[0][0] == "Жим"


class TestParseWithNotes:
    def test_workout_and_note(self):
        """Пример из хендлера «Тренировка ученику»."""
        workouts, notes = parse_workouts_with_notes(
            "Жим 20 3 10, Пронация 15 4 12\nНе забывай разминать запястье!"
        )
        assert workouts == [
            ("Жим", 20.0, 3, "10"),
            ("Пронация", 15.0, 4, "12"),
        ]
        assert notes == ["Не забывай разминать запястье!"]

    def test_only_notes(self):
        workouts, notes = parse_workouts_with_notes("Сегодня самочувствие плохое")
        assert workouts == []
        assert notes == ["Сегодня самочувствие плохое"]


class TestHelpers:
    def test_clean_name(self):
        assert clean_exercise_name("жим лёжа,") == "Жим лёжа"
        assert clean_exercise_name("Жим 20 кг") == "Жим 20"

    def test_progress_bar(self):
        assert "█" in make_progress_bar(50)
        assert "░" in make_progress_bar(50)
        assert make_progress_bar(0).endswith("0%")
        assert make_progress_bar(150).endswith("100%")  # клампинг сверху

    def test_reps_always_string(self):
        """reps всегда str — в БД колонка TEXT, а старый код иногда возвращал int."""
        for text in ["Жим 20", "Тяга 40 3", "Жим 20 3 10", "Жим (15) 4 12"]:
            for workout in parse_workouts(text):
                assert isinstance(workout[3], str), f"{text!r}: reps не строка"


class TestConsistency:
    """Парсер в parsers.py — единственный: utils.py импортирует его же."""

    def test_utils_reexports_same_functions(self):
        import utils
        import parsers
        assert utils.parse_workouts is parsers.parse_workouts
        assert utils.parse_workouts_with_notes is parsers.parse_workouts_with_notes
