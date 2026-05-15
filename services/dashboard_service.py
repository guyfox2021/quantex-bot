from datetime import datetime, timezone

from services import (
    binance_service,
    portfolio_service,
    settings_service,
    signal_service,
    buyback_service,
    snapshot_service,
)
from services.transaction_service import get_last_transactions


def _base_coin(symbol: str) -> str:
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
        if symbol.upper().endswith(quote):
            return symbol.upper()[: -len(quote)]
    return symbol.upper()


def _status_label(status: str) -> str:
    return {
        "NEW": "Новий",
        "SENT": "Очікує дії",
        "CONFIRMED": "Виконано",
        "IGNORED": "Пропущено",
        "EXPIRED": "Застарів",
        "REJECTED": "Відхилено",
    }.get(status or "", status or "Невідомо")


def _signal_label(signal_type: str, trigger_type: str | None = None) -> str:
    if trigger_type:
        return {
            "BUYBACK": "Викуп після продажу",
            "BUY_DIP": "Докупка на просадці",
            "BUY_DROP": "Докупка на просадці",
            "SELL_PROFIT": "Фіксація прибутку",
        }.get(trigger_type, trigger_type)
    return {
        "BUY": "Купівля",
        "SELL": "Продаж",
        "HOLD": "Очікування",
    }.get(signal_type or "", signal_type or "Сигнал")


def _tx_label(tx_type: str) -> str:
    return {
        "BUY": "Купівля",
        "SELL": "Продаж",
        "MANUAL_BUY": "Ручна купівля",
        "MANUAL_SELL": "Ручний продаж",
        "MONTHLY_DEPOSIT": "Щомісячне поповнення",
        "EXTRA_DEPOSIT": "Додаткове поповнення",
        "INITIAL_DEPOSIT": "Стартовий капітал",
        "RESERVE_ADD": "Поповнення резерву",
    }.get(tx_type or "", tx_type or "Угода")


