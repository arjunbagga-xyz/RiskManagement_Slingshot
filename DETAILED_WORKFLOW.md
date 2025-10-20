# Detailed Workflow: Order Placement and Management

This document provides a comprehensive, step-by-step explanation of the trading tool's internal mechanisms, from the moment an order is placed to its eventual closure via the trailing stop-loss system.

## Core Components

The system's logic is primarily handled by three components:

1.  **Flask Web Application (`app.py`)**: Manages user authentication, handles HTTP requests (like placing an order), and serves the user interface.
2.  **WebSocket Manager (`websocket_manager.py`)**: Runs in a dedicated background thread for each user session. It maintains a persistent connection to the broker's real-time data feed, receives price ticks, and implements the core stop-loss logic.
3.  **Order Placement Worker (`app.py`)**: A separate background thread that safely places stop-loss orders from a queue, preventing the real-time WebSocket thread from blocking.
4.  **SQLite Database (`db.py`, `schema.sql`)**: Persists order information, settings, and instrument lists, ensuring data is not lost if the application restarts.

---

## Step-by-Step Workflow

### 1. User Authentication and Session Initialization

- **Action**: The user logs in through the web interface using their Zerodha or Upstox credentials.
- **Mechanism**: The Flask application handles the OAuth2 redirect flow with the chosen broker. Upon successful authentication, the broker provides an `access_token`.
- **Outcome**:
    - The `access_token` is stored in the server's memory, associated with the user's session.
    - A dedicated `WebSocketManager` thread is initialized and started for the session. This thread immediately uses the `access_token` to authenticate and establish a persistent WebSocket connection with the broker's streaming API.
    - The application also performs an initial **Order Status Synchronization** (see step 5) to ensure the local database is aligned with the broker's records for any previously open positions.

### 2. Placing a New Order

- **Action**: The user fills out the order form in the UI (selecting the symbol, quantity, transaction type, etc.) and clicks "Place Order".
- **Mechanism**:
    1.  The browser sends a `POST` request to the `/place_order` endpoint in the Flask application.
    2.  The application validates the form data.
    3.  It uses the stored `access_token` to send an API request to the broker to place the initial market or limit order.
    4.  The broker executes the trade and returns a unique `order_id` upon success.
- **Outcome**:
    - An initial position is opened with the broker.
    - The application immediately calculates the **initial stop-loss price** based on the entry price and the user-defined stop-loss percentage (e.g., `initial_stoploss_price = entry_price * (1 - stoploss_percent / 100)`).
    - All order details, including the broker's `order_id`, symbol, entry price, the initial stop-loss percentage, the calculated `initial_stoploss_price`, and a status of `"OPEN"`, are saved to the local SQLite database.
    - The application instructs the running `WebSocketManager` to **subscribe** to real-time price ticks for the instrument associated with the order.

### 3. Real-Time Trailing Stop-Loss Monitoring

- **Action**: The `WebSocketManager` continuously receives price updates (ticks) for the subscribed instrument. This process begins immediately after the order is placed.
- **Mechanism**: The core logic resides in the `process_tick` method within the `WebSocketManager`. For every single tick received:
    1.  **Fetch Order**: It retrieves the corresponding `"OPEN"` order from the database using the instrument token from the tick data.
    2.  **Stop-Loss Check**: It performs the critical check: `if (current_price <= current_stoploss_price)`.
        - If this condition is `True`, the **Stop-Loss is Triggered** (see Step 4).
    3.  **Trailing Logic**: If the stop-loss is *not* triggered, the system checks if it should "trail" the stop-loss up to lock in profits.
        - **Price Selection**: It intelligently selects the price to use for this calculation. For volatile intraday products (`MIS`), it uses the more conservative **best bid price**. For long-term products (`CNC`), it uses the **last traded price (LTP)**. This prevents the stop-loss from being adjusted upwards on a temporary, unsustainable price spike.
        - **Calculation**: It calculates a *potential* new stop-loss price: `new_stoploss_price = price_for_trailing * (1 - stoploss_percent / 100)`.
        - **Update**: It compares the newly calculated price with the one stored in the database: `if (new_stoploss_price > current_stoploss_price)`.
        - If the new price is higher, the `current_stoploss_price` value for the order in the database is **updated**. This is the "trailing" action. The stop-loss level has now moved up, protecting a portion of the unrealized gains.

### 4. Stop-Loss Trigger and Order Execution

- **Action**: The price of the instrument drops and hits the `current_stoploss_price` stored in the database.
- **Mechanism**:
    1.  **Immediate Status Update**: To prevent duplicate triggers from subsequent ticks, the order's status in the database is immediately updated from `"OPEN"` to `"TRIGGERED"`.
    2.  **Queue for Safety**: A thread-safe exit order is created (a `MARKET SELL` if the original order was a `BUY`). This order is **not** executed directly by the WebSocket thread. Instead, it is placed into a `queue.Queue`. This is a crucial design choice to ensure the real-time price-processing thread never gets blocked by a slow network request.
    3.  **Worker Thread Execution**: The dedicated `order_placement_worker` thread, which has been waiting in the background, immediately picks up the order from the queue.
    4.  **Exit Order Placement**: The worker thread sends the API request to the broker to place the market order and exit the position.
    5.  **Final Status Update**: Upon confirmation from the broker that the exit order was placed, the worker thread updates the order's status in the database from `"TRIGGERED"` to `"CLOSED"`.

