# Audit Checklist

Use this checklist when the user asks for a deep audit, optimization pass, or architecture review.

## 1. Logic And Alpha

- Verify factor computation uses only information available at signal time.
- Inspect `shift(-n)`, forward returns, and future exit-price lookup.
- Confirm signal date, trade date, and label horizon are aligned across:
  `train_mfts_lgbm.py`
  `daily_ml_select.py`
  `daily_verify.py`
  `quant_portfolio_backtest.py`
- Check filters for ST, suspension, limit-up entry lock, limit-down exit lock, and BJ exclusions.
- Confirm high-coverage gates prevent low-sample fake stability.

## 2. Performance

- Count and inspect:
  `iterrows(`
  `apply(`
  `transform(lambda`
  `rolling(`
  repeated `read_parquet(`
- Prefer vectorized grouped calculations and windowed parquet reads.
- Focus first on files in the production path, not on report-only pages.

## 3. Financial Engineering

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

## 4. Robustness

- Review broad `except Exception` blocks and decide whether they should fail fast.
- Check metadata refresh and fallback chains for silent degradation.
- Verify orchestration does not continue into P2 or P3 after critical gating failures.
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
