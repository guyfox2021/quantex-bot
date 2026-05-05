from datetime import datetime
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("Europe/Kiev")


def fmt_usdt(value: float) -> str:
    return f"{value:,.2f}"


def fmt_btc(value: float) -> str:
    return f"{value:.8f}"


def fmt_percent(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def fmt_price(value: float) -> str:
    return f"{value:,.2f}"


def fmt_local_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return value[:16].replace("T", " ")
