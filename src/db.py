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

def init_db():
    conn = get_db_connection()
    with open('schema.sql', 'r') as f:
        conn.executescript(f.read())
    conn.close()

def update_upstox_instruments():
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
    try:
        response = requests.get(url)
        response.raise_for_status()

        decompressed_data = gzip.decompress(response.content)
        instrument_list = json.loads(decompressed_data)

        conn = get_db_connection()
        conn.execute('DELETE FROM instruments WHERE broker = ?', ('Upstox',))

        for instrument in instrument_list:
            if instrument.get('instrument_type') == 'EQ' and instrument.get('exchange') in ['NSE', 'BSE']:
                try:
                    conn.execute(
                        'INSERT INTO instruments (instrument_key, trading_symbol, exchange, broker) VALUES (?, ?, ?, ?)',
                        (instrument['instrument_key'], instrument['trading_symbol'], instrument['exchange'], 'Upstox')
                    )
                except sqlite3.IntegrityError:
                    # Ignore if the instrument already exists for another broker
                    pass

        conn.commit()
        conn.close()
        return "Upstox instrument list updated successfully."
    except Exception as e:
        logging.error(f"Error updating Upstox instrument list: {e}")
        return f"Error updating Upstox instrument list: {e}"

def update_zerodha_instruments(kite):
    try:
        instruments = kite.instruments()
        conn = get_db_connection()
        conn.execute('DELETE FROM instruments WHERE broker = ?', ('Zerodha',))

        for instrument in instruments:
            if instrument.get('instrument_type') == 'EQ' and instrument.get('exchange') in ['NSE', 'BSE']:
                try:
                    conn.execute(
                        'INSERT INTO instruments (instrument_key, trading_symbol, exchange, broker) VALUES (?, ?, ?, ?)',
                        (instrument['instrument_token'], instrument['tradingsymbol'], instrument['exchange'], 'Zerodha')
                    )
                except sqlite3.IntegrityError:
                    # Ignore if the instrument already exists for another broker
                    pass

        conn.commit()
        conn.close()
        return "Zerodha instrument list updated successfully."
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
