# 1. Используем легкий официальный образ Python 3.14
FROM python:3.14-slim

# 2. Устанавливаем переменную окружения, чтобы Python не создавал .pyc файлы и буферизировал логи
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. Рабочая директория внутри контейнера
WORKDIR /app

# 4. Устанавливаем системные зависимости для корректной работы matplotlib (шрифты)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 \
    libpng16-16 \
    && rm -rf /var/lib/apt/lists/*

# 5. Копируем только файл зависимостей (это кэширует слой, если код меняется, а зависимости нет)
COPY requirements.txt .

# 6. Устанавливаем Python-зависимости
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 7. Копируем весь остальной код проекта
COPY . .

# 8. Создаем директорию для базы данных (если её нет)
RUN mkdir -p /app/data

# 9. Указываем боту хранить БД в этой директории
ENV DB_PATH=/app/data/bot.db

# 10. Команда запуска
CMD ["python", "bot.py"]