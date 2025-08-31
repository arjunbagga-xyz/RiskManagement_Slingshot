import threading
import time
import logging

class WebSocketManager(threading.Thread):
    def __init__(self, broker, access_token, order_queue, api_key=None):
        super().__init__()
        self.broker = broker
        self.access_token = access_token
        self.api_key = api_key
        self.order_queue = order_queue
        self.ws = None
        self.running = False

    def run(self):
        self.running = True
        # Main loop to connect and reconnect
        while self.running:
            self.connect()
            # Keep the thread alive while connected
            while self.ws and self.ws.is_connected():
                time.sleep(1)
            if self.running:
                logging.info(f"{self.broker} WebSocket disconnected. Reconnecting in 5 seconds...")
                time.sleep(5)

    def connect(self):
        raise NotImplementedError("Subclasses must implement the connect method.")

    def subscribe(self, instrument_tokens):
        raise NotImplementedError("Subclasses must implement the subscribe method.")

    def unsubscribe(self, instrument_tokens):
        raise NotImplementedError("Subclasses must implement the unsubscribe method.")

    def on_tick(self, tick_data):
        if self.broker == 'Zerodha':
            for tick in tick_data:
                self.process_tick(tick.get('instrument_token'), tick.get('last_price'))
        elif self.broker == 'Upstox':
            feeds = tick_data.get('feeds', {})
            for instrument_key, feed in feeds.items():
                ltp = feed.get('ltpc', {}).get('ltp')
                self.process_tick(instrument_key, ltp)

    def process_tick(self, instrument_token, ltp):
        from db import get_db_connection

        if not instrument_token or not ltp:
            return

        conn = get_db_connection()
        order = conn.execute('SELECT * FROM orders WHERE status = "OPEN" AND instrument_key = ?', (str(instrument_token),)).fetchone()

        if not order:
            conn.close()
            return

        try:
            initial_price = float(order['price'])
            stoploss_percent = float(order['initial_stoploss'])
            current_stoploss_price = float(order['current_stoploss_price'] or initial_price * (1 - stoploss_percent / 100))

            if ltp <= current_stoploss_price:
                logging.info(f"--- STOP-LOSS TRIGGERED for order {order['order_id']} ---")

                exit_transaction_type = 'SELL' if order['transaction_type'] == 'BUY' else 'BUY'
                order_details = {
                    'order_id': order['id'],
                    'broker': order['broker'],
                    'exchange': order['exchange'],
                    'symbol': order['symbol'],
                    'transaction_type': exit_transaction_type,
                    'quantity': order['quantity'],
                    'product': order['product'],
                    'instrument_key': order['instrument_key']
                }
                self.order_queue.put(order_details)

                # The worker thread will now handle the status update
                # conn.execute('UPDATE orders SET status = ? WHERE id = ?', ('CLOSED', order['id']))
                # conn.commit()
            else:
                # Update trailing stop-loss
                new_stoploss_price = ltp * (1 - stoploss_percent / 100)
                if new_stoploss_price > current_stoploss_price:
                    current_stoploss_price = new_stoploss_price

                profit = ((ltp - initial_price) / initial_price) * 100
                conn.execute(
                    'UPDATE orders SET price = ?, current_stoploss_price = ?, potential_profit = ? WHERE id = ?',
                    (ltp, current_stoploss_price, profit, order['id'])
                )
                conn.commit()
        except Exception as e:
            logging.error(f"Error processing tick for order {order['order_id']}: {e}")
        finally:
            conn.close()

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

from kiteconnect import KiteTicker

