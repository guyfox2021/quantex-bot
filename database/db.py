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
    if "commission_percent" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN commission_percent REAL DEFAULT 0.1")

    signal_cols = [row[1] for row in conn.execute("PRAGMA table_info(signals)").fetchall()]
    if "trigger_type" not in signal_cols:
        conn.execute("ALTER TABLE signals ADD COLUMN trigger_type TEXT")
    if "level_percent" not in signal_cols:
        conn.execute("ALTER TABLE signals ADD COLUMN level_percent REAL")
    if "buyback_cycle_id" not in signal_cols:
        conn.execute("ALTER TABLE signals ADD COLUMN buyback_cycle_id INTEGER")

    tx_cols = [row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()]
    if "status" not in tx_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN status TEXT DEFAULT 'ACTIVE'")
    if "voided_at" not in tx_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN voided_at TEXT")
    if "void_reason" not in tx_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN void_reason TEXT")
    if "fee_asset" not in tx_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN fee_asset TEXT DEFAULT 'USDT'")

    cycle_cols = [row[1] for row in conn.execute("PRAGMA table_info(buyback_cycles)").fetchall()]
    if "closed_at" not in cycle_cols:
        conn.execute("ALTER TABLE buyback_cycles ADD COLUMN closed_at TEXT")
    conn.commit()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _run_migrations(conn)
        conn.commit()