def _iso_to_display(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d.%m %H:%M")
    except ValueError:
        return value


async def build_dashboard_payload() -> dict:
    settings = settings_service.get_settings()
    symbol = settings.get("symbol", "BTCUSDT")
    coin = _base_coin(symbol)
    price = await binance_service.get_price(symbol)
    metrics = portfolio_service.calculate_portfolio_metrics(price)
    snapshot_service.save_snapshot(metrics, settings, min_interval_minutes=60)

    target = float(settings.get("target_value", 0) or 0)
    progress = metrics.get("portfolio_value", 0) / target * 100 if target > 0 else 0
    open_cycles = buyback_service.get_open_cycles(settings.get("active_strategy", "accumulation_v2"))
    signals = signal_service.get_last_signals(12)
    transactions = get_last_transactions(12)
    snapshots = snapshot_service.get_snapshots(160)

    latest_signal = signals[0] if signals else None
    last_buy_time = signal_service.get_last_confirmed_buy_time()
    buy_cooldown_active = bool(
        last_buy_time and (datetime.now(timezone.utc) - last_buy_time).total_seconds() < 6 * 3600
    )

    return {
        "meta": {
            "symbol": symbol,
            "coin": coin,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        "summary": {
            "portfolio_value": metrics.get("portfolio_value", 0),
            "total_deposited": metrics.get("total_deposited", 0),
            "target_value": target,
            "progress_percent": progress,
            "total_pnl": metrics.get("total_pnl", 0),
            "total_pnl_percent": metrics.get("total_pnl_percent", 0),
            "realized_pnl": metrics.get("realized_pnl", 0),
            "unrealized_pnl": metrics.get("unrealized_pnl", 0),
            "btc_amount": metrics.get("btc_amount", 0),
            "btc_value": metrics.get("btc_value", 0),
            "usdt_reserve": metrics.get("usdt_reserve", 0),
            "current_price": metrics.get("current_price", 0),
            "avg_price": metrics.get("avg_price", 0),
        },
        "strategy": {
            "name": settings.get("active_strategy", "accumulation"),
            "signals_enabled": bool(settings.get("signals_enabled", 1)),
            "buy_cooldown_active": buy_cooldown_active,
            "buyback_open_count": len(open_cycles),
            "buy_dip_blocked": bool(open_cycles),
        },
        "latest_signal": _format_signal(latest_signal) if latest_signal else None,
        "signals": [_format_signal(sig) for sig in signals],
        "transactions": [_format_transaction(tx, coin) for tx in transactions],
        "buyback_cycles": [_format_cycle(cycle) for cycle in open_cycles],
        "charts": _format_charts(snapshots, metrics, settings),
    }


def _format_signal(sig: dict) -> dict:
    return {
        "id": sig.get("id"),
        "title": _signal_label(sig.get("signal_type", ""), sig.get("trigger_type")),
        "status": _status_label(sig.get("status", "")),
        "type": sig.get("signal_type", ""),
        "trigger": sig.get("trigger_type", ""),
        "level": sig.get("level_percent"),
        "signal_price": sig.get("price", 0),
        "amount_usdt": sig.get("amount_usdt", 0),
        "amount_btc_percent": sig.get("amount_btc_percent", 0),
        "recommendation": sig.get("recommended_action", ""),
        "reason": sig.get("reason", ""),
        "created_at": _iso_to_display(sig.get("created_at")),
    }


def _format_transaction(tx: dict, coin: str) -> dict:
    return {
        "id": tx.get("id"),
        "title": _tx_label(tx.get("type", "")),
        "price": tx.get("price", 0),
        "usdt_amount": tx.get("usdt_amount", 0),
        "coin_amount": tx.get("btc_amount", 0),
        "coin": coin,
        "fee": tx.get("fee", 0),
        "fee_asset": tx.get("fee_asset", "USDT"),
        "created_at": _iso_to_display(tx.get("created_at")),
    }


def _format_cycle(cycle: dict) -> dict:
    return {
        "id": cycle.get("id"),
        "sell_price": cycle.get("sell_price", 0),
        "remaining_btc": cycle.get("remaining_btc", 0),
        "level_2_done": bool(cycle.get("level_2_done", 0)),
        "level_4_done": bool(cycle.get("level_4_done", 0)),
        "status": "Відкритий" if cycle.get("status") == "OPEN" else "Закритий",
        "created_at": _iso_to_display(cycle.get("created_at")),
    }


def _format_charts(snapshots: list[dict], metrics: dict, settings: dict) -> dict:
    if not snapshots:
        snapshots = [{
            "date": "Зараз",
            "btc_price": metrics.get("current_price", 0),
            "usdt_reserve": metrics.get("usdt_reserve", 0),
            "btc_value": metrics.get("btc_value", 0),
            "portfolio_value": metrics.get("portfolio_value", 0),
            "total_deposited": metrics.get("total_deposited", 0),
            "avg_price": metrics.get("avg_price", 0),
            "realized_pnl": metrics.get("realized_pnl", 0),
            "unrealized_pnl": metrics.get("unrealized_pnl", 0),
            "total_pnl": metrics.get("total_pnl", 0),
        }]

    labels = [row.get("date") or row.get("created_at", "") for row in snapshots]
    target = settings.get("target_value", 0)
    return {
        "labels": labels,
        "portfolio": {
            "portfolio_value": [row.get("portfolio_value", 0) for row in snapshots],
            "total_deposited": [row.get("total_deposited", 0) for row in snapshots],
            "target_value": [target for _ in snapshots],
        },
        "pnl": {
            "total_pnl": [row.get("total_pnl", 0) for row in snapshots],
            "realized_pnl": [row.get("realized_pnl", 0) for row in snapshots],
            "unrealized_pnl": [row.get("unrealized_pnl", 0) for row in snapshots],
        },
        "price": {
            "current_price": [row.get("btc_price", 0) for row in snapshots],
            "avg_price": [row.get("avg_price", 0) for row in snapshots],
        },
        "reserve": {
            "usdt_reserve": [row.get("usdt_reserve", 0) for row in snapshots],
        },
    }
