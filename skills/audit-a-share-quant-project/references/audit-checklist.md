# Audit Checklist

Use this checklist when the user asks for a deep audit, optimization pass, or architecture review.

## 1. Runtime, Data, And Evidence Generation

- Run project commands with `conda run -n stock` or the equivalent activated `stock` environment.
- Confirm `ASHARE_DATA_ROOT` resolves to the read-only shared ODS tree.
- Confirm every selected partition has a visible, valid manifest and a recorded digest.
- Confirm historical instrument, ST, board, suspension, and listing status are point-in-time.
- Confirm research returns and labels use adjusted prices; execution uses raw prices and official trade constraints.
- Confirm signal, model, backtest, P2, and promotion artifacts share the same data-generation identity.
- Treat pre-ODS artifacts as historical-only evidence.

## 2. Logic And Alpha

- Verify factor computation uses only information available at signal time.
- Inspect `shift(-n)`, forward returns, and future exit-price lookup.
- Confirm signal date, trade date, and label horizon are aligned across:
  `train_mfts_lgbm.py`
  `daily_ml_select.py`
  `daily_verify.py`
  `quant_portfolio_backtest.py`
- Check filters for ST, suspension, limit-up entry lock, limit-down exit lock, and BJ exclusions.
- Confirm high-coverage gates prevent low-sample fake stability.
- Confirm the model artifact horizon and label contract match the active profile. A horizon mismatch is a hard stop, not a warning.
- Confirm `label_exit_date` and `label_available_at` do not cross train/validation/test boundaries; require horizon-aware purge/embargo.
- Confirm model inference fails on missing/reordered/wrong-dtype features instead of zero-filling.

## 3. Performance

- Count and inspect:
  `iterrows(`
  `apply(`
  `transform(lambda`
  `rolling(`
  repeated `read_parquet(`
- Prefer vectorized grouped calculations and windowed parquet reads.
- Focus first on files in the production path, not on report-only pages.

## 4. Financial Engineering

- Confirm sell-side stamp duty only.
- Confirm slippage and fee side are symmetric with the intended execution model.
- Check benchmark and excess-return math when exposure is below 100%.
- Review:
  max drawdown
  Sortino
  Calmar
  turnover
  block rate
  realized exposure

## 5. Robustness

- Review broad `except Exception` blocks and decide whether they should fail fast.
- Check metadata refresh and fallback chains for silent degradation.
- Verify orchestration does not continue into P2 or P3 after critical gating failures.
- Verify unresolved P0 data, PIT, label, or model-lineage failures block new profile creation and P2 promotion work.
- Verify daily/P2/broker target checksums are equal or connected by an explicit parent-child transform.
- Verify open execution ignores same-day high/low and full-day amount, and trapped positions remain in gross/industry/style budgets.
- Add regression tests for any confirmed production-risk fix.

## Response Shape

Return findings in this order:

1. Severe bug or silent-risk mismatch
2. Why it matters in A-share live or paper trading
3. Concrete fix or optimized code
4. Remaining uncertainty
5. Current market-environment suggestion

Keep summaries brief. Put findings first.

## Priority Labels

Use these labels consistently in recurring maintenance:

- `P0`: silently distorts labels, backtests, paper trading, or risk gates
- `P1`: materially weakens live execution realism or production safety
- `P2`: meaningful performance, robustness, or modularity debt
- `P3`: cleanup or ergonomics with low trading impact
