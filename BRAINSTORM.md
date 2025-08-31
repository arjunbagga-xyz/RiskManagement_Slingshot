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
