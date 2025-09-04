import sqlite3
import requests
import gzip
import json
import logging

DATABASE_NAME = 'orders.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    return conn

import os

def init_db():
    conn = get_db_connection()
    # Check if tables already exist
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders'")
    orders_table_exists = cursor.fetchone()
    
    if not orders_table_exists:
        print("Initializing database...")
        # Construct an absolute path to the schema.sql file
        script_dir = os.path.dirname(os.path.realpath(__file__))
        schema_path = os.path.join(script_dir, '..', 'schema.sql')
        with open(schema_path, 'r') as f:
            conn.executescript(f.read())
        print("Database initialized.")
    else:
        print("Database already initialized.")
        
    conn.close()

def update_upstox_instruments():
    logging.info("Starting Upstox instrument list update...")
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
    try:
        response = requests.get(url)
        response.raise_for_status()

        decompressed_data = gzip.decompress(response.content)
        instrument_list = json.loads(decompressed_data)

        conn = get_db_connection()
        conn.execute('DELETE FROM instruments WHERE broker = ?', ('Upstox',))

        count = 0
        for instrument in instrument_list:
            if instrument.get('instrument_type') == 'EQ' and instrument.get('exchange') in ['NSE', 'BSE']:
                try:
                    conn.execute(
                        'INSERT INTO instruments (instrument_key, trading_symbol, exchange, broker) VALUES (?, ?, ?, ?)',
                        (instrument['instrument_key'], instrument['trading_symbol'], instrument['exchange'], 'Upstox')
                    )
                    count += 1
                except sqlite3.IntegrityError:
                    pass

        conn.commit()
        conn.close()
        logging.info(f"Upstox instrument list updated successfully with {count} instruments.")
        return f"Upstox instrument list updated successfully with {count} instruments."
    except Exception as e:
        logging.error(f"Error updating Upstox instrument list: {e}")
        return f"Error updating Upstox instrument list: {e}"

def update_zerodha_instruments(kite):
    logging.info("Starting Zerodha instrument list update...")
    try:
        instruments = kite.instruments()
        conn = get_db_connection()
        conn.execute('DELETE FROM instruments WHERE broker = ?', ('Zerodha',))

        count = 0
        for instrument in instruments:
            if instrument.get('instrument_type') == 'EQ' and instrument.get('exchange') in ['NSE', 'BSE']:
                try:
                    conn.execute(
                        'INSERT INTO instruments (instrument_key, trading_symbol, exchange, broker) VALUES (?, ?, ?, ?)',
                        (instrument['instrument_token'], instrument['tradingsymbol'], instrument['exchange'], 'Zerodha')
                    )
                    count += 1
                except sqlite3.IntegrityError:
                    pass

        conn.commit()
        conn.close()
        logging.info(f"Zerodha instrument list updated successfully with {count} instruments.")
        return f"Zerodha instrument list updated successfully with {count} instruments."
    except Exception as e:
        logging.error(f"Error updating Zerodha instrument list: {e}")
        return f"Error updating Zerodha instrument list: {e}"

def update_instrument_list(broker, kite_instance=None):
    if broker == 'Upstox':
        return update_upstox_instruments()
    elif broker == 'Zerodha' and kite_instance:
        return update_zerodha_instruments(kite_instance)
    else:
        return "Invalid broker or missing Kite instance for Zerodha."

if __name__ == '__main__':
    init_db()
    print("Database initialized.")