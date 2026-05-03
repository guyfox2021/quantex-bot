import aiohttp
import asyncio


BINANCE_BASE = "https://api.binance.com/api/v3/ticker/price"
TIMEOUT = aiohttp.ClientTimeout(total=10)


async def get_price(symbol: str = "BTCUSDT") -> float:
    url = f"{BINANCE_BASE}?symbol={symbol.upper()}"
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(url) as resp:
                if resp.status == 400:
                    raise ValueError(f"Символ {symbol} не знайдено на Binance.")
                if resp.status != 200:
                    raise ValueError(f"Binance повернув статус {resp.status}")
                data = await resp.json()
                return float(data["price"])
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
