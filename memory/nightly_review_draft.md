# Nightly Memory Review Draft

Generated at `2026-04-26 21:51:38` by `scripts/quant_memory_evolve.py`.

## Summary

- long_term_learning_entries: 7
- active_cards: 12
- active_error_cards: 6
- newly_promoted_active_hashes: 52a0020f68bbb6cc, d9112dec90546429
- input_signature: `24da73547a4d66a7`

## Review Questions

- Did any fresh P2/shadow/promotion evidence contradict an active memory item?
- Did any candidate win by lower exposure rather than better execution-adjusted alpha?
- Are any active errors now resolved and ready to be marked `status: resolved`?
- Are new learnings specific enough to be reused, with evidence and action fields?

## Active Cards For Review

- `3622f3b98422ad92` P2 replay can become invalid if a script-level rebalance path recomputes target weights (errors.md)
- `d9112dec90546429` Promotion can pass strict gates over inconsistent target-weight evidence (errors.md)
- `bc9945e247e7990d` Low-invested candidates can look safer than they are (errors.md)
- `e0d5e375adebd905` Next-day pretrade gates can leak execution outcomes into research selection (errors.md)
- `1ecc8368d4830de8` Research strong, execution weak is often a capacity/portfolio issue, not just a signal issue (errors.md)
- `9d75157e798d069f` Industry ranking penalties alone do not guarantee portfolio-level diversification (errors.md)
- `74b1f655d7ed1108` P2 execution evidence must use the canonical broker path (learnings.md)
- `52a0020f68bbb6cc` Promotion needs target-weight source and checksum evidence (learnings.md)
- `e625b71975eb50ea` v7 industry balance reduces industry concentration but fails promotion (learnings.md)
- `456382d93b4d760e` Alpha attribution must state artifact limitations (learnings.md)
- `beb3e89425ee8117` Industry concentration needs invested and NAV-weight views (learnings.md)
- `01759b00f05f6441` Signal pretrade defaults must be research-safe (learnings.md)

## Suggested Commands

```bash
python scripts/quant_memory_evolve.py
python scripts/quant_profile_promotion_review.py --write-latest
```
