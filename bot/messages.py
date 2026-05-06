from utils.formatters import fmt_usdt, fmt_btc, fmt_percent, fmt_price, fmt_local_datetime
from strategies.registry import get_strategy


def _base_coin(symbol: str) -> str:
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
        if symbol.upper().endswith(quote):
            return symbol.upper()[: -len(quote)]
    return symbol.upper()


def _coin_badge(symbol: str) -> str:
    coin = _base_coin(symbol)
    badges = {
        "BTC": "₿ BTC",
        "ETH": "Ξ ETH",
        "SOL": "◎ SOL",
        "BNB": "◈ BNB",
        "XRP": "✕ XRP",
        "TON": "◉ TON",
    }
    return badges.get(coin, f"🪙 {coin}")


def _signal_badge(signal_type: str) -> str:
    return {
        "BUY": "🟢 BUY",
        "SELL": "🔴 SELL",
        "HOLD": "🟡 HOLD",
    }.get(signal_type, signal_type)


def _status_badge(status: str) -> str:
    return {
        "NEW": "🆕 NEW",
        "SENT": "📨 SENT",
        "CONFIRMED": "✅ CONFIRMED",
        "REJECTED": "❌ REJECTED",
        "IGNORED": "🙈 IGNORED",
    }.get(status, status)


def _tx_badge(tx_type: str) -> str:
    badges = {
        "BUY": "🟢 BUY",
        "SELL": "🔴 SELL",
        "MANUAL_BUY": "✍️ BUY",
        "MANUAL_SELL": "✍️ SELL",
        "MONTHLY_DEPOSIT": "📅 DEPOSIT",
        "EXTRA_DEPOSIT": "⚡ DEPOSIT",
        "INITIAL_DEPOSIT": "🚀 START",
        "RESERVE_ADD": "🏦 RESERVE",
    }
    return badges.get(tx_type, tx_type)


def start_message(is_initialized: bool, active_strategy: str, symbol: str = "BTCUSDT") -> str:
    strategy = get_strategy(active_strategy)
    coin = _coin_badge(symbol)
    init_hint = "" if is_initialized else "\n\nДля початку ініціалізуй портфель через /init або розділ ⚙️ Налаштування."
    return (
        "👋 Вітаю! Це QuantEX.\n\n"
        f"Особистий асистент для трекінга криптоінвестицій, контролю портфеля та сигналів за стратегією.\n\n"
        f"🪙 Активна монета: {coin} ({symbol})\n"
        f"🧠 Активна стратегія:\n🟣 {strategy.title}"
        f"{init_hint}"
    )


def balance_message(metrics: dict, settings: dict) -> str:
    symbol = settings.get("symbol", "BTCUSDT")
    coin = _coin_badge(symbol)
    target = settings.get("target_value", 5000)
    portfolio_value = metrics.get("portfolio_value", 0)
    progress = (portfolio_value / target * 100) if target > 0 else 0

    return (
        f"📊 Баланс ({symbol})\n\n"
        f"<b>Актив</b>\n"
        f"{coin}: {fmt_btc(metrics.get('btc_amount', 0))}\n"
        f"🏦 USDT резерв: {fmt_usdt(metrics.get('usdt_reserve', 0))}\n\n"
        f"<b>Ринок</b>\n"
        f"📍 Середня ціна: {fmt_price(metrics.get('avg_price', 0))} USDT\n"
        f"📈 Поточна ціна: {fmt_price(metrics.get('current_price', 0))} USDT\n\n"
        f"<b>Оцінка</b>\n"
        f"🧾 Вартість монети: {fmt_usdt(metrics.get('btc_value', 0))} USDT\n"
        f"💰 Вартість портфеля: {fmt_usdt(portfolio_value)} USDT\n\n"
        f"<b>Ціль</b>\n"
        f"🎯 Ціль портфеля: {fmt_usdt(target)} USDT\n"
        f"🚀 Прогрес: {progress:.2f}%"
    )


def pnl_message(metrics: dict, symbol: str = "BTCUSDT") -> str:
    coin = _coin_badge(symbol)
    return (
        f"📈 PnL ({symbol})\n\n"
        f"<b>База</b>\n"
        f"🪙 Актив: {coin}\n"
        f"💸 Внесено всього: {fmt_usdt(metrics.get('total_deposited', 0))} USDT\n"
        f"💼 Вартість портфеля: {fmt_usdt(metrics.get('portfolio_value', 0))} USDT\n\n"
        f"<b>Підсумок</b>\n"
        f"📊 Загальний PnL: {fmt_usdt(metrics.get('total_pnl', 0))} USDT\n"
        f"📈 PnL: {fmt_percent(metrics.get('total_pnl_percent', 0))}\n\n"
        f"<b>Деталі</b>\n"
        f"✅ Реалізований PnL: {fmt_usdt(metrics.get('realized_pnl', 0))} USDT\n"
        f"⏳ Нереалізований PnL: {fmt_usdt(metrics.get('unrealized_pnl', 0))} USDT"
    )


