import threading
import time
import logging
import json
from kiteconnect import KiteTicker
import upstox_client
from upstox_client.rest import ApiException
import websocket

class WebSocketManager(threading.Thread):
    """Base class for WebSocket managers for different brokers."""
    def __init__(self, broker, access_token, order_queue, api_key=None):
        super().__init__()
        self.broker = broker
        self.access_token = access_token
        self.api_key = api_key
        self.order_queue = order_queue
        self.ws = None
        self.running = False
        self.subscribed_instruments = set()

    def run(self):
        self.running = True
        while self.running:
            self.connect()
            # Keep the thread alive while connected, or until stop is called
            while self.ws and getattr(self.ws, 'is_connected', lambda: False)() and self.running:
                time.sleep(1)
            if self.running:
                logging.info(f"{self.broker} WebSocket disconnected. Reconnecting in 5 seconds...")
                time.sleep(5)

    def connect(self):
        raise NotImplementedError("Subclasses must implement the connect method.")

    def subscribe(self, instrument_keys):
        self.subscribed_instruments.update(instrument_keys)
        self._resubscribe()

    def unsubscribe(self, instrument_keys):
        self.subscribed_instruments.difference_update(instrument_keys)
        self._resubscribe()

    def _resubscribe(self):
        raise NotImplementedError("Subclasses must implement the resubscribe method.")

    def on_tick(self, ticks):
        """This method is called when a new tick is received."""
        # This logic is now broker-specific
        raise NotImplementedError("Subclasses must implement the on_tick method.")

    def process_tick(self, instrument_token, ltp):
        """Shared logic to process a tick for any broker."""
        from db import get_db_connection

        if not instrument_token or not ltp:
            return

        conn = get_db_connection()
        # Find the order associated with this instrument tick
        order = conn.execute(
            'SELECT * FROM orders WHERE status = "OPEN" AND instrument_key = ?',
            (str(instrument_token),)
        ).fetchone()

        if not order:
            conn.close()
            return

        try:
            initial_price = float(order['price'])
            stoploss_percent = float(order['initial_stoploss'])
            current_stoploss_price = float(order['current_stoploss_price'])

            # --- Stop-Loss Trigger Logic ---
            if ltp <= current_stoploss_price:
                logging.info(f"--- STOP-LOSS TRIGGERED for order {order['order_id']} at price {ltp} (SL: {current_stoploss_price}) ---")

                exit_transaction_type = 'SELL' if order['transaction_type'] == 'BUY' else 'BUY'

                order_details = {
                    'order_id': order['id'], # This is the DB id, not the broker order_id
                    'broker': order['broker'],
                    'exchange': order['exchange'],
                    'symbol': order['symbol'],
                    'transaction_type': exit_transaction_type,
                    'quantity': order['quantity'],
                    'product': order['product'],
                    'instrument_key': order['instrument_key']
                }

                # Put the exit order on the queue for the worker to process
                self.order_queue.put(order_details)

                # Update the status in the DB immediately to prevent re-triggering
                conn.execute('UPDATE orders SET status = ? WHERE id = ?', ('TRIGGERED', order['id']))
                conn.commit()

            # --- Trailing Stop-Loss Logic ---
            else:
                new_stoploss_price = ltp * (1 - stoploss_percent / 100)
                if new_stoploss_price > current_stoploss_price:
                    profit = ((ltp - initial_price) / initial_price) * 100 if initial_price > 0 else 0
                    conn.execute(
                        'UPDATE orders SET current_stoploss_price = ?, potential_profit = ? WHERE id = ?',
                        (new_stoploss_price, profit, order['id'])
                    )
                    conn.commit()
                    logging.info(f"Trailing stop-loss for {order['symbol']} updated to {new_stoploss_price:.2f}")

        except Exception as e:
            logging.error(f"Error processing tick for order {order['order_id']}: {e}")
        finally:
            conn.close()

    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()

class ZerodhaWebSocketManager(WebSocketManager):
    def connect(self):
        logging.info("Connecting to Zerodha WebSocket...")
        self.ws = KiteTicker(self.api_key, self.access_token)
        self.ws.on_ticks = self.on_tick
        self.ws.on_connect = self._on_connect
        self.ws.on_close = lambda ws, code, reason: logging.info(f"Zerodha WebSocket closed: {code} - {reason}")
        self.ws.connect(threaded=True)

    def _on_connect(self, ws, response):
        logging.info("Zerodha WebSocket connected.")
        self._resubscribe()

    def on_tick(self, ticks):
        for tick in ticks:
            self.process_tick(tick.get('instrument_token'), tick.get('last_price'))

    def _resubscribe(self):
        if self.subscribed_instruments and self.ws and self.ws.is_connected():
            int_tokens = [int(t) for t in self.subscribed_instruments]
            logging.info(f"Subscribing to Zerodha instruments: {int_tokens}")
            self.ws.subscribe(int_tokens)
            self.ws.set_mode(self.ws.MODE_LTP, int_tokens)

class UpstoxWebSocketManager(WebSocketManager):
    def _get_ws_url(self):
        api_instance = upstox_client.WebsocketApi(upstox_client.ApiClient(access_token=self.access_token))
        api_response = api_instance.get_market_data_feed_authorize(api_version="v2")
        return api_response.data.authorized_redirect_uri

    def connect(self):
        logging.info("Connecting to Upstox WebSocket...")
        try:
            ws_url = self._get_ws_url()
            self.ws = websocket.WebSocketApp(ws_url,
                                             on_message=self.on_message,
                                             on_error=lambda ws, err: logging.error(f"Upstox WebSocket error: {err}"),
                                             on_close=lambda ws, code, msg: logging.info(f"Upstox WebSocket closed: {code} - {msg}"),
                                             on_open=self._on_open)
            self.ws.run_forever()
        except ApiException as e:
            logging.error(f"Error getting Upstox WebSocket URL: {e}")

    def _on_open(self, ws):
        logging.info("Upstox WebSocket connected.")
        self._resubscribe()

    def on_message(self, ws, message):
        try:
            from upstox_client.feeder.proto.MarketDataFeed_pb2 import FeedResponse
            from google.protobuf.json_format import MessageToDict

            feed = FeedResponse()
            feed.ParseFromString(message)
            data = MessageToDict(feed)

            feeds = data.get('feeds', {})
            for instrument_key, feed_data in feeds.items():
                ltp = feed_data.get('ltpc', {}).get('ltp')
                self.process_tick(instrument_key, ltp)

        except ImportError:
            logging.error("Could not import FeedResponse from upstox_client.feeder.proto.")
        except Exception as e:
            logging.error(f"Error decoding Upstox message: {e}")

    def _resubscribe(self):
        if self.subscribed_instruments and self.ws and self.ws.sock and self.ws.sock.connected:
            request = {
                "guid": "some-guid",
                "method": "sub",
                "data": { "mode": "ltpc", "instrumentKeys": list(self.subscribed_instruments) }
            }
            self.ws.send(json.dumps(request))
            logging.info(f"Subscribing to Upstox instruments: {list(self.subscribed_instruments)}")
