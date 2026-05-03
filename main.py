import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database.db import init_db
from bot.handlers import router
from scheduler.watcher import run_watcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    init_db()
    logger.info("Database initialized.")

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    watcher_task = asyncio.create_task(run_watcher(bot))
    logger.info("Scheduler started.")

    try:
        logger.info("Starting polling...")
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
