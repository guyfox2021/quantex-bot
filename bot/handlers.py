import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.states import (
    InitPortfolio, ManualBuy, ManualSell,
    MonthlyDeposit, ExtraDeposit, SettingsStates, SignalConfirm,
)
from bot.keyboards import (
    main_menu, buy_confirm_kb, sell_confirm_kb, signal_confirm_kb,
    monthly_deposit_kb, trades_kb, signals_kb, refresh_back_kb,
    strategy_kb, settings_kb, history_kb, back_kb, cancel_kb, start_strategy_kb,
)
from bot.messages import (
    start_message, balance_message, pnl_message, strategy_message,
    signal_message, settings_message, transaction_line, signal_line,
)
from services import owner_service, binance_service, portfolio_service
from services import settings_service, signal_service, sheets_service
from services.transaction_service import get_last_transactions
from strategies.registry import get_strategy

logger = logging.getLogger(__name__)
router = Router()

ACCESS_DENIED = "⛔ Доступ заборонено."


# ─── Universal cancel ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "cancel_input")
async def cancel_input(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Скасовано.")
    await callback.answer()


def _price_error(symbol: str) -> str:
    return f"⚠️ Не вдалося отримати поточну ціну {symbol}. Спробуй пізніше."


# ─── /start ───────────────────────────────────────────────────────────────────

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return

    owner_service.ensure_owner(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
    )
    portfolio_service.create_default_portfolio_if_needed()
    settings_service.create_default_settings_if_needed()

    settings = settings_service.get_settings()
    strategy = get_strategy(settings.get("active_strategy", "accumulation"))
    signal_service.ensure_default_triggers(strategy)

    portfolio = portfolio_service.get_portfolio()
    is_init = portfolio.get("is_initialized", 0)
    symbol = settings.get("symbol", "BTCUSDT")
    from bot.messages import _base_coin
    coin = _base_coin(symbol)

    if not is_init:
        await message.answer(
            f"👋 Вітаю! Це QuantEX.\n\n"
            f"Активна стратегія: 🟣 {strategy.title}\n"
            f"Активна монета: {coin} ({symbol})\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📍 ПЕРШИЙ СИГНАЛ: Встановити початкову позицію\n\n"
            f"Для запуску стратегії потрібна стартова покупка {coin}.\n"
            f"Вона стане точкою відліку — від неї рахуватиметься\n"
            f"просадка для докупівель і прибуток для продажів.",
            reply_markup=start_strategy_kb(),
        )
    else:
        await message.answer(
            start_message(True, settings.get("active_strategy", "accumulation"), symbol),
            reply_markup=main_menu(),
        )


@router.callback_query(F.data == "start:init")
async def start_init_cb(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    await callback.message.edit_text(
        f"Введи стартовий капітал у USDT\n"
        f"(наприклад: 1000):",
        reply_markup=cancel_kb(),
    )
    await state.set_state(InitPortfolio.waiting_capital)
    await callback.answer()


# ─── /init ────────────────────────────────────────────────────────────────────

@router.message(Command("init"))
async def cmd_init(message: Message, state: FSMContext):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    await message.answer(
        f"Введи стартовий капітал у USDT\n(наприклад: 1000):",
        reply_markup=cancel_kb(),
    )
    await state.set_state(InitPortfolio.waiting_capital)


@router.message(InitPortfolio.waiting_capital)
async def init_capital_entered(message: Message, state: FSMContext):
    try:
        capital = float(message.text.replace(",", "."))
        if capital <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну суму у USDT (наприклад: 1000).", reply_markup=cancel_kb())
        return

    buy_amount = capital * 0.70
    reserve_amount = capital * 0.30
    await state.update_data(capital=capital)

    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    await message.answer(
        f"📍 Початковий сигнал стратегії\n\n"
        f"Капітал: {capital:.2f} USDT\n\n"
        f"Розподіл за стратегією:\n"
        f"  📈 Купити {coin}: {buy_amount:.2f} USDT (70%) — точка відліку\n"
        f"  💰 Резерв: {reserve_amount:.2f} USDT (30%) — для докупівель\n\n"
        f"Підтверди покупку:",
        reply_markup=buy_confirm_kb("init"),
    )
    await state.set_state(InitPortfolio.confirming)


@router.callback_query(InitPortfolio.confirming, F.data.startswith("init:"))
async def init_confirm_cb(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()

    if action == "cancel":
        await callback.message.edit_text("❌ Ініціалізацію скасовано.")
        await state.clear()
        return

    if action == "custom":
        await callback.message.edit_text("Введи ціну покупки у USDT:", reply_markup=cancel_kb())
        await state.set_state(InitPortfolio.waiting_custom_price)
        return

    if action == "market":
        symbol = settings_service.get_symbol()
        try:
            price = await binance_service.get_price(symbol)
        except Exception:
            await callback.message.edit_text(_price_error(symbol))
            await state.clear()
            return
        await _do_init(callback.message, state, data["capital"], price)


@router.message(InitPortfolio.waiting_custom_price)
async def init_custom_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну ціну у USDT.")
        return
    data = await state.get_data()
    await _do_init(message, state, data["capital"], price)


async def _do_init(msg, state: FSMContext, capital: float, price: float):
    portfolio_service.initialize_portfolio(capital, price)
    settings = settings_service.get_settings()
    strategy = get_strategy(settings.get("active_strategy", "accumulation"))
    signal_service.ensure_default_triggers(strategy)

    symbol = settings.get("symbol", "BTCUSDT")
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    buy_amount = capital * 0.70
    reserve_amount = capital * 0.30
    btc_bought = buy_amount / price

    await msg.answer(
        f"✅ Стратегію запущено!\n\n"
        f"Куплено {coin}: {btc_bought:.8f}\n"
        f"Ціна входу: {price:,.2f} USDT\n"
        f"Резерв: {reserve_amount:.2f} USDT\n\n"
        f"Бот надішле сигнал при:\n"
        f"  📉 Просадці -5%, -10%, -15%, -20% від максимуму\n"
        f"  📈 Прибутку +15%, +25%, +40% від ціни входу",
        reply_markup=main_menu(),
    )
    await state.clear()


# ─── /price ───────────────────────────────────────────────────────────────────

@router.message(Command("price"))
async def cmd_price(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    symbol = settings_service.get_symbol()
    try:
        price = await binance_service.get_price(symbol)
        await message.answer(f"💰 Поточна ціна {symbol}:\n{price:,.2f} USDT")
    except Exception:
        await message.answer(_price_error(symbol))


# ─── /signal ──────────────────────────────────────────────────────────────────

@router.message(Command("signal"))
async def cmd_signal(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    await _check_and_send_signal(message, send_hold=True)


async def _check_and_send_signal(message: Message, send_hold: bool = False, bot=None):
    symbol = settings_service.get_symbol()
    try:
        price = await binance_service.get_price(symbol)
    except Exception:
        if message:
            await message.answer(_price_error(symbol))
        return None

    portfolio = portfolio_service.get_portfolio()
    settings = settings_service.get_settings()
    strategy = get_strategy(settings.get("active_strategy", "accumulation"))
    triggers = signal_service.get_triggers(strategy.name)

    market_data = {"price": price}
    signal = strategy.check(portfolio, market_data, settings, triggers)

    if signal.signal_type in ("BUY", "SELL"):
        sig_id = signal_service.save_signal(signal, price, status="SENT")
        if signal.trigger_type:
            signal_service.mark_triggered(strategy.name, signal.trigger_type, signal.level_percent)

        text = signal_message(signal, symbol, price)
        kb = signal_confirm_kb(sig_id, signal.signal_type)
        if message:
            await message.answer(text, reply_markup=kb)
        return signal

    if send_hold and message:
        await message.answer(signal_message(signal, symbol, price))

    return signal


# ─── 📊 Баланс ────────────────────────────────────────────────────────────────

@router.message(F.text == "📊 Баланс")
async def btn_balance(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    await _send_balance(message)


async def _send_balance(message: Message):
    symbol = settings_service.get_symbol()
    try:
        price = await binance_service.get_price(symbol)
    except Exception:
        await message.answer(_price_error(symbol))
        return
    metrics = portfolio_service.calculate_portfolio_metrics(price)
    settings = settings_service.get_settings()
    await message.answer(
        balance_message(metrics, settings),
        reply_markup=refresh_back_kb("balance:refresh", "balance:back"),
    )


@router.callback_query(F.data == "balance:refresh")
async def balance_refresh(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    symbol = settings_service.get_symbol()
    try:
        price = await binance_service.get_price(symbol)
    except Exception:
        await callback.answer(_price_error(symbol))
        return
    metrics = portfolio_service.calculate_portfolio_metrics(price)
    settings = settings_service.get_settings()
    await callback.message.edit_text(
        balance_message(metrics, settings),
        reply_markup=refresh_back_kb("balance:refresh", "balance:back"),
    )
    await callback.answer()


@router.callback_query(F.data == "balance:back")
async def balance_back(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


# ─── 📈 PnL ───────────────────────────────────────────────────────────────────

@router.message(F.text == "📈 PnL")
async def btn_pnl(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    await _send_pnl(message)


async def _send_pnl(message: Message):
    symbol = settings_service.get_symbol()
    try:
        price = await binance_service.get_price(symbol)
    except Exception:
        await message.answer(_price_error(symbol))
        return
    metrics = portfolio_service.calculate_portfolio_metrics(price)
    await message.answer(
        pnl_message(metrics, symbol),
        reply_markup=refresh_back_kb("pnl:refresh", "pnl:back"),
    )


@router.callback_query(F.data == "pnl:refresh")
async def pnl_refresh(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    symbol = settings_service.get_symbol()
    try:
        price = await binance_service.get_price(symbol)
    except Exception:
        await callback.answer(_price_error(symbol))
        return
    metrics = portfolio_service.calculate_portfolio_metrics(price)
    await callback.message.edit_text(
        pnl_message(metrics, symbol),
        reply_markup=refresh_back_kb("pnl:refresh", "pnl:back"),
    )
    await callback.answer()


@router.callback_query(F.data == "pnl:back")
async def pnl_back(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


# ─── 🧠 Стратегія ─────────────────────────────────────────────────────────────

@router.message(F.text == "🧠 Стратегія")
async def btn_strategy(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    settings = settings_service.get_settings()
    await message.answer(
        strategy_message(settings.get("active_strategy", "accumulation")),
        reply_markup=strategy_kb(),
    )


@router.callback_query(F.data == "strategy:check_signal")
async def strategy_check_signal(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    await callback.answer()
    await _check_and_send_signal(callback.message, send_hold=True)


@router.callback_query(F.data == "strategy:back")
async def strategy_back(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


@router.callback_query(F.data == "strategy:info")
async def strategy_info(callback: CallbackQuery):
    await callback.answer()


# ─── 💰 Угоди ─────────────────────────────────────────────────────────────────

@router.message(F.text == "💰 Угоди")
async def btn_trades(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    await message.answer(f"💰 Угоди ({coin})", reply_markup=trades_kb())


@router.callback_query(F.data == "trade:back")
async def trade_back(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


# ─── Manual Buy ───────────────────────────────────────────────────────────────

@router.callback_query(F.data == "trade:manual_buy")
async def trade_manual_buy(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    await callback.message.answer(f"Введи суму покупки {coin} в USDT:", reply_markup=cancel_kb())
    await state.set_state(ManualBuy.waiting_amount)
    await callback.answer()


@router.message(ManualBuy.waiting_amount)
async def manual_buy_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну суму у USDT.")
        return
    await state.update_data(amount=amount)
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    await message.answer(
        f"Покупка {coin} на {amount:.2f} USDT\nВиберіть спосіб:",
        reply_markup=buy_confirm_kb("manualbuy"),
    )
    await state.set_state(ManualBuy.waiting_amount)


@router.callback_query(F.data.startswith("manualbuy:"))
async def manual_buy_confirm(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    amount = data.get("amount", 0)

    if action == "cancel":
        await callback.message.edit_text("❌ Покупку скасовано.")
        await state.clear()
        return

    if action == "custom":
        await callback.message.answer("Введи ціну покупки у USDT:", reply_markup=cancel_kb())
        await state.set_state(ManualBuy.waiting_custom_price)
        await callback.answer()
        return

    if action == "market":
        symbol = settings_service.get_symbol()
        try:
            price = await binance_service.get_price(symbol)
        except Exception:
            await callback.message.edit_text(_price_error(symbol))
            await state.clear()
            return
        _execute_buy(amount, price, "MANUAL_BUY", "Ручна покупка за ринком")
        from bot.messages import _base_coin
        coin = _base_coin(symbol)
        await callback.message.edit_text(
            f"✅ Куплено {coin} на {amount:.2f} USDT\nЦіна: {price:,.2f} USDT"
        )
        await state.clear()
    await callback.answer()


@router.message(ManualBuy.waiting_custom_price)
async def manual_buy_custom_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну ціну у USDT.")
        return
    data = await state.get_data()
    amount = data.get("amount", 0)
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    _execute_buy(amount, price, "MANUAL_BUY", "Ручна покупка за своєю ціною")
    await message.answer(
        f"✅ Куплено {coin} на {amount:.2f} USDT\nЦіна: {price:,.2f} USDT"
    )
    await state.clear()


def _execute_buy(amount: float, price: float, tx_type: str, note: str):
    portfolio_service.apply_buy(amount, price, tx_type, note)
    portfolio_service.add_deposit(amount)
    settings = settings_service.get_settings()
    metrics = portfolio_service.calculate_portfolio_metrics(price)
    sheets_service.update_dashboard(metrics, settings)


# ─── Manual Sell ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "trade:manual_sell")
async def trade_manual_sell(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    await callback.message.answer(f"Введи відсоток {coin}-позиції для продажу (наприклад: 10):", reply_markup=cancel_kb())
    await state.set_state(ManualSell.waiting_percent)
    await callback.answer()


@router.message(ManualSell.waiting_percent)
async def manual_sell_percent(message: Message, state: FSMContext):
    try:
        pct = float(message.text.replace(",", "."))
        if pct <= 0 or pct > 100:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи відсоток від 1 до 100.")
        return
    await state.update_data(percent=pct)
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    await message.answer(
        f"Продаж {pct:.2f}% {coin}-позиції\nВиберіть спосіб:",
        reply_markup=sell_confirm_kb("manualsell"),
    )
    await state.set_state(ManualSell.waiting_percent)


@router.callback_query(F.data.startswith("manualsell:"))
async def manual_sell_confirm(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    pct = data.get("percent", 0)

    if action == "cancel":
        await callback.message.edit_text("❌ Продаж скасовано.")
        await state.clear()
        return

    if action == "custom":
        await callback.message.answer("Введи ціну продажу у USDT:", reply_markup=cancel_kb())
        await state.set_state(ManualSell.waiting_custom_price)
        await callback.answer()
        return

    if action == "market":
        symbol = settings_service.get_symbol()
        try:
            price = await binance_service.get_price(symbol)
        except Exception:
            await callback.message.edit_text(_price_error(symbol))
            await state.clear()
            return
        from bot.messages import _base_coin
        coin = _base_coin(symbol)
        portfolio_service.apply_sell(pct, price, "MANUAL_SELL", "Ручний продаж за ринком")
        settings = settings_service.get_settings()
        metrics = portfolio_service.calculate_portfolio_metrics(price)
        sheets_service.update_dashboard(metrics, settings)
        await callback.message.edit_text(f"✅ Продано {pct:.2f}% {coin}\nЦіна: {price:,.2f} USDT")
        await state.clear()
    await callback.answer()


@router.message(ManualSell.waiting_custom_price)
async def manual_sell_custom_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну ціну у USDT.")
        return
    data = await state.get_data()
    pct = data.get("percent", 0)
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    portfolio_service.apply_sell(pct, price, "MANUAL_SELL", "Ручний продаж за своєю ціною")
    settings = settings_service.get_settings()
    metrics = portfolio_service.calculate_portfolio_metrics(price)
    sheets_service.update_dashboard(metrics, settings)
    await message.answer(f"✅ Продано {pct:.2f}% {coin}\nЦіна: {price:,.2f} USDT")
    await state.clear()


# ─── Monthly Deposit ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "trade:monthly")
async def trade_monthly(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    settings = settings_service.get_settings()
    monthly = settings.get("monthly_deposit", 500)
    btc_buy = monthly * 0.70
    reserve = monthly * 0.30
    symbol = settings.get("symbol", "BTCUSDT")
    from bot.messages import _base_coin
    coin = _base_coin(symbol)

    await state.update_data(monthly=monthly, btc_buy=btc_buy, reserve=reserve)
    await callback.message.answer(
        f"💵 Щомісячне поповнення\n\n"
        f"Сума: {monthly:.2f} USDT\n\n"
        f"Рекомендація:\n"
        f"Купити {coin} на {btc_buy:.2f} USDT.\n"
        f"Додати в резерв {reserve:.2f} USDT.",
        reply_markup=monthly_deposit_kb(),
    )
    await state.set_state(MonthlyDeposit.waiting_custom_price)
    await callback.answer()


@router.callback_query(F.data.startswith("monthly:"))
async def monthly_confirm(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    monthly = data.get("monthly", 500)
    btc_buy = data.get("btc_buy", 350)
    reserve = data.get("reserve", 150)

    if action == "cancel":
        await callback.message.edit_text("❌ Поповнення скасовано.")
        await state.clear()
        return

    if action == "reserve_only":
        portfolio_service.add_reserve(monthly, "MONTHLY_DEPOSIT", "Щомісячне поповнення (тільки резерв)")
        portfolio_service.add_deposit(monthly)
        await callback.message.edit_text(f"✅ Додано {monthly:.2f} USDT до резерву.")
        await state.clear()
        return

    if action == "custom":
        await callback.message.answer("Введи ціну покупки у USDT:", reply_markup=cancel_kb())
        await callback.answer()
        return

    if action == "market":
        symbol = settings_service.get_symbol()
        try:
            price = await binance_service.get_price(symbol)
        except Exception:
            await callback.message.edit_text(_price_error(symbol))
            await state.clear()
            return
        from bot.messages import _base_coin
        coin = _base_coin(symbol)
        portfolio_service.apply_buy(btc_buy, price, "MONTHLY_DEPOSIT", "Щомісячне поповнення — купівля")
        portfolio_service.add_reserve(reserve, "RESERVE_ADD", "Щомісячне поповнення — резерв")
        portfolio_service.add_deposit(monthly)
        settings = settings_service.get_settings()
        metrics = portfolio_service.calculate_portfolio_metrics(price)
        sheets_service.update_dashboard(metrics, settings)
        await callback.message.edit_text(
            f"✅ Щомісячне поповнення виконано!\n"
            f"{coin} куплено на {btc_buy:.2f} USDT за ціною {price:,.2f}\n"
            f"Додано в резерв: {reserve:.2f} USDT"
        )
        await state.clear()
    await callback.answer()


# ─── Extra Deposit ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "trade:extra")
async def trade_extra(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    await callback.message.answer("Введи суму додаткового поповнення в USDT:", reply_markup=cancel_kb())
    await state.set_state(ExtraDeposit.waiting_amount)
    await callback.answer()


@router.message(ExtraDeposit.waiting_amount)
async def extra_deposit_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну суму у USDT.")
        return

    symbol = settings_service.get_symbol()
    try:
        price = await binance_service.get_price(symbol)
    except Exception:
        await message.answer(_price_error(symbol))
        return

    portfolio = portfolio_service.get_portfolio()
    settings = settings_service.get_settings()
    strategy = get_strategy(settings.get("active_strategy", "accumulation"))
    from bot.messages import _base_coin
    coin = _base_coin(symbol)

    avg_price = portfolio.get("avg_price", 0)
    split = strategy.calc_extra_deposit_split(amount, avg_price, price) if hasattr(strategy, "calc_extra_deposit_split") else {"btc_buy": amount * 0.7, "reserve": amount * 0.3, "btc_pct": 70}

    btc_buy = split["btc_buy"]
    reserve = split["reserve"]
    btc_pct = split["btc_pct"]

    await state.update_data(amount=amount, btc_buy=btc_buy, reserve=reserve)
    await message.answer(
        f"💵 Додаткове поповнення: {amount:.2f} USDT\n\n"
        f"Рекомендація ({btc_pct:.0f}% {coin} / {100 - btc_pct:.0f}% резерв):\n"
        f"Купити {coin} на {btc_buy:.2f} USDT.\n"
        f"Додати в резерв {reserve:.2f} USDT.",
        reply_markup=buy_confirm_kb("extrabuy"),
    )
    await state.set_state(ExtraDeposit.waiting_custom_price)


@router.callback_query(F.data.startswith("extrabuy:"))
async def extra_buy_confirm(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    amount = data.get("amount", 0)
    btc_buy = data.get("btc_buy", 0)
    reserve = data.get("reserve", 0)

    if action == "cancel":
        await callback.message.edit_text("❌ Поповнення скасовано.")
        await state.clear()
        return

    if action == "custom":
        await callback.message.answer("Введи ціну покупки у USDT:", reply_markup=cancel_kb())
        await callback.answer()
        return

    if action == "market":
        symbol = settings_service.get_symbol()
        try:
            price = await binance_service.get_price(symbol)
        except Exception:
            await callback.message.edit_text(_price_error(symbol))
            await state.clear()
            return
        from bot.messages import _base_coin
        coin = _base_coin(symbol)
        portfolio_service.apply_buy(btc_buy, price, "EXTRA_DEPOSIT", "Додаткове поповнення — купівля")
        portfolio_service.add_reserve(reserve, "RESERVE_ADD", "Додаткове поповнення — резерв")
        portfolio_service.add_deposit(amount)
        settings = settings_service.get_settings()
        metrics = portfolio_service.calculate_portfolio_metrics(price)
        sheets_service.update_dashboard(metrics, settings)
        await callback.message.edit_text(
            f"✅ Додаткове поповнення виконано!\n"
            f"{coin} куплено на {btc_buy:.2f} USDT за ціною {price:,.2f}\n"
            f"Додано в резерв: {reserve:.2f} USDT"
        )
        await state.clear()
    await callback.answer()


# ─── Signal confirm from scheduler ───────────────────────────────────────────

@router.callback_query(F.data.startswith("sigconfirm:"))
async def signal_confirm_cb(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return

    parts = callback.data.split(":")
    signal_id = int(parts[1])
    signal_type = parts[2]
    action = parts[3]

    if action == "skip":
        signal_service.update_signal_status(signal_id, "IGNORED")
        await callback.message.edit_text("❌ Сигнал проігноровано.")
        await callback.answer()
        return

    if action == "custom":
        await state.update_data(signal_id=signal_id, signal_type=signal_type)
        await callback.message.answer("Введи ціну виконання у USDT:", reply_markup=cancel_kb())
        await state.set_state(SignalConfirm.waiting_custom_price)
        await callback.answer()
        return

    if action == "market":
        symbol = settings_service.get_symbol()
        try:
            price = await binance_service.get_price(symbol)
        except Exception:
            await callback.message.edit_text(_price_error(symbol))
            return
        await _execute_signal_action(callback.message, state, signal_id, signal_type, price)
    await callback.answer()


@router.message(SignalConfirm.waiting_custom_price)
async def signal_confirm_custom_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну ціну у USDT.")
        return
    data = await state.get_data()
    await _execute_signal_action(message, state, data["signal_id"], data["signal_type"], price)


async def _execute_signal_action(msg, state: FSMContext, signal_id: int, signal_type: str, price: float):
    signals = signal_service.get_last_signals(20)
    sig_data = next((s for s in signals if s["id"] == signal_id), None)
    if not sig_data:
        await msg.answer("❌ Сигнал не знайдено.")
        await state.clear()
        return

    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)

    if signal_type == "BUY":
        amount_usdt = sig_data.get("amount_usdt", 0)
        portfolio_service.apply_buy(amount_usdt, price, "BUY", f"Покупка за сигналом #{signal_id}")
        portfolio_service.add_deposit(amount_usdt)
        signal_service.update_signal_status(signal_id, "CONFIRMED")
        await msg.answer(f"✅ Куплено {coin} на {amount_usdt:.2f} USDT за ціною {price:,.2f}")
    elif signal_type == "SELL":
        pct = sig_data.get("amount_btc_percent", 0)
        portfolio_service.apply_sell(pct, price, "SELL", f"Продаж за сигналом #{signal_id}")
        signal_service.update_signal_status(signal_id, "CONFIRMED")
        await msg.answer(f"✅ Продано {pct:.2f}% {coin} за ціною {price:,.2f}")

    settings = settings_service.get_settings()
    metrics = portfolio_service.calculate_portfolio_metrics(price)
    sheets_service.update_dashboard(metrics, settings)
    await state.clear()


# ─── 🔔 Сигнали ───────────────────────────────────────────────────────────────

@router.message(F.text == "🔔 Сигнали")
async def btn_signals(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return

    sigs = signal_service.get_last_signals(1)
    if sigs:
        last = sigs[0]
        strategy = get_strategy(last.get("strategy_name", "accumulation"))
        text = (
            "🔔 Сигнали\n\n"
            f"Останній сигнал:\n"
            f"Тип: {last.get('signal_type', '')}\n"
            f"Стратегія: {strategy.title}\n"
            f"Ціна: {last.get('price', 0):,.2f} USDT\n"
            f"Статус: {last.get('status', '')}\n\n"
            f"Причина:\n{last.get('reason', '')}"
        )
    else:
        text = "🔔 Сигнали\n\nСигналів ще немає."

    await message.answer(text, reply_markup=signals_kb())


@router.callback_query(F.data == "signals:check")
async def signals_check(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    await callback.answer()
    await _check_and_send_signal(callback.message, send_hold=True)


@router.callback_query(F.data == "signals:history")
async def signals_history(callback: CallbackQuery):
    sigs = signal_service.get_last_signals(10)
    if not sigs:
        await callback.message.answer("Сигналів ще немає.", reply_markup=back_kb("signals:back"))
        await callback.answer()
        return
    lines = [signal_line(s) for s in sigs]
    text = "🔔 Останні сигнали:\n\n" + "\n\n---\n\n".join(lines)
    await callback.message.answer(text, reply_markup=back_kb("signals:back"))
    await callback.answer()


@router.callback_query(F.data == "signals:back")
async def signals_back(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


# ─── 📜 Історія ───────────────────────────────────────────────────────────────

@router.message(F.text == "📜 Історія")
async def btn_history(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    await message.answer("📜 Історія", reply_markup=history_kb())


@router.callback_query(F.data == "history:trades")
async def history_trades(callback: CallbackQuery):
    txs = get_last_transactions(10)
    if not txs:
        await callback.message.answer("Угод ще немає.", reply_markup=back_kb("history:back"))
        await callback.answer()
        return
    lines = [transaction_line(tx) for tx in txs]
    text = "💰 Останні угоди:\n\n" + "\n\n".join(lines)
    await callback.message.answer(text, reply_markup=back_kb("history:back"))
    await callback.answer()


@router.callback_query(F.data == "history:signals")
async def history_signals(callback: CallbackQuery):
    sigs = signal_service.get_last_signals(10)
    if not sigs:
        await callback.message.answer("Сигналів ще немає.", reply_markup=back_kb("history:back"))
        await callback.answer()
        return
    lines = [signal_line(s) for s in sigs]
    text = "🔔 Останні сигнали:\n\n" + "\n\n---\n\n".join(lines)
    await callback.message.answer(text, reply_markup=back_kb("history:back"))
    await callback.answer()


@router.callback_query(F.data == "history:back")
async def history_back(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


# ─── ⚙️ Налаштування ──────────────────────────────────────────────────────────

@router.message(F.text == "⚙️ Налаштування")
async def btn_settings(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    settings = settings_service.get_settings()
    await message.answer(settings_message(settings), reply_markup=settings_kb())


@router.callback_query(F.data == "settings:toggle_signals")
async def settings_toggle_signals(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    new_val = settings_service.toggle_signals()
    status = "увімкнено" if new_val else "вимкнено"
    await callback.answer(f"Сигнали {status}")
    settings = settings_service.get_settings()
    await callback.message.edit_text(settings_message(settings), reply_markup=settings_kb())


@router.callback_query(F.data == "settings:target")
async def settings_target(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    await callback.message.answer("Введи нову ціль портфеля у USDT:", reply_markup=cancel_kb())
    await state.set_state(SettingsStates.waiting_target_value)
    await callback.answer()


@router.message(SettingsStates.waiting_target_value)
async def settings_target_value(message: Message, state: FSMContext):
    try:
        value = float(message.text.replace(",", "."))
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректне число.")
        return
    settings_service.update_target_value(value)
    await message.answer(f"✅ Ціль оновлена: {value:,.2f} USDT")
    await state.clear()


@router.callback_query(F.data == "settings:monthly")
async def settings_monthly(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    await callback.message.answer("Введи суму щомісячного поповнення у USDT:", reply_markup=cancel_kb())
    await state.set_state(SettingsStates.waiting_monthly_deposit)
    await callback.answer()


@router.message(SettingsStates.waiting_monthly_deposit)
async def settings_monthly_value(message: Message, state: FSMContext):
    try:
        value = float(message.text.replace(",", "."))
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректне число.")
        return
    settings_service.update_monthly_deposit(value)
    await message.answer(f"✅ Щомісячне поповнення оновлено: {value:,.2f} USDT")
    await state.clear()


@router.callback_query(F.data == "settings:interval")
async def settings_interval(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    await callback.message.answer("Введи частоту перевірки у хвилинах (мін. 1):", reply_markup=cancel_kb())
    await state.set_state(SettingsStates.waiting_check_interval)
    await callback.answer()


@router.message(SettingsStates.waiting_check_interval)
async def settings_interval_value(message: Message, state: FSMContext):
    try:
        minutes = int(message.text.strip())
        if minutes < 1:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи ціле число, мінімум 1.")
        return
    settings_service.update_check_interval(minutes)
    await message.answer(f"✅ Частота перевірки оновлена: {minutes} хв")
    await state.clear()


@router.callback_query(F.data == "settings:strategy")
async def settings_strategy(callback: CallbackQuery):
    await callback.answer("Зараз доступна лише стратегія «Моє накопичення позиції».", show_alert=True)


# ─── 🪙 Зміна монети ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "settings:symbol")
async def settings_symbol(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    current = settings_service.get_symbol()
    await callback.message.answer(
        f"Поточна монета: {current}\n\n"
        "Введи новий символ торгової пари Binance\n"
        "(наприклад: ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT):\n\n"
        "⚠️ При зміні монети портфель буде скинуто до нуля!",
        reply_markup=cancel_kb(),
    )
    await state.set_state(SettingsStates.waiting_symbol)
    await callback.answer()


@router.message(SettingsStates.waiting_symbol)
async def settings_symbol_value(message: Message, state: FSMContext):
    symbol = message.text.strip().upper()
    if not symbol or len(symbol) < 5:
        await message.answer("❌ Невірний символ. Приклад: ETHUSDT, SOLUSDT.")
        return

    await message.answer(f"⏳ Перевіряю {symbol} на Binance...")
    valid = await binance_service.validate_symbol(symbol)
    if not valid:
        await message.answer(
            f"❌ Символ {symbol} не знайдено на Binance.\n"
            "Перевір назву та спробуй ще раз."
        )
        return

    old_symbol = settings_service.get_symbol()
    settings_service.update_symbol(symbol)
    portfolio_service.reset_portfolio()
    signal_service.reset_buy_drop_triggers("accumulation")

    await message.answer(
        f"✅ Монету змінено: {old_symbol} → {symbol}\n\n"
        f"Портфель скинуто до нуля.\n"
        f"Виконай /init щоб ініціалізувати новий портфель.",
        reply_markup=main_menu(),
    )
    await state.clear()


@router.callback_query(F.data == "settings:back")
async def settings_back(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()
