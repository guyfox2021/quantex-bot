import asyncio
import logging

from aiogram import Bot

import config
from services import binance_service, portfolio_service, settings_service, signal_service, sheets_service, buyback_service
from strategies.registry import get_strategy
from bot.messages import signal_message
from bot.keyboards import signal_confirm_kb

logger = logging.getLogger(__name__)


async def run_watcher(bot: Bot):
    while True:
        try:
            settings = settings_service.get_settings()
            interval = settings.get("check_interval_minutes", config.CHECK_INTERVAL_MINUTES)
            await asyncio.sleep(interval * 60)

            settings = settings_service.get_settings()
            if not settings.get("signals_enabled", 1):
                continue

            portfolio = portfolio_service.get_portfolio()
            if not portfolio.get("is_initialized", 0):
                continue

            symbol = settings.get("symbol", "BTCUSDT")
            try:
                price = await binance_service.get_price(symbol)
            except Exception as e:
                logger.warning(f"Watcher: failed to get BTC price: {e}")
                continue

            updated = portfolio_service.update_last_high(price)
            active_strategy_name = settings.get("active_strategy", "accumulation")
            strategy = get_strategy(active_strategy_name)

            if updated:
                signal_service.reset_buy_entry_triggers(strategy.name)

            open_buybacks = buyback_service.get_open_cycles(strategy.name)
            signal_service.refresh_ignored_signal_locks(strategy.name, price, portfolio, open_buybacks)
            triggers = signal_service.get_triggers(strategy.name)
            market_data = {
                "price": price,
                "open_buybacks": open_buybacks,
            }
            signal = strategy.check(portfolio, market_data, settings, triggers)

            if signal.signal_type not in ("BUY", "SELL"):
                continue

            if signal.signal_type == "BUY" and not signal_service.can_send_buy_signal(cooldown_hours=6):
                logger.info("Watcher: BUY signal skipped because cooldown is active.")
                continue

            if signal.trigger_type and signal.level_percent is not None:
                if signal_service.has_active_signal_for_trigger(strategy.name, signal.trigger_type, signal.level_percent):
                    continue

            if signal.trigger_type:
                already = any(
                    t["trigger_type"] == signal.trigger_type
                    and t["level_percent"] == signal.level_percent
                    and t["is_triggered"]
                    for t in triggers
                )
                if already:
                    continue

            sig_id = signal_service.save_signal(signal, price, status="SENT")
            if signal.trigger_type:
                signal_service.mark_triggered(strategy.name, signal.trigger_type, signal.level_percent)

            text = signal_message(signal, symbol, price, portfolio)
            kb = signal_confirm_kb(sig_id, signal.signal_type)

            try:
                await bot.send_message(config.OWNER_TELEGRAM_ID, text, reply_markup=kb)
            except Exception as e:
                logger.error(f"Watcher: failed to send signal to owner: {e}")

            try:
                from datetime import datetime, timezone
                from database.db import get_connection
                now = datetime.now(timezone.utc).isoformat()
                metrics = portfolio_service.calculate_portfolio_metrics(price)
                sheets_service.update_dashboard(metrics, settings)
            except Exception as e:
                logger.error(f"Watcher: sheets update error: {e}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Watcher error: {e}")
            await asyncio.sleep(60)
