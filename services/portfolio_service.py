from datetime import datetime, timezone
from database.db import get_connection
from services.transaction_service import add_transaction, get_active_transactions
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
    fee: float = 0.0,
    fee_asset: str = "USDT",
) -> dict:
    symbol = get_symbol()
    coin = _base_coin(symbol)
    fee_asset = (fee_asset or "USDT").upper()
    portfolio = get_portfolio()
    if not portfolio:
        return {}

    gross_btc_bought = usdt_amount / price if price > 0 else 0.0
    btc_fee = fee if fee_asset == coin else 0.0
    usdt_fee = fee if fee_asset == "USDT" else 0.0
    if btc_fee > gross_btc_bought:
        raise ValueError(f"Комісія не може бути більшою за куплену кількість {coin}.")
    btc_bought = gross_btc_bought - btc_fee
    btc_amount_new = portfolio.get("btc_amount", 0.0) + btc_bought
    total_btc_cost_new = portfolio.get("total_btc_cost", 0.0) + usdt_amount + usdt_fee
    avg_price_new = total_btc_cost_new / btc_amount_new if btc_amount_new > 0 else 0.0
    usdt_reserve_new = portfolio.get("usdt_reserve", 0.0)
    if spend_from_reserve:
        reserve_spend = usdt_amount + usdt_fee
        if reserve_spend > usdt_reserve_new:
            raise ValueError("Недостатньо USDT у резерві для покупки.")
        usdt_reserve_new -= reserve_spend

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

    add_transaction(tx_type, price, usdt_amount, btc_bought, fee=fee, fee_asset=fee_asset, note=note, symbol=symbol)
    return get_portfolio()


def apply_sell(
    sell_percent: float,
    price: float,
    tx_type: str,
    note: str = "",
    fee: float = 0.0,
    fee_asset: str = "USDT",
) -> dict:
    symbol = get_symbol()
    coin = _base_coin(symbol)
    fee_asset = (fee_asset or "USDT").upper()
    portfolio = get_portfolio()
    if not portfolio:
        return {}

    btc_amount = portfolio.get("btc_amount", 0.0)
    total_btc_cost = portfolio.get("total_btc_cost", 0.0)
    realized_pnl = portfolio.get("realized_pnl", 0.0)
    usdt_reserve = portfolio.get("usdt_reserve", 0.0)

    btc_sold = btc_amount * sell_percent / 100
    usdt_received = btc_sold * price
    usdt_fee = fee if fee_asset == "USDT" else 0.0
    btc_fee = fee if fee_asset == coin else 0.0
    if usdt_fee > usdt_received:
        raise ValueError("Комісія не може бути більшою за суму продажу.")
    if btc_sold + btc_fee > btc_amount:
        raise ValueError(f"Комісія не може бути більшою за доступний залишок {coin}.")
    total_btc_removed = btc_sold + btc_fee
    cost_removed = total_btc_cost * (total_btc_removed / btc_amount) if btc_amount > 0 else 0.0
    realized_pnl_add = usdt_received - usdt_fee - cost_removed

    btc_amount_new = btc_amount - total_btc_removed
    usdt_reserve_new = usdt_reserve + usdt_received - usdt_fee
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

    add_transaction(tx_type, price, usdt_received, total_btc_removed, fee=fee, fee_asset=fee_asset, note=note, symbol=symbol)
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


