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
