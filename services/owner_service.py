from datetime import datetime, timezone
from database.db import get_connection
import config


def is_owner(telegram_id: int) -> bool:
    return telegram_id == config.OWNER_TELEGRAM_ID


def ensure_owner(telegram_id: int, username: str = None, first_name: str = None) -> None:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM owner WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if not existing:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO owner (telegram_id, username, first_name, created_at) VALUES (?, ?, ?, ?)",
                (telegram_id, username, first_name, now),
            )
            conn.commit()
