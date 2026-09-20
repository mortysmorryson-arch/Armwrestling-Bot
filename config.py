"""
Конфигурация — v5: точные ID из твоего discover.py (20.09.2026)
Groq у тебя отдает: qwen/qwen3.8-27b, openai/gpt-oss-20b/120b
Google у тебя отдает: gemini-2.5-flash, gemini-2.5-pro, gemini-flash-latest
"""
import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PROXY_URL = os.getenv("PROXY_URL", "").strip()

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

CHROMA_COLLECTION_NAME = "armwrestling_kb"
CHROMA_PATH = "chroma_db"
CHUNK_SIZE = 500
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "").strip()
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "0") or 0)

MODELS = [
    # Groq — проверены твоим discover.py (status 200)
    {"name": "openai/gpt-oss-20b", "provider": "groq", "power": 5},  # UP
    {"name": "openai/gpt-oss-120b", "provider": "groq", "power": 5}, # UP
    {"name": "qwen/qwen3.8-27b", "provider": "groq", "power": 4},     # discover показал active:true
    {"name": "allam-2-7b", "provider": "groq", "power": 3},          # discover показал

    # Google — стабильные, твои gemini-2.5 сейчас 404/503, оставляем только рабочий
    # {"name": "gemini-2.5-flash", "provider": "google", "power": 5},         # 404 у тебя
    # {"name": "gemini-flash-latest", "provider": "google", "power": 4},      # 503 high demand
    {"name": "gemini-3.1-flash-lite", "provider": "google", "power": 5},    # UP(2.57s) — оставляем

    # Qwen / DeepSeek / OpenRouter — пока закомментированы, раскомментируй после фикса ключа/баланса
    # {"name": "qwen-plus", "provider": "qwen", "power": 3},
    # {"name": "deepseek-chat", "provider": "deepseek", "power": 3},
    # {"name": "google/gemma-3-4b-it:free", "provider": "openrouter", "power": 3},
]
