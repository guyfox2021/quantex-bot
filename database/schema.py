SCHEMA = """
CREATE TABLE IF NOT EXISTS owner (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    btc_amount REAL DEFAULT 0,
    usdt_reserve REAL DEFAULT 0,
    total_btc_cost REAL DEFAULT 0,
    avg_price REAL DEFAULT 0,
    last_high REAL DEFAULT 0,
    total_deposited REAL DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    is_initialized INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    strategy_name TEXT DEFAULT 'accumulation',
    symbol TEXT DEFAULT 'BTCUSDT',
    price REAL DEFAULT 0,
    usdt_amount REAL DEFAULT 0,
    btc_amount REAL DEFAULT 0,
    fee REAL DEFAULT 0,
    note TEXT,
    status TEXT DEFAULT 'ACTIVE',
    voided_at TEXT,
    void_reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_type TEXT NOT NULL,
    strategy_name TEXT DEFAULT 'accumulation',
    price REAL DEFAULT 0,
    reason TEXT,
    recommended_action TEXT,
    amount_usdt REAL DEFAULT 0,
    amount_btc_percent REAL DEFAULT 0,
    trigger_type TEXT,
    level_percent REAL,
    buyback_cycle_id INTEGER,
    status TEXT DEFAULT 'NEW',
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_value REAL DEFAULT 5000,
    monthly_deposit REAL DEFAULT 500,
    check_interval_minutes INTEGER DEFAULT 5,
    signals_enabled INTEGER DEFAULT 1,
    active_strategy TEXT DEFAULT 'accumulation',
    symbol TEXT DEFAULT 'BTCUSDT',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    trigger_type TEXT NOT NULL,
    level_percent REAL NOT NULL,
    is_triggered INTEGER DEFAULT 0,
    triggered_at TEXT
);

CREATE TABLE IF NOT EXISTS buyback_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL DEFAULT 'accumulation_v2',
    symbol TEXT DEFAULT 'BTCUSDT',
    sell_signal_id INTEGER,
    sell_price REAL NOT NULL,
    btc_sold REAL NOT NULL,
    usdt_received REAL NOT NULL,
    remaining_btc REAL NOT NULL,
    level_2_done INTEGER DEFAULT 0,
    level_4_done INTEGER DEFAULT 0,
    status TEXT DEFAULT 'OPEN',
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS daily_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    btc_price REAL DEFAULT 0,
    btc_amount REAL DEFAULT 0,
    usdt_reserve REAL DEFAULT 0,
    btc_value REAL DEFAULT 0,
    portfolio_value REAL DEFAULT 0,
    total_deposited REAL DEFAULT 0,
    avg_price REAL DEFAULT 0,
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    total_pnl REAL DEFAULT 0,
    total_pnl_percent REAL DEFAULT 0,
    active_strategy TEXT DEFAULT 'accumulation',
    created_at TEXT NOT NULL
);
"""
