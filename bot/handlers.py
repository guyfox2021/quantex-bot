import logging
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

import config
from bot.states import (
    InitPortfolio, ManualBuy, ManualSell,
    MonthlyDeposit, ExtraDeposit, EditTransaction, SettingsStates, SignalConfirm,
)
from bot.keyboards import (
    main_menu, buy_confirm_kb, sell_confirm_kb, signal_confirm_kb,
    monthly_deposit_kb, trades_kb, signals_kb, refresh_back_kb,
    strategy_kb, strategy_select_kb, settings_kb, history_kb, back_kb, cancel_kb, start_strategy_kb,
    confirm_delete_trade_kb, transaction_delete_select_kb, transaction_edit_select_kb, dashboard_link_kb,
)
from bot.messages import (
    start_message, balance_message, pnl_message, strategy_message,
    signal_message, settings_message, transaction_line, signal_line,
)
from services import owner_service, binance_service, portfolio_service, buyback_service
from services import settings_service, signal_service, sheets_service
from services.transaction_service import (
    get_last_transactions, void_transaction,
    get_active_transactions_desc, get_transaction, update_transaction_values,
    apply_commission_to_zero_fee_transactions,
)
from strategies.registry import get_strategy, list_strategies

logger = logging.getLogger(__name__)
router = Router()

ACCESS_DENIED = "⛔ Доступ заборонено."


# ─── Universal cancel ─────────────────────────────────────────────────────────

