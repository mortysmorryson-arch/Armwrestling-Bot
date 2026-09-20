#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Индексатор базы знаний для RAG.
Читает .md из knowledge_base/, разбивает на чанки,
получает эмбеддинги через ОБЛАЧНЫЙ API (см. embeddings.py — без Ollama)
и сохраняет в ChromaDB.

Запуск: python build_index.py
Требуется GOOGLE_API_KEY или QWEN_API_KEY в .env.
"""

import os
import re
import logging
from pathlib import Path
from typing import List

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    print("❌ Установите chromadb: pip install chromadb")
    exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Загрузка конфигурации
try:
    from config import CHUNK_SIZE, CHROMA_COLLECTION_NAME
except ImportError:
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
    CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "armwrestling_kb")
    logger.warning("config.py не найден, используются значения по умолчанию")

from embeddings import embed_texts, get_config  # noqa: E402

# Константы
KB_DIR = Path("knowledge_base")
CHROMA_PATH = Path("chroma_db")
OVERLAP_RATIO = 0.15
# Размер батча запросов эмбеддингов (у Qwen лимит ~10 текстов на запрос)
EMBED_BATCH_SIZES = {"google": 32, "qwen": 10}


def get_source_type(file_path: Path) -> str:
    rel = file_path.relative_to(KB_DIR)
    if len(rel.parents) >= 1:
        return rel.parts[0] if rel.parts else "unknown"
    return "unknown"


def read_md_files() -> List[Path]:
    if not KB_DIR.exists():
        logger.warning(f"Папка {KB_DIR} не существует. Создайте её и добавьте .md файлы.")
        return []
    files = list(KB_DIR.rglob("*.md"))
    logger.info(f"Найдено {len(files)} .md файлов")
    return files


def split_text_into_chunks(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = None) -> List[str]:
    if overlap is None:
        overlap = int(chunk_size * OVERLAP_RATIO)

    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    if not paragraphs:
        return []

    chunks = []
    current_chunk = []
    current_len = 0

    for para in paragraphs:
        sentences = []
        if len(para) > chunk_size:
            raw_sentences = re.split(r'(?<=[.!?])\s+', para)
            sentences = [s.strip() for s in raw_sentences if s.strip()]
        else:
            sentences = [para]

        for sentence in sentences:
            sentence_len = len(sentence)
            if current_len + sentence_len <= chunk_size:
                current_chunk.append(sentence)
                current_len += sentence_len
            else:
                if current_chunk:
                    chunks.append(' '.join(current_chunk))
                overlap_text = []
                overlap_len = 0
                for sent in reversed(current_chunk):
                    if overlap_len + len(sent) <= overlap:
                        overlap_text.insert(0, sent)
                        overlap_len += len(sent)
                    else:
                        break
                current_chunk = overlap_text + [sentence]
                current_len = overlap_len + sentence_len

    if current_chunk:
        chunks.append(' '.join(current_chunk))

    return chunks


def clear_collection(collection, source_names: List[str]):
    if not source_names:
        return
    try:
        results = collection.get(where={"source": {"$in": source_names}})
        ids = results["ids"]
        if ids:
            collection.delete(ids)
            logger.info(f"Удалено {len(ids)} чанков из {len(source_names)} источников")
    except Exception as e:
        logger.warning(f"Ошибка очистки коллекции: {e}")


def build_index():
    try:
        cfg = get_config()
    except RuntimeError as e:
        logger.error(f"❌ {e}")
        return
    logger.info(f"Эмбеддинги: {cfg['provider']} / {cfg['model']} (dim={cfg['dim']})")

    try:
        client = chromadb.PersistentClient(path=str(CHROMA_PATH))

        # Если коллекция старая (легаси bge-m3 без метаданных) или построена
        # другой моделью — пересоздаём под текущую модель эмбеддингов
        try:
            existing = client.get_collection(CHROMA_COLLECTION_NAME)
            meta = existing.metadata or {}
            if "embedding_model" not in meta:
                logger.warning(
                    "Найден старый индекс без метаданных (bge-m3/Ollama). "
                    f"Пересоздаю под {cfg['model']} (dim={cfg['dim']})"
                )
                client.delete_collection(CHROMA_COLLECTION_NAME)
            elif meta.get("embedding_model") != cfg["model"] or meta.get("embedding_dim") != cfg["dim"]:
                logger.warning(
                    f"Индекс построен {meta.get('embedding_model')}(dim={meta.get('embedding_dim')}), "
                    f"пересоздаю под {cfg['model']}(dim={cfg['dim']})"
                )
                client.delete_collection(CHROMA_COLLECTION_NAME)
        except Exception:
            pass  # коллекции нет — просто создадим

        collection = client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            metadata={
                "embedding_model": cfg["model"],
                "embedding_dim": cfg["dim"],
            }
        )
        logger.info(f"Коллекция '{CHROMA_COLLECTION_NAME}' готова")
    except Exception as e:
        logger.error(f"Ошибка инициализации ChromaDB: {e}")
        return

    files = read_md_files()
    if not files:
        return

    all_chunks = []
    all_metadatas = []
    all_ids = []
    sources_set = set()

    for file_path in files:
        logger.info(f"Обработка {file_path}")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read()
        except Exception as e:
            logger.error(f"Ошибка чтения {file_path}: {e}")
            continue

        chunks = split_text_into_chunks(text)
        if not chunks:
            logger.warning(f"Файл {file_path} пуст или не содержит текста")
            continue

        source = file_path.name
        source_type = get_source_type(file_path)
        sources_set.add(source)

        for idx, chunk in enumerate(chunks):
            doc_id = f"{source}_{idx}"
            all_ids.append(doc_id)
            all_chunks.append(chunk)
            all_metadatas.append({
                "source": source,
                "source_type": source_type,
                "chunk_index": idx,
                "file_path": str(file_path)
            })

    logger.info(f"Всего чанков для индексации: {len(all_chunks)}")
    if not all_chunks:
        logger.warning("Нет чанков для индексации")
        return

    clear_collection(collection, list(sources_set))

    # Векторизация батчами (размер зависит от лимитов провайдера)
    embed_batch_size = EMBED_BATCH_SIZES.get(cfg["provider"], 10)
    all_embeddings: List[List[float]] = []
    try:
        for i in range(0, len(all_chunks), embed_batch_size):
            batch = all_chunks[i:i + embed_batch_size]
            vectors = embed_texts(batch)
            if len(vectors) != len(batch):
                raise RuntimeError(f"Получено {len(vectors)} векторов на {len(batch)} текстов")
            all_embeddings.extend(vectors)
            logger.info(f"Эмбеддинги {min(i + embed_batch_size, len(all_chunks))}/{len(all_chunks)}")
    except Exception as e:
        logger.error(f"Ошибка получения эмбеддингов: {e}")
        return

    try:
        # Добавляем в ChromaDB батчами по 100
        batch_size = 100
        for i in range(0, len(all_ids), batch_size):
            batch_ids = all_ids[i:i+batch_size]
            batch_chunks = all_chunks[i:i+batch_size]
            batch_metadatas = all_metadatas[i:i+batch_size]
            batch_vectors = all_embeddings[i:i+batch_size]

            collection.add(
                ids=batch_ids,
                documents=batch_chunks,
                metadatas=batch_metadatas,
                embeddings=batch_vectors
            )
            logger.info(f"Добавлена партия {i+1}-{min(i+batch_size, len(all_ids))} из {len(all_ids)}")
    except Exception as e:
        logger.error(f"Ошибка добавления в ChromaDB: {e}")
        return

    logger.info(f"✅ Индексация завершена. Добавлено {len(all_ids)} чанков в коллекцию '{CHROMA_COLLECTION_NAME}'")
    logger.info(f"📂 ChromaDB сохранена в {CHROMA_PATH}")


if __name__ == "__main__":
    build_index()