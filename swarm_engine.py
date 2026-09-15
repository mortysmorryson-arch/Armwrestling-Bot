#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Движок роя: параллельный опрос моделей + председатель.
Без прокси — все запросы идут напрямую (через системный VPN).
Ретрай: одна повторная попытка с бэкоффом 2 секунды.
"""

import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any

import requests

try:
    from config import (
        GOOGLE_API_KEY, GROQ_API_KEY,
        DEEPSEEK_API_KEY, QWEN_API_KEY,
    )
except ImportError:
    GOOGLE_API_KEY = ""
    GROQ_API_KEY = ""
    DEEPSEEK_API_KEY = ""
    QWEN_API_KEY = ""

logger = logging.getLogger(__name__)


class FatalApiError(Exception):
    """Неповторяемая ошибка API (4xx, кроме 429): ретрай бессмысленен."""


# ---------- HTTP-вызовы ----------

def _call_google(model: str, prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    r = requests.post(
        url,
        params={"key": GOOGLE_API_KEY},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 4096},
        },
        timeout=60,
    )
    if r.status_code == 429:
        raise Exception("429 Rate Limit")
    if r.status_code == 413:
        raise FatalApiError(
            "HTTP 413: промпт слишком большой для этой модели (лимит токенов). "
            "Сократите запрос или базу знаний."
        )
    if not r.ok:
        if 400 <= r.status_code < 500:
            raise FatalApiError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _call_groq(model: str, prompt: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4000,
            "temperature": 0.7,
        },
        timeout=60,
    )
    if r.status_code == 429:
        raise Exception("429 Rate Limit")
    if r.status_code == 413:
        raise FatalApiError(
            "HTTP 413: промпт слишком большой для этой модели (лимит токенов). "
            "Сократите запрос или базу знаний."
        )
    if not r.ok:
        if 400 <= r.status_code < 500:
            raise FatalApiError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


def _call_deepseek(model: str, prompt: str) -> str:
    url = "https://api.deepseek.com/chat/completions"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4000,
            "temperature": 0.7,
        },
        timeout=60,
    )
    if r.status_code == 429:
        raise Exception("429 Rate Limit")
    if r.status_code == 413:
        raise FatalApiError(
            "HTTP 413: промпт слишком большой для этой модели (лимит токенов). "
            "Сократите запрос или базу знаний."
        )
    if not r.ok:
        if 400 <= r.status_code < 500:
            raise FatalApiError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


def _call_qwen(model: str, prompt: str) -> str:
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {QWEN_API_KEY}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4000,
            "temperature": 0.7,
        },
        timeout=60,
    )
    if r.status_code == 429:
        raise Exception("429 Rate Limit")
    if r.status_code == 413:
        raise FatalApiError(
            "HTTP 413: промпт слишком большой для этой модели (лимит токенов). "
            "Сократите запрос или базу знаний."
        )
    if not r.ok:
        if 400 <= r.status_code < 500:
            raise FatalApiError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


def _ask_one(model_status, prompt: str) -> str:
    provider = model_status.provider
    name = model_status.name
    if provider == "google":
        return _call_google(name, prompt)
    elif provider == "groq":
        return _call_groq(name, prompt)
    elif provider == "deepseek":
        return _call_deepseek(name, prompt)
    elif provider == "qwen":
        return _call_qwen(name, prompt)
    else:
        raise Exception(f"Провайдер '{provider}' не поддерживается")


# ---------- Failover ----------

def ask_with_retry(model_status, prompt: str) -> Dict[str, Any]:
    """Один запрос к модели. При ошибке — один повтор с бэкоффом 2 секунды."""
    start = time.time()

    try:
        text = _ask_one(model_status, prompt)
        return {
            "model": model_status.name,
            "provider": model_status.provider,
            "text": text,
            "time": time.time() - start,
        }
    except FatalApiError as e:
        # 4xx (кроме 429): повтор с тем же промптом даст ту же ошибку
        logger.error(f"Фатальная ошибка {model_status.name}: {e}")
        return {
            "model": model_status.name,
            "provider": model_status.provider,
            "text": f"❌ {e}",
            "time": time.time() - start,
        }
    except Exception as e:
        logger.warning(f"Ошибка {model_status.name}: {e}. Повтор через 2с.")

    time.sleep(2)

    try:
        text = _ask_one(model_status, prompt)
        return {
            "model": model_status.name,
            "provider": model_status.provider,
            "text": text,
            "time": time.time() - start,
        }
    except Exception as e:
        logger.error(f"Повторная ошибка {model_status.name}: {e}")
        return {
            "model": model_status.name,
            "provider": model_status.provider,
            "text": f"❌ {e}",
            "time": time.time() - start,
        }


# ---------- Swarm ----------

class Swarm:
    def __init__(self, registry, overall_timeout: int = 90):
        self.registry = registry
        self.overall_timeout = overall_timeout

    def run(self, prompt: str, run_judge: bool = True):
        if self.registry is None:
            raise Exception("Реестр моделей не инициализирован")

        available = self.registry.get_available(top_n=3)
        if len(available) == 0:
            raise Exception("Все модели недоступны")
        if len(available) < 2:
            raise Exception(f"Недостаточно моделей для роя: {len(available)} (нужно минимум 2)")

        logger.info(f"Рой запущен: {[m.name for m in available]}")

        answers: List[Dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=len(available)) as ex:
            futures = [ex.submit(ask_with_retry, m, prompt) for m in available]
            for fut in as_completed(futures):
                try:
                    answers.append(fut.result(timeout=self.overall_timeout))
                except Exception as e:
                    logger.error(f"Критическая ошибка воркера: {e}")

        if not run_judge:
            return answers, None

        good = [a for a in answers if not a["text"].startswith("❌")]
        if len(good) < 2:
            return answers, {
                "model": "error",
                "provider": "error",
                "text": f"⚠️ Недостаточно успешных ответов: {len(good)} из {len(available)}",
                "time": 0,
            }

        combined = "\n\n".join(
            f"--- {a['model']} ({a['provider']}):\n{a['text']}" for a in good
        )
        judge_prompt = (
            f"Задача: {prompt}\n\n"
            f"Ответы экспертов роя:\n{combined}\n\n"
            "Ты — председатель. На основе ответов экспертов составь ЕДИНЫЙ ГОТОВЫЙ ПЛАН "
            "ТРЕНИРОВОК для тренера. Дай конкретную программу с упражнениями, весом, "
            "подходами, повторениями, прогрессией и контрольными маркерами. "
            "Не описывай ошибки каждого эксперта — просто дай итоговый лучший вариант. "
            "Программа должна быть практичной и понятной тренеру."
        )

        # Судья: на большом объединённом ответе модели с жёстким TPM (Groq)
        # ловят 413 — тогда судьим ставим модель с большим контекстом (Google)
        judge_model = available[0]
        if len(combined) > 4000:
            big_context = [m for m in available if m.provider == "google"]
            if big_context:
                judge_model = big_context[0]
                logger.info(f"Судья (большой контекст): {judge_model.name}")
        try:
            verdict = ask_with_retry(judge_model, judge_prompt)
            return answers, verdict
        except Exception as e:
            logger.error(f"Ошибка судьи: {e}")
            return answers, {
                "model": "error",
                "provider": "error",
                "text": f"❌ Судья упал: {e}",
                "time": 0,
            }