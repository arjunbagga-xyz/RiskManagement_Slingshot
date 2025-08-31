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

### Future Enhancements:
- **Order Book Integration:** The current implementation uses the Last Traded Price (LTP) for the trailing stop-loss logic. A future enhancement could be to use order book data (bid/ask prices and depth) to make more sophisticated stop-loss decisions. This would be particularly useful for options and futures trading.
- **Thread-Safe Order Placement:** The current implementation logs a message when a stop-loss is triggered instead of placing an order, because the WebSocket thread does not have safe access to the broker API instance. A future enhancement would be to implement a thread-safe queue to communicate from the WebSocket thread back to the main application thread, which would then place the exit order. This would complete the automation of the trailing stop-loss.
- **More Granular Subscriptions:** The application currently subscribes to the `ltp` (or `ltpc`) feed. For certain strategies, it might be beneficial to subscribe to the `full` feed, which includes market depth, and use that data in the stop-loss logic.

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
