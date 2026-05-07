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
    fee_asset: str = "USDT",
    note: str = "",
    strategy_name: str = "accumulation",
    symbol: str = "BTCUSDT",
) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO transactions
               (type, strategy_name, symbol, price, usdt_amount, btc_amount, fee, fee_asset, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tx_type, strategy_name, symbol, price, usdt_amount, btc_amount, fee, fee_asset, note, _now()),
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


def get_active_transactions_desc(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE status = 'ACTIVE' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_transaction(transaction_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM transactions WHERE id = ?",
            (transaction_id,),
        ).fetchone()
        return dict(row) if row else {}


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


def update_transaction_values(
    transaction_id: int,
    price: float,
    usdt_amount: float,
    btc_amount: float,
    fee: float,
    fee_asset: str,
    reason: str = "Edited from Telegram UI",
) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT note FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        old_note = row["note"] if row else ""
        note_suffix = f"\n[{_now()}] {reason}"
        conn.execute(
            """UPDATE transactions
               SET price = ?,
                   usdt_amount = ?,
                   btc_amount = ?,
                   fee = ?,
                   fee_asset = ?,
                   note = ?
               WHERE id = ? AND status = 'ACTIVE'""",
            (
                price,
                usdt_amount,
                btc_amount,
                fee,
                fee_asset.upper(),
                f"{old_note or ''}{note_suffix}",
                transaction_id,
            ),
        )
        conn.commit()


def apply_commission_to_zero_fee_transactions(commission_percent: float) -> dict:
    rate = commission_percent / 100
    updated_buy = 0
    updated_sell = 0
    now = _now()

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM transactions
               WHERE status = 'ACTIVE'
               AND COALESCE(fee, 0) = 0
               ORDER BY id ASC"""
        ).fetchall()

        for row in rows:
            tx = dict(row)
            tx_type = tx.get("type", "")
            symbol = tx.get("symbol", "BTCUSDT") or "BTCUSDT"
            coin = _base_coin(symbol)
            note = tx.get("note", "") or ""

            if tx_type in ("BUY", "MANUAL_BUY", "MONTHLY_DEPOSIT", "EXTRA_DEPOSIT"):
                btc_amount = float(tx.get("btc_amount", 0.0) or 0.0)
                if btc_amount <= 0:
                    continue
                fee = btc_amount * rate
                net_btc = max(btc_amount - fee, 0.0)
                conn.execute(
                    """UPDATE transactions
                       SET btc_amount = ?,
                           fee = ?,
                           fee_asset = ?,
                           note = ?
                       WHERE id = ?""",
                    (
                        net_btc,
                        fee,
                        coin,
                        f"{note}\n[{now}] Auto commission backfill {commission_percent:g}%",
                        tx["id"],
                    ),
                )
                updated_buy += 1
                continue

            if tx_type in ("SELL", "MANUAL_SELL"):
                usdt_amount = float(tx.get("usdt_amount", 0.0) or 0.0)
                if usdt_amount <= 0:
                    continue
                fee = usdt_amount * rate
                conn.execute(
                    """UPDATE transactions
                       SET fee = ?,
                           fee_asset = 'USDT',
                           note = ?
                       WHERE id = ?""",
                    (
                        fee,
                        f"{note}\n[{now}] Auto commission backfill {commission_percent:g}%",
                        tx["id"],
                    ),
                )
                updated_sell += 1

        conn.commit()

    return {"buy": updated_buy, "sell": updated_sell, "total": updated_buy + updated_sell}


def _base_coin(symbol: str) -> str:
    for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
        if symbol.upper().endswith(quote):
            return symbol.upper()[: -len(quote)]
    return symbol.upper()
