def safe_percent_change(current: float, base: float) -> float:
    if base == 0:
        return 0.0
    return (current - base) / base * 100


def calculate_drawdown(last_high: float, current_price: float) -> float:
    if last_high == 0:
        return 0.0
    return (last_high - current_price) / last_high * 100


def calculate_profit_percent(current_price: float, avg_price: float) -> float:
    if avg_price == 0:
        return 0.0
    return (current_price - avg_price) / avg_price * 100


def calculate_btc_amount(usdt_amount: float, price: float) -> float:
    if price == 0:
        return 0.0
    return usdt_amount / price
