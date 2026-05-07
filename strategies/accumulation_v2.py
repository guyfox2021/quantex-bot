from strategies.base import BaseStrategy, StrategySignal
from utils.calculations import calculate_drawdown, calculate_profit_percent
from utils.formatters import fmt_signal_amount


class AccumulationV2Strategy(BaseStrategy):
    name = "accumulation_v2"
    title = "Моє накопичення позиції v2"
    description = (
        "Активне накопичення BTC з фіксацією прибутку, викупом після відкату "
        "та докупками від поточного USDT-резерву."
    )

    SELL_LEVELS = [
        {"level": 3.0, "btc_percent": 10.0},
        {"level": 5.0, "btc_percent": 15.0},
        {"level": 10.0, "btc_percent": 25.0},
    ]
    BUYBACK_LEVELS = [
        {"level": 2.0, "portion": 0.50},
        {"level": 4.0, "portion": 1.00},
    ]
    BUY_DIP_LEVELS = [
        {"level": 3.0, "reserve_percent": 15.0},
        {"level": 5.0, "reserve_percent": 25.0},
        {"level": 10.0, "reserve_percent": 40.0},
    ]
    MIN_BUY_USDT = 10.0

    def check(self, portfolio: dict, market_data: dict, settings: dict, triggers: list) -> StrategySignal:
        current_price = market_data.get("price", 0.0)
        avg_price = portfolio.get("avg_price", 0.0)
        last_high = portfolio.get("last_high", 0.0)
        btc_amount = portfolio.get("btc_amount", 0.0)
        usdt_reserve = portfolio.get("usdt_reserve", 0.0)
        open_buybacks = market_data.get("open_buybacks", [])

        triggered_map = {
            (t["trigger_type"], t["level_percent"]): t["is_triggered"]
            for t in triggers
        }

        buyback_signal = self._check_buyback(open_buybacks, current_price, usdt_reserve)
        if buyback_signal:
            return buyback_signal

        has_open_buyback = bool(open_buybacks)

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

        if has_open_buyback:
            return self._hold("Є відкритий BUYBACK cycle. BUY_DIP заблоковано до його закриття.")

        if last_high > 0 and btc_amount > 0:
            drawdown = calculate_drawdown(last_high, current_price)
            for lvl in sorted(self.BUY_DIP_LEVELS, key=lambda x: x["level"], reverse=True):
                level = lvl["level"]
                reserve_percent = lvl["reserve_percent"]
                already_triggered = triggered_map.get(("BUY_DIP", float(level)), 0)
                amount = usdt_reserve * reserve_percent / 100
                if drawdown >= level and not already_triggered:
                    if amount < self.MIN_BUY_USDT:
                        return self._hold(f"Сума докупки {amount:.2f} USDT менша за мінімум {self.MIN_BUY_USDT:.2f} USDT.")
                    return StrategySignal(
                        signal_type="BUY",
                        strategy_name=self.name,
                        reason=f"BTC впав на -{drawdown:.2f}% від локального максимуму.",
                        recommended_action=f"Купити BTC на {fmt_signal_amount(amount)} USDT.",
                        amount_usdt=amount,
                        trigger_type="BUY_DIP",
                        level_percent=level,
                    )

        return self._hold("Умови для BUYBACK, SELL або BUY DIP не виконані.")

    def _check_buyback(self, open_buybacks: list[dict], current_price: float, usdt_reserve: float) -> StrategySignal | None:
        for cycle in open_buybacks:
            sell_price = cycle.get("sell_price", 0.0)
            if sell_price <= 0:
                continue
            drop = (sell_price - current_price) / sell_price * 100
            for lvl in sorted(self.BUYBACK_LEVELS, key=lambda x: x["level"], reverse=True):
                level = lvl["level"]
                done_key = "level_4_done" if level >= 4.0 else "level_2_done"
                if cycle.get(done_key, 0):
                    continue
                if drop < level:
                    continue

                if level >= 4.0:
                    btc_to_buy = cycle.get("remaining_btc", 0.0)
                else:
                    btc_to_buy = min(cycle.get("btc_sold", 0.0) * lvl["portion"], cycle.get("remaining_btc", 0.0))
                amount = btc_to_buy * current_price
                if amount < self.MIN_BUY_USDT:
                    return self._hold(f"BUYBACK #{cycle.get('id')} менший за мінімум {self.MIN_BUY_USDT:.2f} USDT.")
                if amount > usdt_reserve:
                    return self._hold(f"Недостатньо USDT у резерві для BUYBACK #{cycle.get('id')}: потрібно {amount:.2f} USDT.")

                return StrategySignal(
                    signal_type="BUY",
                    strategy_name=self.name,
                    reason=f"BTC відкотився після продажу на -{drop:.2f}%.",
                    recommended_action=f"Викупити BTC на {fmt_signal_amount(amount)} USDT.",
                    amount_usdt=amount,
                    trigger_type="BUYBACK",
                    level_percent=level,
                    buyback_cycle_id=cycle.get("id"),
                )
        return None

    def _hold(self, reason: str) -> StrategySignal:
        return StrategySignal(
            signal_type="HOLD",
            strategy_name=self.name,
            reason=reason,
            recommended_action="Тримати поточну позицію.",
        )

    def get_default_triggers(self) -> list[dict]:
        triggers = []
        for lvl in self.SELL_LEVELS:
            triggers.append({
                "strategy_name": self.name,
                "trigger_type": "SELL_PROFIT",
                "level_percent": lvl["level"],
                "is_triggered": 0,
            })
        for lvl in self.BUY_DIP_LEVELS:
            triggers.append({
                "strategy_name": self.name,
                "trigger_type": "BUY_DIP",
                "level_percent": lvl["level"],
                "is_triggered": 0,
            })
        return triggers

    def get_parameters_text(self) -> str:
        return (
            "Параметри v2:\n"
            "SELL_PROFIT:\n"
            "+3%  -> продати 10% BTC\n"
            "+5%  -> продати 15% BTC\n"
            "+10% -> продати 25% BTC\n\n"
            "BUYBACK після SELL:\n"
            "-2% від ціни продажу -> викупити 50% проданого BTC\n"
            "-4% від ціни продажу -> викупити решту\n\n"
            "BUY DIP від локального максимуму:\n"
            "-3%  -> купити на 15% USDT-резерву\n"
            "-5%  -> купити на 25% USDT-резерву\n"
            "-10% -> купити на 40% USDT-резерву\n"
            "BUY_DIP блокується, доки відкритий BUYBACK cycle.\n\n"
            "BUY cooldown: мінімум 6 годин між BUY-сигналами.\n\n"
            "Пріоритет сигналів: BUYBACK -> SELL_PROFIT -> BUY_DIP -> HOLD"
        )

    def calc_monthly_deposit_split(self, monthly_amount: float, avg_price: float, current_price: float) -> dict:
        if avg_price > 0 and current_price > avg_price * 1.05:
            btc_pct = 0.50
        else:
            btc_pct = 0.70
        btc_buy = monthly_amount * btc_pct
        reserve = monthly_amount - btc_buy
        return {"btc_buy": btc_buy, "reserve": reserve, "btc_pct": btc_pct * 100}

    def calc_extra_deposit_split(self, extra_amount: float, avg_price: float, current_price: float) -> dict:
        return self.calc_monthly_deposit_split(extra_amount, avg_price, current_price)
