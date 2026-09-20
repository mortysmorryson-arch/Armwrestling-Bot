#!/usr/bin/env python3
"""
Диагностика сети для бота (v2).

Что делает:
  1) Проверяет прямой доступ к api.telegram.org;
  2) Проверяет каждый прокси из .env (PROXY_URL может быть списком через запятую);
  3) СКАНИРУЕТ типичные порты локальных прокси-клиентов (Happ: 10808/10809,
     NekoBox: 2080, v2rayN: 1080/1081, Clash: 7890/7891...) и находит живой;
  4) Печатает готовую строку для .env.

Запуск:  python scripts/check_network.py
"""
import asyncio
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))
os.chdir(PROJECT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()
PROXY_URL = os.getenv("PROXY_URL", "").strip()

TEST_URL = "https://api.telegram.org/"
TIMEOUT = 12

# Порты локальных прокси известных клиентов (Happ = 10808 socks5 / 10809 http)
COMMON_PORTS = [10808, 10809, 2080, 1080, 1081, 10806, 7890, 7891, 10801, 9090]


async def check_direct() -> bool:
    import aiohttp

    try:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(TEST_URL) as resp:
                print(f"  ✅ напрямую: HTTP {resp.status} — связь есть")
                return True
    except Exception as e:
        print(f"  ❌ напрямую: {type(e).__name__} — прямой доступ блокируется")
        return False


async def check_proxy_url(url: str) -> bool:
    """Проверяет один прокси (socks5/socks4/http) доступом к api.telegram.org."""
    import aiohttp
    from aiohttp_socks import ProxyConnector

    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    try:
        if url.startswith(("socks5://", "socks4://", "socks5h://")):
            connector = ProxyConnector.from_url(url)
            session_cm = aiohttp.ClientSession(connector=connector, timeout=timeout)
        elif url.startswith("http://"):
            session_cm = aiohttp.ClientSession(timeout=timeout)
        else:
            print(f"  ❌ {url}: не понимаю схему (нужен socks5:// или http://)")
            return False
        try:
            async with session_cm as session:
                kwargs = {"proxy": url} if url.startswith("http://") else {}
                async with session.get(TEST_URL, **kwargs) as resp:
                    print(f"  ✅ {url}: HTTP {resp.status} — работает")
                    return True
        finally:
            if not session_cm.closed:
                await session_cm.close()
    except Exception as e:
        detail = str(e).split("[")[0].strip()
        print(f"  ❌ {url}: {type(e).__name__} {detail}")
        return False


async def port_is_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.5)
        w.close()
        return True
    except Exception:
        return False


async def scan_local_proxies() -> list:
    """Ищет живые локальные прокси на типичных портах и проверяет каждый."""
    print("\n3. Сканирую типичные порты локальных прокси на 127.0.0.1...")
    print("   (Happ: 10808/10809 · NekoBox: 2080 · v2rayN: 1080/1081 · Clash: 7890/7891)")
    found: list = []
    open_ports = [p for p in COMMON_PORTS if await port_is_open(p)]
    if not open_ports:
        print("  ❌ Ни один типичный порт не открыт. Похоже, VPN-клиент не запущен,")
        print("     либо у него нестандартный порт (посмотрите в настройках клиента).")
        return found
    print(f"  🔌 Открытые порты: {open_ports} — проверяю как прокси...")
    for port in open_ports:
        for url in (f"socks5://127.0.0.1:{port}", f"http://127.0.0.1:{port}"):
            if await check_proxy_url(url):
                found.append(url)
                break  # этот порт уже работает — http-вариант не пробуем
    return found


def parse_env_list() -> list:
    result = []
    for part in PROXY_URL.replace(";", ",").split(","):
        part = part.strip()
        if part:
            result.append(part)
    return result


async def main() -> int:
    print(f"Проверяем доступность {TEST_URL}\n")

    print("1. Прямое подключение (без прокси и VPN):")
    direct_ok = await check_direct()

    env_proxies = parse_env_list()
    env_results: list = []
    if env_proxies:
        print(f"\n2. Прокси из .env ({len(env_proxies)} шт.):")
        for url in env_proxies:
            env_results.append((url, await check_proxy_url(url)))
    else:
        print("\n2. Прокси: PROXY_URL в .env не задан — проверка пропущена")

    scanned = await scan_local_proxies()

    # ===================== РЕКОМЕНДАЦИИ =====================
    working = [u for u, ok in env_results if ok] + [u for u in scanned if u not in
               [x for x, ok in env_results if ok]]

    print("\n" + "=" * 60)
    if direct_ok:
        print("✅ Прямое подключение РАБОТАЕТ. Варианты:")
        print("   • оставьте PROXY_URL пустым в .env и просто запустите бота;")
        if working:
            print(f"   • или оставьте запасным прокси: PROXY_URL={', '.join(working[:3])}, direct")
    elif working:
        print("✅ Прямой доступ заблокирован, но рабочие прокси найдены!")
        env_line = ", ".join(working[:3])
        if len(working) < 3:
            env_line += ", direct"
        print("\n   Вставьте эту строку в .env (вместо старой PROXY_URL):")
        print(f"   PROXY_URL={env_line}")
        print("\n   → Бот будет перебирать их сам и переживёт перезапуск Happ.")
        print("   Запуск: python bot.py  (системный VPN включать не нужно)")
    else:
        print("❌ Рабочего пути к Telegram нет. Чек-лист:")
        print("   1) Запустите Happ и ПОДКЛЮЧИТЕСЬ к серверу (кнопка подключения);")
        print("   2) В Happ: Настройки → Расширенные настройки — проверьте локальные")
        print("      порты прокси (по умолчанию SOCKS5 10808, HTTP 10809);")
        print("   3) Запустите этот скрипт ещё раз — я найду порт автоматически;")
        print("   4) Если портов нет вообще — в Happ нет локального прокси-режима,")
        print("      обновите Happ или используйте другой клиент (v2rayN, NekoBox).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