def strategy_message(active_strategy: str) -> str:
    strategy = get_strategy(active_strategy)
    return (
        "🧠 Стратегія\n\n"
        f"Активна стратегія:\n🟣 {strategy.title}\n\n"
        f"Опис:\n{strategy.description}\n\n"
        f"{strategy.get_parameters_text()}"
    )


def signal_message(signal, symbol: str = "BTCUSDT", price: float = 0.0, portfolio: dict | None = None) -> str:
    coin = _base_coin(symbol)
    price_line = f"\n💰 Поточна ціна {coin}: {fmt_price(price)} USDT" if price > 0 else ""
    sell_amount_line = ""
    if signal.signal_type == "SELL" and portfolio and signal.amount_btc_percent > 0:
        btc_amount = portfolio.get("btc_amount", 0.0)
        btc_to_sell = btc_amount * signal.amount_btc_percent / 100
        usdt_estimate = btc_to_sell * price if price > 0 else 0.0
        sell_amount_line = (
            f"\n\n🧮 Розрахунок продажу:\n"
            f"{signal.amount_btc_percent:.2f}% позиції = {fmt_btc(btc_to_sell)} {coin}"
            f"\n💰 Орієнтовно: {fmt_usdt(usdt_estimate)} USDT"
        )
    if signal.signal_type == "BUY":
        return (
            f"{_signal_badge(signal.signal_type)} | {coin}\n\n"
            f"📌 Причина:\n{signal.reason}\n\n"
            f"⚡ Рекомендована дія:\n{signal.recommended_action}"
            f"{sell_amount_line}"
            f"{price_line}"
        )
    elif signal.signal_type == "SELL":
        return (
            f"{_signal_badge(signal.signal_type)} | {coin}\n\n"
            f"📌 Причина:\n{signal.reason}\n\n"
            f"⚡ Рекомендована дія:\n{signal.recommended_action}"
            f"{sell_amount_line}"
            f"{price_line}"
        )
    else:
        return (
            "🟡 HOLD\n\n"
            "🫱 Умови для покупки або продажу не виконані."
        )


def settings_message(settings: dict) -> str:
    strategy = get_strategy(settings.get("active_strategy", "accumulation"))
    signals_status = "🟢 увімкнено" if settings.get("signals_enabled", 1) else "🔕 вимкнено"
    symbol = settings.get("symbol", "BTCUSDT")
    return (
        "⚙️ Налаштування\n\n"
        f"🪙 Монета: {_coin_badge(symbol)} ({symbol})\n"
        f"🎯 Ціль портфеля: {fmt_usdt(settings.get('target_value', 5000))} USDT\n"
        f"📅 Щомісячне поповнення: {fmt_usdt(settings.get('monthly_deposit', 500))} USDT\n"
        f"⏱ Частота перевірки: {settings.get('check_interval_minutes', 5)} хв\n"
        f"🔔 Сигнали: {signals_status}\n"
        f"🧠 Активна стратегія: {strategy.title}"
    )


def transaction_line(tx: dict) -> str:
    created = fmt_local_datetime(tx.get("created_at", ""))
    tx_type = tx.get("type", "")
    symbol = tx.get("symbol", "BTCUSDT")
    coin = _coin_badge(symbol)
    usdt = fmt_usdt(tx.get("usdt_amount", 0))
    btc = fmt_btc(tx.get("btc_amount", 0))
    price = fmt_price(tx.get("price", 0))
    return (
        f"<b>{created}</b>\n"
        f"{_tx_badge(tx_type)} | {usdt} USDT | {btc} {coin}\n"
        f"Ціна: {price}"
    )


def signal_line(sig: dict) -> str:
    created = fmt_local_datetime(sig.get("created_at", ""))
    strategy_name = sig.get("strategy_name", "")
    price = fmt_price(sig.get("price", 0))
    status = sig.get("status", "")
    reason = sig.get("reason", "")
    strategy = get_strategy(strategy_name)
    return (
        f"🕒 {created}\n"
        f"{_signal_badge(sig.get('signal_type', ''))}\n"
        f"🧠 Стратегія: {strategy.title}\n"
        f"💹 Ціна: {price} USDT\n"
        f"📌 Статус: {_status_badge(status)}\n\n"
        f"Причина:\n{reason}"
    )
