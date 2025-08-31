# XAI_FIELDS — TCA Fields and Sign Semantics

This document describes the Transaction Cost Analysis (TCA) output fields, their sign conventions, and the two supported semantics for Implementation Shortfall.

## Field glossary

- `implementation_shortfall_bps` (legacy-positive)
  - Description: Implementation shortfall expressed as a positive cost (bps). This is the legacy representation kept for backward compatibility (R1).
  - Semantics: Sum of positive cost components (spread, latency, adverse, temporary impact) + signed fees (fees_bps ≤ 0) + rebates.
  - Example: 12.5

- `canonical_is_bps` (canonical signed)
  - Description: Canonical implementation shortfall with signed components (costs ≤ 0, rebate ≥ 0). Negative values indicate a cost to the trader, positive values indicate net benefit.
  - Semantics: canonical_is_bps = raw_edge_bps + fees_bps + slippage_in_bps + slippage_out_bps + adverse_bps + latency_bps + impact_bps + rebate_bps
  - Example: -12.5

- Canonical component fields (signed as indicated):
  - `raw_edge_bps`: float (signed; upstream expected edge, can be positive or negative)
  - `fees_bps`: float (≤ 0)
  - `rebate_bps`: float (≥ 0)
  - `slippage_in_bps`: float (≤ 0)
  - `slippage_out_bps`: float (≤ 0)
  - `latency_bps`: float (≤ 0)
  - `adverse_bps`: float (≤ 0)
  - `impact_bps`: float (≤ 0)

- Legacy compatibility fields (positive costs):
  - `spread_cost_bps` = -slippage_in_bps
  - `latency_slippage_bps` = -latency_bps
  - `adverse_selection_bps` = -adverse_bps
  - `temporary_impact_bps` = -impact_bps

## Identities

Two equivalent representations are preserved (within floating point tolerance 1e-6):

1. Canonical (signed) identity:

   canonical_is_bps = raw_edge_bps + fees_bps + slippage_in_bps + slippage_out_bps + adverse_bps + latency_bps + impact_bps + rebate_bps

2. Legacy (positive) decomposition returned in `implementation_shortfall_bps`:

   implementation_shortfall_bps = raw_edge_bps + fees_bps + spread_cost_bps + latency_slippage_bps + adverse_selection_bps + temporary_impact_bps + rebate_bps

Note: mapping uses spread_cost_bps = -slippage_in_bps, etc., so numeric equivalence holds.

## Examples

- BUY taker sample (values in bps):
  - raw_edge_bps = 0.0
  - fees_bps = -0.1
  - slippage_in_bps = -10.0
  - latency_bps = -1.0
  - adverse_bps = -0.2
  - impact_bps = -0.5
  - rebate_bps = 0.0

  canonical_is_bps = -11.8
  implementation_shortfall_bps = 11.8

- SELL maker sample (maker rebate):
  - raw_edge_bps = 5.0
  - fees_bps = -0.05
  - slippage_in_bps = 0.0
  - rebate_bps = 0.3

  canonical_is_bps = 5.25
  implementation_shortfall_bps = 5.25

## Migration notes

- R1: Keep `implementation_shortfall_bps` as legacy-positive for backward compatibility. Add `canonical_is_bps` to expose canonical signed IS.
- R2: Plan to deprecate legacy field and migrate consumers to `canonical_is_bps`.
