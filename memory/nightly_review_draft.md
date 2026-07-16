# Nightly Memory Review Draft

Generated at `2026-07-16 20:46:45` by `scripts/quant_memory_evolve.py`.

## Summary

- long_term_learning_entries: 116
- active_cards: 12
- active_error_cards: 91
- newly_promoted_active_hashes: e3019ff439273b18
- input_signature: `437a0e4c49972fed`

## Review Questions

- Did any fresh P2/shadow/promotion evidence contradict an active memory item?
- Did any candidate win by lower exposure rather than better execution-adjusted alpha?
- Are any active errors now resolved and ready to be marked `status: resolved`?
- Are new learnings specific enough to be reused, with evidence and action fields?

## Active Cards For Review

- `ee42163aac326712` P2 reserve re-optimization can silently overrun upstream target weights (errors.md)
- `804a2848958e0a57` Sell-trap clusters can be hidden by aggregate window metrics (errors.md)
- `3622f3b98422ad92` P2 replay can become invalid if a script-level rebalance path recomputes target weights (errors.md)
- `e3019ff439273b18` Execution limits must consume official pre-close and limit prices (errors.md)
- `4b41aa7a0fa41f82` P2 profile cap bugs make old reserve/exit-trap artifacts legacy evidence (errors.md)
- `b1f22b18a20137c4` Invested-average style gates can manufacture low-risk cash exposure (errors.md)
- `9427c1f1cf410cd5` Same row count can hide mismatched P2 evidence calendars (errors.md)
- `e4c3c4cd6fdb5c30` Score-alpha and coverage pass can still fail P2 execution smoke (errors.md)
- `defc2d7f975d27f4` Score-alpha pass can hide profile daily coverage gaps (errors.md)
- `750f1097d77c800a` Shared daily files can be stale/orphan artifacts when market bars are missing (errors.md)
- `d58c1a9eb1723810` Target-score overrides can reduce losses by starving deployment (errors.md)
- `7247b085026f5410` BJ-only shared daily files can masquerade as repeated P2 failures (errors.md)

## Suggested Commands

```bash
python scripts/quant_memory_evolve.py
python scripts/quant_profile_promotion_review.py --write-latest
```
