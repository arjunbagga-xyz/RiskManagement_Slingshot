DROP TABLE IF EXISTS orders;
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    initial_stoploss REAL NOT NULL,
    current_stoploss_price REAL NOT NULL,
    potential_profit REAL,
    status TEXT NOT NULL,
    transaction_type TEXT,
    exchange TEXT,
    product TEXT,
    broker TEXT NOT NULL,
    instrument_key TEXT,
    leverage INTEGER
);

DROP TABLE IF EXISTS instruments;
CREATE TABLE instruments (
    instrument_key TEXT,
    trading_symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    broker TEXT NOT NULL,
    PRIMARY KEY (trading_symbol, exchange, broker)
);

DROP TABLE IF EXISTS settings;
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

DROP TABLE IF EXISTS encryption_key;
CREATE TABLE encryption_key (
    key BLOB NOT NULL
);
