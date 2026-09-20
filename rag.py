#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Модуль RAG (Retrieval-Augmented Generation) для поиска релевантных чанков в ChromaDB.
Асинхронная обёртка над синхронным клиентом ChromaDB.
Эмбеддинги — облачные (см. embeddings.py), без локальной Ollama.
"""

import asyncio
import logging
from typing import List, Dict, Any

try:
    import chromadb
except ImportError:
    raise ImportError("Установите chromadb: pip install chromadb")

from embeddings import embed_query, get_config

try:
    from config import CHROMA_COLLECTION_NAME, CHROMA_PATH
except ImportError:
    CHROMA_COLLECTION_NAME = "armwrestling_kb"
    CHROMA_PATH = "chroma_db"
    logging.warning("config.py не найден, используются значения по умолчанию")

logger = logging.getLogger(__name__)


def _get_collection():
    """Подключается к коллекции с проверкой совпадения модели эмбеддингов."""
    cfg = get_config()
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_collection(CHROMA_COLLECTION_NAME)
    meta = collection.metadata or {}
    indexed_model = meta.get("embedding_model")
    if not indexed_model:
        # Метаданных нет → коллекция от старого индексатора (bge-m3/Ollama)
        raise RuntimeError(
            "Индекс построен старым индексатором (bge-m3/Ollama). "
            "Пересоберите: python build_index.py"
        )
    indexed_dim = meta.get("embedding_dim")
    if indexed_model != cfg["model"]:
        raise RuntimeError(
            f"Индекс построен моделью {indexed_model}, а сейчас активна {cfg['model']}. "
            f"Пересоберите индекс: python build_index.py"
        )
    if indexed_dim and indexed_dim != cfg["dim"]:
        raise RuntimeError(
            f"Размерность индекса ({indexed_dim}) не совпадает с текущей ({cfg['dim']}). "
            f"Пересоберите индекс: python build_index.py"
        )
    return collection


def _search_chromadb(query_vector: List[float], top_n: int) -> List[Dict[str, Any]]:
    """
    Синхронный поиск в ChromaDB по вектору запроса.
    Возвращает список словарей с полями text, source, source_type, distance.
    """
    try:
        collection = _get_collection()
    except RuntimeError:
        raise  # понятные ошибки конфигурации пробрасываем как есть
    except Exception as e:
        logger.error(
            f"Ошибка подключения к ChromaDB: {e}. "
            f"Если индекса нет — соберите его: python build_index.py"
        )
        return []

    try:
        results = collection.query(
            query_embeddings=[query_vector],
            n_results=top_n,
            include=["documents", "metadatas", "distances"]
        )
    except Exception as e:
        logger.error(f"Ошибка запроса к ChromaDB: {e}")
        return []

    docs = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    output = []
    for i, doc in enumerate(docs):
        output.append({
            "text": doc,
            "source": metadatas[i].get("source", "unknown"),
            "source_type": metadatas[i].get("source_type", "unknown"),
            "chunk_index": metadatas[i].get("chunk_index", 0),
            "distance": distances[i] if distances else None,
        })
    return output


async def retrieve(query: str, top_n: int = 3) -> List[Dict[str, Any]]:
    """
    Асинхронный поиск релевантных чанков в базе знаний.

    Возвращает список словарей с ключами:
        text, source, source_type, chunk_index, distance.
    При ошибке эмбеддинга/поиска возвращает [] — RAG просто не дополнит промпт.
    """
    if not query or not query.strip():
        logger.warning("Пустой запрос, возвращаем пустой список")
        return []

    def _sync_retrieve():
        embedding = embed_query(query)
        return _search_chromadb(embedding, top_n)

    try:
        result = await asyncio.to_thread(_sync_retrieve)
        return result
    except RuntimeError as e:
        # Ошибки конфигурации (не та модель/размерность, нет ключа) — громко в лог
        logger.error(f"RAG недоступен: {e}")
        return []
    except Exception as e:
        logger.error(f"Ошибка в retrieve: {e}")
        return []
