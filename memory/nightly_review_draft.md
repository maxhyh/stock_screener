# Nightly Memory Review Draft

Generated at `2026-04-27 00:07:28` by `scripts/quant_memory_evolve.py`.

## Summary

- long_term_learning_entries: 10
- active_cards: 12
- active_error_cards: 9
- newly_promoted_active_hashes: 1f387fa177c59de7, 58967edab4e6aa66, a8edccf342ce5e8d
- input_signature: `a6c89bd9a386c548`

## Review Questions

- Did any fresh P2/shadow/promotion evidence contradict an active memory item?
- Did any candidate win by lower exposure rather than better execution-adjusted alpha?
- Are any active errors now resolved and ready to be marked `status: resolved`?
- Are new learnings specific enough to be reused, with evidence and action fields?

## Active Cards For Review

- `3622f3b98422ad92` P2 replay can become invalid if a script-level rebalance path recomputes target weights (errors.md)
- `a8edccf342ce5e8d` Shared daily fallback contaminates profile replay evidence (errors.md)
- `d9112dec90546429` Promotion can pass strict gates over inconsistent target-weight evidence (errors.md)
- `1f387fa177c59de7` Reserve pool can raise exposure while worsening realized losses (errors.md)
- `bc9945e247e7990d` Low-invested candidates can look safer than they are (errors.md)
- `e0d5e375adebd905` Next-day pretrade gates can leak execution outcomes into research selection (errors.md)
- `1ecc8368d4830de8` Research strong, execution weak is often a capacity/portfolio issue, not just a signal issue (errors.md)
- `2bb4cab621e09813` Expanding candidate count without primary-topN semantics creates micro-position drift (errors.md)
- `9d75157e798d069f` Industry ranking penalties alone do not guarantee portfolio-level diversification (errors.md)
- `58967edab4e6aa66` v8 improves invested weight but fails execution-alpha validation (learnings.md)
- `74b1f655d7ed1108` P2 execution evidence must use the canonical broker path (learnings.md)
- `52a0020f68bbb6cc` Promotion needs target-weight source and checksum evidence (learnings.md)

## Suggested Commands

```bash
python scripts/quant_memory_evolve.py
python scripts/quant_profile_promotion_review.py --write-latest
```
