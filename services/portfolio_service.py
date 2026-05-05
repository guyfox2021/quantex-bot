from datetime import datetime, timezone
from database.db import get_connection
from services.transaction_service import add_transaction
from services.settings_service import get_symbol


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_portfolio() -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM portfolio ORDER BY id LIMIT 1").fetchone()
        if row:
            return dict(row)
        return {}


def create_default_portfolio_if_needed() -> None:
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM portfolio LIMIT 1").fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO portfolio
                   (btc_amount, usdt_reserve, total_btc_cost, avg_price, last_high,
                    total_deposited, realized_pnl, is_initialized, updated_at)
                   VALUES (0, 0, 0, 0, 0, 0, 0, 0, ?)""",
                (_now(),),
            )
            conn.commit()


def update_last_high(current_price: float) -> bool:
    portfolio = get_portfolio()
    if not portfolio:
        return False
    if current_price > portfolio.get("last_high", 0):
        with get_connection() as conn:
            conn.execute(
                "UPDATE portfolio SET last_high = ?, updated_at = ? WHERE id = ?",
                (current_price, _now(), portfolio["id"]),
            )
            conn.commit()
        return True
    return False


def calculate_portfolio_metrics(current_price: float) -> dict:
    portfolio = get_portfolio()
    if not portfolio:
        return {}

    btc_amount = portfolio.get("btc_amount", 0.0)
    usdt_reserve = portfolio.get("usdt_reserve", 0.0)
    total_btc_cost = portfolio.get("total_btc_cost", 0.0)
    total_deposited = portfolio.get("total_deposited", 0.0)
    realized_pnl = portfolio.get("realized_pnl", 0.0)

    btc_value = btc_amount * current_price
    portfolio_value = btc_value + usdt_reserve
    unrealized_pnl = btc_value - total_btc_cost
    total_pnl = portfolio_value - total_deposited
    total_pnl_percent = (total_pnl / total_deposited * 100) if total_deposited > 0 else 0.0

    return {
        **portfolio,
        "current_price": current_price,
        "btc_value": btc_value,
        "portfolio_value": portfolio_value,
        "unrealized_pnl": unrealized_pnl,
        "total_pnl": total_pnl,
        "total_pnl_percent": total_pnl_percent,
        "realized_pnl": realized_pnl,
    }


def initialize_portfolio(start_capital: float, buy_price: float) -> dict:
    """70% капіталу — купівля монети (точка відліку), 30% — резерв для докупівель."""
    symbol = get_symbol()
    buy_amount = start_capital * 0.70
    reserve_amount = start_capital * 0.30
    btc_bought = buy_amount / buy_price if buy_price > 0 else 0.0

    with get_connection() as conn:
        conn.execute(
            """UPDATE portfolio SET
               btc_amount = ?,
               usdt_reserve = ?,
               total_btc_cost = ?,
               avg_price = ?,
               last_high = ?,
               total_deposited = ?,
               realized_pnl = 0,
               is_initialized = 1,
               updated_at = ?
               WHERE id = (SELECT id FROM portfolio LIMIT 1)""",
            (btc_bought, reserve_amount, buy_amount, buy_price, buy_price, start_capital, _now()),
        )
        conn.commit()

    coin = _base_coin(symbol)
    add_transaction("INITIAL_DEPOSIT", 0, start_capital, 0, note="Стартовий капітал", symbol=symbol)
    add_transaction("BUY", buy_price, buy_amount, btc_bought, note=f"Початкова покупка {coin}", symbol=symbol)
    add_transaction("RESERVE_ADD", 0, reserve_amount, 0, note="Стартовий резерв (30%)", symbol=symbol)

    return get_portfolio()


def apply_buy(
    usdt_amount: float,
    price: float,
    tx_type: str,
    note: str = "",
    spend_from_reserve: bool = False,
) -> dict:
    symbol = get_symbol()
    portfolio = get_portfolio()
    if not portfolio:
        return {}

    btc_bought = usdt_amount / price if price > 0 else 0.0
    btc_amount_new = portfolio.get("btc_amount", 0.0) + btc_bought
    total_btc_cost_new = portfolio.get("total_btc_cost", 0.0) + usdt_amount
    avg_price_new = total_btc_cost_new / btc_amount_new if btc_amount_new > 0 else 0.0
    usdt_reserve_new = portfolio.get("usdt_reserve", 0.0)
    if spend_from_reserve:
        if usdt_amount > usdt_reserve_new:
            raise ValueError("Недостатньо USDT у резерві для покупки.")
        usdt_reserve_new -= usdt_amount

    new_last_high = max(portfolio.get("last_high", 0.0), price)

    with get_connection() as conn:
        conn.execute(
            """UPDATE portfolio SET
               btc_amount = ?,
               usdt_reserve = ?,
               total_btc_cost = ?,
               avg_price = ?,
               last_high = ?,
               updated_at = ?
               WHERE id = ?""",
            (btc_amount_new, usdt_reserve_new, total_btc_cost_new, avg_price_new,
             new_last_high, _now(), portfolio["id"]),
        )
        conn.commit()

    add_transaction(tx_type, price, usdt_amount, btc_bought, note=note, symbol=symbol)
    return get_portfolio()


def apply_sell(sell_percent: float, price: float, tx_type: str, note: str = "") -> dict:
    symbol = get_symbol()
    portfolio = get_portfolio()
    if not portfolio:
        return {}

    btc_amount = portfolio.get("btc_amount", 0.0)
    total_btc_cost = portfolio.get("total_btc_cost", 0.0)
    realized_pnl = portfolio.get("realized_pnl", 0.0)
    usdt_reserve = portfolio.get("usdt_reserve", 0.0)

    btc_sold = btc_amount * sell_percent / 100
    usdt_received = btc_sold * price
    cost_removed = total_btc_cost * sell_percent / 100
    realized_pnl_add = usdt_received - cost_removed

    btc_amount_new = btc_amount - btc_sold
    usdt_reserve_new = usdt_reserve + usdt_received
    total_btc_cost_new = total_btc_cost - cost_removed
    realized_pnl_new = realized_pnl + realized_pnl_add
    avg_price_new = total_btc_cost_new / btc_amount_new if btc_amount_new > 0 else 0.0

    with get_connection() as conn:
        conn.execute(
            """UPDATE portfolio SET
               btc_amount = ?,
               usdt_reserve = ?,
               total_btc_cost = ?,
               avg_price = ?,
               realized_pnl = ?,
               updated_at = ?
               WHERE id = ?""",
            (btc_amount_new, usdt_reserve_new, total_btc_cost_new, avg_price_new,
             realized_pnl_new, _now(), portfolio["id"]),
        )
        conn.commit()

    add_transaction(tx_type, price, usdt_received, btc_sold, note=note, symbol=symbol)
    return get_portfolio()


def add_reserve(usdt_amount: float, tx_type: str, note: str = "") -> dict:
    symbol = get_symbol()
    portfolio = get_portfolio()
    if not portfolio:
        return {}

    usdt_reserve_new = portfolio.get("usdt_reserve", 0.0) + usdt_amount

    with get_connection() as conn:
        conn.execute(
            "UPDATE portfolio SET usdt_reserve = ?, updated_at = ? WHERE id = ?",
            (usdt_reserve_new, _now(), portfolio["id"]),
        )
        conn.commit()

    add_transaction(tx_type, 0, usdt_amount, 0, note=note, symbol=symbol)
    return get_portfolio()


def add_deposit(usdt_amount: float) -> None:
    portfolio = get_portfolio()
    if not portfolio:
        return
    total_deposited_new = portfolio.get("total_deposited", 0.0) + usdt_amount
    with get_connection() as conn:
        conn.execute(
            "UPDATE portfolio SET total_deposited = ?, updated_at = ? WHERE id = ?",
            (total_deposited_new, _now(), portfolio["id"]),
        )
        conn.commit()


def reset_portfolio() -> None:
    """Reset portfolio to zero when switching coins."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE portfolio SET
               btc_amount = 0, usdt_reserve = 0, total_btc_cost = 0, avg_price = 0,
               last_high = 0, total_deposited = 0, realized_pnl = 0,
               is_initialized = 0, updated_at = ?
               WHERE id = (SELECT id FROM portfolio LIMIT 1)""",
            (_now(),),
        )
        conn.commit()


def _base_coin(symbol: str) -> str:
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
        if symbol.upper().endswith(quote):
            return symbol.upper()[: -len(quote)]
    return symbol.upper()
