# Real-Time Trading Tool with Trailing Stop-Loss

This is a web-based trading tool that allows you to connect to Zerodha and Upstox, place orders, and manage risk with a real-time, streaming trailing stop-loss mechanism. The application features a modern, "flashy" UI for a better user experience.

## Features

- **Real-Time Trailing Stop-Loss:** The application uses a persistent WebSocket connection to the broker's streaming API to monitor your open positions in real-time. The trailing stop-loss is updated with every price tick, providing a fast and efficient way to manage risk.
- **Modern UI:** A sleek and modern user interface with a dark, neon-accented theme.
- **Searchable Symbol List:** Quickly find and select trading symbols with a searchable, autocomplete input field that is populated with broker-specific instruments.
- **Dynamic Order Form:** The order form intelligently enables or disables options based on your selections to prevent invalid order combinations.
- **Broker Integration:** Login with your Zerodha or Upstox account.
- **Order Placement:** Place Market and Limit orders.
- **Order Tracking:** View your placed orders and their current status in a clean, themed table.

## Architecture

The application uses a multi-threaded architecture to handle real-time data processing. When a user logs in, a dedicated WebSocket manager thread is started for that session. This thread maintains a persistent connection to the broker's streaming API. When an order is placed, the application subscribes to the market data for that instrument. The trailing stop-loss logic is executed in the WebSocket manager's `on_tick` handler, ensuring that stop-loss decisions are made with minimal latency.

## Setup and Installation

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
    ```

3.  **Install the dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

To connect to the broker APIs, you need to set the following environment variables. You can get your API keys from the developer portals of Zerodha and Upstox.

### For Zerodha:
- `ZERODHA_API_KEY`: Your Zerodha Kite Connect API key.
- `ZERODHA_API_SECRET`: Your Zerodha Kite Connect API secret.

### For Upstox:
- `UPSTOX_API_KEY`: Your Upstox API key.
- `UPSTOX_API_SECRET`: Your Upstox API secret.
- `UPSTOX_REDIRECT_URI`: The redirect URI you configured in your Upstox developer app (e.g., `http://localhost:5000/callback/upstox`).

## How to Run the Application

Once you have installed the dependencies and configured the environment variables, you can run the application with the following command:

```bash
python src/app.py
```

The application will be available at `http://localhost:5000`.

### Logging

The application logs important events and errors to `app.log`. Check this file for any issues, especially with the WebSocket connection and price updates.

## Brainstorming and Future Enhancements

For more detailed discussions on application features and architecture, please see the `BRAINSTORM.md` file.
