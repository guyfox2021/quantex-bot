from datetime import datetime, timezone
import re

from database.db import get_connection
from services.settings_service import get_symbol


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_cycle(
    sell_price: float,
    btc_sold: float,
    usdt_received: float,
    sell_signal_id: int | None = None,
    strategy_name: str = "accumulation_v2",
) -> int:
    symbol = get_symbol()
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO buyback_cycles
               (strategy_name, symbol, sell_signal_id, sell_price, btc_sold,
                usdt_received, remaining_btc, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)""",
            (
                strategy_name,
                symbol,
                sell_signal_id,
                sell_price,
                btc_sold,
                usdt_received,
                btc_sold,
                _now(),
                _now(),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_open_cycles(strategy_name: str = "accumulation_v2") -> list[dict]:
    symbol = get_symbol()
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM buyback_cycles
               WHERE strategy_name = ? AND symbol = ? AND status = 'OPEN'
               ORDER BY id ASC""",
            (strategy_name, symbol),
        ).fetchall()
        return [dict(r) for r in rows]


def get_open_buyback_cycles(strategy_name: str = "accumulation_v2") -> list[dict]:
    return get_open_cycles(strategy_name)


def has_open_buyback_cycle(strategy_name: str = "accumulation_v2") -> bool:
    return bool(get_open_cycles(strategy_name))


def get_cycle(cycle_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM buyback_cycles WHERE id = ?", (cycle_id,)).fetchone()
        return dict(row) if row else {}


def mark_level_done(cycle_id: int, level_percent: float, btc_bought: float) -> None:
    cycle = get_cycle(cycle_id)
    if not cycle:
        return

    level_col = "level_4_done" if float(level_percent) >= 4.0 else "level_2_done"
    remaining = max(cycle.get("remaining_btc", 0.0) - btc_bought, 0.0)
    status = "CLOSED" if remaining <= 0 or (level_col == "level_4_done") else "OPEN"
    closed_at = _now() if status == "CLOSED" else cycle.get("closed_at")

    with get_connection() as conn:
        conn.execute(
            f"""UPDATE buyback_cycles SET
                {level_col} = 1,
                remaining_btc = ?,
                status = ?,
                closed_at = ?,
                updated_at = ?
               WHERE id = ?""",
            (remaining, status, closed_at, _now(), cycle_id),
        )
        conn.commit()

    if status == "CLOSED":
        # A completed buyback closes the sell-buyback cycle, so profit-take levels
        # should become available again for the next upward move.
        from services.signal_service import reset_sell_profit_triggers

        reset_sell_profit_triggers(cycle.get("strategy_name", "accumulation_v2"))


def close_cycle(cycle_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE buyback_cycles SET status = 'CLOSED', closed_at = COALESCE(closed_at, ?), updated_at = ? WHERE id = ?",
            (_now(), _now(), cycle_id),
        )
        conn.commit()


def close_cycles_for_strategy(strategy_name: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE buyback_cycles SET status = 'CLOSED', closed_at = COALESCE(closed_at, ?), updated_at = ? WHERE strategy_name = ? AND status = 'OPEN'",
            (_now(), _now(), strategy_name),
        )
        conn.commit()


def sync_cycles_from_active_transactions(strategy_name: str = "accumulation_v2") -> None:
    symbol = get_symbol()
    now = _now()
    with get_connection() as conn:
        txs = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM transactions WHERE status = 'ACTIVE' ORDER BY id ASC"
            ).fetchall()
        ]
        signals = {
            row["id"]: dict(row)
            for row in conn.execute("SELECT * FROM signals").fetchall()
        }
        cycles = {
            row["sell_signal_id"]: dict(row)
            for row in conn.execute(
                "SELECT * FROM buyback_cycles WHERE strategy_name = ? AND symbol = ?",
                (strategy_name, symbol),
            ).fetchall()
            if row["sell_signal_id"] is not None
        }

        active_sell_txs = {}
        active_buyback_txs = []
        for tx in txs:
            signal_id = _signal_id_from_note(tx.get("note", "") or "")
            if not signal_id:
                continue
            sig = signals.get(signal_id)
            if not sig or sig.get("strategy_name") != strategy_name:
                continue
            if tx.get("type") == "SELL" and sig.get("trigger_type") == "SELL_PROFIT":
                active_sell_txs[signal_id] = tx
            elif tx.get("type") == "BUY" and sig.get("trigger_type") == "BUYBACK":
                active_buyback_txs.append((tx, sig))

        for sell_signal_id, cycle in cycles.items():
            if sell_signal_id not in active_sell_txs:
                conn.execute(
                    "UPDATE buyback_cycles SET status = 'CLOSED', closed_at = COALESCE(closed_at, ?), updated_at = ? WHERE id = ?",
                    (now, now, cycle["id"]),
                )

        for sell_signal_id, sell_tx in active_sell_txs.items():
            cycle = cycles.get(sell_signal_id)
            sell_fee = float(sell_tx.get("fee", 0.0) or 0.0)
            sell_fee_asset = (sell_tx.get("fee_asset", "USDT") or "USDT").upper()
            net_usdt_received = float(sell_tx.get("usdt_amount", 0.0) or 0.0)
            if sell_fee_asset == "USDT":
                net_usdt_received -= sell_fee
            if not cycle:
                cursor = conn.execute(
                    """INSERT INTO buyback_cycles
                       (strategy_name, symbol, sell_signal_id, sell_price, btc_sold,
                        usdt_received, remaining_btc, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)""",
                    (
                        strategy_name,
                        symbol,
                        sell_signal_id,
                        sell_tx.get("price", 0.0),
                        sell_tx.get("btc_amount", 0.0),
                        net_usdt_received,
                        sell_tx.get("btc_amount", 0.0),
                        now,
                        now,
                    ),
                )
                cycle_id = cursor.lastrowid
            else:
                cycle_id = cycle["id"]

            remaining = float(sell_tx.get("btc_amount", 0.0) or 0.0)
            level_2_done = 0
            level_4_done = 0
            for buy_tx, buy_sig in active_buyback_txs:
                if int(buy_sig.get("buyback_cycle_id") or 0) != int(cycle_id):
                    continue
                remaining = max(remaining - float(buy_tx.get("btc_amount", 0.0) or 0.0), 0.0)
                if float(buy_sig.get("level_percent") or 0.0) >= 4.0:
                    level_4_done = 1
                else:
                    level_2_done = 1

            status = "CLOSED" if remaining <= 0 or level_4_done else "OPEN"
            closed_at = (cycle.get("closed_at") if cycle else None) if status == "CLOSED" else None
            conn.execute(
                """UPDATE buyback_cycles SET
                   sell_price = ?,
                   btc_sold = ?,
                   usdt_received = ?,
                   remaining_btc = ?,
                   level_2_done = ?,
                   level_4_done = ?,
                   status = ?,
                   closed_at = ?,
                   updated_at = ?
                   WHERE id = ?""",
                (
                    sell_tx.get("price", 0.0),
                    sell_tx.get("btc_amount", 0.0),
                    net_usdt_received,
                    remaining,
                    level_2_done,
                    level_4_done,
                    status,
                    closed_at or (now if status == "CLOSED" else None),
                    now,
                    cycle_id,
                ),
            )

        conn.commit()


def _signal_id_from_note(note: str) -> int | None:
    match = re.search(r"#(\d+)", note)
    return int(match.group(1)) if match else None
