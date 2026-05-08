from datetime import datetime, timedelta, timezone
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


def get_signal(signal_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
        return dict(row) if row else None


def get_last_buy_signal_time() -> datetime | None:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT created_at FROM signals
               WHERE signal_type = 'BUY'
               AND status IN ('NEW', 'SENT', 'CONFIRMED')
               ORDER BY created_at DESC LIMIT 1"""
        ).fetchone()
    if not row or not row["created_at"]:
        return None
    try:
        dt = datetime.fromisoformat(row["created_at"])
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def can_send_buy_signal(cooldown_hours: int = 6) -> bool:
    last_buy_time = get_last_buy_signal_time()
    if not last_buy_time:
        return True
    return datetime.now(timezone.utc) - last_buy_time >= timedelta(hours=cooldown_hours)


def has_active_signal_for_trigger(strategy_name: str, trigger_type: str, level_percent: float) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT id FROM signals
               WHERE strategy_name = ?
               AND trigger_type = ?
               AND level_percent = ?
               AND status IN ('NEW', 'SENT', 'IGNORED')
               AND (amount_usdt > 0 OR amount_btc_percent > 0)
               ORDER BY id DESC LIMIT 1""",
            (strategy_name, trigger_type, level_percent),
        ).fetchone()
        return row is not None


def refresh_ignored_signal_locks(
    strategy_name: str,
    current_price: float,
    portfolio: dict,
    open_buybacks: list[dict] | None = None,
) -> None:
    """Unlock skipped signals after price leaves their trigger zone."""
    if current_price <= 0:
        return

    open_buybacks = open_buybacks or []
    cycles_by_id = {int(c.get("id")): c for c in open_buybacks if c.get("id") is not None}
    avg_price = float(portfolio.get("avg_price", 0) or 0)
    last_high = float(portfolio.get("last_high", 0) or 0)
    to_expire: list[dict] = []

    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM signals
               WHERE strategy_name = ?
               AND status = 'IGNORED'
               AND trigger_type IS NOT NULL
               ORDER BY id ASC""",
            (strategy_name,),
        ).fetchall()

    for row in rows:
        sig = dict(row)
        trigger_type = sig.get("trigger_type")
        level = float(sig.get("level_percent") or 0)
        should_expire = False

        if trigger_type == "BUYBACK":
            cycle = cycles_by_id.get(int(sig.get("buyback_cycle_id") or 0))
            sell_price = float((cycle or {}).get("sell_price", 0) or 0)
            if not cycle or sell_price <= 0:
                should_expire = True
            else:
                drop = (sell_price - current_price) / sell_price * 100
                should_expire = drop < level
        elif trigger_type in ("BUY_DIP", "BUY_DROP"):
            if last_high <= 0:
                should_expire = True
            else:
                drawdown = (last_high - current_price) / last_high * 100
                should_expire = drawdown < level
        elif trigger_type == "SELL_PROFIT":
            if avg_price <= 0:
                should_expire = True
            else:
                profit = (current_price - avg_price) / avg_price * 100
                should_expire = profit < level

        if should_expire:
            to_expire.append(sig)

    if not to_expire:
        return

    now = _now()
    with get_connection() as conn:
        for sig in to_expire:
            conn.execute(
                "UPDATE signals SET status = 'EXPIRED', updated_at = ? WHERE id = ?",
                (now, sig["id"]),
            )
            if sig.get("trigger_type") != "BUYBACK":
                conn.execute(
                    """UPDATE strategy_triggers
                       SET is_triggered = 0, triggered_at = NULL
                       WHERE strategy_name = ? AND trigger_type = ? AND level_percent = ?""",
                    (strategy_name, sig.get("trigger_type"), sig.get("level_percent")),
                )
        conn.commit()


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


def reset_sell_profit_triggers(strategy_name: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE strategy_triggers SET is_triggered = 0, triggered_at = NULL
               WHERE strategy_name = ? AND trigger_type = 'SELL_PROFIT'""",
            (strategy_name,),
        )
        conn.commit()
