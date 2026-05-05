from datetime import datetime, timezone
from database.db import get_connection
from strategies.base import StrategySignal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_signal(signal: StrategySignal, price: float, status: str = "NEW") -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO signals
               (signal_type, strategy_name, price, reason, recommended_action,
                amount_usdt, amount_btc_percent, trigger_type, level_percent,
                buyback_cycle_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal.signal_type,
                signal.strategy_name,
                price,
                signal.reason,
                signal.recommended_action,
                signal.amount_usdt,
                signal.amount_btc_percent,
                signal.trigger_type,
                signal.level_percent,
                signal.buyback_cycle_id,
                status,
                _now(),
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_signal_status(signal_id: int, status: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE signals SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), signal_id),
        )
        conn.commit()


def get_last_signals(limit: int = 10) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def has_active_signal_for_trigger(strategy_name: str, trigger_type: str, level_percent: float) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id FROM signals
               WHERE strategy_name = ?
               AND trigger_type = ?
               AND level_percent = ?
               AND status IN ('NEW', 'SENT')
               AND (amount_usdt > 0 OR amount_btc_percent > 0)
               ORDER BY id DESC LIMIT 1""",
            (strategy_name, trigger_type, level_percent),
        ).fetchone()
        return row is not None


def ensure_default_triggers(strategy) -> None:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM strategy_triggers WHERE strategy_name = ?",
            (strategy.name,),
        ).fetchall()
        if existing:
            return
        for t in strategy.get_default_triggers():
            conn.execute(
                """INSERT INTO strategy_triggers
                   (strategy_name, trigger_type, level_percent, is_triggered)
                   VALUES (?, ?, ?, 0)""",
                (t["strategy_name"], t["trigger_type"], t["level_percent"]),
            )
        conn.commit()


def get_triggers(strategy_name: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM strategy_triggers WHERE strategy_name = ?",
            (strategy_name,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_triggered(strategy_name: str, trigger_type: str, level_percent: float) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE strategy_triggers SET is_triggered = 1, triggered_at = ?
               WHERE strategy_name = ? AND trigger_type = ? AND level_percent = ?""",
            (_now(), strategy_name, trigger_type, level_percent),
        )
        conn.commit()


def reset_buy_drop_triggers(strategy_name: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE strategy_triggers SET is_triggered = 0, triggered_at = NULL
               WHERE strategy_name = ? AND trigger_type = 'BUY_DROP'""",
            (strategy_name,),
        )
        conn.commit()


def reset_buy_entry_triggers(strategy_name: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE strategy_triggers SET is_triggered = 0, triggered_at = NULL
               WHERE strategy_name = ? AND trigger_type IN ('BUY_DROP', 'BUY_DIP')""",
            (strategy_name,),
        )
        conn.commit()
