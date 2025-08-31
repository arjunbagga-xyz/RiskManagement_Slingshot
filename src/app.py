from flask import Flask, render_template, request, redirect, session, flash, jsonify
from kiteconnect import KiteConnect
import upstox_client
import os
import time
import threading
import logging
import queue
from db import get_db_connection, update_instrument_list
from websocket_manager import ZerodhaWebSocketManager, UpstoxWebSocketManager

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.secret_key = os.urandom(24)

# --- Logging ---
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration ---
ZERODHA_API_KEY = os.getenv("ZERODHA_API_KEY", "your_zerodha_api_key")
ZERODHA_API_SECRET = os.getenv("ZERODHA_API_SECRET", "your_zerodha_api_secret")
UPSTOX_API_KEY = os.getenv("UPSTOX_API_KEY", "your_upstox_api_key")
UPSTOX_API_SECRET = os.getenv("UPSTOX_API_SECRET", "your_upstox_api_secret")
UPSTOX_REDIRECT_URI = os.getenv("UPSTOX_REDIRECT_URI", "http://localhost:5000/callback/upstox")

# --- Global variables for access tokens & websocket managers (simplified for single-user context) ---
ACCESS_TOKENS = {
    "zerodha": None,
    "upstox": None
}
WEBSOCKET_MANAGERS = {
    "zerodha": None,
    "upstox": None
}

# --- Utility Functions ---
def get_upstox_product(product_str):
    return {"MIS": "I", "CNC": "D", "NRML": "I"}.get(product_str, "I")

# --- Zerodha Login ---
kite = KiteConnect(api_key=ZERODHA_API_KEY)

# --- Order Queue for Thread-Safe Order Placement ---
order_queue = queue.Queue()

def order_placement_worker():
    """This worker runs in a background thread to place orders from the queue."""
    while True:
        order_details = order_queue.get()
        if order_details is None: # A way to stop the worker
            break

        broker = order_details['broker']
        logging.info(f"Worker picked up a {broker} order for {order_details['symbol']}.")

        try:
            # Use app_context to be able to access session and other context-bound objects
            # if needed in the future, though not strictly necessary for this implementation.
            with app.app_context():
                if broker == 'Zerodha':
                    access_token = ACCESS_TOKENS.get('zerodha')
                    if not access_token:
                        logging.error("Zerodha access token not found for order placement.")
                        continue
                    kite.set_access_token(access_token)
                    kite.place_order(
                        variety="regular", exchange=order_details['exchange'],
                        tradingsymbol=order_details['symbol'],
                        transaction_type=order_details['transaction_type'],
                        quantity=order_details['quantity'],
                        product=order_details['product'],
                        order_type='MARKET'
                    )
                elif broker == 'Upstox':
                    access_token = ACCESS_TOKENS.get('upstox')
                    if not access_token:
                        logging.error("Upstox access token not found for order placement.")
                        continue

                    configuration = upstox_client.Configuration()
                    configuration.access_token = access_token
                    api_instance = upstox_client.OrderApi(upstox_client.ApiClient(configuration))
                    api_instance.place_order(
                        api_version="v2",
                        body=upstox_client.PlaceOrderRequest(
                            quantity=order_details['quantity'],
                            product=get_upstox_product(order_details['product']),
                            validity="DAY",
                            instrument_token=order_details['instrument_key'],
                            order_type='MARKET',
                            transaction_type='s' if order_details['transaction_type'] == 'SELL' else 'b'
                        )
                    )

                logging.info(f"Stop-loss order placed successfully for {order_details['symbol']}.")

                # Update the order status in the database to prevent re-triggering
                conn = get_db_connection()
                conn.execute('UPDATE orders SET status = ? WHERE id = ?', ('CLOSED', order_details['order_id']))
                conn.commit()
                conn.close()

        except Exception as e:
            logging.error(f"Error placing stop-loss order from worker: {e}")
        finally:
            order_queue.task_done()

# --- Routes ---

@app.route('/login/zerodha')
def login_zerodha():
    return redirect(kite.login_url())

@app.route('/callback/zerodha')
def callback_zerodha():
    request_token = request.args.get('request_token')
    try:
        data = kite.generate_session(request_token, api_secret=ZERODHA_API_SECRET)
        access_token = data['access_token']
        ACCESS_TOKENS["zerodha"] = access_token
        session['logged_in_broker'] = 'Zerodha'

        if WEBSOCKET_MANAGERS['zerodha']:
            WEBSOCKET_MANAGERS['zerodha'].stop()

        WEBSOCKET_MANAGERS['zerodha'] = ZerodhaWebSocketManager(access_token, ZERODHA_API_KEY, order_queue)
        WEBSOCKET_MANAGERS['zerodha'].start()

        kite.set_access_token(access_token)
        message = update_instrument_list('Zerodha', kite)
        flash(message, "info")
        flash("Successfully logged in with Zerodha.", "success")
        return redirect('/')
    except Exception as e:
        flash(f"Error during Zerodha authentication: {e}", "error")
        return redirect('/login')

@app.route('/login/upstox')
def login_upstox():
    auth_url = f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={UPSTOX_API_KEY}&redirect_uri={UPSTOX_REDIRECT_URI}"
    return redirect(auth_url)

