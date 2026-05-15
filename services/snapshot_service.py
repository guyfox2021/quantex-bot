from datetime import datetime, timedelta, timezone

from database.db import get_connection
from services.transaction_service import get_active_transactions


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def save_snapshot(metrics: dict, settings: dict, min_interval_minutes: int = 60) -> bool:
    """Store a portfolio snapshot, throttled so charts stay readable."""
    now = _now_dt()
    with get_connection() as conn:
        last = conn.execute(
            "SELECT created_at FROM daily_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_dt = _parse_dt(last["created_at"]) if last else None
        if last_dt and now - last_dt < timedelta(minutes=min_interval_minutes):
            return False

        conn.execute(
            """INSERT INTO daily_snapshots
               (date, btc_price, btc_amount, usdt_reserve, btc_value,
                portfolio_value, total_deposited, avg_price, realized_pnl,
                unrealized_pnl, total_pnl, total_pnl_percent, active_strategy,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now.strftime("%Y-%m-%d %H:%M"),
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
                now.isoformat(),
            ),
        )
        conn.commit()
        return True


def get_snapshots(limit: int = 120) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM daily_snapshots
               ORDER BY id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def rebuild_snapshots_from_transactions(settings: dict, current_price: float) -> int:
    """Recreate chart history from active transactions."""
    transactions = get_active_transactions()
    state = {
        "btc_amount": 0.0,
        "usdt_reserve": 0.0,
        "total_btc_cost": 0.0,
        "avg_price": 0.0,
        "last_high": 0.0,
        "total_deposited": 0.0,
        "realized_pnl": 0.0,
    }
    rows = []
    last_price = current_price

    for tx in transactions:
        price = float(tx.get("price", 0.0) or 0.0)
        if price > 0:
            last_price = price
        _apply_transaction_to_state(state, tx)
        if state["btc_amount"] > 0 or state["usdt_reserve"] > 0:
            rows.append(_snapshot_row(state, settings, last_price, tx.get("created_at")))

    if not rows:
        rows.append(_snapshot_row(state, settings, current_price, _now()))
    elif current_price > 0:
        rows.append(_snapshot_row(state, settings, current_price, _now()))

    with get_connection() as conn:
        conn.execute("DELETE FROM daily_snapshots")
        conn.executemany(
            """INSERT INTO daily_snapshots
               (date, btc_price, btc_amount, usdt_reserve, btc_value,
                portfolio_value, total_deposited, avg_price, realized_pnl,
                unrealized_pnl, total_pnl, total_pnl_percent, active_strategy,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
    return len(rows)


def _snapshot_row(state: dict, settings: dict, price: float, created_at: str | None) -> tuple:
    created = _parse_dt(created_at) or _now_dt()
    btc_amount = state["btc_amount"]
    usdt_reserve = state["usdt_reserve"]
    total_btc_cost = state["total_btc_cost"]
    total_deposited = state["total_deposited"]
    realized_pnl = state["realized_pnl"]
    btc_value = btc_amount * price
    portfolio_value = btc_value + usdt_reserve
    unrealized_pnl = btc_value - total_btc_cost
    total_pnl = portfolio_value - total_deposited
    total_pnl_percent = total_pnl / total_deposited * 100 if total_deposited > 0 else 0.0
    return (
        created.strftime("%Y-%m-%d %H:%M"),
        price,
        btc_amount,
        usdt_reserve,
        btc_value,
        portfolio_value,
        total_deposited,
        state["avg_price"],
        realized_pnl,
        unrealized_pnl,
        total_pnl,
        total_pnl_percent,
        settings.get("active_strategy", "accumulation"),
        created.isoformat(),
    )


def _apply_transaction_to_state(state: dict, tx: dict) -> None:
    tx_type = tx.get("type", "")
    usdt_amount = float(tx.get("usdt_amount", 0.0) or 0.0)
    btc_amount = float(tx.get("btc_amount", 0.0) or 0.0)
    price = float(tx.get("price", 0.0) or 0.0)
    fee = float(tx.get("fee", 0.0) or 0.0)
    fee_asset = (tx.get("fee_asset", "USDT") or "USDT").upper()
    symbol = tx.get("symbol", "BTCUSDT") or "BTCUSDT"
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


def _base_coin(symbol: str) -> str:
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
        if symbol.upper().endswith(quote):
            return symbol.upper()[: -len(quote)]
    return symbol.upper()
