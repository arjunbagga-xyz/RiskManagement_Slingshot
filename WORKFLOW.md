# Application Workflow Diagrams

This document contains UML diagrams that illustrate the workflow of the trading tool application. The diagrams are created using PlantUML.

## 1. Login and Order Placement Sequence Diagram

This diagram shows the sequence of interactions between the user, the browser, the Flask application, and the broker APIs for logging in and placing an order.

```plantuml
@startuml
actor User
participant Browser
participant "Flask App" as App
participant "Broker API" as Broker

User -> Browser: Accesses the application
Browser -> App: GET /
App --> Browser: Renders index.html

User -> Browser: Clicks "Login"
Browser -> App: GET /login
App --> Browser: Renders login.html with broker options

User -> Browser: Clicks "Login with Zerodha"
Browser -> App: GET /login/zerodha
App -> Broker: Redirects to Zerodha login page
Broker --> Browser: Shows login page
User -> Browser: Enters credentials
Browser -> Broker: Submits credentials
Broker --> App: Redirects with request_token

App -> Broker: POST /session/token with request_token
Broker --> App: Returns access_token
App -> App: Stores access_token in session
App --> Browser: Redirects to /

User -> Browser: Fills and submits order form
Browser -> App: POST /place_order
App -> Broker: Places order with access_token
Broker --> App: Returns order_id
App -> App: Stores order in memory
App --> Browser: Redirects to / with success message
@enduml
```

## 2. Trailing Stop-Loss Activity Diagram

This diagram illustrates the logic of the trailing stop-loss mechanism.

```plantuml
@startuml
start
:User clicks "Refresh Prices";
:For each OPEN order;
    :Fetch Last Traded Price (LTP) from Broker API;
    if (LTP <= Current Stop-Loss Price?) then (yes)
        :Trigger SELL order (exit position);
        :Update order status to "CLOSED";
        :end;
    else (no)
        if (LTP > Highest Price since order placed?) then (yes)
            :Update Highest Price;
            :Calculate new Trailing Stop-Loss Price;
            :Update order with new stop-loss;
        endif
    endif
:Redirect to homepage with updated order info;
stop
@enduml
```
