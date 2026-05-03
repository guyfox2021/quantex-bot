def fmt_usdt(value: float) -> str:
    return f"{value:,.2f}"


def fmt_btc(value: float) -> str:
    return f"{value:.8f}"


def fmt_percent(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def fmt_price(value: float) -> str:
    return f"{value:,.2f}"
