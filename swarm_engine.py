#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Движок роя — FIXED v5: использует HTTP прокси для requests (не требует PySocks)
+ socks остается для aiohttp в model_registry
"""
import time, logging, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
import requests
try:
    from config import GOOGLE_API_KEY, GROQ_API_KEY, DEEPSEEK_API_KEY, QWEN_API_KEY, OPENROUTER_API_KEY, PROXY_URL
except ImportError:
    GOOGLE_API_KEY = GROQ_API_KEY = DEEPSEEK_API_KEY = QWEN_API_KEY = OPENROUTER_API_KEY = PROXY_URL = ""

logger = logging.getLogger(__name__)
class FatalApiError(Exception): pass

def _parse_proxy_list(raw: str):
    result=[]
    for part in re.split(r"[,;]+", raw or ""):
        part=part.strip()
        if not part: continue
        if part.lower() in {"direct","none","no","-"}:
            result.append(None)
        elif "://" in part:
            result.append(part)
    return result

def _get_proxy_dict():
    """Для requests: предпочитаем HTTP прокси (работает без PySocks), fallback на SOCKS если есть PySocks"""
    proxies = _parse_proxy_list(PROXY_URL)
    # 1. Ищем http
    for p in proxies:
        if p and p.startswith("http"):
            return {"http": p, "https": p}
    # 2. Если только socks — пробуем, но предупредим
    for p in proxies:
        if p and p.startswith("socks"):
            # requests[socks] требует PySocks, если его нет — будет Missing dependencies
            # Поэтому лучше использовать http://127.0.0.1:10809, он у Happ всегда есть
            return {"http": p, "https": p}
    return None

def _call_google(model: str, prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    r = requests.post(url, params={"key": GOOGLE_API_KEY}, json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 4096}}, timeout=60, proxies=_get_proxy_dict())
    if r.status_code == 429: raise Exception("429 Rate Limit")
    if r.status_code == 413: raise FatalApiError("HTTP 413: промпт слишком большой")
    if not r.ok:
        if 400 <= r.status_code < 500: raise FatalApiError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]

def _call_groq(model: str, prompt: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    r = requests.post(url, headers={"Authorization": f"Bearer {GROQ_API_KEY}"}, json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 4000, "temperature": 0.7}, timeout=60, proxies=_get_proxy_dict())
    if r.status_code == 429: raise Exception("429 Rate Limit")
    if r.status_code == 413: raise FatalApiError("HTTP 413: промпт слишком большой")
    if not r.ok:
        if 400 <= r.status_code < 500: raise FatalApiError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]

def _call_deepseek(model: str, prompt: str) -> str:
    url = "https://api.deepseek.com/chat/completions"
    r = requests.post(url, headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}, json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 4000, "temperature": 0.7}, timeout=60, proxies=_get_proxy_dict())
    if r.status_code == 429: raise Exception("429 Rate Limit")
    if r.status_code == 413: raise FatalApiError("HTTP 413: промпт слишком большой")
    if not r.ok:
        if 400 <= r.status_code < 500: raise FatalApiError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]

def _call_qwen(model: str, prompt: str) -> str:
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    r = requests.post(url, headers={"Authorization": f"Bearer {QWEN_API_KEY}"}, json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 4000, "temperature": 0.7}, timeout=60, proxies=_get_proxy_dict())
    if r.status_code == 429: raise Exception("429 Rate Limit")
    if r.status_code == 413: raise FatalApiError("HTTP 413: промпт слишком большой")
    if not r.ok:
        if 400 <= r.status_code < 500: raise FatalApiError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]

def _call_openrouter(model: str, prompt: str) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    r = requests.post(url, headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "HTTP-Referer": "https://github.com/mortysmorryson-arch/Armwrestling-Bot", "X-Title": "Armwrestling Bot"}, json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 4000, "temperature": 0.7}, timeout=60, proxies=_get_proxy_dict())
    if r.status_code == 429: raise Exception("429 Rate Limit (OpenRouter 20 rpm)")
    if r.status_code == 413: raise FatalApiError("HTTP 413: промпт слишком большой")
    if not r.ok:
        if 400 <= r.status_code < 500: raise FatalApiError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise Exception(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]

def _ask_one(model_status, prompt: str) -> str:
    p, n = model_status.provider, model_status.name
    if p == "google": return _call_google(n, prompt)
    if p == "groq": return _call_groq(n, prompt)
    if p == "deepseek": return _call_deepseek(n, prompt)
    if p == "qwen": return _call_qwen(n, prompt)
    if p == "openrouter": return _call_openrouter(n, prompt)
    raise Exception(f"Провайдер '{p}' не поддерживается")

def ask_with_retry(model_status, prompt: str) -> Dict[str, Any]:
    start=time.time()
    try:
        text=_ask_one(model_status, prompt)
        return {"model": model_status.name, "provider": model_status.provider, "text": text, "time": time.time()-start}
    except FatalApiError as e:
        logger.error(f"Фатальная {model_status.name}: {e}")
        return {"model": model_status.name, "provider": model_status.provider, "text": f"❌ {e}", "time": time.time()-start}
    except Exception as e:
        logger.warning(f"Ошибка {model_status.name}: {e}. Повтор через 2с.")
    time.sleep(2)
    try:
        text=_ask_one(model_status, prompt)
        return {"model": model_status.name, "provider": model_status.provider, "text": text, "time": time.time()-start}
    except Exception as e:
        logger.error(f"Повторная {model_status.name}: {e}")
        return {"model": model_status.name, "provider": model_status.provider, "text": f"❌ {e}", "time": time.time()-start}

class Swarm:
    def __init__(self, registry, overall_timeout: int = 90):
        self.registry=registry
        self.overall_timeout=overall_timeout
    def run(self, prompt: str, run_judge: bool = True):
        if self.registry is None: raise Exception("Реестр не инициализирован")
        available=self.registry.get_available(top_n=3)
        if len(available)==0: raise Exception("Все модели недоступны")
        if len(available)<2: raise Exception(f"Недостаточно моделей: {len(available)}")
        logger.info(f"Рой запущен: {[m.name for m in available]}")
        answers: List[Dict[str, Any]]=[]
        with ThreadPoolExecutor(max_workers=len(available)) as ex:
            futures=[ex.submit(ask_with_retry, m, prompt) for m in available]
            for fut in as_completed(futures):
                try: answers.append(fut.result(timeout=self.overall_timeout))
                except Exception as e: logger.error(f"Критическая ошибка воркера: {e}")
        if not run_judge: return answers, None
        good=[a for a in answers if not a["text"].startswith("❌")]
        if len(good)<2: return answers, {"model":"error","provider":"error","text":f"⚠️ Недостаточно успешных: {len(good)} из {len(available)}","time":0}
        combined="\n\n".join(f"--- {a['model']} ({a['provider']}):\n{a['text']}" for a in good)
        judge_prompt=(f"Задача: {prompt}\n\nОтветы экспертов:\n{combined}\n\nТы — председатель. Составь ЕДИНЫЙ ГОТОВЫЙ ПЛАН ТРЕНИРОВОК с упражнениями, весом, подходами, повторениями, прогрессией.")
        judge_model=available[0]
        if len(combined)>4000:
            big=[m for m in available if m.provider=="google"]
            if big: judge_model=big[0]; logger.info(f"Судья (большой контекст): {judge_model.name}")
        try: verdict=ask_with_retry(judge_model, judge_prompt); return answers, verdict
        except Exception as e: return answers, {"model":"error","provider":"error","text":f"❌ Судья упал: {e}","time":0}
