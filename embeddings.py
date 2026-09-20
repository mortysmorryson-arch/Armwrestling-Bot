#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Эмбеддинги через облачные API — БЕЗ локальной Ollama.

Используется существующий ключ из .env, ничего дополнительно ставить/запускать
не нужно:
  • google (по умолчанию) — gemini-embedding-001 через GOOGLE_API_KEY;
  • qwen — text-embedding-v4 через QWEN_API_KEY (dashscope).

Выбор провайдера: переменная EMBEDDING_PROVIDER в .env (google|qwen) или
автоматически — по тому, какой ключ заполнен.
ВНИМАНИЕ: смена модели эмбеддингов требует пересборки индекса (build_index.py).
"""

import logging
import os
import time
from typing import List, Optional

import requests

try:
    from config import (
        GOOGLE_API_KEY, QWEN_API_KEY,
        EMBEDDING_PROVIDER, EMBEDDING_MODEL, EMBEDDING_DIMENSION,
    )
except ImportError:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
    QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
    EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "").strip()
    EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "0") or 0)

logger = logging.getLogger(__name__)

# Размер вектора: 768 у Google (Matryoshka-усечение полной размерности 3072),
# 1024 у Qwen. Экономит место и ускоряет поиск, качество поиска не страдает.
GOOGLE_DEFAULT_MODEL = "gemini-embedding-001"
GOOGLE_DEFAULT_DIM = 768
QWEN_DEFAULT_MODEL = "text-embedding-v4"
QWEN_DEFAULT_DIM = 1024

_TIMEOUT = 30


def get_config() -> dict:
    """Возвращает активную конфигурацию эмбеддера (с автодетектом провайдера)."""
    provider = EMBEDDING_PROVIDER
    if not provider:
        if GOOGLE_API_KEY:
            provider = "google"
        elif QWEN_API_KEY:
            provider = "qwen"
        else:
            raise RuntimeError(
                "Не настроены эмбеддинги: в .env нет ни GOOGLE_API_KEY, ни QWEN_API_KEY. "
                "Заполните один из ключей (или задайте EMBEDDING_PROVIDER явно)."
            )
    if provider == "google":
        if not GOOGLE_API_KEY:
            raise RuntimeError("EMBEDDING_PROVIDER=google, но GOOGLE_API_KEY пуст в .env")
        return {
            "provider": provider,
            "model": EMBEDDING_MODEL or GOOGLE_DEFAULT_MODEL,
            "dim": EMBEDDING_DIMENSION or GOOGLE_DEFAULT_DIM,
        }
    if provider == "qwen":
        if not QWEN_API_KEY:
            raise RuntimeError("EMBEDDING_PROVIDER=qwen, но QWEN_API_KEY пуст в .env")
        return {
            "provider": provider,
            "model": EMBEDDING_MODEL or QWEN_DEFAULT_MODEL,
            "dim": EMBEDDING_DIMENSION or QWEN_DEFAULT_DIM,
        }
    raise RuntimeError(f"Неизвестный EMBEDDING_PROVIDER: {provider!r} (доступны: google, qwen)")


def _post_with_retry(url: str, payload: dict, headers: dict, attempts: int = 3):
    """POST с ретраем на 429/5xx и сетевые ошибки (бэкофф 2с, 4с)."""
    last_exc: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                logger.warning(f"Эмбеддинг: {last_exc}; повтор {attempt + 2}/{attempts}")
                time.sleep(2 * (attempt + 1))
                continue
            if not resp.ok:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        except requests.exceptions.RequestException as e:
            last_exc = e
            logger.warning(f"Эмбеддинг: сетевая ошибка ({e}); повтор {attempt + 2}/{attempts}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Эмбеддинг не удался после {attempts} попыток: {last_exc}")


def _embed_google(texts: List[str], task_type: str) -> List[List[float]]:
    """Gemini embeddings. task_type: RETRIEVAL_QUERY или RETRIEVAL_DOCUMENT."""
    cfg = get_config()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{cfg['model']}:batchEmbedContents"
    )
    headers = {"x-goog-api-key": GOOGLE_API_KEY}
    payload = {
        "requests": [
            {
                "model": f"models/{cfg['model']}",
                "content": {"parts": [{"text": t}]},
                "taskType": task_type,
                "outputDimensionality": cfg["dim"],
            }
            for t in texts
        ]
    }
    data = _post_with_retry(url, payload, headers)
    embeddings = data.get("embeddings")
    if not embeddings or len(embeddings) != len(texts):
        raise RuntimeError(f"Неожиданный ответ Google embeddings: {str(data)[:300]}")
    return [e["values"] for e in embeddings]


def _embed_qwen(texts: List[str]) -> List[List[float]]:
    """Qwen text-embedding-v4 через dashscope (OpenAI-совместимый режим)."""
    cfg = get_config()
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
    headers = {"Authorization": f"Bearer {QWEN_API_KEY}"}
    payload = {"model": cfg["model"], "input": texts, "dimensions": cfg["dim"]}
    data = _post_with_retry(url, payload, headers)
    items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
    if len(items) != len(texts):
        raise RuntimeError(f"Неожиданный ответ Qwen embeddings: {str(data)[:300]}")
    return [item["embedding"] for item in items]


def embed_texts(texts: List[str], is_query: bool = False) -> List[List[float]]:
    """
    Векторизация пакета текстов (для build_index).
    Для запросов (is_query=True) используется task_type запроса.
    """
    if not texts:
        return []
    provider = get_config()["provider"]
    if provider == "google":
        task_type = "RETRIEVAL_QUERY" if is_query else "RETRIEVAL_DOCUMENT"
        return _embed_google(texts, task_type)
    return _embed_qwen(texts)


def embed_query(text: str) -> List[float]:
    """Векторизация одного запроса (для rag.retrieve)."""
    return embed_texts([text], is_query=True)[0]
