# Brainstorming Notes

This file contains brainstorming notes and discussions about the features and architecture of the trading tool.

## Note 1: The "Update Instruments" Button

### What it does:
The "Update Instruments" button manually triggers a refresh of the instrument list for the currently logged-in broker. When a user logs in, the application automatically fetches a list of all tradable symbols (e.g., stocks on NSE, BSE) from the broker's API and stores them in a local database. This list is then used to power the searchable symbol field on the order form.

### Brainstorming its requirement:
- **Is it necessary?** The instrument list is already updated automatically upon login. However, this process can fail for several reasons:
    1. A temporary network issue.
    2. An error with the broker's API at the moment of login.
    3. The list of instruments might change during the day (though this is rare for equities).

- **Pros of keeping it:**
    - **Resilience:** It provides a manual override for the user if the automatic update fails. Instead of having to log out and log back in, the user can simply click a button to try the update again.
    - **Debugging:** It's a useful tool for debugging issues with the instrument fetching process.
    - **User Control:** It gives the user a sense of control over the application's data.

- **Cons of keeping it:**
    - **UI Clutter:** It adds another button to the interface, which could be seen as clutter.
    - **Potential for Abuse:** Frequent clicking could lead to rate-limiting by the broker's API, although this is unlikely for a single user.

- **Conclusion:** The button is a valuable feature for resilience and user control. The benefits of having a manual refresh mechanism outweigh the minor UI clutter. It should be kept.

---

## Note 2: Real-Time Architecture with WebSockets

### The Change:
The application has been migrated from a simple HTTP polling mechanism to a real-time, WebSocket-based architecture for tracking prices and managing trailing stop-losses.

### Benefits:
- **Low Latency:** Price updates are received and processed in real-time, which is critical for a time-sensitive feature like a trailing stop-loss.
- **Efficiency:** A single, persistent WebSocket connection is much more efficient than repeatedly making HTTP requests, reducing network overhead and resource consumption.
- **Scalability:** The new architecture is more scalable and can handle a larger number of open positions and price updates.

### Key Implementation Details:
- **Thread-Safe Order Placement:** When a stop-loss is triggered, the `WebSocketManager` does not place an order directly. Instead, it puts the details of the required exit order onto a thread-safe `queue`. A dedicated worker thread, running in the main application context, continuously monitors this queue. When a new order appears, the worker thread is responsible for safely calling the broker's API to place the market exit order. This design decouples the real-time tick processing from the order placement logic, ensuring thread safety and robust execution.

### Future Enhancements:
- **Order Book Integration:** The current implementation uses the Last Traded Price (LTP) for the trailing stop-loss logic. A future enhancement could be to use order book data (bid/ask prices and depth) to make more sophisticated stop-loss decisions. This would be particularly useful for options and futures trading.
- **More Granular Subscriptions:** The application currently subscribes to the `ltp` (or `ltpc`) feed. For certain strategies, it might be beneficial to subscribe to the `full` feed, which includes market depth, and use that data in the stop-loss logic.

---

## Note 3: Order Status Synchronization

### The Problem:
What happens if an order is filled, cancelled, or rejected by the broker while the application is not running? The local database would still show the order as "OPEN," leading to data inconsistency and potentially incorrect behavior when the application restarts.

### The Solution:
To solve this, the application implements an **order status synchronization** feature.

- **Trigger:** This process is automatically triggered every time a WebSocket connection to the broker is successfully established.
- **Mechanism:**
    1. The `WebSocketManager` queries the local database for all orders marked with the "OPEN" status.
    2. For each open order, it makes an API call to the broker to get the latest status of that specific order.
    3. It then compares the broker's status with the local status.
    4. If the broker reports the order as `COMPLETE`, `FILLED`, `CANCELLED`, or `REJECTED`, the application updates the order's status in the local database to match.
- **Benefit:** This ensures that the application's state is always consistent with the broker's, providing a more robust and reliable system. It prevents the application from trying to manage a stop-loss for an order that no longer exists.

---

## Note 4: Trailing Stop-Loss Execution Logic

This section details the mathematics and logic used to implement the automated trailing stop-loss feature.

### 1. Initial Stop-Loss Price Calculation
When an order is placed, the system immediately calculates the initial absolute price at which a stop-loss would be triggered. This is not just a percentage; it's a concrete value.

- **Formula:** `initial_stop_price = purchase_price * (1 - (stop_loss_percentage / 100))`
- **Example:**
  - You buy a stock at a `purchase_price` of **$100**.
  - You set a `stop_loss_percentage` of **5%**.
  - The `initial_stop_price` is calculated as `100 * (1 - (5 / 100)) = 100 * 0.95 = $95`.
- This value (`$95`) is stored in the database as the initial `current_stoploss_price`.

### 2. The "Trailing" Mechanism
As the price of the asset changes, the system continuously recalculates a *potential* new stop-loss price. The goal is to move the stop-loss up as the price rises (for a buy order), locking in profits.

- **Formula:** `new_stop_price = current_asset_price * (1 - (stop_loss_percentage / 100))`
- **Example:**
  - The stock price rises to **$110**.
  - The `new_stop_price` is recalculated as `110 * 0.95 = $104.50`.

### 2a. Advanced Price Selection for Trailing
The choice of `current_asset_price` in the formula above is critical. While the Last Traded Price (LTP) is the default, it may not always be the safest price to use for trailing, especially in volatile markets. The application uses a more sophisticated approach depending on the product type.

- **Default (for CNC orders):** The system uses the **LTP**. This is suitable for long-term delivery-based trades where minor, momentary price fluctuations are less critical.
- **Advanced (for MIS/NRML orders):** For intraday products, the system uses the **best bid price** from the market depth feed (when available) for buy-side orders.
  - **Why?** The best bid represents the highest price a buyer is currently willing to pay for the asset. Trailing based on the bid price is more conservative and realistic than using the LTP, which could be an anomalous print. It ensures the stop-loss trails the actual demand for the stock, providing a safer cushion against volatility.

### 3. The Update Condition
The stop-loss price is only ever updated if the new calculated price is *higher* than the existing one. The stop-loss never moves down.

- **Logic:** `if new_stop_price > current_stoploss_price`
- **Example:**
  - The `new_stop_price` is **$104.50**, and the `current_stoploss_price` is **$95**.
  - Since `$104.50 > $95`, the system updates the `current_stoploss_price` in the database to **$104.50**.
  - If the stock price were to drop to $105, the `new_stop_price` would be `105 * 0.95 = $99.75`. Since this is lower than the current stop of $104.50, no update occurs.

### 4. The Trigger Condition
An exit order is sent for execution only when the asset's current price drops to or below the stored `current_stoploss_price`.

- **Logic:** `IF current_asset_price <= current_stoploss_price THEN execute_exit_order()`
- **Example:**
  - The `current_stoploss_price` is **$104.50**.
  - The stock price drops from its high and hits **$104.50**.
  - The condition is met, and a market sell order is placed in the execution queue.
