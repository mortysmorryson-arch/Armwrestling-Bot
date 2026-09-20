"""
Конфигурация бота: переменные окружения и настройки моделей роя.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PROXY_URL = os.getenv("PROXY_URL", "").strip()

# --- API-ключи моделей ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")

# --- ChromaDB ---
CHROMA_COLLECTION_NAME = "armwrestling_kb"
CHROMA_PATH = "chroma_db"

# --- RAG ---
CHUNK_SIZE = 500

# --- Эмбеддинги (RAG, без локальной Ollama) ---
# Провайдер: "" (авто — по заполненному ключу), "google" или "qwen"
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()
# Модель и размерность: пусто = значения по умолчанию провайдера
# (google: gemini-embedding-001, 768; qwen: text-embedding-v4, 1024)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "").strip()
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "0") or 0)

# --- Модели роя (без прокси) ---
# ВНИМАНИЕ: имена моделей проверяются healthcheck'ом при старте;
# "deepseek-flash" не существует у DeepSeek (была вечная DOWN) — заменён на deepseek-chat.
MODELS = [
    {"name": "gemini-3.1-flash-lite", "provider": "google", "power": 4},
    {"name": "openai/gpt-oss-120b", "provider": "groq", "power": 5},
    {"name": "qwen/qwen3.6-27b", "provider": "groq", "power": 4},
    {"name": "deepseek-chat", "provider": "deepseek", "power": 3},
    {"name": "qwen-plus", "provider": "qwen", "power": 4},
]