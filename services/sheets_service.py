import logging
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)

_client = None
_sheet = None


def _get_sheet():
    global _client, _sheet
    if not config.GOOGLE_SHEETS_ENABLED:
        return None
    if _sheet is not None:
        return _sheet
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
        _client = gspread.authorize(creds)
        _sheet = _client.open_by_key(config.GOOGLE_SHEET_ID)
        return _sheet
    except Exception as e:
        logger.error(f"Google Sheets init error: {e}")
        return None


def _get_or_create_worksheet(sheet, title: str, rows: int = 1000, cols: int = 20):
    try:
        return sheet.worksheet(title)
    except Exception:
        return sheet.add_worksheet(title=title, rows=rows, cols=cols)


def update_dashboard(metrics: dict, settings: dict) -> None:
    if not config.GOOGLE_SHEETS_ENABLED:
        return
    try:
        sheet = _get_sheet()
        if not sheet:
            return
        ws = _get_or_create_worksheet(sheet, "Dashboard")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        data = [
            ["Поточна ціна BTC", metrics.get("current_price", 0)],
            ["BTC amount", metrics.get("btc_amount", 0)],
            ["USDT reserve", metrics.get("usdt_reserve", 0)],
            ["BTC value", metrics.get("btc_value", 0)],
            ["Portfolio value", metrics.get("portfolio_value", 0)],
            ["Total deposited", metrics.get("total_deposited", 0)],
            ["Total PnL", metrics.get("total_pnl", 0)],
            ["PnL %", metrics.get("total_pnl_percent", 0)],
            ["Realized PnL", metrics.get("realized_pnl", 0)],
            ["Unrealized PnL", metrics.get("unrealized_pnl", 0)],
            ["Avg price", metrics.get("avg_price", 0)],
            ["Active strategy", settings.get("active_strategy", "accumulation")],
            ["Target value", settings.get("target_value", 5000)],
            ["Progress %", (metrics.get("portfolio_value", 0) / settings.get("target_value", 1) * 100) if settings.get("target_value") else 0],
            ["Updated at", now],
        ]
        ws.clear()
        ws.update("A1", data)
    except Exception as e:
        logger.error(f"Google Sheets dashboard update error: {e}")


def append_snapshot(metrics: dict, settings: dict) -> None:
    if not config.GOOGLE_SHEETS_ENABLED:
        return
    try:
        sheet = _get_sheet()
        if not sheet:
            return
        ws = _get_or_create_worksheet(sheet, "Portfolio")
        headers = [
            "date", "btc_price", "btc_amount", "usdt_reserve", "btc_value",
            "portfolio_value", "total_deposited", "avg_price", "realized_pnl",
            "unrealized_pnl", "total_pnl", "total_pnl_percent", "active_strategy",
        ]
        if ws.row_count < 2 or not ws.row_values(1):
            ws.append_row(headers)
        row = [
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            metrics.get("current_price", 0),
            metrics.get("btc_amount", 0),
            metrics.get("usdt_reserve", 0),
            metrics.get("btc_value", 0),
            metrics.get("portfolio_value", 0),
            metrics.get("total_deposited", 0),
            metrics.get("avg_price", 0),
            metrics.get("realized_pnl", 0),
            metrics.get("unrealized_pnl", 0),
            metrics.get("total_pnl", 0),
            metrics.get("total_pnl_percent", 0),
            settings.get("active_strategy", "accumulation"),
        ]
        ws.append_row(row)
    except Exception as e:
        logger.error(f"Google Sheets snapshot error: {e}")


def append_transaction(tx: dict) -> None:
    if not config.GOOGLE_SHEETS_ENABLED:
        return
    try:
        sheet = _get_sheet()
        if not sheet:
            return
        ws = _get_or_create_worksheet(sheet, "Transactions")
        headers = ["date", "type", "strategy", "symbol", "price", "usdt_amount", "btc_amount", "fee", "note"]
        if ws.row_count < 2 or not ws.row_values(1):
            ws.append_row(headers)
        ws.append_row([
            tx.get("created_at", ""),
            tx.get("type", ""),
            tx.get("strategy_name", ""),
            tx.get("symbol", "BTCUSDT"),
            tx.get("price", 0),
            tx.get("usdt_amount", 0),
            tx.get("btc_amount", 0),
            tx.get("fee", 0),
            tx.get("note", ""),
        ])
    except Exception as e:
        logger.error(f"Google Sheets transaction error: {e}")


def append_signal(signal_data: dict) -> None:
    if not config.GOOGLE_SHEETS_ENABLED:
        return
    try:
        sheet = _get_sheet()
        if not sheet:
            return
        ws = _get_or_create_worksheet(sheet, "Signals")
        headers = [
            "date", "signal_type", "strategy", "price", "reason",
            "recommended_action", "amount_usdt", "amount_btc_percent", "status",
        ]
        if ws.row_count < 2 or not ws.row_values(1):
            ws.append_row(headers)
        ws.append_row([
            signal_data.get("created_at", ""),
            signal_data.get("signal_type", ""),
            signal_data.get("strategy_name", ""),
            signal_data.get("price", 0),
            signal_data.get("reason", ""),
            signal_data.get("recommended_action", ""),
            signal_data.get("amount_usdt", 0),
            signal_data.get("amount_btc_percent", 0),
            signal_data.get("status", "NEW"),
        ])
    except Exception as e:
        logger.error(f"Google Sheets signal error: {e}")
