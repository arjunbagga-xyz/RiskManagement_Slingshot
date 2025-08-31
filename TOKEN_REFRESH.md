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

---

## Brainstorming: Manual vs. Automated Stop-loss

This section discusses the implications of including manual `Stop-loss (SL)` and `Stop-loss Market (SL-M)` order types in an application that already features an automated trailing stop-loss system.

### Current System: Automated Trailing Stop-loss

The application currently uses a background process to monitor open positions and apply a trailing stop-loss based on a user-defined percentage.

- **Pros:** Automatically protects profits, simple for the user to set up (just a percentage).
- **Cons:** Relies on the application being constantly online and connected to the broker. If the application fails, the stop-loss is not active.

### Manual Stop-loss Orders (`SL` / `SL-M`)

These are orders placed directly with the broker. They remain on the broker's servers until triggered or canceled.

- **Pros:**
    - **Reliability:** The order resides on the broker's system, so it will execute even if the application is offline.
    - **User Control:** Allows for precise stop-loss placement based on technical analysis, not just a fixed percentage.
- **Cons:**
    - **Complexity and Conflict:** If we allow users to place manual `SL`/`SL-M` orders, a conflict arises with the application's automated trailing stop-loss. The system would need complex logic to manage both:
        1. When the application's trailing stop-loss is triggered, it must first cancel the user's manual stop-loss order before placing the exit order.
        2. This introduces a potential race condition and a point of failure. If the cancellation fails, the user could be left with an unwanted open order.
    - **Static Nature:** Manual stop-losses are static and do not trail, meaning the user might miss out on locking in profits as the price moves favorably.

### Recommendation

Given the added complexity and potential for serious errors, it is recommended to **avoid implementing manual `SL`/`SL-M` orders** alongside the current automated trailing stop-loss system.

The current implementation is safer and less prone to edge cases. The focus should be on ensuring the reliability of the background worker that manages the trailing stop-loss. Future enhancements could involve allowing the user to set the initial stop-loss with a fixed price, but the trailing logic should remain managed by the application to avoid conflicts.
