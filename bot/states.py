from aiogram.fsm.state import State, StatesGroup


class InitPortfolio(StatesGroup):
    waiting_capital = State()
    waiting_custom_price = State()
    confirming = State()


class ManualBuy(StatesGroup):
    waiting_amount = State()
    waiting_custom_price = State()


class ManualSell(StatesGroup):
    waiting_percent = State()
    waiting_custom_price = State()


class MonthlyDeposit(StatesGroup):
    waiting_custom_price = State()


class ExtraDeposit(StatesGroup):
    waiting_amount = State()
    waiting_custom_price = State()


class EditTransaction(StatesGroup):
    waiting_price = State()
    waiting_usdt_amount = State()
    waiting_coin_amount = State()


class SettingsStates(StatesGroup):
    waiting_target_value = State()
    waiting_monthly_deposit = State()
    waiting_check_interval = State()
    waiting_commission_percent = State()
    waiting_symbol = State()


class SignalConfirm(StatesGroup):
    waiting_custom_price = State()