@app.route('/callback/upstox')
def callback_upstox():
    code = request.args.get('code')
    api_instance = upstox_client.LoginApi()
    try:
        api_response = api_instance.token(
            api_version="v2",
            code=code,
            client_id=UPSTOX_API_KEY,
            client_secret=UPSTOX_API_SECRET,
            redirect_uri=UPSTOX_REDIRECT_URI,
            grant_type='authorization_code'
        )
        access_token = api_response.access_token
        ACCESS_TOKENS["upstox"] = access_token
        session['logged_in_broker'] = 'Upstox'

        if WEBSOCKET_MANAGERS['upstox']:
            WEBSOCKET_MANAGERS['upstox'].stop()

        WEBSOCKET_MANAGERS['upstox'] = UpstoxWebSocketManager(access_token, order_queue)
        WEBSOCKET_MANAGERS['upstox'].start()

        message = update_instrument_list('Upstox', kite_instance=None)
        flash(message, "info")
        flash("Successfully logged in with Upstox.", "success")
        return redirect('/')
    except Exception as e:
        flash(f"Error during Upstox authentication: {e}", "error")
        return redirect('/login')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/')
def index():
    is_logged_in = session.get('logged_in_broker') is not None
    conn = get_db_connection()
    orders = conn.execute('SELECT * FROM orders').fetchall()
    conn.close()
    return render_template('index.html', is_logged_in=is_logged_in, orders=orders)

@app.route('/place_order', methods=['POST'])
def place_order():
    conn = get_db_connection()
    broker = session.get('logged_in_broker')
    if not broker:
        flash("You are not logged in.", "error")
        conn.close()
        return redirect('/login')

    try:
        if broker == 'Zerodha':
            kite.set_access_token(ACCESS_TOKENS['zerodha'])
            order_id = kite.place_order(
                variety="regular", exchange=request.form['exchange'],
                tradingsymbol=request.form['symbol'],
                transaction_type=request.form['transaction_type'],
                quantity=int(request.form['quantity']),
                product=request.form['product'], order_type=request.form['order_type'],
                price=float(request.form['price']) if request.form['price'] else None
            )
        elif broker == 'Upstox':
            instrument = conn.execute('SELECT instrument_key FROM instruments WHERE trading_symbol = ? AND exchange = ?',
                                      (request.form['symbol'].upper(), request.form['exchange'].upper())).fetchone()
            if not instrument:
                flash(f"Instrument not found for {request.form['symbol']} on {request.form['exchange']}", "error")
                conn.close()
                return redirect('/')
            instrument_token = instrument['instrument_key']

            configuration = upstox_client.Configuration()
            configuration.access_token = ACCESS_TOKENS['upstox']
            api_instance = upstox_client.OrderApi(upstox_client.ApiClient(configuration))
            api_response = api_instance.place_order(
                api_version="v2",
                body=upstox_client.PlaceOrderRequest(
                    quantity=int(request.form['quantity']),
                    product=get_upstox_product(request.form['product']),
                    validity="DAY",
                    price=float(request.form['price']) if request.form['price'] else 0,
                    instrument_token=instrument_token,
                    order_type=request.form['order_type'],
                    transaction_type='b' if request.form['transaction_type'] == 'BUY' else 's',
                    disclosed_quantity=0, trigger_price=0, is_amo=False
                )
            )
            order_id = api_response.data.order_id

        instrument_key_to_store = instrument_token if broker == 'Upstox' else conn.execute('SELECT instrument_key FROM instruments WHERE trading_symbol = ? AND exchange = ? AND broker = ?', (request.form['symbol'].upper(), request.form['exchange'].upper(), broker)).fetchone()['instrument_key']

        price = float(request.form['price'] or 0)
        stoploss_percent = float(request.form['stoploss'])
        initial_stoploss_price = price * (1 - stoploss_percent / 100) if price > 0 else 0

        conn.execute(
            'INSERT INTO orders (order_id, symbol, quantity, price, initial_stoploss, current_stoploss_price, status, broker, transaction_type, exchange, product, instrument_key) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (order_id, request.form['symbol'], int(request.form['quantity']), price, stoploss_percent, initial_stoploss_price, 'OPEN', broker, request.form['transaction_type'], request.form['exchange'], request.form['product'], instrument_key_to_store)
        )
        conn.commit()

        # Subscribe to the instrument's ticks
        ws_manager = WEBSOCKET_MANAGERS.get(broker.lower())
        if ws_manager:
            ws_manager.subscribe([instrument_key_to_store])

        flash(f"{broker} order placed successfully! Order ID: {order_id}", "success")

    except Exception as e:
        flash(f"Error placing {broker} order: {e}", "error")

    conn.close()
    return redirect('/')

@app.route('/update_instruments')
def update_instruments_route():
    broker = session.get('logged_in_broker')
    if not broker:
        flash("Please login first.", "error")
        return redirect('/login')

    kite_instance = None
    if broker == 'Zerodha':
        access_token = ACCESS_TOKENS.get('zerodha')
        if not access_token:
            flash("Zerodha session expired. Please login again.", "error")
            return redirect('/login/zerodha')
        kite.set_access_token(access_token)
        kite_instance = kite

    message = update_instrument_list(broker, kite_instance)
    flash(message, "info")
    return redirect('/')

@app.route('/logout')
def logout():
    ACCESS_TOKENS["zerodha"] = None
    ACCESS_TOKENS["upstox"] = None
    session.clear()
    flash("You have been logged out.", "success")
    return redirect('/')

@app.route('/api/symbols')
def api_symbols():
    broker = session.get('logged_in_broker')
    if not broker:
        return jsonify([])

    conn = get_db_connection()
    symbols = conn.execute('SELECT trading_symbol FROM instruments WHERE broker = ?', (broker,)).fetchall()
    conn.close()
    return jsonify([s['trading_symbol'] for s in symbols])

# Start the background worker thread for order placement
order_worker_thread = threading.Thread(target=order_placement_worker, daemon=True)
order_worker_thread.start()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
