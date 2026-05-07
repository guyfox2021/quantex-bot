from strategies.base import BaseStrategy, StrategySignal
from utils.calculations import calculate_drawdown, calculate_profit_percent
from utils.formatters import fmt_signal_amount


class AccumulationStrategy(BaseStrategy):
    name = "accumulation"
    title = "Моє накопичення позиції"
    description = (
        "Поступове накопичення BTC з USDT-резервом, докупками на просадках "
        "та частковою фіксацією прибутку на сильному рості."
    )

    BUY_LEVELS = [
        {"level": 5.0,  "amount_usdt": 50.0},
        {"level": 10.0, "amount_usdt": 75.0},
        {"level": 15.0, "amount_usdt": 100.0},
        {"level": 20.0, "amount_usdt": 150.0},
    ]

    SELL_LEVELS = [
        {"level": 15.0, "btc_percent": 10.0},
        {"level": 25.0, "btc_percent": 10.0},
        {"level": 40.0, "btc_percent": 15.0},
    ]

    def check(self, portfolio: dict, market_data: dict, settings: dict, triggers: list) -> StrategySignal:
        current_price = market_data.get("price", 0.0)
        avg_price = portfolio.get("avg_price", 0.0)
        last_high = portfolio.get("last_high", 0.0)
        btc_amount = portfolio.get("btc_amount", 0.0)
        usdt_reserve = portfolio.get("usdt_reserve", 0.0)

        triggered_map = {
            (t["trigger_type"], t["level_percent"]): t["is_triggered"]
            for t in triggers
        }

        if last_high > 0 and btc_amount > 0:
            drawdown = calculate_drawdown(last_high, current_price)
            for lvl in sorted(self.BUY_LEVELS, key=lambda x: x["level"], reverse=True):
                level = lvl["level"]
                amount = lvl["amount_usdt"]
                already_triggered = triggered_map.get(("BUY_DROP", float(level)), 0)
                if amount > usdt_reserve:
                    continue
                if drawdown >= level and not already_triggered:
                    return StrategySignal(
                        signal_type="BUY",
                        strategy_name=self.name,
                        reason=f"BTC впав на -{drawdown:.2f}% від локального максимуму.",
                        recommended_action=f"Купити BTC на {fmt_signal_amount(amount)} USDT.",
                        amount_usdt=amount,
                        trigger_type="BUY_DROP",
                        level_percent=level,
                    )

        if avg_price > 0 and btc_amount > 0:
            profit = calculate_profit_percent(current_price, avg_price)
            for lvl in sorted(self.SELL_LEVELS, key=lambda x: x["level"], reverse=True):
                level = lvl["level"]
                pct = lvl["btc_percent"]
                already_triggered = triggered_map.get(("SELL_PROFIT", float(level)), 0)
                if profit >= level and not already_triggered:
                    return StrategySignal(
                        signal_type="SELL",
                        strategy_name=self.name,
                        reason=f"BTC вище середньої ціни на +{profit:.2f}%.",
                        recommended_action=f"Продати {fmt_signal_amount(pct)}% BTC-позиції.",
                        amount_btc_percent=pct,
                        trigger_type="SELL_PROFIT",
                        level_percent=level,
                    )

        return StrategySignal(
            signal_type="HOLD",
            strategy_name=self.name,
            reason="Умови для покупки або продажу не виконані.",
            recommended_action="Тримати поточну позицію.",
        )

    def get_default_triggers(self) -> list[dict]:
        triggers = []
        for lvl in self.BUY_LEVELS:
            triggers.append({
                "strategy_name": self.name,
                "trigger_type": "BUY_DROP",
                "level_percent": lvl["level"],
                "is_triggered": 0,
            })
        for lvl in self.SELL_LEVELS:
            triggers.append({
                "strategy_name": self.name,
                "trigger_type": "SELL_PROFIT",
                "level_percent": lvl["level"],
                "is_triggered": 0,
            })
        return triggers

    def get_parameters_text(self) -> str:
        return (
            "Параметри:\n"
            "Старт: 70% BTC / 30% резерв\n"
            "Щомісячне поповнення: 70% BTC / 30% резерв\n\n"
            "Докупки:\n"
            "-5%  → 50 USDT\n"
            "-10% → 75 USDT\n"
            "-15% → 100 USDT\n"
            "-20% → 150 USDT\n\n"
            "Продажі:\n"
            "+15% → 10% BTC\n"
            "+25% → 10% BTC\n"
            "+40% → 15% BTC"
        )

    def calc_extra_deposit_split(self, extra_amount: float, avg_price: float, current_price: float) -> dict:
        if avg_price == 0:
            btc_pct = 0.70
        else:
            price_diff = (current_price - avg_price) / avg_price * 100
            if price_diff < 0:
                btc_pct = 0.80
            elif price_diff < 10:
                btc_pct = 0.60
            else:
                btc_pct = 0.30

        btc_buy = extra_amount * btc_pct
        reserve = extra_amount * (1 - btc_pct)
        return {"btc_buy": btc_buy, "reserve": reserve, "btc_pct": btc_pct * 100}
