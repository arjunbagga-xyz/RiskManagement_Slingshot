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

User -> Browser: Accesses the application (GET /)
Browser -> App: GET /
App -> App: Check if user is logged in
alt User is not logged in
    App --> Browser: Redirect to /login
    Browser -> App: GET /login
    App --> Browser: Renders login.html
else User is logged in
    App --> Browser: Renders index.html
end

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
:User places an order;
:Application subscribes to WebSocket price feed for the instrument;
note right
  This runs in a background thread
end note

repeat
  :WebSocket sends a new price tick (LTP);
  :Application receives the tick;
  if (LTP <= Current Stop-Loss Price?) then (yes)
    :Place exit order in a thread-safe queue;
    :Update order status to "CLOSED";
    break
  else (no)
    :Calculate potential new stop-loss price;
    if (potential new price > current stop-loss price) then (yes)
      :Update the order with the new stop-loss price;
    endif
  endif
repeat while (position is open)
stop
@enduml
```
