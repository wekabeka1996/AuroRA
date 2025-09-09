# Limit Order Execution Diagram

```mermaid
graph TD
    A[Signal Generation] --> B[Risk Check]
    B --> C{Allow?}
    C -->|Yes| D[ORDER.SUBMIT]
    D --> E[place_order (limit)]
    E --> F[create_order via CCXT]
    F --> G[Біржа]
    G --> H[ORDER.ACK (pending)]
    H --> I[Wait for Fill]
    I --> J[ORDER.FILL]
    J --> K[Position Update]
    C -->|No| L[RISK.DENY]
```