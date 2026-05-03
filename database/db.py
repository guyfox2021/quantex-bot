import sqlite3
from database.schema import SCHEMA
import config


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    cols = [row[1] for row in conn.execute("PRAGMA table_info(settings)").fetchall()]
    if "symbol" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN symbol TEXT DEFAULT 'BTCUSDT'")
    conn.commit()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _run_migrations(conn)
        conn.commit()
