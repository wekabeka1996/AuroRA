# Partial Fill Execution Diagram

```mermaid
graph TD
    A[place_order] --> B[ORDER.ACK]
    B --> C[ORDER.FILL (partial)]
    C --> D[Position Update (partial)]
    D --> E[Wait for more fills]
    E --> F[ORDER.FILL (remaining)]
    F --> G[Position Update (full)]
```