class ZerodhaWebSocketManager(WebSocketManager):
    def __init__(self, access_token, api_key, order_queue):
        super().__init__('Zerodha', access_token, order_queue, api_key)
        self.subscribed_tokens = set()

    def connect(self):
        logging.info("Connecting to Zerodha WebSocket...")
        self.ws = KiteTicker(self.api_key, self.access_token)
        self.ws.on_ticks = self.on_tick
        self.ws.on_connect = self.on_connect
        self.ws.on_close = self.on_close
        self.ws.connect(threaded=True)

    def on_connect(self, ws, response):
        logging.info("Zerodha WebSocket connected.")
        if self.subscribed_tokens:
            self.subscribe(list(self.subscribed_tokens))

    def on_close(self, ws, code, reason):
        logging.info(f"Zerodha WebSocket closed: {code} - {reason}")

    def subscribe(self, instrument_tokens):
        logging.info(f"Subscribing to Zerodha instruments: {instrument_tokens}")
        # Convert tokens to integers for the library
        int_tokens = [int(t) for t in instrument_tokens]
        self.subscribed_tokens.update(int_tokens)
        if self.ws and self.ws.is_connected():
            self.ws.subscribe(int_tokens)
            self.ws.set_mode(self.ws.MODE_LTP, int_tokens)

    def unsubscribe(self, instrument_tokens):
        logging.info(f"Unsubscribing from Zerodha instruments: {instrument_tokens}")
        self.subscribed_tokens.difference_update(instrument_tokens)
        if self.ws and self.ws.is_connected():
            self.ws.unsubscribe(instrument_tokens)

import upstox_client
from upstox_client.rest import ApiException
import websocket
import json

class UpstoxWebSocketManager(WebSocketManager):
    def __init__(self, access_token, order_queue):
        super().__init__('Upstox', access_token, order_queue)
        self.api_client = upstox_client.ApiClient()
        self.api_client.set_access_token(self.access_token)
        self.subscribed_instruments = set()

    def get_market_data_feed_authorize(self):
        api_instance = upstox_client.WebsocketApi(self.api_client)
        api_response = api_instance.get_market_data_feed_authorize(api_version="v2")
        return api_response.data.authorized_redirect_uri

    def connect(self):
        logging.info("Connecting to Upstox WebSocket...")
        try:
            ws_url = self.get_market_data_feed_authorize()
            self.ws = websocket.WebSocketApp(ws_url,
                                             on_message=self.on_message,
                                             on_error=self.on_error,
                                             on_close=self.on_close,
                                             on_open=self.on_open)
            self.ws.run_forever()
        except ApiException as e:
            logging.error(f"Error getting Upstox WebSocket URL: {e}")

    def on_open(self, ws):
        logging.info("Upstox WebSocket connected.")
        if self.subscribed_instruments:
            self.subscribe(list(self.subscribed_instruments))

    def on_message(self, ws, message):
        decoded_data = self.decode_message(message)
        self.on_tick(decoded_data)

    def on_error(self, ws, error):
        logging.error(f"Upstox WebSocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        logging.info(f"Upstox WebSocket closed: {close_status_code} - {close_msg}")

    def subscribe(self, instrument_keys):
        logging.info(f"Subscribing to Upstox instruments: {instrument_keys}")
        self.subscribed_instruments.update(instrument_keys)
        if self.ws and self.ws.sock and self.ws.sock.connected:
            request = {
                "guid": "some-guid",
                "method": "sub",
                "data": {
                    "mode": "ltpc",
                    "instrumentKeys": instrument_keys
                }
            }
            self.ws.send(json.dumps(request))

    def unsubscribe(self, instrument_keys):
        logging.info(f"Unsubscribing from Upstox instruments: {instrument_keys}")
        self.subscribed_instruments.difference_update(instrument_keys)
        if self.ws and self.ws.sock and self.ws.sock.connected:
            request = {
                "guid": "some-guid",
                "method": "unsub",
                "data": {
                    "instrumentKeys": instrument_keys
                }
            }
            self.ws.send(json.dumps(request))

    def decode_message(self, message):
        # Upstox sends protobuf messages, so they need to be decoded
        try:
            from upstox_client.feeder.proto.MarketDataFeed_pb2 import FeedResponse
            from google.protobuf.json_format import MessageToDict

            feed = FeedResponse()
            feed.ParseFromString(message)
            return MessageToDict(feed)
        except ImportError:
            logging.error("Could not import FeedResponse from upstox_client.feeder.proto. Please ensure the upstox-python-sdk is installed correctly.")
            return {}
