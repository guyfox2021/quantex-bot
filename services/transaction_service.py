from datetime import datetime, timezone
from database.db import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_transaction(
    tx_type: str,
    price: float,
    usdt_amount: float,
    btc_amount: float,
    fee: float = 0.0,
    note: str = "",
    strategy_name: str = "accumulation",
    symbol: str = "BTCUSDT",
) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO transactions
               (type, strategy_name, symbol, price, usdt_amount, btc_amount, fee, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tx_type, strategy_name, symbol, price, usdt_amount, btc_amount, fee, note, _now()),
        )
        conn.commit()


def get_last_transactions(limit: int = 10) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