### 5. System Resilience: Order Status Synchronization

- **Action**: This occurs automatically upon initial connection or reconnection of the WebSocket.
- **Mechanism**: The system is designed to be resilient to disconnects.
    1.  The `sync_order_status` function is called.
    2.  It queries the local database for all orders marked as `"OPEN"`.
    3.  For each open order, it makes an API call to the broker to get its *actual*, current status.
    4.  It compares the local status with the broker's status. If, for example, an order was manually closed or canceled on the broker's platform while the tool was offline, the tool will update its local database to match (e.g., changing the status to `"CLOSED"` or `"CANCELLED"`).
- **Outcome**: This ensures the application's state remains consistent with the reality of the user's brokerage account, preventing erroneous stop-loss orders from being placed for positions that are already closed.

---

## Pseudo-code for Key Functions

This pseudo-code illustrates the logic of the main functions involved in the workflow.

### `handle_place_order_request(form_data)`

*This function is executed in the Flask web server when the user submits the order form.*

```
FUNCTION handle_place_order_request(form_data):
  // 1. Place the initial order with the broker
  broker_api = GET_BROKER_API_CLIENT()
  order_result = broker_api.place_order(
    symbol = form_data.symbol,
    quantity = form_data.quantity,
    type = form_data.order_type,
    ...
  )

  IF order_result is NOT successful:
    DISPLAY "Error placing order" to user
    RETURN

  // 2. Calculate and store order details in the local database
  order_id = order_result.order_id
  entry_price = order_result.average_price
  stoploss_percent = form_data.stoploss_percent

  initial_stoploss_price = entry_price * (1 - stoploss_percent / 100)

  database.execute(
    INSERT INTO orders (
      order_id, symbol, entry_price, initial_stoploss,
      current_stoploss_price, status
    ) VALUES (
      order_id, form_data.symbol, entry_price, stoploss_percent,
      initial_stoploss_price, "OPEN"
    )
  )

  // 3. Subscribe to price updates for this instrument
  websocket_manager = GET_SESSION_WEBSOCKET_MANAGER()
  instrument_key = GET_INSTRUMENT_KEY_FOR_SYMBOL(form_data.symbol)
  websocket_manager.subscribe(instrument_key)

  DISPLAY "Order placed successfully" to user
END FUNCTION
```

### `process_tick(tick_data)`

*This function is executed in the WebSocketManager's background thread for every price tick received.*

```
FUNCTION process_tick(tick_data):
  instrument_key = tick_data.instrument_key
  ltp = tick_data.last_traded_price
  best_bid_price = tick_data.best_bid_price

  // 1. Get the order associated with this instrument from our database
  order = database.query(
    SELECT * FROM orders WHERE instrument_key = instrument_key AND status = "OPEN"
  )

  IF order is NOT found:
    RETURN // No open order for this tick, do nothing

  // 2. Check if the stop-loss has been triggered
  current_stoploss = order.current_stoploss_price
  IF ltp <= current_stoploss:
    // Update status immediately to prevent re-triggering
    database.execute(
      UPDATE orders SET status = "TRIGGERED" WHERE order_id = order.order_id
    )

    // Create a thread-safe exit order and queue it for the worker
    exit_order = CREATE_EXIT_ORDER_DETAILS(order)
    order_queue.put(exit_order)

    LOG "Stop-loss triggered for order " + order.order_id
    RETURN // Stop processing this tick further

  // 3. If not triggered, perform the trailing logic
  price_for_trailing = ltp // Default for CNC orders
  IF order.product_type is "MIS":
    price_for_trailing = best_bid_price // Use safer price for intraday

  stoploss_percent = order.initial_stoploss
  potential_new_stoploss = price_for_trailing * (1 - stoploss_percent / 100)

  IF potential_new_stoploss > current_stoploss:
    database.execute(
      UPDATE orders SET current_stoploss_price = potential_new_stoploss
      WHERE order_id = order.order_id
    )
    LOG "Trailed stop-loss for " + order.symbol + " to " + potential_new_stoploss
  END IF
END FUNCTION
```

### `order_placement_worker()`

*This function runs in its own dedicated background thread and processes orders from the queue.*

```
FUNCTION order_placement_worker():
  WHILE application is running:
    // The .get() call will block and wait until an item is in the queue
    exit_order_details = order_queue.get()

    LOG "Worker picked up exit order for " + exit_order_details.symbol

    // Place the actual exit order with the broker
    broker_api = GET_BROKER_API_CLIENT()
    result = broker_api.place_market_order(
      symbol = exit_order_details.symbol,
      quantity = exit_order_details.quantity,
      transaction_type = "SELL" // Or "BUY" if shorting
    )

    IF result is successful:
      // Finalize the order status in the local database
      database.execute(
        UPDATE orders SET status = "CLOSED" WHERE order_id = exit_order_details.order_id
      )
      LOG "Exit order placed successfully and position closed."
    ELSE
      LOG "CRITICAL ERROR: Failed to place stop-loss exit order!"
      // Here, you might add logic to retry or alert the user
    END IF
  END WHILE
END FUNCTION
```
