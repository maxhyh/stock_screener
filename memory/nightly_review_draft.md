# Nightly Memory Review Draft

Generated at `2026-04-26 21:05:06` by `scripts/quant_memory_evolve.py`.

## Summary

- long_term_learning_entries: 4
- active_cards: 7
- active_error_cards: 3
- newly_promoted_active_hashes: 1ecc8368d4830de8, 456382d93b4d760e, 9d75157e798d069f, bc9945e247e7990d, beb3e89425ee8117, e625b71975eb50ea, f0e4f37438eb406c
- input_signature: `c359327cbb3e30c0`

## Review Questions

- Did any fresh P2/shadow/promotion evidence contradict an active memory item?
- Did any candidate win by lower exposure rather than better execution-adjusted alpha?
- Are any active errors now resolved and ready to be marked `status: resolved`?
- Are new learnings specific enough to be reused, with evidence and action fields?

## Active Cards For Review

- `bc9945e247e7990d` Low-invested candidates can look safer than they are (errors.md)
- `1ecc8368d4830de8` Research strong, execution weak is often a capacity/portfolio issue, not just a signal issue (errors.md)
- `9d75157e798d069f` Industry ranking penalties alone do not guarantee portfolio-level diversification (errors.md)
- `e625b71975eb50ea` v7 industry balance reduces industry concentration but fails promotion (learnings.md)
- `456382d93b4d760e` Alpha attribution must state artifact limitations (learnings.md)
- `beb3e89425ee8117` Industry concentration needs invested and NAV-weight views (learnings.md)
- `f0e4f37438eb406c` Research-side annualized return can be misleading when hard-pass rate is zero (learnings.md)

## Suggested Commands

```bash
python scripts/quant_memory_evolve.py
python scripts/quant_profile_promotion_review.py --write-latest
```
