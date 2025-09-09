# Stop/TP Execution Diagram

```mermaid
graph TD
    A[Desire Exit or TP Condition] --> B[ORDER.SUBMIT (close)]
    B --> C[close_position]
    C --> D[place_order (market, reduce_only)]
    D --> E[create_order via CCXT]
    E --> F[Біржа]
    F --> G[ORDER.ACK]
    G --> H[ORDER.FILL]
    H --> I[Position Closed]
```