@router.callback_query(F.data == "cancel_input")
async def cancel_input(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Скасовано.")
    await callback.message.answer("Головне меню:", reply_markup=main_menu())
    await callback.answer()


def _price_error(symbol: str) -> str:
    return f"⚠️ Не вдалося отримати поточну ціну {symbol}. Спробуй пізніше."


def _auto_fee(fee_base_amount: float, default_asset: str) -> tuple[float, str]:
    commission_percent = settings_service.get_settings().get("commission_percent", 0.1)
    return fee_base_amount * commission_percent / 100, default_asset.upper()


def _format_fee(fee: float, fee_asset: str) -> str:
    return f"{fee:g} {fee_asset}"


async def _safe_edit_text(message, text: str, **kwargs):
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        raise


async def _restore_main_menu(message: Message, text: str = "Головне меню:"):
    await message.answer(text, reply_markup=main_menu())


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
            f"📍 ПЕРШЙ СГНАЛ: Встановити початкову позицію\n\n"
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


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    await _restore_main_menu(message)


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
    open_buybacks = buyback_service.get_open_cycles(strategy.name)
    signal_service.refresh_ignored_signal_locks(strategy.name, price, portfolio, open_buybacks)
    triggers = signal_service.get_triggers(strategy.name)

    market_data = {
        "price": price,
        "open_buybacks": open_buybacks,
    }
    signal = strategy.check(portfolio, market_data, settings, triggers)

    if signal.signal_type in ("BUY", "SELL"):
        if signal.signal_type == "BUY" and not signal_service.can_send_buy_signal(cooldown_hours=6):
            if send_hold and message:
                await message.answer("ℹ️ BUY-сигнал пропущено: активний cooldown 6 годин після попереднього BUY.")
            return signal

        if signal.trigger_type and signal.level_percent is not None:
            has_active = signal_service.has_active_signal_for_trigger(
                strategy.name,
                signal.trigger_type,
                signal.level_percent,
            )
            if has_active:
                if send_hold and message:
                    await message.answer("ℹ️ Такий сигнал уже був надісланий або пропущений на поточному рівні.")
                return signal

        sig_id = signal_service.save_signal(signal, price, status="SENT")
        if signal.trigger_type:
            signal_service.mark_triggered(strategy.name, signal.trigger_type, signal.level_percent)

        text = signal_message(signal, symbol, price, portfolio)
        kb = signal_confirm_kb(sig_id, signal.signal_type)
        if message:
            await message.answer(text, reply_markup=kb)
        return signal

    if send_hold and message:
        await message.answer(signal_message(signal, symbol, price, portfolio))

    return signal


# ─── 📊 Баланс ────────────────────────────────────────────────────────────────

@router.message(F.text == "🌐 Дашборд")
async def btn_dashboard(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return

    url = _dashboard_url()
    if not url:
        await message.answer("❌ Посилання на дашборд ще не налаштовано.")
        return

    await message.answer(
        "🌐 Дашборд QuantEX\n\nГрафіки портфеля, PnL, резерву, сигналів та BUYBACK cycles.",
        reply_markup=dashboard_link_kb(url),
    )


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
    await _safe_edit_text(
        callback.message,
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
    await _safe_edit_text(
        callback.message,
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
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    settings = settings_service.get_settings()
    await callback.message.answer(
        strategy_message(settings.get("active_strategy", "accumulation")),
        reply_markup=back_kb("strategy:back"),
    )
    await callback.answer("Відкрив деталі стратегії")


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


@router.callback_query(F.data == "trade:delete_select")
async def trade_delete_select(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return

    transactions = get_active_transactions_desc(20)
    if not transactions:
        await callback.answer("Немає активних транзакцій для видалення.", show_alert=True)
        return

    text = "🗑 Вибери помилкову угоду для видалення з розрахунку:"
    await callback.message.answer(text, reply_markup=transaction_delete_select_kb(transactions))
    await callback.answer()


@router.callback_query(F.data == "trade:delete_cancel")
async def trade_delete_cancel(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer("Дію відмінено")


@router.callback_query(F.data == "trade:edit_select")
async def trade_edit_select(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return

    transactions = get_active_transactions_desc(20)
    if not transactions:
        await callback.answer("Немає активних транзакцій для зміни.", show_alert=True)
        return

    await callback.message.answer(
        "✏️ Вибери угоду, яку потрібно змінити:",
        reply_markup=transaction_edit_select_kb(transactions),
    )
    await callback.answer()


def _dashboard_url() -> str:
    if config.DASHBOARD_PUBLIC_URL:
        return config.DASHBOARD_PUBLIC_URL
    if config.DASHBOARD_TOKEN:
        return f"http://167.71.63.195:{config.DASHBOARD_PORT}/dashboard?token={config.DASHBOARD_TOKEN}"
    return ""


@router.callback_query(F.data == "trade:edit_cancel")
async def trade_edit_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await callback.answer("Редагування відмінено")


@router.callback_query(F.data.startswith("trade:edit_pick:"))
async def trade_edit_pick(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return

    tx_id = int(callback.data.rsplit(":", 1)[1])
    tx = get_transaction(tx_id)
    if not tx or tx.get("status") != "ACTIVE":
        await callback.answer("Ця транзакція вже не активна або не знайдена.", show_alert=True)
        return

    edit_kind = _edit_transaction_kind(tx)
    await state.update_data(edit_tx_id=tx_id, edit_kind=edit_kind)

    if edit_kind == "USDT_ONLY":
        text = (
            "✏️ Зміна угоди\n\n"
            f"{transaction_line(tx)}\n\n"
            "Введи нову суму USDT:"
        )
        await callback.message.edit_text(text, reply_markup=cancel_kb())
        await state.set_state(EditTransaction.waiting_usdt_amount)
    else:
        side_text = "покупки" if edit_kind == "BUY" else "продажу"
        text = (
            "✏️ Зміна угоди\n\n"
            f"{transaction_line(tx)}\n\n"
            f"Введи фактичну ціну {side_text} у USDT:"
        )
        await callback.message.edit_text(text, reply_markup=cancel_kb())
        await state.set_state(EditTransaction.waiting_price)
    await callback.answer()


@router.message(EditTransaction.waiting_price)
async def trade_edit_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну ціну.")
        return

    data = await state.get_data()
    tx_id = data.get("edit_tx_id")
    tx = get_transaction(tx_id)
    if not tx or tx.get("status") != "ACTIVE":
        await message.answer("❌ Транзакція не знайдена або вже не активна.")
        await state.clear()
        return

    edit_kind = data.get("edit_kind")
    await state.update_data(edit_price=price)
    if edit_kind == "BUY":
        await message.answer("Введи суму покупки в USDT:", reply_markup=cancel_kb())
        await state.set_state(EditTransaction.waiting_usdt_amount)
        return

    symbol = tx.get("symbol", settings_service.get_symbol())
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    await message.answer(f"Введи кількість {coin}, яку було продано:", reply_markup=cancel_kb())
    await state.set_state(EditTransaction.waiting_coin_amount)


@router.message(EditTransaction.waiting_usdt_amount)
async def trade_edit_usdt_amount(message: Message, state: FSMContext):
    try:
        usdt_amount = float(message.text.replace(",", "."))
        if usdt_amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну суму USDT.")
        return

    data = await state.get_data()
    tx_id = data.get("edit_tx_id")
    tx = get_transaction(tx_id)
    if not tx or tx.get("status") != "ACTIVE":
        await message.answer("❌ Транзакція не знайдена або вже не активна.")
        await state.clear()
        return

    edit_kind = data.get("edit_kind")
    if edit_kind == "BUY":
        price = data.get("edit_price", 0.0)
        symbol = tx.get("symbol", settings_service.get_symbol())
        from bot.messages import _base_coin
        coin = _base_coin(symbol)
        fee, fee_asset = _auto_fee(usdt_amount / price if price > 0 else 0.0, coin)
        btc_amount = max((usdt_amount / price if price > 0 else 0.0) - fee, 0.0)
        await _update_transaction_and_rebuild(tx_id, price, usdt_amount, btc_amount, fee, fee_asset)
        await message.answer(
            "✅ Угоду змінено. Портфель повністю перераховано.\n"
            f"Комісія: {_format_fee(fee, fee_asset)}",
            reply_markup=main_menu(),
        )
        await state.clear()
        return

    await _update_transaction_and_rebuild(tx_id, 0.0, usdt_amount, 0.0, 0.0, "USDT")
    await message.answer("✅ Угоду змінено. Портфель повністю перераховано.", reply_markup=main_menu())
    await state.clear()


@router.message(EditTransaction.waiting_coin_amount)
async def trade_edit_coin_amount(message: Message, state: FSMContext):
    try:
        coin_amount = float(message.text.replace(",", "."))
        if coin_amount < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну кількість монети.")
        return

    data = await state.get_data()
    tx_id = data.get("edit_tx_id")
    tx = get_transaction(tx_id)
    if not tx or tx.get("status") != "ACTIVE":
        await message.answer("❌ Транзакція не знайдена або вже не активна.")
        await state.clear()
        return

    price = data.get("edit_price", 0.0)
    usdt_amount = coin_amount * price
    fee, fee_asset = _auto_fee(usdt_amount, "USDT")
    await _update_transaction_and_rebuild(tx_id, price, usdt_amount, coin_amount, fee, fee_asset)
    await message.answer(
        "✅ Угоду змінено. Портфель повністю перераховано.\n"
        f"Комісія: {_format_fee(fee, fee_asset)}",
        reply_markup=main_menu(),
    )
    await state.clear()


def _edit_transaction_kind(tx: dict) -> str:
    tx_type = tx.get("type", "")
    price = float(tx.get("price", 0.0) or 0.0)
    btc_amount = float(tx.get("btc_amount", 0.0) or 0.0)
    if tx_type in ("SELL", "MANUAL_SELL"):
        return "SELL"
    if tx_type in ("BUY", "MANUAL_BUY", "MONTHLY_DEPOSIT", "EXTRA_DEPOSIT") and price > 0 and btc_amount > 0:
        return "BUY"
    return "USDT_ONLY"


async def _update_transaction_and_rebuild(
    tx_id: int,
    price: float,
    usdt_amount: float,
    btc_amount: float,
    fee: float,
    fee_asset: str,
) -> None:
    update_transaction_values(tx_id, price, usdt_amount, btc_amount, fee, fee_asset)
    portfolio_service.rebuild_portfolio_from_transactions()
    buyback_service.sync_cycles_from_active_transactions()

    symbol = settings_service.get_symbol()
    try:
        current_price = await binance_service.get_price(symbol)
        metrics = portfolio_service.calculate_portfolio_metrics(current_price)
        settings = settings_service.get_settings()
        sheets_service.update_dashboard(metrics, settings)
    except Exception:
        pass


@router.callback_query(F.data.startswith("trade:delete_pick:"))
async def trade_delete_pick(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return

    tx_id = int(callback.data.rsplit(":", 1)[1])
    tx = get_transaction(tx_id)
    if not tx or tx.get("status") != "ACTIVE":
        await callback.answer("Ця транзакція вже не активна або не знайдена.", show_alert=True)
        return

    text = (
        "🗑 Видалення угоди з розрахунку\n\n"
        "Бот позначить цю транзакцію як видалену та одразу перерахує портфель "
        "з усіх інших активних транзакцій.\n\n"
        "Транзакція:\n\n"
        f"{transaction_line(tx)}"
    )
    await callback.message.edit_text(text, reply_markup=confirm_delete_trade_kb(tx_id))
    await callback.answer()


@router.callback_query(F.data.startswith("trade:delete_confirm:"))
async def trade_delete_confirm(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return

    tx_id = int(callback.data.rsplit(":", 1)[1])
    tx = get_transaction(tx_id)
    if not tx or tx.get("status") != "ACTIVE":
        await callback.answer("Ця транзакція вже не активна або не знайдена.", show_alert=True)
        return

    void_transaction(tx_id, "Deleted from Telegram UI with full portfolio rebuild")
    portfolio_service.rebuild_portfolio_from_transactions()
    buyback_service.sync_cycles_from_active_transactions()

    symbol = settings_service.get_symbol()
    try:
        price = await binance_service.get_price(symbol)
        metrics = portfolio_service.calculate_portfolio_metrics(price)
        settings = settings_service.get_settings()
        sheets_service.update_dashboard(metrics, settings)
    except Exception:
        pass

    await callback.message.edit_text("✅ Угоду видалено з розрахунку. Портфель повністю перераховано.")
    await callback.message.answer("Головне меню:", reply_markup=main_menu())
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
        from bot.messages import _base_coin
        coin = _base_coin(symbol)
        fee, fee_asset = _auto_fee(amount / price if price > 0 else 0.0, coin)
        _execute_buy(amount, price, "MANUAL_BUY", "Ручна покупка за ринком", fee, fee_asset)
        await callback.message.edit_text(
            f"✅ Куплено {coin} на {amount:.2f} USDT\nЦіна: {price:,.2f} USDT\nКомісія: {_format_fee(fee, fee_asset)}"
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
    fee, fee_asset = _auto_fee(amount / price if price > 0 else 0.0, coin)
    _execute_buy(amount, price, "MANUAL_BUY", "Ручна покупка за своєю ціною", fee, fee_asset)
    await message.answer(
        f"✅ Куплено {coin} на {amount:.2f} USDT\nЦіна: {price:,.2f} USDT\nКомісія: {_format_fee(fee, fee_asset)}",
        reply_markup=main_menu(),
    )
    await state.clear()


def _execute_buy(amount: float, price: float, tx_type: str, note: str, fee: float = 0.0, fee_asset: str = "USDT"):
    portfolio_service.apply_buy(amount, price, tx_type, note, fee=fee, fee_asset=fee_asset)
    portfolio_service.add_deposit(amount + (fee if fee_asset == "USDT" else 0.0))
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
        portfolio = portfolio_service.get_portfolio()
        btc_to_sell = portfolio.get("btc_amount", 0.0) * pct / 100
        fee, fee_asset = _auto_fee(btc_to_sell * price, "USDT")
        try:
            portfolio_service.apply_sell(pct, price, "MANUAL_SELL", "Ручний продаж за ринком", fee=fee, fee_asset=fee_asset)
        except ValueError as e:
            await callback.message.answer(f"❌ {e}")
            await state.clear()
            await callback.answer()
            return
        settings = settings_service.get_settings()
        metrics = portfolio_service.calculate_portfolio_metrics(price)
        sheets_service.update_dashboard(metrics, settings)
        from bot.messages import _base_coin
        coin = _base_coin(symbol)
        await callback.message.edit_text(f"✅ Продано {pct:.2f}% {coin}\nЦіна: {price:,.2f} USDT\nКомісія: {_format_fee(fee, fee_asset)}")
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
    portfolio = portfolio_service.get_portfolio()
    btc_to_sell = portfolio.get("btc_amount", 0.0) * pct / 100
    fee, fee_asset = _auto_fee(btc_to_sell * price, "USDT")
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    try:
        portfolio_service.apply_sell(pct, price, "MANUAL_SELL", "Ручний продаж за своєю ціною", fee=fee, fee_asset=fee_asset)
    except ValueError as e:
        await message.answer(f"❌ {e}")
        await state.clear()
        return
    settings = settings_service.get_settings()
    metrics = portfolio_service.calculate_portfolio_metrics(price)
    sheets_service.update_dashboard(metrics, settings)
    await message.answer(
        f"✅ Продано {pct:.2f}% {coin}\nЦіна: {price:,.2f} USDT\nКомісія: {_format_fee(fee, fee_asset)}",
        reply_markup=main_menu(),
    )
    await state.clear()


# ─── Monthly Deposit ──────────────────────────────────────────────────────────

@router.callback_query(F.data == "trade:monthly")
async def trade_monthly(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    settings = settings_service.get_settings()
    monthly = settings.get("monthly_deposit", 500)
    symbol = settings.get("symbol", "BTCUSDT")
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    strategy = get_strategy(settings.get("active_strategy", "accumulation"))

    try:
        price = await binance_service.get_price(symbol)
        portfolio = portfolio_service.get_portfolio()
        if hasattr(strategy, "calc_monthly_deposit_split"):
            split = strategy.calc_monthly_deposit_split(monthly, portfolio.get("avg_price", 0), price)
        else:
            split = {"btc_buy": monthly * 0.70, "reserve": monthly * 0.30, "btc_pct": 70}
    except Exception:
        split = {"btc_buy": monthly * 0.70, "reserve": monthly * 0.30, "btc_pct": 70}

    btc_buy = split["btc_buy"]
    reserve = split["reserve"]
    btc_pct = split.get("btc_pct", 70)

    await state.update_data(monthly=monthly, btc_buy=btc_buy, reserve=reserve)
    await callback.message.answer(
        f"💵 Щомісячне поповнення\n\n"
        f"Сума: {monthly:.2f} USDT\n\n"
        f"Рекомендація ({btc_pct:.0f}% {coin} / {100 - btc_pct:.0f}% резерв):\n"
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
        await callback.answer()
        return

    if action == "custom":
        await callback.message.answer("Введи ціну покупки у USDT:", reply_markup=cancel_kb())
        await state.set_state(MonthlyDeposit.waiting_custom_price)
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
        fee, fee_asset = _auto_fee(btc_buy / price if price > 0 else 0.0, coin)
        _execute_deposit_buy(monthly, btc_buy, reserve, price, "MONTHLY_DEPOSIT", "Щомісячне поповнення", fee, fee_asset)
        await callback.message.edit_text(
            f"✅ Щомісячне поповнення виконано!\n"
            f"{coin} куплено на {btc_buy:.2f} USDT за ціною {price:,.2f}\n"
            f"Додано в резерв: {reserve:.2f} USDT\n"
            f"Комісія: {_format_fee(fee, fee_asset)}"
        )
        await state.clear()
    await callback.answer()


@router.message(MonthlyDeposit.waiting_custom_price)
async def monthly_custom_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну ціну у USDT.")
        return
    data = await state.get_data()
    btc_buy = data.get("btc_buy", data.get("monthly", 500) * 0.70)
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    monthly = data.get("monthly", 500)
    reserve = data.get("reserve", monthly * 0.30)
    fee, fee_asset = _auto_fee(btc_buy / price if price > 0 else 0.0, coin)
    _execute_deposit_buy(monthly, btc_buy, reserve, price, "MONTHLY_DEPOSIT", "Щомісячне поповнення", fee, fee_asset)

    await message.answer(
        f"✅ Щомісячне поповнення виконано!\n"
        f"{coin} куплено на {btc_buy:.2f} USDT за ціною {price:,.2f}\n"
        f"Додано в резерв: {reserve:.2f} USDT\n"
        f"Комісія: {_format_fee(fee, fee_asset)}"
    )
    await state.clear()


def _execute_deposit_buy(
    total_deposit: float,
    btc_buy: float,
    reserve: float,
    price: float,
    tx_type: str,
    note_prefix: str,
    fee: float,
    fee_asset: str,
):
    portfolio_service.apply_buy(
        btc_buy,
        price,
        tx_type,
        f"{note_prefix} — купівля",
        fee=fee,
        fee_asset=fee_asset,
    )
    portfolio_service.add_reserve(reserve, "RESERVE_ADD", f"{note_prefix} — резерв")
    portfolio_service.add_deposit(total_deposit + (fee if fee_asset == "USDT" else 0.0))
    settings = settings_service.get_settings()
    metrics = portfolio_service.calculate_portfolio_metrics(price)
    sheets_service.update_dashboard(metrics, settings)

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
        await state.set_state(ExtraDeposit.waiting_custom_price)
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
        fee, fee_asset = _auto_fee(btc_buy / price if price > 0 else 0.0, coin)
        _execute_deposit_buy(amount, btc_buy, reserve, price, "EXTRA_DEPOSIT", "Додаткове поповнення", fee, fee_asset)
        await callback.message.edit_text(
            f"✅ Додаткове поповнення виконано!\n"
            f"{coin} куплено на {btc_buy:.2f} USDT за ціною {price:,.2f}\n"
            f"Додано в резерв: {reserve:.2f} USDT\n"
            f"Комісія: {_format_fee(fee, fee_asset)}"
        )
        await state.clear()
    await callback.answer()


@router.message(ExtraDeposit.waiting_custom_price)
async def extra_custom_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректну ціну у USDT.")
        return

    data = await state.get_data()
    amount = data.get("amount", 0)
    btc_buy = data.get("btc_buy", 0)
    reserve = data.get("reserve", 0)
    if amount <= 0:
        await message.answer("❌ Не знайдено суму поповнення. Спробуй ще раз.")
        await state.clear()
        return
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    fee, fee_asset = _auto_fee(btc_buy / price if price > 0 else 0.0, coin)
    _execute_deposit_buy(amount, btc_buy, reserve, price, "EXTRA_DEPOSIT", "Додаткове поповнення", fee, fee_asset)

    await message.answer(
        f"✅ Додаткове поповнення виконано!\n"
        f"{coin} куплено на {btc_buy:.2f} USDT за ціною {price:,.2f}\n"
        f"Додано в резерв: {reserve:.2f} USDT\n"
        f"Комісія: {_format_fee(fee, fee_asset)}"
    )
    await state.clear()


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
        await callback.message.edit_text(
            "\u274c \u0421\u0438\u0433\u043d\u0430\u043b \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e. "
            "\u042f\u043a\u0449\u043e \u0446\u0456\u043d\u0430 \u0432\u0438\u0439\u0434\u0435 \u0437 \u0440\u0456\u0432\u043d\u044f \u0456 \u043f\u043e\u0432\u0435\u0440\u043d\u0435\u0442\u044c\u0441\u044f \u0437\u043d\u043e\u0432\u0443, \u0431\u043e\u0442 \u043d\u0430\u0434\u0456\u0448\u043b\u0435 \u043d\u043e\u0432\u0438\u0439 \u0441\u0438\u0433\u043d\u0430\u043b. "
            "\u042f\u043a\u0449\u043e \u0446\u0456\u043d\u0430 \u0437\u0430\u043b\u0438\u0448\u0438\u0442\u044c\u0441\u044f \u0432 \u0446\u0456\u0439 \u0437\u043e\u043d\u0456, \u0431\u043e\u0442 \u043d\u0430\u0433\u0430\u0434\u0430\u0454 \u043f\u043e\u0432\u0442\u043e\u0440\u043d\u043e \u043f\u0440\u0438\u0431\u043b\u0438\u0437\u043d\u043e \u0447\u0435\u0440\u0435\u0437 15 \u0445\u0432\u0438\u043b\u0438\u043d."
        )
        await callback.answer()
        return

    if action in ("custom", "market"):
        await state.update_data(signal_id=signal_id, signal_type=signal_type)
        await callback.message.answer(
            "\u0412\u0432\u0435\u0434\u0438 \u0444\u0430\u043a\u0442\u0438\u0447\u043d\u0443 \u0446\u0456\u043d\u0443 \u0432\u0438\u043a\u043e\u043d\u0430\u043d\u043d\u044f \u0443 USDT:",
            reply_markup=cancel_kb(),
        )
        await state.set_state(SignalConfirm.waiting_custom_price)
        await callback.answer()
        return
    await callback.answer()


@router.message(SignalConfirm.waiting_custom_price)
async def signal_confirm_custom_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("\u274c \u0412\u0432\u0435\u0434\u0438 \u043a\u043e\u0440\u0435\u043a\u0442\u043d\u0443 \u0446\u0456\u043d\u0443 \u0443 USDT.")
        return

    data = await state.get_data()
    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)
    await state.update_data(execution_price=price)

    if data["signal_type"] == "BUY":
        await message.answer(f"\u0412\u0432\u0435\u0434\u0438 \u0444\u0430\u043a\u0442\u0438\u0447\u043d\u043e \u043a\u0443\u043f\u043b\u0435\u043d\u0443 \u043a\u0456\u043b\u044c\u043a\u0456\u0441\u0442\u044c {coin}:", reply_markup=cancel_kb())
    else:
        await message.answer(f"\u0412\u0432\u0435\u0434\u0438 \u0444\u0430\u043a\u0442\u0438\u0447\u043d\u043e \u043f\u0440\u043e\u0434\u0430\u043d\u0443 \u043a\u0456\u043b\u044c\u043a\u0456\u0441\u0442\u044c {coin}:", reply_markup=cancel_kb())
    await state.set_state(SignalConfirm.waiting_coin_amount)


@router.message(SignalConfirm.waiting_coin_amount)
async def signal_confirm_coin_amount(message: Message, state: FSMContext):
    try:
        actual_coin_amount = float(message.text.replace(",", "."))
        if actual_coin_amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("\u274c \u0412\u0432\u0435\u0434\u0438 \u043a\u043e\u0440\u0435\u043a\u0442\u043d\u0443 \u043a\u0456\u043b\u044c\u043a\u0456\u0441\u0442\u044c \u043c\u043e\u043d\u0435\u0442\u0438.")
        return

    data = await state.get_data()
    price = float(data.get("execution_price", 0.0) or 0.0)
    if price <= 0:
        await message.answer("\u274c \u041d\u0435 \u0432\u0434\u0430\u043b\u043e\u0441\u044f \u043e\u0442\u0440\u0438\u043c\u0430\u0442\u0438 \u0446\u0456\u043d\u0443 \u0432\u0438\u043a\u043e\u043d\u0430\u043d\u043d\u044f. \u0421\u043f\u0440\u043e\u0431\u0443\u0439 \u0449\u0435 \u0440\u0430\u0437.")
        await state.clear()
        return

    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)

    if data["signal_type"] == "BUY":
        fee, fee_asset = _auto_fee(actual_coin_amount, coin)
    else:
        fee, fee_asset = _auto_fee(actual_coin_amount * price, "USDT")

    await _execute_signal_action(
        message,
        state,
        data["signal_id"],
        data["signal_type"],
        price,
        fee,
        fee_asset,
        actual_coin_amount=actual_coin_amount,
    )


async def _execute_signal_action(
    msg,
    state: FSMContext,
    signal_id: int,
    signal_type: str,
    price: float,
    fee: float = 0.0,
    fee_asset: str = "USDT",
    actual_coin_amount: float | None = None,
):
    sig_data = signal_service.get_signal(signal_id)
    if not sig_data:
        await msg.answer("\u274c \u0421\u0438\u0433\u043d\u0430\u043b \u043d\u0435 \u0437\u043d\u0430\u0439\u0434\u0435\u043d\u043e.")
        await state.clear()
        return

    symbol = settings_service.get_symbol()
    from bot.messages import _base_coin
    coin = _base_coin(symbol)

    if signal_type == "BUY":
        gross_btc_bought = actual_coin_amount if actual_coin_amount is not None else 0.0
        amount_usdt = gross_btc_bought * price
        net_btc_bought = max(gross_btc_bought - fee, 0.0) if fee_asset == coin else gross_btc_bought
        try:
            portfolio_service.apply_buy(
                amount_usdt,
                price,
                "BUY",
                f"\u041f\u043e\u043a\u0443\u043f\u043a\u0430 \u0437\u0430 \u0441\u0438\u0433\u043d\u0430\u043b\u043e\u043c #{signal_id}",
                spend_from_reserve=True,
                fee=fee,
                fee_asset=fee_asset,
            )
        except ValueError as e:
            await msg.answer(f"\u274c {e}")
            await state.clear()
            return
        if sig_data.get("trigger_type") == "BUYBACK" and sig_data.get("buyback_cycle_id"):
            buyback_service.mark_level_done(
                sig_data["buyback_cycle_id"],
                sig_data.get("level_percent", 0),
                net_btc_bought,
            )
        signal_service.update_signal_status(signal_id, "CONFIRMED")
        await msg.answer(
            f"\u2705 \u041a\u0443\u043f\u043b\u0435\u043d\u043e {gross_btc_bought:.8f} {coin}\n"
            f"\u0412\u0438\u0442\u0440\u0430\u0447\u0435\u043d\u043e: {amount_usdt:.2f} USDT\n"
            f"\u0426\u0456\u043d\u0430: {price:,.2f}\n"
            f"\u041a\u043e\u043c\u0456\u0441\u0456\u044f: {fee:g} {fee_asset}"
        )
    elif signal_type == "SELL":
        gross_btc_sold = actual_coin_amount if actual_coin_amount is not None else 0.0
        btc_sold = gross_btc_sold + (fee if fee_asset == coin else 0.0)
        usdt_received = gross_btc_sold * price - (fee if fee_asset == "USDT" else 0.0)
        try:
            portfolio_service.apply_sell_amount(
                gross_btc_sold,
                price,
                "SELL",
                f"\u041f\u0440\u043e\u0434\u0430\u0436 \u0437\u0430 \u0441\u0438\u0433\u043d\u0430\u043b\u043e\u043c #{signal_id}",
                fee=fee,
                fee_asset=fee_asset,
            )
        except ValueError as e:
            await msg.answer(f"\u274c {e}")
            await state.clear()
            return
        if sig_data.get("strategy_name") == "accumulation_v2" and sig_data.get("trigger_type") == "SELL_PROFIT":
            buyback_service.create_cycle(
                sell_price=price,
                btc_sold=btc_sold,
                usdt_received=usdt_received,
                sell_signal_id=signal_id,
                strategy_name="accumulation_v2",
            )
        signal_service.update_signal_status(signal_id, "CONFIRMED")
        await msg.answer(
            f"\u2705 \u041f\u0440\u043e\u0434\u0430\u043d\u043e {gross_btc_sold:.8f} {coin}\n"
            f"\u041e\u0442\u0440\u0438\u043c\u0430\u043d\u043e: {usdt_received:.2f} USDT\n"
            f"\u0426\u0456\u043d\u0430: {price:,.2f}\n"
            f"\u041a\u043e\u043c\u0456\u0441\u0456\u044f: {fee:g} {fee_asset}"
        )

    settings = settings_service.get_settings()
    metrics = portfolio_service.calculate_portfolio_metrics(price)
    sheets_service.update_dashboard(metrics, settings)
    await state.clear()


@router.message(F.text == "🔔 Сигнали")
async def btn_signals(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return

    sigs = signal_service.get_last_signals(1)
    if sigs:
        last = sigs[0]
        text = (
            "🔔 Сигнали\n\n"
            "Останній сигнал:\n\n"
            f"{signal_line(last)}"
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
    await message.answer(f"✅ Ціль оновлена: {value:,.2f} USDT", reply_markup=main_menu())
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
    await message.answer(f"✅ Щомісячне поповнення оновлено: {value:,.2f} USDT", reply_markup=main_menu())
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
    await message.answer(f"✅ Частота перевірки оновлена: {minutes} хв", reply_markup=main_menu())
    await state.clear()


@router.callback_query(F.data == "settings:commission")
async def settings_commission(callback: CallbackQuery, state: FSMContext):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    current = settings_service.get_settings().get("commission_percent", 0.1)
    await callback.message.answer(
        f"Поточна комісія: {current:g}%\n\n"
        "Введи новий відсоток комісії біржі.\n"
        "Наприклад: 0.1 для Binance 0.1%.",
        reply_markup=cancel_kb(),
    )
    await state.set_state(SettingsStates.waiting_commission_percent)
    await callback.answer()


@router.message(SettingsStates.waiting_commission_percent)
async def settings_commission_value(message: Message, state: FSMContext):
    try:
        value = float(message.text.replace(",", "."))
        if value < 0 or value > 10:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи коректний відсоток від 0 до 10.")
        return
    settings_service.update_commission_percent(value)
    await message.answer(f"✅ Комісію оновлено: {value:g}%", reply_markup=main_menu())
    await state.clear()


@router.callback_query(F.data == "settings:commission_backfill")
async def settings_commission_backfill(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return

    settings = settings_service.get_settings()
    commission_percent = settings.get("commission_percent", 0.1)
    result = apply_commission_to_zero_fee_transactions(commission_percent)
    portfolio_service.rebuild_portfolio_from_transactions()
    buyback_service.sync_cycles_from_active_transactions()

    symbol = settings_service.get_symbol()
    try:
        price = await binance_service.get_price(symbol)
        metrics = portfolio_service.calculate_portfolio_metrics(price)
        sheets_service.update_dashboard(metrics, settings_service.get_settings())
    except Exception:
        pass

    await callback.message.answer(
        "✅ Старі угоди перераховано з комісією.\n\n"
        f"Комісія: {commission_percent:g}%\n"
        f"BUY угод оновлено: {result['buy']}\n"
        f"SELL угод оновлено: {result['sell']}\n"
        f"Всього: {result['total']}",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "settings:strategy")
async def settings_strategy(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return
    settings = settings_service.get_settings()
    await callback.message.answer(
        "Обери активну стратегію:",
        reply_markup=strategy_select_kb(list_strategies(), settings.get("active_strategy", "accumulation")),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("strategy:set:"))
async def settings_strategy_set(callback: CallbackQuery):
    if not owner_service.is_owner(callback.from_user.id):
        await callback.answer(ACCESS_DENIED)
        return

    strategy_name = callback.data.split(":", 2)[2]
    strategy = get_strategy(strategy_name)
    old_strategy_name = settings_service.get_settings().get("active_strategy", "accumulation")
    settings_service.update_active_strategy(strategy.name)
    signal_service.ensure_default_triggers(strategy)

    if old_strategy_name != strategy.name:
        buyback_service.close_cycles_for_strategy(old_strategy_name)

    await callback.message.edit_text(
        f"✅ Активну стратегію змінено:\n{strategy.title}",
        reply_markup=back_kb("settings:back"),
    )
    await callback.answer()


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
    if symbol == old_symbol:
        await message.answer(
            f"✅ Символ уже встановлено: {symbol}\n\n"
            "Портфель не змінювався.",
            reply_markup=main_menu(),
        )
        await state.clear()
        return

    settings_service.update_symbol(symbol)
    portfolio_service.reset_portfolio()
    for strategy in list_strategies():
        signal_service.reset_buy_entry_triggers(strategy.name)
        buyback_service.close_cycles_for_strategy(strategy.name)

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


@router.message()
async def fallback_owner_message(message: Message):
    if not owner_service.is_owner(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    await message.answer(
        "   .        /menu.",
        reply_markup=main_menu(),
    )

