import sqlite3

DATABASE_NAME = 'orders.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    with open('schema.sql', 'r') as f:
        conn.executescript(f.read())
    conn.close()

import requests
import gzip
import json

def create_schema_file():
    schema = """
    DROP TABLE IF EXISTS orders;
    CREATE TABLE orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        initial_stoploss REAL NOT NULL,
        current_stoploss REAL NOT NULL,
        current_stoploss_price REAL,
        potential_profit REAL,
        status TEXT NOT NULL,
        transaction_type TEXT,
        exchange TEXT,
        product TEXT,
        broker TEXT NOT NULL
    );

    DROP TABLE IF EXISTS instruments;
    CREATE TABLE instruments (
        instrument_key TEXT PRIMARY KEY,
        trading_symbol TEXT NOT NULL,
        exchange TEXT NOT NULL
    );
    """
    with open('schema.sql', 'w') as f:
        f.write(schema)

def update_instrument_list():
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
    try:
        response = requests.get(url)
        response.raise_for_status()

        decompressed_data = gzip.decompress(response.content)
        instrument_list = json.loads(decompressed_data)

        conn = get_db_connection()
        conn.execute('DELETE FROM instruments') # Clear old data

        for instrument in instrument_list:
            if instrument.get('instrument_type') == 'EQ' and instrument.get('exchange') in ['NSE', 'BSE']:
                conn.execute(
                    'INSERT INTO instruments (instrument_key, trading_symbol, exchange) VALUES (?, ?, ?)',
                    (instrument['instrument_key'], instrument['trading_symbol'], instrument['exchange'])
                )

        conn.commit()
        conn.close()
        return "Instrument list updated successfully."
    except Exception as e:
        return f"Error updating instrument list: {e}"

if __name__ == '__main__':
    create_schema_file()
    init_db()
    print("Database initialized.")
