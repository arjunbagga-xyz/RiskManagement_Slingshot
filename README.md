# Trading Tool with Trailing Stop-Loss

This is a web-based trading tool that allows you to connect to Zerodha and Upstox, place orders, and manage risk with a trailing stop-loss mechanism. The application features a modern, glassmorphism-themed UI for a better user experience.

## Features

- **Modern UI:** A sleek and modern user interface with a glassmorphism theme.
- **Searchable Symbol List:** Quickly find and select trading symbols with a searchable, autocomplete input field.
- **Dynamic Order Form:** The order form intelligently enables or disables options based on your selections to prevent invalid order combinations.
- **Broker Integration:** Login with your Zerodha or Upstox account.
- **Order Placement:** Place different types of orders (Market, Limit, SL, SL-M).
- **Trailing Stop-Loss:** Automatically manage your risk with a trailing stop-loss that adjusts as the price moves in your favor.
- **Order Tracking:** View your placed orders and their current status in a clean, themed table.
- **Web-based UI:** A simple and intuitive user interface built with Flask.

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

**How to set environment variables:**

- **On Linux/macOS:**
  ```bash
  export ZERODHA_API_KEY="your_key"
  export ZERODHA_API_SECRET="your_secret"
  # ... and so on for the other variables
  ```
  To make them permanent, add these lines to your `~/.bashrc` or `~/.zshrc` file.

- **On Windows:**
  ```powershell
  $env:ZERODHA_API_KEY="your_key"
  $env:ZERODHA_API_SECRET="your_secret"
  # ... and so on
  ```
  To set them permanently, you can use the System Properties dialog.

## How to Run the Application

Once you have installed the dependencies and configured the environment variables, you can run the application with the following command:

**Note:** This application is designed for a single-user context. The access tokens are stored in a global variable and are not suitable for a multi-user web application.

```bash
python src/app.py
```

The application will be available at `http://localhost:5000`.

### Production Deployment

For a production deployment, it is recommended to use a proper WSGI server like Gunicorn or uWSGI instead of Flask's built-in development server.

Example with Gunicorn:
```bash
gunicorn --workers 4 --bind 0.0.0.0:8000 "src.app:app"
```

### Logging

The application logs important events and errors to `app.log`. Check this file for any issues, especially with the background price refresher.

## Token Refresh

Please refer to the `TOKEN_REFRESH.md` file for a detailed explanation of the token refresh mechanisms and a discussion on stop-loss strategies.
