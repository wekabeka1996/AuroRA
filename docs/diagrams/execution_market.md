# Market Order Execution Diagram

```mermaid
graph TD
    A[Signal Generation] --> B[Risk Check via Aurora API]
    B --> C{Allow?}
    C -->|Yes| D[ORDER.SUBMIT]
    D --> E[place_order (market)]
    E --> F[create_order via CCXT]
    F --> G[Біржа]
    G --> H[ORDER.ACK]
    H --> I[ORDER.FILL (immediate)]
    I --> J[Position Update]
    C -->|No| K[RISK.DENY]
```