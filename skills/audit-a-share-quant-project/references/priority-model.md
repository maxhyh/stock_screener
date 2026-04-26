# Priority Model

Use this model to rank findings and choose the next maintenance target.

## Severity

- `P0`: Silent PnL distortion or false confidence
  Examples:
  look-ahead bias
  entry and exit timing mismatch
  benchmark or excess-return math drift
  pretrade and execution inconsistency that changes tradable basket quality

- `P1`: Live or paper execution realism risk
  Examples:
  limit-up or limit-down handling mismatch
  suspension or ST filtering mismatch
  weak metadata gates that reduce effective risk control
  cost-model errors with meaningful PnL impact

- `P2`: High-value maintainability or performance debt
  Examples:
  repeated rolling bottlenecks on production paths
  broad exception handling in core flows
  orchestration and engine coupling that slows future fixes

- `P3`: Low-risk cleanup
  Examples:
  naming cleanup
  report-only polish
  redundant helper logic with no current behavioral risk

## Tie-Breakers

When severity is similar, prefer issues that are:

1. In the production path
2. Easy to reproduce and regression-test
3. Small patch, large realism gain
4. Likely to recur if not encoded into tests or this skill

## Next Target Selection

At the end of a maintenance pass, choose the next target by asking:

1. Does it affect live or paper credibility?
2. Can it be fixed safely in one pass?
3. Will it shrink future maintenance cost?

If all three are true, elevate it.
