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
    def __init__(self, broker, access_token, order_queue, api_key=None, broker_api=None):
        super().__init__()
        self.broker = broker
        self.access_token = access_token
        self.api_key = api_key
        self.broker_api = broker_api
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

    def sync_order_status(self):
        """
        Queries the broker for the status of all open orders and updates the local database.
        """
        logging.info(f"[{self.broker}] Syncing order status for open orders...")
        conn = get_db_connection()
        open_orders = conn.execute('SELECT id, order_id FROM orders WHERE status = "OPEN"').fetchall()

        if not open_orders:
            logging.info(f"[{self.broker}] No open orders to sync.")
            conn.close()
            return

        for order in open_orders:
            try:
                broker_status = None
                if self.broker == 'Zerodha':
                    order_history = self.broker_api.order_history(order_id=order['order_id'])
                    if order_history:
                        broker_status = order_history[-1]['status']

                elif self.broker == 'Upstox':
                    api_response = self.broker_api.get_order_details(api_version="v2", order_id=order['order_id'])
                    broker_status = api_response.data.status

                if broker_status:
                    logging.info(f"  - Order {order['order_id']}: Local Status=OPEN, Broker Status={broker_status}")
                    # If the order is filled on the broker side, close it locally
                    if broker_status.upper() in ['COMPLETE', 'FILLED']:
                        conn.execute('UPDATE orders SET status = ? WHERE id = ?', ('CLOSED', order['id']))
                        conn.commit()
                        logging.info(f"    - Updated order {order['order_id']} to CLOSED.")
                    # If the order was cancelled or rejected, mark it as such
                    elif broker_status.upper() in ['CANCELLED', 'REJECTED']:
                        conn.execute('UPDATE orders SET status = ? WHERE id = ?', (broker_status.upper(), order['id']))
                        conn.commit()
                        logging.info(f"    - Updated order {order['order_id']} to {broker_status.upper()}.")

            except Exception as e:
                logging.error(f"Error syncing status for order {order['order_id']}: {e}")

        conn.close()
        logging.info(f"[{self.broker}] Order sync complete.")

    def process_tick(self, instrument_token, tick_data):
        """Shared logic to process a tick for any broker."""
        from .db import get_db_connection

        # --- Broker-specific data extraction ---
        ltp = None
        best_bid = None
        if self.broker == 'Zerodha':
            ltp = tick_data.get('last_price')
            if 'depth' in tick_data:
                try:
                    best_bid = tick_data['depth']['buy'][0]['price']
                except (IndexError, KeyError):
                    best_bid = None # No buy orders in depth
        elif self.broker == 'Upstox':
            # Upstox sends either ltpc or ff (full feed)
            if 'ff' in tick_data:
                # When in full feed, ltp is inside the ltpc object within ff
                ltp = tick_data.get('ff', {}).get('ltpc', {}).get('ltp')
                try:
                    best_bid = tick_data['ff']['market_depth']['buy'][0]['price']
                except (IndexError, KeyError):
                    best_bid = None
            else:
                # Fallback to just ltpc if that's all we get
                ltp = tick_data.get('ltpc', {}).get('ltp')

        if not instrument_token or ltp is None:
            return

        conn = get_db_connection()
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

            # --- Stop-Loss Trigger Logic (using LTP) ---
            if ltp <= current_stoploss_price:
                logging.info(f"--- STOP-LOSS TRIGGERED for order {order['order_id']} at price {ltp} (SL: {current_stoploss_price}) ---")
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
                conn.execute('UPDATE orders SET status = ? WHERE id = ?', ('TRIGGERED', order['id']))
                conn.commit()

            # --- Trailing Stop-Loss Logic ---
            else:
                # Auto-select the price to use for trailing based on product type
                product_type = order['product']
                price_for_trailing = ltp  # Default to LTP for CNC and as a fallback

                if product_type in ['MIS', 'NRML']:
                    # For intraday/volatile products, use the more conservative best bid price for BUY orders
                    if order['transaction_type'] == 'BUY' and best_bid is not None:
                        price_for_trailing = best_bid
                    # For SELL orders (short-selling), one might use the best ask price.
                    # This is not implemented as the UI doesn't explicitly support shorting.

                new_stoploss_price = price_for_trailing * (1 - stoploss_percent / 100)
                if new_stoploss_price > current_stoploss_price:
                    profit = ((ltp - initial_price) / initial_price) * 100 if initial_price > 0 else 0
                    conn.execute(
                        'UPDATE orders SET current_stoploss_price = ?, potential_profit = ? WHERE id = ?',
                        (new_stoploss_price, profit, order['id'])
                    )
                    conn.commit()
                    logging.info(f"Trailing stop-loss for {order['symbol']} updated to {new_stoploss_price:.2f} (using price: {price_for_trailing}, product: {product_type})")

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
        self.sync_order_status()
        self._resubscribe()

    def on_tick(self, ticks):
        for tick in ticks:
            self.process_tick(tick.get('instrument_token'), tick)

    def _resubscribe(self):
        if self.subscribed_instruments and self.ws and self.ws.is_connected():
            int_tokens = [int(t) for t in self.subscribed_instruments]
            logging.info(f"Subscribing to Zerodha instruments: {int_tokens}")
            self.ws.subscribe(int_tokens)
            self.ws.set_mode(self.ws.MODE_FULL, int_tokens)

class UpstoxWebSocketManager(WebSocketManager):
    def connect(self):
        logging.info("Connecting to Upstox WebSocket using MarketDataStreamer...")
        try:
            # The MarketDataStreamer handles the authorization and connection internally.
            # It uses the api_client from the broker_api object, which is already
            # configured with the access token.
            self.ws = upstox_client.MarketDataStreamer(
                api_client=self.broker_api.api_client,
                instrument_keys=list(self.subscribed_instruments),
                mode='full'
            )

            # Assign callbacks using the SDK's event handler system
            self.ws.on("open", self._on_open)
            self.ws.on("message", self.on_message)
            self.ws.on("error", lambda err: logging.error(f"Upstox WebSocket error: {err}"))
            self.ws.on("close", lambda code, msg: logging.info(f"Upstox WebSocket closed: {code} - {msg}"))

            # This call is blocking and will run the event loop in the current thread
            self.ws.connect()

        except Exception as e:
            logging.error(f"Error connecting to Upstox WebSocket: {e}")

    def _on_open(self, *args):
        logging.info("Upstox WebSocket connected.")
        self.sync_order_status()
        self._resubscribe()

    def on_message(self, message):
        # The MarketDataStreamer provides the data as a dictionary,
        # so no need for protobuf parsing.
        try:
            # The structure is message -> feeds -> instrument_key -> data
            for instrument_key, feed_data in message.get('feeds', {}).items():
                self.process_tick(instrument_key, feed_data)
        except Exception as e:
            logging.error(f"Error processing Upstox message: {e}")

    def _resubscribe(self):
        if not self.subscribed_instruments:
            return

        if self.ws:
            logging.info(f"Subscribing to Upstox instruments: {list(self.subscribed_instruments)}")
            # The SDK's subscribe method takes the list of instruments and the mode
            self.ws.subscribe(list(self.subscribed_instruments), "full")

    # Override the base class stop method to use the SDK's disconnect
    def stop(self):
        self.running = False
        if self.ws:
            self.ws.disconnect()
