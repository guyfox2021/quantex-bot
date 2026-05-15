import asyncio
import logging
from pathlib import Path

from aiohttp import web

import config
from database.db import init_db
from services.dashboard_service import build_dashboard_payload

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static" / "dashboard"
TEMPLATE_PATH = BASE_DIR / "templates" / "dashboard.html"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _token_ok(request: web.Request) -> bool:
    token = config.DASHBOARD_TOKEN
    if not token:
        return False
    return request.query.get("token") == token


async def dashboard_page(request: web.Request) -> web.Response:
    if not _token_ok(request):
        raise web.HTTPForbidden(text="Forbidden")
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    return web.Response(text=html, content_type="text/html")


async def dashboard_data(request: web.Request) -> web.Response:
    if not _token_ok(request):
        raise web.HTTPForbidden(text="Forbidden")
    payload = await build_dashboard_payload()
    return web.json_response(payload)


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


def create_app() -> web.Application:
    init_db()
    app = web.Application()
    app.router.add_get("/", dashboard_page)
    app.router.add_get("/dashboard", dashboard_page)
    app.router.add_get("/api/dashboard", dashboard_data)
    app.router.add_get("/health", health)
    app.router.add_static("/static/dashboard", STATIC_DIR, name="dashboard_static")
    return app


async def main() -> None:
    if not config.DASHBOARD_TOKEN:
        raise RuntimeError("DASHBOARD_TOKEN is not set")
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.DASHBOARD_HOST, config.DASHBOARD_PORT)
    await site.start()
    logger.info("Dashboard started on %s:%s", config.DASHBOARD_HOST, config.DASHBOARD_PORT)
    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
