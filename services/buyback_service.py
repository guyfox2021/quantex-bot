from datetime import datetime, timezone

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

    with get_connection() as conn:
        conn.execute(
            f"""UPDATE buyback_cycles SET
                {level_col} = 1,
                remaining_btc = ?,
                status = ?,
                updated_at = ?
               WHERE id = ?""",
            (remaining, status, _now(), cycle_id),
        )
        conn.commit()

    if status == "CLOSED":
        # A completed buyback closes the sell-buyback cycle, so profit-take levels
        # should become available again for the next upward move.
        from services.signal_service import reset_sell_profit_triggers

        reset_sell_profit_triggers(cycle.get("strategy_name", "accumulation_v2"))


def close_cycles_for_strategy(strategy_name: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE buyback_cycles SET status = 'CLOSED', updated_at = ? WHERE strategy_name = ? AND status = 'OPEN'",
            (_now(), strategy_name),
        )
        conn.commit()
