from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Баланс"), KeyboardButton(text="📈 PnL")],
            [KeyboardButton(text="🧠 Стратегія"), KeyboardButton(text="💰 Угоди")],
            [KeyboardButton(text="🔔 Сигнали"), KeyboardButton(text="📜 Історія")],
            [KeyboardButton(text="⚙️ Налаштування")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def buy_confirm_kb(context: str = "buy") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Купив за ринком", callback_data=f"{context}:market"),
            InlineKeyboardButton(text="✏️ Ввести свою ціну", callback_data=f"{context}:custom"),
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"{context}:cancel")],
    ])


def sell_confirm_kb(context: str = "sell") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Продав за ринком", callback_data=f"{context}:market"),
            InlineKeyboardButton(text="✏️ Ввести свою ціну", callback_data=f"{context}:custom"),
        ],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data=f"{context}:cancel")],
    ])


def signal_confirm_kb(signal_id: int, signal_type: str) -> InlineKeyboardMarkup:
    prefix = f"sigconfirm:{signal_id}:{signal_type}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Виконав за ринком", callback_data=f"{prefix}:market"),
            InlineKeyboardButton(text="✏️ Ввести свою ціну", callback_data=f"{prefix}:custom"),
        ],
        [InlineKeyboardButton(text="❌ Пропустити", callback_data=f"{prefix}:skip")],
    ])


def monthly_deposit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Купив за ринком", callback_data="monthly:market"),
            InlineKeyboardButton(text="✏️ Ввести свою ціну", callback_data="monthly:custom"),
        ],
        [InlineKeyboardButton(text="💰 Додати тільки в резерв", callback_data="monthly:reserve_only")],
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="monthly:cancel")],
    ])


def trades_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Купити вручну", callback_data="trade:manual_buy")],
        [InlineKeyboardButton(text="➖ Продати вручну", callback_data="trade:manual_sell")],
        [InlineKeyboardButton(text="💵 Щомісячне поповнення", callback_data="trade:monthly")],
        [InlineKeyboardButton(text="💵 Додаткове поповнення", callback_data="trade:extra")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="trade:back")],
    ])


def signals_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Перевірити зараз", callback_data="signals:check")],
        [InlineKeyboardButton(text="📜 Останні сигнали", callback_data="signals:history")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="signals:back")],
    ])


def refresh_back_kb(refresh_cb: str, back_cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Оновити", callback_data=refresh_cb),
            InlineKeyboardButton(text="🔙 Назад", callback_data=back_cb),
        ]
    ])


def strategy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟣 Деталі стратегії", callback_data="strategy:info")],
        [InlineKeyboardButton(text="🔄 Перевірити сигнал", callback_data="strategy:check_signal")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="strategy:back")],
    ])


def strategy_select_kb(strategies, active_strategy: str) -> InlineKeyboardMarkup:
    rows = []
    for strategy in strategies:
        prefix = "✅ " if strategy.name == active_strategy else ""
        rows.append([InlineKeyboardButton(text=f"{prefix}{strategy.title}", callback_data=f"strategy:set:{strategy.name}")])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Ціль портфеля", callback_data="settings:target")],
        [InlineKeyboardButton(text="💵 Щомісячне поповнення", callback_data="settings:monthly")],
        [InlineKeyboardButton(text="⏱ Частота перевірки", callback_data="settings:interval")],
        [InlineKeyboardButton(text="🔔 Увімкнути/вимкнути сигнали", callback_data="settings:toggle_signals")],
        [InlineKeyboardButton(text="🧠 Активна стратегія", callback_data="settings:strategy")],
        [InlineKeyboardButton(text="🪙 Монета (символ)", callback_data="settings:symbol")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="settings:back")],
    ])


def history_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Останні угоди", callback_data="history:trades")],
        [InlineKeyboardButton(text="🚨 Останні сигнали", callback_data="history:signals")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="history:back")],
    ])


def back_kb(cb: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=cb)]
    ])


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_input")]
    ])


def start_strategy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Розпочати стратегію", callback_data="start:init")]
    ])
