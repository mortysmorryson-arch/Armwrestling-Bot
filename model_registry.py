#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Реестр моделей роя: периодический пинг доступности.
Без прокси — все запросы идут напрямую (через системный VPN).
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import aiohttp

try:
    from config import (
        MODELS, GOOGLE_API_KEY, GROQ_API_KEY,
        DEEPSEEK_API_KEY, QWEN_API_KEY,
    )
except ImportError:
    MODELS = []
    GOOGLE_API_KEY = ""
    GROQ_API_KEY = ""
    DEEPSEEK_API_KEY = ""
    QWEN_API_KEY = ""
    logging.warning("config.py не найден, реестр будет пустой")

logger = logging.getLogger(__name__)

HEALTHCHECK_INTERVAL = 300  # 5 минут
PING_TIMEOUT = 15


@dataclass
class ModelStatus:
    name: str
    provider: str
    power: int
    available: bool = False
    latency: float = float('inf')
    last_check: float = 0.0


class ModelRegistry:
    def __init__(self):
        self.models: List[ModelStatus] = [ModelStatus(**m) for m in MODELS]
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        logger.info(f"Реестр инициализирован: {len(self.models)} моделей")

    # ---------- Пинги ----------

    async def _ping_google(self, name: str) -> Tuple[bool, float]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent"
        try:
            start = time.time()
            timeout = aiohttp.ClientTimeout(total=PING_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    params={"key": GOOGLE_API_KEY},
                    json={
                        "contents": [{"parts": [{"text": "1"}]}],
                        "generationConfig": {"maxOutputTokens": 1},
                    },
                ) as resp:
                    if resp.status == 200:
                        return True, time.time() - start
                    return False, float('inf')
        except Exception as e:
            logger.debug(f"Google '{name}': {type(e).__name__}: {e}")
            return False, float('inf')

    async def _ping_groq(self, name: str) -> Tuple[bool, float]:
        url = "https://api.groq.com/openai/v1/chat/completions"
        try:
            start = time.time()
            timeout = aiohttp.ClientTimeout(total=PING_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    json={
                        "model": name,
                        "messages": [{"role": "user", "content": "1"}],
                        "max_tokens": 1,
                    },
                ) as resp:
                    if resp.status == 200:
                        return True, time.time() - start
                    return False, float('inf')
        except Exception as e:
            logger.debug(f"Groq '{name}': {type(e).__name__}: {e}")
            return False, float('inf')

    async def _ping_deepseek(self, name: str) -> Tuple[bool, float]:
        url = "https://api.deepseek.com/v1/chat/completions"
        try:
            start = time.time()
            timeout = aiohttp.ClientTimeout(total=PING_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                    json={
                        "model": name,
                        "messages": [{"role": "user", "content": "1"}],
                        "max_tokens": 1,
                    },
                ) as resp:
                    if resp.status == 200:
                        return True, time.time() - start
                    return False, float('inf')
        except Exception as e:
            logger.debug(f"DeepSeek '{name}': {type(e).__name__}: {e}")
            return False, float('inf')

    async def _ping_qwen(self, name: str) -> Tuple[bool, float]:
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        try:
            start = time.time()
            timeout = aiohttp.ClientTimeout(total=PING_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    headers={"Authorization": f"Bearer {QWEN_API_KEY}"},
                    json={
                        "model": name,
                        "messages": [{"role": "user", "content": "1"}],
                        "max_tokens": 1,
                    },
                ) as resp:
                    if resp.status == 200:
                        return True, time.time() - start
                    return False, float('inf')
        except Exception as e:
            logger.debug(f"Qwen '{name}': {type(e).__name__}: {e}")
            return False, float('inf')

    async def _ping_model(self, model: ModelStatus) -> Tuple[bool, float]:
        if model.provider == "google":
            return await self._ping_google(model.name)
        elif model.provider == "groq":
            return await self._ping_groq(model.name)
        elif model.provider == "deepseek":
            return await self._ping_deepseek(model.name)
        elif model.provider == "qwen":
            return await self._ping_qwen(model.name)
        else:
            logger.debug(f"Провайдер '{model.provider}' не поддерживается")
            return False, float('inf')

    # ---------- Healthcheck ----------

    async def _check_all(self):
        async with self._lock:
            for model in self.models:
                alive, latency = await self._ping_model(model)
                model.available = alive
                model.latency = latency
                model.last_check = time.time()

            alive_count = sum(1 for m in self.models if m.available)
            details = " | ".join(
                f"{m.name}={'UP' if m.available else 'DOWN'}"
                + (f"({m.latency:.2f}s)" if m.available else "")
                for m in self.models
            )
            logger.info(f"Healthcheck: {alive_count}/{len(self.models)} живых | {details}")

    async def start_healthcheck(self):
        if self._task is None:
            self._task = asyncio.create_task(self._healthcheck_loop())

    async def _healthcheck_loop(self):
        while True:
            try:
                await self._check_all()
            except Exception as e:
                logger.error(f"Ошибка в healthcheck: {type(e).__name__}: {e}")
            await asyncio.sleep(HEALTHCHECK_INTERVAL)

    # ---------- API ----------

    def get_available(self, top_n: int = 3) -> List[ModelStatus]:
        available = [m for m in self.models if m.available]
        available.sort(key=lambda m: (-m.power, m.latency))
        return available[:top_n]

    def get_model(self, name: str) -> Optional[ModelStatus]:
        for m in self.models:
            if m.name == name:
                return m
        return None


# ---------- Глобальный реестр ----------

_registry: Optional[ModelRegistry] = None


def init_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


def get_registry() -> Optional[ModelRegistry]:
    return _registry