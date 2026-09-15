# 🏋️ Armwrestling Bot (и твой DevOps-полигон)

Telegram-бот для тренера по армрестлингу: учёт тренировок, цели, чат с учениками,
 reminders, AI-консультант `/swarm` (рой из 3 LLM + RAG по базе знаний).

## Структура проекта

```
├── bot.py               # точка входа: polling, фоновые задачи, error-handler
├── config.py            # конфиг из .env (12-Factor App: конфигурация вне кода)
├── database.py          # вся работа с SQLite (aiosqlite) + миграции схемы
├── parsers.py           # парсер «Жим 20 3 10» (чистая функция, покрыта тестами)
├── rag.py               # поиск по базе знаний (ChromaDB)
├── embeddings.py        # эмбеддинги через облачные API (Google/Qwen)
├── build_index.py       # индексация knowledge_base/ в ChromaDB
├── swarm_engine.py      # параллельный опрос LLM + судья
├── model_registry.py    # healthcheck моделей каждые 5 минут
├── routers/             # хендлеры aiogram по зонам (common/admin/chat/student/swarm)
├── knowledge_base/      # база знаний (Markdown, подпапки = категории)
├── scripts/
│   ├── verify_phase1.py # автопроверка критических функций (27 проверок)
│   └── check_network.py # диагностика доступа к Telegram (прямое/прокси)
├── Dockerfile           # образ бота
├── docker-compose.yml   # сервис + volumes для данных
└── test_parser.py       # pytest
```

## Запуск локально (Windows/Linux)

```bash
python -m venv venv
venv\Scripts\activate            # Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # заполни BOT_TOKEN, ADMIN_ID, ключи API
python scripts\check_network.py  # диагностика сети → подскажет PROXY_URL
python build_index.py            # разово: индекс базы знаний
python bot.py
```

## Запуск через Docker (модуль 15 курса)

```bash
docker compose up -d --build     # сборка + запуск
docker compose logs -f bot       # логи
docker compose down              # остановка (данные сохранятся в volumes)
```

**Важно про volumes (модуль 20 «Хранение в Docker»):** БД (`./data`) и RAG-индекс
(`./chroma_db`) смонтированы с хоста. Контейнер можно удалять и пересобирать —
данные переживут. Перед первым запуском в Docker выполните на хосте
`python build_index.py` (индекс строится на хосте и монтируется в контейнер).

## Команды бота

- `/swarm <запрос>` — AI-консультант: рой из 3 моделей + база знаний, гибридный
  режим (база — приоритет, пробелы помечены [ОБЩИЕ ПРИНЦИПЫ]);
- `/health` — состояние: модели, БД, индекс (админ);
- `/students`, `/invites`, `/block`, `/unblock`, `/revoke` — админ-функции;
- текст «Жим 20 3 10, Пронация 15 4 12» — запись тренировки.

## Прокси

`PROXY_URL` в `.env` — список через запятую, бот переключается сам:
`socks5://127.0.0.1:10808, http://127.0.0.1:10809`
(локальные порты Happ; системный VPN не нужен). Диагностика: `scripts/check_network.py`.

## Тесты и проверки

```bash
pytest test_parser.py -v          # юнит-тесты парсера
python scripts/verify_phase1.py   # 27 интеграционных проверок (БД, планировщик, импорт)
```

## 🎓 Что этот проект покрывает из курса DevOps

| Тема курса | Где в проекте |
|---|---|
| Linux [1–13] | серверный деплой, права на volumes, bash для хоста |
| Linux [11] cron | домашка №2: бэкапы БД по расписанию |
| Linux [12] iptables | домашка №1: фаервол для VPS |
| Linux [14] Диски/LVM | том ./data на сервере, мониторинг места |
| Docker [15], Docker для начинающих | Dockerfile, compose, volumes, логи |
| Git [32–34] | ведите проект в репозитории (домашка №3) |
| GitLab CI [42–48] | будущий этап: pipeline с ruff+pytest (скрипты готовы) |
| Prometheus [50–58] | будущий этап: экспортер метрик бота → Grafana |

## Домашние задания (в порядке сложности)

1. **VPS + фаервол**: возьмите дешёвый VPS, установите Ubuntu, настройте SSH-ключи,
   ufw/iptables: открыт только 22-й порт. Разверните бота через docker compose.
2. **Бэкапы**: crontab-задача каждую ночь: `sqlite3 data/bot.db ".backup ..."` +
   копия `chroma_db` в tar-архив с датой, ротация 7 дней (bash + find -mtime).
3. **Git + CI**: инициализируйте репозиторий (без `.env` и `bot.db`!), отправьте на
   GitHub/GitLab, добавьте `.gitlab-ci.yml`: этапы `lint` (ruff) и `test` (pytest).