def rebuild_portfolio_from_transactions(preserve_last_high: bool = False) -> dict:
    portfolio_before = get_portfolio()
    preserved_last_high = portfolio_before.get("last_high", 0.0) if preserve_last_high else 0.0
    transactions = get_active_transactions()

    state = {
        "btc_amount": 0.0,
        "usdt_reserve": 0.0,
        "total_btc_cost": 0.0,
        "avg_price": 0.0,
        "last_high": 0.0,
        "total_deposited": 0.0,
        "realized_pnl": 0.0,
        "is_initialized": 0,
    }

    for tx in transactions:
        _apply_transaction_to_state(state, tx)

    state["avg_price"] = (
        state["total_btc_cost"] / state["btc_amount"] if state["btc_amount"] > 0 else 0.0
    )
    state["last_high"] = max(state["last_high"], preserved_last_high)
    state["is_initialized"] = 1 if (state["btc_amount"] > 0 or state["usdt_reserve"] > 0 or state["total_deposited"] > 0) else 0

    with get_connection() as conn:
        conn.execute(
            """UPDATE portfolio SET
               btc_amount = ?,
               usdt_reserve = ?,
               total_btc_cost = ?,
               avg_price = ?,
               last_high = ?,
               total_deposited = ?,
               realized_pnl = ?,
               is_initialized = ?,
               updated_at = ?
               WHERE id = (SELECT id FROM portfolio LIMIT 1)""",
            (
                state["btc_amount"],
                state["usdt_reserve"],
                state["total_btc_cost"],
                state["avg_price"],
                state["last_high"],
                state["total_deposited"],
                state["realized_pnl"],
                state["is_initialized"],
                _now(),
            ),
        )
        conn.commit()

    return get_portfolio()


def _apply_transaction_to_state(state: dict, tx: dict) -> None:
    tx_type = tx.get("type", "")
    usdt_amount = float(tx.get("usdt_amount", 0.0) or 0.0)
    btc_amount = float(tx.get("btc_amount", 0.0) or 0.0)
    price = float(tx.get("price", 0.0) or 0.0)
    fee = float(tx.get("fee", 0.0) or 0.0)
    fee_asset = (tx.get("fee_asset", "USDT") or "USDT").upper()
    symbol = tx.get("symbol", get_symbol()) or get_symbol()
    coin = _base_coin(symbol)
    usdt_fee = fee if fee_asset == "USDT" else 0.0
    note = tx.get("note", "") or ""

    if tx_type == "INITIAL_DEPOSIT":
        state["total_deposited"] += usdt_amount
        return

    if tx_type == "RESERVE_ADD":
        state["usdt_reserve"] += usdt_amount
        if "Щомісячне поповнення" in note or "Додаткове поповнення" in note:
            state["total_deposited"] += usdt_amount
        return

    if tx_type in ("BUY", "MANUAL_BUY", "MONTHLY_DEPOSIT", "EXTRA_DEPOSIT"):
        if btc_amount > 0 and price > 0:
            if tx_type == "BUY" and "Покупка за сигналом" in note:
                state["usdt_reserve"] = max(state["usdt_reserve"] - usdt_amount - usdt_fee, 0.0)
            elif tx_type in ("MANUAL_BUY", "MONTHLY_DEPOSIT", "EXTRA_DEPOSIT"):
                state["total_deposited"] += usdt_amount + usdt_fee

            state["btc_amount"] += btc_amount
            state["total_btc_cost"] += usdt_amount + usdt_fee
            state["avg_price"] = state["total_btc_cost"] / state["btc_amount"] if state["btc_amount"] > 0 else 0.0
            state["last_high"] = max(state["last_high"], price)
            return

        if tx_type == "MONTHLY_DEPOSIT" and btc_amount == 0:
            state["usdt_reserve"] += usdt_amount
            state["total_deposited"] += usdt_amount
            return

    if tx_type in ("SELL", "MANUAL_SELL"):
        if btc_amount <= 0 or state["btc_amount"] <= 0:
            return
        btc_sold = min(btc_amount, state["btc_amount"])
        avg_cost_per_btc = state["total_btc_cost"] / state["btc_amount"] if state["btc_amount"] > 0 else 0.0
        cost_removed = avg_cost_per_btc * btc_sold
        state["btc_amount"] -= btc_sold
        state["usdt_reserve"] += usdt_amount - usdt_fee
        state["total_btc_cost"] = max(state["total_btc_cost"] - cost_removed, 0.0)
        state["realized_pnl"] += usdt_amount - usdt_fee - cost_removed
        state["avg_price"] = state["total_btc_cost"] / state["btc_amount"] if state["btc_amount"] > 0 else 0.0
        return


def _base_coin(symbol: str) -> str:
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
        if symbol.upper().endswith(quote):
            return symbol.upper()[: -len(quote)]
    return symbol.upper()
