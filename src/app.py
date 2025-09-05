from flask import Flask, render_template, request, redirect, session, flash, jsonify
from kiteconnect import KiteConnect
import upstox_client
import os
import time
import threading
import logging
import queue
from functools import wraps
from db import get_db_connection, update_instrument_list, init_db
from websocket_manager import ZerodhaWebSocketManager, UpstoxWebSocketManager
from security import encrypt_value, decrypt_value

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.secret_key = os.urandom(24)

# --- Initialize DB ---
with app.app_context():
    init_db()

# --- Logging ---
logging.basicConfig(filename='app.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration Loading ---
def load_settings_from_db():
    """Loads all settings from the database and returns them as a dict."""
    try:
        conn = get_db_connection()
        settings_from_db = conn.execute('SELECT key, value FROM settings').fetchall()
        conn.close()

        settings = {}
        for row in settings_from_db:
            settings[row['key']] = decrypt_value(row['value'])
        return settings
    except Exception as e:
        logging.error(f"Could not load settings from database: {e}. Please run the app and configure via /settings.")
        return {}

APP_SETTINGS = load_settings_from_db()

ZERODHA_API_KEY = APP_SETTINGS.get("ZERODHA_API_KEY")
ZERODHA_API_SECRET = APP_SETTINGS.get("ZERODHA_API_SECRET")
UPSTOX_API_KEY = APP_SETTINGS.get("UPSTOX_API_KEY")
UPSTOX_API_SECRET = APP_SETTINGS.get("UPSTOX_API_SECRET")
UPSTOX_REDIRECT_URI = APP_SETTINGS.get("UPSTOX_REDIRECT_URI", "http://localhost:5000/callback/upstox")

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
# Initialize KiteConnect. It will be updated with the API key from settings.
kite = KiteConnect(api_key=None)

# --- Settings Management ---
def get_all_settings():
    conn = get_db_connection()
    settings_from_db = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    settings = {}
    for row in settings_from_db:
        # We just want to know if the key exists, not its value here
        # So we'll decrypt but just store a placeholder if it's not empty
        decrypted_value = decrypt_value(row['value'])
        if decrypted_value:
            settings[row['key']] = "********" # Placeholder for UI
    # Also get the non-secret redirect URI
    redirect_uri_row = next((r for r in settings_from_db if r['key'] == 'UPSTOX_REDIRECT_URI'), None)
    if redirect_uri_row:
        settings['UPSTOX_REDIRECT_URI'] = decrypt_value(redirect_uri_row['value'])

    return settings

def save_setting(key, value):
    if not value: # Don't save empty strings
        return
    encrypted_value = encrypt_value(value)
    conn = get_db_connection()
    # The value from encrypt_value is bytes, but sqlite will store it as TEXT
    conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, encrypted_value.decode('utf-8')))
    conn.commit()
    conn.close()

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

                    v3_request_body = upstox_client.PlaceOrderRequest(
                        quantity=order_details['quantity'],
                        product=get_upstox_product(order_details['product']),
                        validity="DAY",
                        instrument_token=order_details['instrument_key'],
                        order_type='MARKET',
                        transaction_type='s' if order_details['transaction_type'] == 'SELL' else 'b',
                        price=0,
                        disclosed_quantity=0,
                        trigger_price=0,
                        is_amo=False
                    )

                    api_instance.place_order(
                        api_version="v3",
                        body=v3_request_body
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

# --- Decorators ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('logged_in_broker') is None:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def login_required_api(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('logged_in_broker') is None:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated_function

# --- Routes -- -

@app.route('/init-db')
def init_db_route():
    init_db()
    flash('Database initialized successfully!', 'success')
    return redirect('/')

@app.route('/login/zerodha')
def login_zerodha():
    # Dynamically update the api_key before generating the login URL
    kite.api_key = APP_SETTINGS.get("ZERODHA_API_KEY")
    if not kite.api_key:
        flash("Zerodha API Key is not configured. Please configure it in Settings.", "error")
        return redirect('/settings')
    return redirect(kite.login_url())

@app.route('/callback/zerodha')
def callback_zerodha():
    request_token = request.args.get('request_token')
    try:
        # Use the globally loaded secret key
        api_secret = APP_SETTINGS.get("ZERODHA_API_SECRET")
        if not api_secret:
            flash("Zerodha API Secret is not configured.", "error")
            return redirect('/settings')

        data = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data['access_token']
        ACCESS_TOKENS["zerodha"] = access_token
        session['logged_in_broker'] = 'Zerodha'

        if WEBSOCKET_MANAGERS['zerodha']:
            WEBSOCKET_MANAGERS['zerodha'].stop()

        WEBSOCKET_MANAGERS['zerodha'] = ZerodhaWebSocketManager(
            broker='Zerodha',
            access_token=access_token,
            order_queue=order_queue,
            api_key=kite.api_key,
            broker_api=kite
        )
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
    api_key = APP_SETTINGS.get("UPSTOX_API_KEY")
    redirect_uri = APP_SETTINGS.get("UPSTOX_REDIRECT_URI")
    if not api_key or not redirect_uri:
        flash("Upstox API Key or Redirect URI is not configured. Please configure it in Settings.", "error")
        return redirect('/settings')
    auth_url = f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={api_key}&redirect_uri={redirect_uri}"
    return redirect(auth_url)

@app.route('/callback/upstox')
def callback_upstox():
    code = request.args.get('code')
    api_instance = upstox_client.LoginApi()
    try:
        api_key = APP_SETTINGS.get("UPSTOX_API_KEY")
        api_secret = APP_SETTINGS.get("UPSTOX_API_SECRET")
        redirect_uri = APP_SETTINGS.get("UPSTOX_REDIRECT_URI")

        if not all([api_key, api_secret, redirect_uri]):
            flash("Upstox API settings are not fully configured.", "error")
            return redirect('/settings')

        api_response = api_instance.token(
            api_version="v2",
            code=code,
            client_id=api_key,
            client_secret=api_secret,
            redirect_uri=redirect_uri,
            grant_type='authorization_code'
        )
        access_token = api_response.access_token
        ACCESS_TOKENS["upstox"] = access_token
        session['logged_in_broker'] = 'Upstox'

        if WEBSOCKET_MANAGERS['upstox']:
            WEBSOCKET_MANAGERS['upstox'].stop()

        # Create an API client for Upstox to pass to the manager
        configuration = upstox_client.Configuration()
        configuration.access_token = access_token
        upstox_api_client = upstox_client.ApiClient(configuration)
        upstox_order_api = upstox_client.OrderApi(upstox_api_client)

        WEBSOCKET_MANAGERS['upstox'] = UpstoxWebSocketManager(
            broker='Upstox',
            access_token=access_token,
            order_queue=order_queue,
            broker_api=upstox_order_api
        )
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
@login_required
def index():
    is_logged_in = session.get('logged_in_broker') is not None
    conn = get_db_connection()
    orders = conn.execute('SELECT * FROM orders').fetchall()
    conn.close()
    return render_template('index.html', is_logged_in=is_logged_in, orders=orders)

@app.route('/place_order', methods=['POST'])
@login_required
def place_order():
    conn = get_db_connection()
    broker = session.get('logged_in_broker')

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

            # Construct the V3 request body
            v3_request_body = upstox_client.PlaceOrderRequest(
                quantity=int(request.form['quantity']),
                product=get_upstox_product(request.form['product']),
                validity="DAY",
                price=float(request.form['price']) if request.form['price'] else 0,
                instrument_token=instrument_token,
                order_type=request.form['order_type'],
                transaction_type='b' if request.form['transaction_type'] == 'BUY' else 's',
                disclosed_quantity=0,
                trigger_price=0,
                is_amo=False
            )

            # Call the v3 place_order endpoint
            api_response = api_instance.place_order(
                api_version="v3",
                body=v3_request_body
            )
            # V3 returns a list of order IDs. For non-sliced orders, it will be a single element list.
            # We'll safely take the first one.
            order_id = api_response.data.order_ids[0] if api_response.data.order_ids else None
            if not order_id:
                raise Exception("Failed to place order with Upstox, no order ID returned.")

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
@login_required
def update_instruments_route():
    broker = session.get('logged_in_broker')

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

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        # Save settings from the form
        save_setting('ZERODHA_API_KEY', request.form.get('zerodha_api_key'))
        save_setting('ZERODHA_API_SECRET', request.form.get('zerodha_api_secret'))
        save_setting('UPSTOX_API_KEY', request.form.get('upstox_api_key'))
        save_setting('UPSTOX_API_SECRET', request.form.get('upstox_api_secret'))
        save_setting('UPSTOX_REDIRECT_URI', request.form.get('upstox_redirect_uri'))

        flash("Settings saved successfully. Please restart the application for changes to take effect.", "success")
        return redirect('/settings')

    # For GET request
    is_logged_in = session.get('logged_in_broker') is not None
    current_settings = get_all_settings()
    return render_template('settings.html', is_logged_in=is_logged_in, settings=current_settings)

@app.route('/api/symbols')
@login_required_api
def api_symbols():
    broker = session.get('logged_in_broker')

    conn = get_db_connection()
    symbols = conn.execute('SELECT trading_symbol FROM instruments WHERE broker = ?', (broker,)).fetchall()
    conn.close()
    return jsonify([s['trading_symbol'] for s in symbols])

@app.route('/shutdown')
def shutdown():
    shutdown_func = request.environ.get('werkzeug.server.shutdown')
    if shutdown_func is None:
        flash('Cannot shut down server. Not running with the Werkzeug Server.', 'error')
        return redirect('/')

    # Stop the websocket managers gracefully
    for manager in WEBSOCKET_MANAGERS.values():
        if manager and manager.is_alive():
            manager.stop()

    # Stop the order placement worker
    order_queue.put(None)

    shutdown_func()
    return "Server shutting down..."

# Start the background worker thread for order placement
order_worker_thread = threading.Thread(target=order_placement_worker, daemon=True)
order_worker_thread.start()

if __name__ == '__main__':
    app.run(debug=True, port=5000)