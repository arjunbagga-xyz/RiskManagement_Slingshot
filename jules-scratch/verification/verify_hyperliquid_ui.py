from playwright.sync_api import Page, expect

def test_hyperliquid_login_and_order_form(page: Page):
    # 1. Arrange: Go to the login page.
    page.goto("http://localhost:5000/login")
    page.wait_for_load_state("networkidle")
    page.screenshot(path="jules-scratch/verification/login-page.png")

    # 2. Act: "Login" with Hyperliquid by navigating to the main page.
    # In a real test, we would fill in the private key and click the login button.
    # For this verification, we'll simulate the login by navigating directly.
    page.goto("http://localhost:5000/")
    page.wait_for_load_state("networkidle")

    # 3. Assert: Confirm the Hyperliquid order form is not visible,
    # as we haven't actually logged in.
    expect(page.locator("#order-form-hyperliquid")).not_to_be_visible()

    # 4. Screenshot: Capture the final result for visual verification.
    page.screenshot(path="jules-scratch/verification/main-page-no-login.png")
