# discover.py — правильно читает .env
import asyncio, os, re
from dotenv import load_dotenv
load_dotenv()  # важно! без этого ключи пустые

from aiohttp_socks import ProxyConnector
import aiohttp

PROXY_URL = os.getenv("PROXY_URL", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

def parse_proxy(raw):
    for part in re.split(r"[,;]+", raw or ""):
        part=part.strip()
        if "://" in part:
            return part
    return None

proxy = parse_proxy(PROXY_URL)
print(f"PROXY_URL из .env: {PROXY_URL or 'ПУСТО'}")
print(f"Прокси для теста: {proxy}")
print(f"GROQ key: {'SET' if GROQ_API_KEY else 'EMPTY'} len={len(GROQ_API_KEY) if GROQ_API_KEY else 0}")
print(f"GOOGLE key: {'SET' if GOOGLE_API_KEY else 'EMPTY'} len={len(GOOGLE_API_KEY) if GOOGLE_API_KEY else 0}")
print(f"QWEN key: {'SET' if QWEN_API_KEY else 'EMPTY'}")
print(f"DEEPSEEK key: {'SET' if DEEPSEEK_API_KEY else 'EMPTY'}")
print(f"OPENROUTER key: {'SET' if OPENROUTER_API_KEY else 'EMPTY'}")

async def discover_groq():
    if not GROQ_API_KEY:
        print("\n[GROQ] нет ключа — пропускаю")
        return
    kwargs = {}
    req_proxy = None
    if proxy and proxy.startswith("socks"):
        kwargs["connector"] = ProxyConnector.from_url(proxy)
    elif proxy and proxy.startswith("http"):
        req_proxy = proxy
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout, **kwargs) as s:
        async with s.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {GROQ_API_KEY}"}, proxy=req_proxy) as r:
            txt = await r.text()
            print(f"\n[Groq] GET /models status {r.status}")
            print(txt[:3000])

async def discover_google():
    if not GOOGLE_API_KEY:
        print("\n[Google] нет ключа — пропускаю")
        return
    kwargs={}
    req_proxy=None
    if proxy and proxy.startswith("socks"):
        kwargs["connector"] = ProxyConnector.from_url(proxy)
    elif proxy and proxy.startswith("http"):
        req_proxy=proxy
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout, **kwargs) as s:
        async with s.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": GOOGLE_API_KEY}, proxy=req_proxy) as r:
            txt = await r.text()
            print(f"\n[Google] GET /v1beta/models status {r.status}")
            print(txt[:4000])

async def main():
    await discover_groq()
    await discover_google()

asyncio.run(main())
