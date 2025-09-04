# Real-Time Trading Tool with Trailing Stop-Loss

This is a web-based trading tool that allows you to connect to Zerodha and Upstox, place orders, and manage risk with a real-time, streaming trailing stop-loss mechanism. The application features a modern, "flashy" UI for a better user experience.

## Features

- **Advanced Real-Time Trailing Stop-Loss:** The application uses a persistent WebSocket connection to monitor positions. The trailing stop-loss is updated with every price tick and uses advanced logic (LTP for long-term trades, best bid price for intraday) for maximum accuracy and safety.
- **Order Status Synchronization:** Automatically syncs local order statuses with the broker upon connection, ensuring data consistency even if the application was offline.
- **Modern UI:** A sleek and modern user interface with a dark, neon-accented theme.
- **Potential Profit Tracking:** The UI displays the potential profit percentage that is "locked in" by the current stop-loss price, giving you a clear view of your risk management.
- **Searchable Symbol List:** Quickly find and select trading symbols with a searchable, autocomplete input field that is populated with broker-specific instruments.
- **Dynamic Order Form:** The order form intelligently enables or disables options based on your selections to prevent invalid order combinations.
- **Broker Integration:** Login with your Zerodha or Upstox account.
- **Secure Login:** The application now requires users to log in before accessing the main features, ensuring that trading activities are secure and private.
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

Before you can log in, you must configure your broker's API credentials.

1.  Run the application for the first time. You will be directed to the login page.
2.  From the login page, you can navigate to the **Settings** page (or will be redirected if no settings are found).
3.  On the Settings page, enter your API keys from the developer portals of Zerodha and Upstox.
4.  The application will store these credentials securely in its local database.

You will need to provide:
- Zerodha API Key & API Secret
- Upstox API Key, API Secret, and Redirect URI

The application will need to be restarted after saving the settings for the changes to take effect.

## How to Run the Application

Once you have installed the dependencies and configured your settings, you can run the application:

```bash
python src/app.py
```

The application will be available at `http://localhost:5000`. Upon visiting this URL, you will be prompted to log in with your chosen broker.

### Logging

The application logs important events and errors to `app.log`. Check this file for any issues, especially with the WebSocket connection and price updates.

## Brainstorming and Future Enhancements

For more detailed discussions on application features and architecture, please see the `BRAINSTORM.md` file.

---

## Creating a Standalone Executable

You can package this application into a single executable file (`.exe`) for easy distribution and execution. This allows you to run the application without needing to have Python or the dependencies installed separately. The executable will run as a background process.

### 1. Install PyInstaller
First, ensure you have PyInstaller installed in your environment:
```bash
pip install pyinstaller
```

### 2. Create the Spec File
Create a file named `RealTimeTradingTool.spec` in the root directory of the project with the following content. This file tells PyInstaller how to build your application.

```python
# RealTimeTradingTool.spec
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['src/app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Add data files (templates, static assets, and schema)
a.datas += [
    ('templates', 'templates', 'DATA'),
    ('static', 'static', 'DATA'),
    ('schema.sql', 'schema.sql', 'DATA')
]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RealTimeTradingTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # This creates a windowed (no console) application
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RealTimeTradingTool',
)
```

### 3. Build the Executable
Run PyInstaller from your terminal in the project's root directory, pointing it to the spec file you just created:
```bash
pyinstaller RealTimeTradingTool.spec
```

### 4. Run the Application
Once the build process is complete, you will find the executable inside the `dist/RealTimeTradingTool` directory (or `dist/RealTimeTradingTool.exe` on Windows). You can now run this file directly to start the application. Use the "Exit Application" button in the UI to gracefully shut down the server.
