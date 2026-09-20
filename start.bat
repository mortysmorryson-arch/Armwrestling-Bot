@echo off
chcp 65001 >nul
title ArmWrestling Bot
cd /d "%~dp0"

rem ===== 1. Проверка .env (при первом запуске создаётся из шаблона) =====
if not exist ".env" (
  if exist ".env.example" (
    copy /y ".env.example" ".env" >nul
    echo Создан файл .env из шаблона .env.example
    echo Сейчас откроется блокнот: впишите BOT_TOKEN и ADMIN_ID,
    echo затем сохраните файл и закройте блокнот.
    notepad .env
  )
)
if not exist ".env" (
  echo [ОШИБКА] Нет файла .env. Создайте его рядом с bot.py и впишите:
  echo BOT_TOKEN=токен_от_BotFather
  echo ADMIN_ID=ваш_telegram_id
  pause
  exit /b 1
)

rem ===== 2. Виртуальное окружение (создаётся один раз) =====
if not exist "venv\Scripts\python.exe" (
  echo [1/3] Создаю виртуальное окружение venv...
  python -m venv venv 2>nul || py -m venv venv
)
if not exist "venv\Scripts\python.exe" (
  echo [ОШИБКА] Не удалось создать venv. Проверьте, что Python установлен и добавлен в PATH.
  pause
  exit /b 1
)
set "PY=venv\Scripts\python.exe"

rem ===== 3. Зависимости (ставятся один раз) =====
"%PY%" -c "import aiogram, aiosqlite" >nul 2>&1
if errorlevel 1 (
  echo [2/3] Устанавливаю зависимости, это пара минут...
  "%PY%" -m pip install --upgrade pip
  "%PY%" -m pip install -r requirements.txt
)

rem ===== 4. Запуск =====
echo [3/3] Запускаю бота. Остановка: Ctrl+C или закрытие окна.
"%PY%" bot.py

echo.
echo Бот остановлен.
pause
