#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Реестр моделей роя — FIXED v2 с поддержкой PROXY (Happ)
Что починено:
1. Пишет ПОЧЕМУ DOWN
2. Правильные имена моделей
3. ИДЕТ ЧЕРЕЗ PROXY_URL (как Telegram) — фиксит ClientConnectorError
"""
import asyncio
import logging
import time
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import aiohttp

try:
    from aiohttp_socks import ProxyConnector
    HAS_SOCKS = True
except ImportError:
    HAS_SOCKS = False
    ProxyConnector = None

try:
    from config import (
        MODELS, GOOGLE_API_KEY, GROQ_API_KEY,
        DEEPSEEK_API_KEY, QWEN_API_KEY,
        OPENROUTER_API_KEY,
        PROXY_URL,
    )
except ImportError:
    MODELS = []
    GOOGLE_API_KEY = ""
    GROQ_API_KEY = ""
    DEEPSEEK_API_KEY = ""
    QWEN_API_KEY = ""
    OPENROUTER_API_KEY = ""
    PROXY_URL = ""
    logging.warning("config.py не найден, реестр будет пустой")

logger = logging.getLogger(__name__)

HEALTHCHECK_INTERVAL = 300
PING_TIMEOUT = 15

@dataclass
class ModelStatus:
    name: str
    provider: str
    power: int
    available: bool = False
    latency: float = float('inf')
    last_check: float = 0.0
    last_error: str = ""

def _parse_proxy_list(raw: str) -> List[Optional[str]]:
    result: List[Optional[str]] = []
    for part in re.split(r"[,;]+", raw or ""):
        part = part.strip()
        if not part:
            continue
        if part.lower() in {"direct", "none", "no", "-"}:
            result.append(None)
        elif "://" in part:
            result.append(part)
    return result

def _get_proxy() -> Optional[str]:
    proxies = _parse_proxy_list(PROXY_URL)
    return proxies[0] if proxies else None

def _make_session_kwargs(proxy: Optional[str]):
    """Возвращает kwargs для aiohttp.ClientSession с учетом SOCKS"""
    if not proxy:
        return {}
    if proxy.startswith("socks") and HAS_SOCKS:
        try:
            connector = ProxyConnector.from_url(proxy)
            return {"connector": connector}
        except Exception as e:
            logger.warning(f"Не смог создать SOCKS коннектор {proxy}: {e}")
            return {}
    # для http прокси будем передавать proxy в каждый запрос, не в сессию
    return {}

class ModelRegistry:
    def __init__(self):
        self.models: List[ModelStatus] = [ModelStatus(**m) for m in MODELS]
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        proxy = _get_proxy()
        logger.info(f"Реестр инициализирован: {len(self.models)} моделей | Прокси: {proxy or 'напрямую (direct)'}")
        for m in self.models:
            if not self._has_key(m.provider):
                logger.warning(f"⚠️ {m.name} ({m.provider}): нет API ключа — будет SKIP")

    def _has_key(self, provider: str) -> bool:
        keys = {
            "google": GOOGLE_API_KEY,
            "groq": GROQ_API_KEY,
            "deepseek": DEEPSEEK_API_KEY,
            "qwen": QWEN_API_KEY,
            "openrouter": OPENROUTER_API_KEY if 'OPENROUTER_API_KEY' in globals() else "",
        }
        return bool(keys.get(provider, "").strip())

    # ---------- helpers для прокси ----------
    async def _post_with_proxy(self, url, *, headers=None, params=None, json=None, proxy=None):
        """Единый POST с поддержкой SOCKS/HTTP прокси"""
        timeout = aiohttp.ClientTimeout(total=PING_TIMEOUT)
        proxy_to_use = proxy if proxy is not None else _get_proxy()
        kwargs = _make_session_kwargs(proxy_to_use)
        # если это http-прокси (не socks), то передаем proxy в запрос
        request_proxy = proxy_to_use if proxy_to_use and proxy_to_use.startswith("http") else None
        
        async with aiohttp.ClientSession(timeout=timeout, **kwargs) as session:
            async with session.post(url, headers=headers, params=params, json=json, proxy=request_proxy) as resp:
                return resp, await resp.text()

    # ---------- Пинги ----------
    async def _ping_google(self, name: str) -> Tuple[bool, float, str]:
        if not GOOGLE_API_KEY:
            return False, float('inf'), "no key"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{name}:generateContent"
        try:
            start = time.time()
            resp, body = await self._post_with_proxy(
                url,
                params={"key": GOOGLE_API_KEY},
                json={"contents": [{"parts": [{"text": "1"}]}], "generationConfig": {"maxOutputTokens": 1}},
            )
            if resp.status == 200:
                return True, time.time() - start, "OK"
            err = f"{resp.status}: {body[:200]}"
            if resp.status == 404:
                err = f"404 model not found ({name})"
            elif resp.status == 401:
                err = "401 invalid GOOGLE_API_KEY"
            elif resp.status == 429:
                err = "429 rate limited"
            return False, float('inf'), err
        except asyncio.TimeoutError:
            return False, float('inf'), "timeout 15s"
        except Exception as e:
            return False, float('inf'), f"{type(e).__name__}: {e}"

    async def _ping_groq(self, name: str) -> Tuple[bool, float, str]:
        if not GROQ_API_KEY:
            return False, float('inf'), "no key"
        url = "https://api.groq.com/openai/v1/chat/completions"
        try:
            start = time.time()
            resp, body = await self._post_with_proxy(
                url,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={"model": name, "messages": [{"role": "user", "content": "1"}], "max_tokens": 1},
            )
            if resp.status == 200:
                return True, time.time() - start, "OK"
            err = f"{resp.status}: {body[:200]}"
            if resp.status == 404:
                err = f"404 model not found ({name})"
            elif resp.status == 401:
                err = "401 invalid GROQ_API_KEY"
            elif resp.status == 429:
                err = "429 rate limited"
            return False, float('inf'), err
        except asyncio.TimeoutError:
            return False, float('inf'), "timeout 15s"
        except Exception as e:
            return False, float('inf'), f"{type(e).__name__}: {e}"

    async def _ping_deepseek(self, name: str) -> Tuple[bool, float, str]:
        if not DEEPSEEK_API_KEY:
            return False, float('inf'), "no key"
        url = "https://api.deepseek.com/chat/completions"
        try:
            start = time.time()
            resp, body = await self._post_with_proxy(
                url,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                json={"model": name, "messages": [{"role": "user", "content": "1"}], "max_tokens": 1},
            )
            if resp.status == 200:
                return True, time.time() - start, "OK"
            err = f"{resp.status}: {body[:200]}"
            if resp.status == 404:
                err = f"404 model not found ({name})"
            elif resp.status == 401:
                err = "401 invalid DEEPSEEK_API_KEY"
            return False, float('inf'), err
        except asyncio.TimeoutError:
            return False, float('inf'), "timeout 15s"
        except Exception as e:
            return False, float('inf'), f"{type(e).__name__}: {e}"

    async def _ping_qwen(self, name: str) -> Tuple[bool, float, str]:
        if not QWEN_API_KEY:
            return False, float('inf'), "no key"
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        try:
            start = time.time()
            resp, body = await self._post_with_proxy(
                url,
                headers={"Authorization": f"Bearer {QWEN_API_KEY}"},
                json={"model": name, "messages": [{"role": "user", "content": "1"}], "max_tokens": 1},
            )
            if resp.status == 200:
                return True, time.time() - start, "OK"
            err = f"{resp.status}: {body[:200]}"
            return False, float('inf'), err
        except asyncio.TimeoutError:
            return False, float('inf'), "timeout 15s"
        except Exception as e:
            return False, float('inf'), f"{type(e).__name__}: {e}"

    async def _ping_openrouter(self, name: str) -> Tuple[bool, float, str]:
        if not OPENROUTER_API_KEY:
            return False, float('inf'), "no key"
        url = "https://openrouter.ai/api/v1/chat/completions"
        try:
            start = time.time()
            resp, body = await self._post_with_proxy(
                url,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://github.com/mortysmorryson-arch/Armwrestling-Bot",
                    "X-Title": "Armwrestling Bot",
                },
                json={"model": name, "messages": [{"role": "user", "content": "1"}], "max_tokens": 1},
            )
            if resp.status == 200:
                return True, time.time() - start, "OK"
            err = f"{resp.status}: {body[:200]}"
            if resp.status == 429:
                err = "429 rate limited (20 rpm / 50 per day)"
            return False, float('inf'), err
        except asyncio.TimeoutError:
            return False, float('inf'), "timeout 15s"
        except Exception as e:
            return False, float('inf'), f"{type(e).__name__}: {e}"

    async def _ping_model(self, model: ModelStatus) -> Tuple[bool, float, str]:
        if model.provider == "google":
            return await self._ping_google(model.name)
        elif model.provider == "groq":
            return await self._ping_groq(model.name)
        elif model.provider == "deepseek":
            return await self._ping_deepseek(model.name)
        elif model.provider == "qwen":
            return await self._ping_qwen(model.name)
        elif model.provider == "openrouter":
            return await self._ping_openrouter(model.name)
        else:
            return False, float('inf'), f"unknown provider {model.provider}"

    async def _check_all(self):
        async with self._lock:
            for model in self.models:
                alive, latency, err = await self._ping_model(model)
                model.available = alive
                model.latency = latency
                model.last_check = time.time()
                model.last_error = err
            alive_count = sum(1 for m in self.models if m.available)
            details = " | ".join(
                f"{m.name}={'UP' if m.available else 'DOWN'}"
                + (f"({m.latency:.2f}s)" if m.available else f"({m.last_error})")
                for m in self.models
            )
            logger.info(f"Healthcheck: {alive_count}/{len(self.models)} живых | {details}")
            if alive_count == 0:
                proxy = _get_proxy()
                logger.warning(f"⚠️ Все модели DOWN — проверь .env и PROXY_URL={proxy}! Для моделей нужен тот же прокси что и для Telegram.")

    async def start_healthcheck(self):
        if self._task is None:
            await self._check_all()
            self._task = asyncio.create_task(self._healthcheck_loop())

    async def _healthcheck_loop(self):
        while True:
            try:
                await asyncio.sleep(HEALTHCHECK_INTERVAL)
                await self._check_all()
            except Exception as e:
                logger.error(f"Ошибка в healthcheck: {type(e).__name__}: {e}")

    def get_available(self, top_n: int = 3) -> List[ModelStatus]:
        available = [m for m in self.models if m.available]
        available.sort(key=lambda m: (-m.power, m.latency))
        return available[:top_n]

    def get_model(self, name: str) -> Optional[ModelStatus]:
        for m in self.models:
            if m.name == name:
                return m
        return None

_registry: Optional[ModelRegistry] = None

def init_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry

def get_registry() -> Optional[ModelRegistry]:
    return _registry
