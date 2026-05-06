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


def get_last_transactions(limit: int = 10, include_voided: bool = False) -> list[dict]:
    with get_connection() as conn:
        if include_voided:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE status = 'ACTIVE' ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_active_transactions() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE status = 'ACTIVE' ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_last_active_transaction() -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM transactions WHERE status = 'ACTIVE' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else {}


def void_transaction(transaction_id: int, reason: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE transactions
               SET status = 'VOIDED', voided_at = ?, void_reason = ?
               WHERE id = ?""",
            (_now(), reason, transaction_id),
        )
        conn.commit()
