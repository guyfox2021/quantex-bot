import aiohttp
import asyncio
import time


BINANCE_BASE = "https://api.binance.com/api/v3/ticker/price"
TIMEOUT = aiohttp.ClientTimeout(total=5)
PRICE_CACHE_TTL_SECONDS = 10
_price_cache: dict[str, tuple[float, float]] = {}


async def get_price(symbol: str = "BTCUSDT") -> float:
    symbol = symbol.upper()
    now = time.monotonic()
    cached = _price_cache.get(symbol)
    if cached and now - cached[0] < PRICE_CACHE_TTL_SECONDS:
        return cached[1]

    url = f"{BINANCE_BASE}?symbol={symbol}"
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(url) as resp:
                if resp.status == 400:
                    raise ValueError(f"Символ {symbol} не знайдено на Binance.")
                if resp.status != 200:
                    raise ValueError(f"Binance повернув статус {resp.status}")
                data = await resp.json()
                price = float(data["price"])
                _price_cache[symbol] = (now, price)
                return price
    except asyncio.TimeoutError:
        raise ConnectionError(f"Timeout при отриманні ціни {symbol} з Binance.")
    except (KeyError, TypeError) as e:
        raise ValueError(f"Невірна відповідь від Binance: {e}")
    except aiohttp.ClientError as e:
        raise ConnectionError(f"Мережева помилка: {e}")


async def validate_symbol(symbol: str) -> bool:
    try:
        await get_price(symbol)
        return True
    except Exception:
        return False
