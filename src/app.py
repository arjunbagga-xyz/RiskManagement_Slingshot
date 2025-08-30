from flask import Flask, render_template, request, redirect, session, flash
from kiteconnect import KiteConnect
import upstox_client
import os
import time
import threading
from src.db import get_db_connection, update_instrument_list

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.secret_key = os.urandom(24)

# --- Configuration ---
ZERODHA_API_KEY = os.getenv("ZERODHA_API_KEY", "your_zerodha_api_key")
ZERODHA_API_SECRET = os.getenv("ZERODHA_API_SECRET", "your_zerodha_api_secret")
UPSTOX_API_KEY = os.getenv("UPSTOX_API_KEY", "your_upstox_api_key")
UPSTOX_API_SECRET = os.getenv("UPSTOX_API_SECRET", "your_upstox_api_secret")
UPSTOX_REDIRECT_URI = os.getenv("UPSTOX_REDIRECT_URI", "http://localhost:5000/callback/upstox")

# --- Global variables for access tokens (simplified for single-user context) ---
ACCESS_TOKENS = {
    "zerodha": None,
    "upstox": None
}

# --- Zerodha Login ---
kite = KiteConnect(api_key=ZERODHA_API_KEY)

# --- Background Price Refresher ---
def background_price_refresher():
    while True:
        time.sleep(10)
        with app.app_context():
            conn = get_db_connection()
            orders = conn.execute('SELECT * FROM orders WHERE status = "OPEN"').fetchall()

            if not orders:
                conn.close()
                continue

            broker = orders[0]['broker'] # Assuming all open orders are with the same broker
            access_token = ACCESS_TOKENS.get(broker.lower())

            if not access_token:
                conn.close()
                continue

            for order in orders:
                try:
                    new_price = 0
                    if order['broker'] == 'Zerodha':
                        kite.set_access_token(access_token)
                        instrument = f"{order['exchange']}:{order['symbol']}"
                        ltp_data = kite.ltp(instrument)
                        if ltp_data and instrument in ltp_data:
                            new_price = ltp_data[instrument]['last_price']

                    elif order['broker'] == 'Upstox':
                        instrument = conn.execute('SELECT instrument_key FROM instruments WHERE trading_symbol = ? AND exchange = ?',
                                                  (order['symbol'].upper(), order['exchange'].upper())).fetchone()
                        if instrument:
                            instrument_token = instrument['instrument_key']
                            configuration = upstox_client.Configuration()
                            configuration.access_token = access_token
                            market_quote_api = upstox_client.MarketQuoteApi(upstox_client.ApiClient(configuration))
                            api_response = market_quote_api.get_ltp(api_version="v2", instrument_key=instrument_token)
                            new_price = api_response.data.last_price

                    if new_price == 0:
                        continue

                    initial_price = float(order['price'])
                    stoploss_percent = float(order['initial_stoploss'])
                    current_stoploss_price = float(order['current_stoploss_price'] or initial_price * (1 - stoploss_percent / 100))

                    if new_price <= current_stoploss_price:
                        exit_transaction_type = 'SELL' if order['transaction_type'] == 'BUY' else 'BUY'
                        if order['broker'] == 'Zerodha':
                            kite.place_order(
                                variety="regular", exchange=order['exchange'],
                                tradingsymbol=order['symbol'],
                                transaction_type=exit_transaction_type,
                                quantity=order['quantity'],
                                product=order['product'],
                                order_type='MARKET'
                            )
                        elif order['broker'] == 'Upstox':
                            instrument = conn.execute('SELECT instrument_key FROM instruments WHERE trading_symbol = ? AND exchange = ?',
                                                      (order['symbol'].upper(), order['exchange'].upper())).fetchone()
                            if instrument:
                                instrument_token = instrument['instrument_key']
                                configuration = upstox_client.Configuration()
                                configuration.access_token = access_token
                                api_instance = upstox_client.OrderApi(upstox_client.ApiClient(configuration))
                                api_instance.place_order(
                                    api_version="v2",
                                    body=upstox_client.PlaceOrderRequest(
                                        quantity=order['quantity'],
                                        product={"MIS": "I", "CNC": "D"}.get(order['product'], "I"),
                                        validity="DAY",
                                        instrument_token=instrument_token,
                                        order_type='MARKET',
                                        transaction_type='s' if exit_transaction_type == 'SELL' else 'b'
                                    )
                                )

                        conn.execute('UPDATE orders SET status = ? WHERE id = ?', ('CLOSED', order['id']))
                        conn.commit()
                        print(f"Stop-loss triggered for order {order['order_id']}")
                        continue

                    new_stoploss_price = new_price * (1 - stoploss_percent / 100)
                    if new_stoploss_price > current_stoploss_price:
                        current_stoploss_price = new_stoploss_price

                    profit = ((new_price - initial_price) / initial_price) * 100

                    conn.execute(
                        'UPDATE orders SET price = ?, current_stoploss_price = ?, potential_profit = ? WHERE id = ?',
                        (new_price, current_stoploss_price, profit, order['id'])
                    )
                    conn.commit()

                except Exception as e:
                    print(f"Error processing order {order['order_id']} in background: {e}")

            conn.close()


@app.route('/login/zerodha')
def login_zerodha():
    return redirect(kite.login_url())

@app.route('/callback/zerodha')
def callback_zerodha():
    request_token = request.args.get('request_token')
    try:
        data = kite.generate_session(request_token, api_secret=ZERODHA_API_SECRET)
        ACCESS_TOKENS["zerodha"] = data['access_token']
        session['logged_in_broker'] = 'Zerodha'
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
        ACCESS_TOKENS["upstox"] = api_response.access_token
        session['logged_in_broker'] = 'Upstox'
        flash("Successfully logged in with Upstox.", "success")
        return redirect('/')
    except Exception as e:
        flash(f"Error during Upstox authentication: {e}", "error")
        return redirect('/login')

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
                    product={"MIS": "I", "CNC": "D"}.get(request.form['product'], "I"),
                    validity="DAY",
                    price=float(request.form['price']) if request.form['price'] else 0,
                    instrument_token=instrument_token,
                    order_type=request.form['order_type'],
                    transaction_type='b' if request.form['transaction_type'] == 'BUY' else 's',
                    disclosed_quantity=0, trigger_price=0, is_amo=False
                )
            )
            order_id = api_response.data.order_id

        conn.execute(
            'INSERT INTO orders (order_id, symbol, quantity, price, initial_stoploss, current_stoploss, status, broker, transaction_type, exchange, product) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (order_id, request.form['symbol'], int(request.form['quantity']), float(request.form['price'] or 0), float(request.form['stoploss']), float(request.form['stoploss']), 'OPEN', broker, request.form['transaction_type'], request.form['exchange'], request.form['product'])
        )
        conn.commit()
        flash(f"{broker} order placed successfully! Order ID: {order_id}", "success")

    except Exception as e:
        flash(f"Error placing {broker} order: {e}", "error")

    conn.close()
    return redirect('/')

@app.route('/update_instruments')
def update_instruments_route():
    message = update_instrument_list()
    flash(message, "info")
    return redirect('/')

@app.route('/logout')
def logout():
    ACCESS_TOKENS["zerodha"] = None
    ACCESS_TOKENS["upstox"] = None
    session.clear()
    flash("You have been logged out.", "success")
    return redirect('/')

if __name__ == '__main__':
    refresher_thread = threading.Thread(target=background_price_refresher, daemon=True)
    refresher_thread.start()
    app.run(debug=True, port=5000)
