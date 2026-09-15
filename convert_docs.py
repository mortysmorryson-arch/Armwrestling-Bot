#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Конвертер документов .docx в Markdown для базы знаний бота.
Структура:
- Заголовки Heading 1 -> #, Heading 2 -> ##
- Таблицы -> markdown-таблицы
- Сохраняется в knowledge_base/ с тем же именем .md
"""

import sys
import logging
from pathlib import Path

try:
    from docx import Document
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.text.paragraph import Paragraph
    from docx.table import Table, _Cell
except ImportError:
    print("❌ Установите python-docx: pip install python-docx")
    sys.exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Пути
DOCS_DIR = Path("docs")
KB_DIR = Path("knowledge_base")


def ensure_dirs():
    """Создаёт папки docs и knowledge_base, если их нет."""
    DOCS_DIR.mkdir(exist_ok=True)
    KB_DIR.mkdir(exist_ok=True)


def clean_text(text: str) -> str:
    """Очищает текст от лишних пробелов и символов."""
    if not text:
        return ""
    return " ".join(text.split()).strip()


def paragraph_to_md(paragraph: Paragraph) -> str:
    """Конвертирует абзац в Markdown, учитывая стиль заголовков."""
    text = clean_text(paragraph.text)
    if not text:
        return ""

    style = paragraph.style.name.lower()
    if "heading 1" in style or "заголовок 1" in style:
        return f"# {text}"
    elif "heading 2" in style or "заголовок 2" in style:
        return f"## {text}"
    elif "heading 3" in style or "заголовок 3" in style:
        return f"### {text}"
    else:
        return text


def cell_text(cell: _Cell) -> str:
    """Извлекает текст из ячейки таблицы, объединяя абзацы."""
    texts = []
    for p in cell.paragraphs:
        t = clean_text(p.text)
        if t:
            texts.append(t)
    return " ".join(texts)


def table_to_md(table: Table) -> str:
    """Конвертирует таблицу docx в markdown-таблицу."""
    rows = table.rows
    if not rows:
        return ""

    # Извлечь данные всех ячеек
    data = []
    for row in rows:
        row_data = [cell_text(cell) for cell in row.cells]
        data.append(row_data)

    # Определить ширину столбцов (по максимальной длине)
    col_widths = []
    for col_idx in range(len(data[0])):
        max_len = max(len(row[col_idx]) for row in data)
        col_widths.append(max_len)

    # Построить markdown
    md_lines = []
    # Заголовок (первая строка)
    header = "| " + " | ".join(data[0]) + " |"
    md_lines.append(header)
    # Разделитель
    sep = "|" + "|".join("-" * (w + 2) for w in col_widths) + "|"
    md_lines.append(sep)
    # Остальные строки
    for row in data[1:]:
        # Дополняем строки до нужной длины (если ячеек меньше)
        while len(row) < len(data[0]):
            row.append("")
        line = "| " + " | ".join(row) + " |"
        md_lines.append(line)

    return "\n".join(md_lines)


def convert_docx_to_md(docx_path: Path, md_path: Path):
    """Конвертирует один .docx файл в .md."""
    logger.info(f"Конвертация {docx_path.name} → {md_path.name}")

    try:
        doc = Document(docx_path)
    except Exception as e:
        logger.error(f"Не удалось открыть {docx_path}: {e}")
        return

    md_content = []
    # Обрабатываем все элементы документа по порядку
    for element in doc.element.body:
        if isinstance(element, CT_P):
            # Это параграф
            p = Paragraph(element, doc)
            line = paragraph_to_md(p)
            if line:
                md_content.append(line)
        elif isinstance(element, CT_Tbl):
            # Это таблица
            table = Table(element, doc)
            md_table = table_to_md(table)
            if md_table:
                md_content.append(md_table)
        # Игнорируем другие элементы (например, рисунки)

    # Записываем результат
    try:
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write("\n\n".join(md_content))
        logger.info(f"✅ Сохранён: {md_path}")
    except Exception as e:
        logger.error(f"Ошибка записи {md_path}: {e}")


def main():
    """Основная функция скрипта."""
    ensure_dirs()

    # Проверяем, есть ли .docx файлы
    docx_files = list(DOCS_DIR.glob("*.docx"))
    if not docx_files:
        logger.warning(f"В папке {DOCS_DIR} нет .docx файлов.")
        return

    logger.info(f"Найдено {len(docx_files)} файлов для конвертации.")

    for docx_path in docx_files:
        md_name = docx_path.stem + ".md"
        md_path = KB_DIR / md_name
        convert_docx_to_md(docx_path, md_path)

    logger.info("🎉 Конвертация завершена!")


if __name__ == "__main__":
    main()