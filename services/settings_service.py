from datetime import datetime, timezone
from database.db import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_settings() -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM settings ORDER BY id LIMIT 1").fetchone()
        if row:
            return dict(row)
        return {}


def get_symbol() -> str:
    return get_settings().get("symbol", "BTCUSDT").upper()


def create_default_settings_if_needed() -> None:
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM settings LIMIT 1").fetchone()
        if not existing:
            now = _now()
            conn.execute(
                """INSERT INTO settings
                   (target_value, monthly_deposit, check_interval_minutes,
                    signals_enabled, active_strategy, symbol, commission_percent, created_at, updated_at)
                   VALUES (5000, 500, 5, 1, 'accumulation', 'BTCUSDT', 0.1, ?, ?)""",
                (now, now),
            )
            conn.commit()


def update_target_value(value: float) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE settings SET target_value = ?, updated_at = ? WHERE id = (SELECT id FROM settings LIMIT 1)",
            (value, _now()),
        )
        conn.commit()


def update_monthly_deposit(value: float) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE settings SET monthly_deposit = ?, updated_at = ? WHERE id = (SELECT id FROM settings LIMIT 1)",
            (value, _now()),
        )
        conn.commit()


def update_check_interval(minutes: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE settings SET check_interval_minutes = ?, updated_at = ? WHERE id = (SELECT id FROM settings LIMIT 1)",
            (minutes, _now()),
        )
        conn.commit()


def toggle_signals() -> int:
    settings = get_settings()
    new_val = 0 if settings.get("signals_enabled", 1) else 1
    with get_connection() as conn:
        conn.execute(
            "UPDATE settings SET signals_enabled = ?, updated_at = ? WHERE id = (SELECT id FROM settings LIMIT 1)",
            (new_val, _now()),
        )
        conn.commit()
    return new_val


def update_active_strategy(strategy_name: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE settings SET active_strategy = ?, updated_at = ? WHERE id = (SELECT id FROM settings LIMIT 1)",
            (strategy_name, _now()),
        )
        conn.commit()


def update_symbol(symbol: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE settings SET symbol = ?, updated_at = ? WHERE id = (SELECT id FROM settings LIMIT 1)",
            (symbol.upper(), _now()),
        )
        conn.commit()


def update_commission_percent(value: float) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE settings SET commission_percent = ?, updated_at = ? WHERE id = (SELECT id FROM settings LIMIT 1)",
            (value, _now()),
        )
        conn.commit()
