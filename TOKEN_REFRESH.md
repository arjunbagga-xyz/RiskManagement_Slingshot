# Token Refresh Mechanisms for Zerodha and Upstox

This document outlines the mechanisms for refreshing access tokens for the Zerodha Kite Connect and Upstox APIs.

## Zerodha Kite Connect

**Mechanism:** Manual Login

The Zerodha Kite Connect API requires a manual login each day to generate a new `access_token`. This is a regulatory requirement, and the `access_token` expires at 6 AM every morning.

The process is as follows:
1. The user is redirected to the Kite Connect login page.
2. After a successful login, the user is redirected back to the application with a `request_token`.
3. This `request_token` is exchanged for an `access_token`, which is used to make API calls.

**Automated Refresh:**
- Zerodha provides a `refresh_token` only to certain approved platforms.
- For general use, there is no way to automate the daily token refresh. The user must manually log in every day.

## Upstox API

**Mechanism:** Manual Login (OAuth 2.0)

The Upstox API also requires a manual login process using the standard OAuth 2.0 flow.

The process is as follows:
1. The user is redirected to the Upstox login page.
2. After a successful login, the user is redirected back to the application with an `authorization_code`.
3. This `authorization_code` is exchanged for an `access_token`.

**Automated Refresh:**
- The standard API flow does not provide a `refresh_token`.
- Upstox offers an "extended token" with a one-year validity, but it is for **read-only** access and only available to approved multi-client applications. This token cannot be used for placing orders.
- Therefore, for trading, the user must manually log in every day.

## Conclusion

For both Zerodha and Upstox, any application that performs trading activities will require the user to **manually log in every 24 hours** to generate a new access token. The application should be designed to handle this daily login requirement gracefully.
