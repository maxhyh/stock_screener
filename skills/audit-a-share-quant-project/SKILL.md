---
name: audit-a-share-quant-project
description: Deep audit, recurring maintenance, performance review, documentation/skill hygiene, and robustness hardening for this specific A-share quant trading repository. Use when Codex needs to inspect or continuously improve this repo's Python strategy, data pipeline, training, backtest, execution, orchestration, documentation, local skills, or project memory for look-ahead bias, A-share trading-rule mismatches, ST or suspension filtering gaps, slippage and tax mistakes, Pandas bottlenecks, risk-control inconsistencies, architecture improvements, duplicate docs/skills, or long-term project health.
---

# Audit A Share Quant Project

## Overview

Audit this repository as an A-share production trading system, not as a generic Python project. Focus first on silent PnL distortions and execution mismatches, then on speed, memory use, modularity, and repeated maintainability over many future iterations.

## Start Here

- Treat this as a repo-specific skill. Read code before recommending structural changes.
- Read [references/project-map.md](references/project-map.md) first for entrypoints and likely hotspots.
- Read [references/maintenance-loop.md](references/maintenance-loop.md) when the task is ongoing optimization, not a one-off review.
- Read [references/codex-engineering-discipline.md](references/codex-engineering-discipline.md) before making strategy, execution, promotion, or architecture changes.
- Read [references/priority-model.md](references/priority-model.md) before ranking findings or choosing the next maintenance target.
- Read [references/output-template.md](references/output-template.md) when the user wants a full audit report or a recurring maintenance summary.
- Run `python skills/audit-a-share-quant-project/scripts/find_audit_hotspots.py` from the repo root to surface likely bias, performance, and robustness matches.
- Run `python skills/audit-a-share-quant-project/scripts/build_maintenance_snapshot.py` from the repo root when you need a recurring status snapshot before or after a maintenance pass.
- For documentation or skill-hygiene tasks, inspect `docs/DOCUMENTATION_AND_SKILLS.md`, `docs/README.md`, `docs/PROJECT_INDEX.md`, `AGENTS.md`, `agent.md`, and this skill's `references/`.
- When the task is strategy promotion or shadow tracking, also inspect:
  `scripts/quant_p2_rolling_replay.py`
  `scripts/quant_p2_shadow_diagnosis.py`
  `scripts/quant_profile_promotion_review.py`
- Prefer the production chain over `archive/`.
- If the user asks for fixes, implement them instead of stopping at analysis.

## Audit Order

1. Inspect the production chain:
   `scripts/daily_all.py`
   `scripts/daily_incremental_update.py`
   `scripts/daily_ml_select.py`
   `core/mfts_screener.py`
   `scripts/quant_portfolio_backtest.py`
   `core/risk/pretrade.py`
   `core/execution/paper_broker.py`
2. Verify A-share execution assumptions:
   T+1,涨跌停, ST, 停牌, 北交所排除, 印花税卖出单边, lot size, next-trade-day alignment.
3. Verify label and backtest consistency:
   training label mode, `daily_verify` label mode, portfolio entry and exit timing, P2 and P3 alignment.
4. Profile Pandas hotspots:
   row loops, `iterrows`, `apply(axis=1)`, repeated `groupby().transform(lambda x: x.rolling(...))`, full-file parquet loads.
5. Check robustness:
   broad exceptions, metadata coverage gates, state leakage, output coupling, weak fallbacks.
6. For strategy upgrade candidates:
   compare research strength against P2 shadow evidence and do not recommend promotion if execution-side NAV, ADV blocking, or industry concentration clearly worsen.

## Maintenance Mode

- Treat this skill as cumulative. Each use should either reduce confirmed risk, improve observability, or leave behind a reusable test or tool.
- Apply the Codex engineering discipline: think before changing, keep patches simple, preserve evidence lineage, and define verification before coding.
- Do not repeat closed findings without checking whether the code or data path changed.
- Prefer small, high-leverage fixes over wide refactors unless the user explicitly asks for architectural change.
- When you confirm and fix a risk, update tests or add a new regression that would fail on the old behavior.
- Leave a clear “next maintenance target” when the current pass surfaces more issues than should be fixed in one go.
- Do not request external expert review after every pass. Keep working locally when the next patch, replay, attribution, or promotion artifact is clear. Escalate only for genuine uncertainty, strategic forks, unresolved methodology risk, or near-promotion/default-profile decisions that need independent scrutiny.
- When expert review is needed, first prepare a clean GitHub snapshot, then provide a complete expert prompt that states the expert role, current repository state, evidence paths, unresolved questions, and the specific decision needing review.

## Prioritization Rules

- Rank findings using the repo-specific model in `references/priority-model.md`.
- Bias toward issues that can silently inflate backtest or paper-trade quality.
- In ties, prefer:
  production-path files,
  execution realism,
  regressions that are cheap to test,
  fixes that reduce future maintenance load.
- Treat “small patch, large realism gain” as higher value than large architectural cleanup.

## Long-Term Improvement Rules

- Keep strategy logic, execution realism, and orchestration concerns separated.
- Prefer repo-native scripts and references over long repeated explanation in future turns.
- Keep documentation responsibilities separated: `README.md` for onboarding, `docs/PROJECT_INDEX.md` for topology, `docs/WORKFLOW.md` for commands, `docs/DOCUMENTATION_AND_SKILLS.md` for doc/skill governance, and expert-review docs only for review snapshots.
- Do not add a new repo-local skill unless its trigger boundary is stable, recurring, and clearly separate from this audit skill.
- When you discover a recurring repo pattern, encode it here or in `references/` so the next maintenance pass starts with better context.
- Use maintenance snapshots to compare whether hotspot counts and risk surfaces are shrinking over time.
- Treat shadow diagnostics as first-class maintenance evidence when the current target is a profile or strategy candidate rather than a core engine bug.

## What To Look For

### Logic And Alpha

- Never allow future data in factors, labels, or execution simulation. Inspect `shift(-n)`, exit-price lookup, target-date slicing, and merge logic.
- Confirm suspended, ST, limit-locked, and untradable names are filtered consistently across scan, ML, backtest, and execution.
- Compare ranking universe, gated universe, and executed universe. Call out any mismatch that can create fake paper alpha.
- Treat missing industry classification as a real risk because it weakens industry caps and exposure reports.

### Performance

- Prioritize hot paths that run on 5000+ stocks over cosmetic cleanup.
- Replace row loops and repeated rolling lambdas in core factor computation before optimizing report pages.
- Reduce parquet reads to needed columns and date windows whenever possible.
- Prefer vectorized grouped operations, categorical codes, and one-pass precomputation.

### Financial Engineering

- Check that commissions, slippage, and stamp duty are applied on the correct side and at the correct trade event.
- Scale benchmark and excess-return math by realized exposure when the strategy is not always fully invested.
- Prefer metrics that match the actual holding-period and execution regime:
  max drawdown, Sortino, Calmar, turnover, block rate, exposure-adjusted excess return.

### Robustness

- Flag broad `except Exception` blocks that hide production failures.
- Check metadata and industry coverage gates before P2 and P3 execution.
- Keep strategy logic decoupled from orchestration and reporting.
- Add or update tests whenever you fix a confirmed risk.

## Output Contract

- Report severe bugs and silent-risk mismatches first.
- Then provide optimized core snippets or concrete patches.
- End with A-share market-environment suggestions tied to regime, liquidity, crowding, and execution feasibility.
- Distinguish between `already fixed in this branch`, `confirmed issue`, and `suspected issue needing data verification`.
- For recurring maintenance tasks, also include:
  what improved in this pass,
  what still needs attention,
  what should be audited next.
- Prefer the response formats in `references/output-template.md` when the task is a formal audit or recurring maintenance update.

## References

- Read [references/project-map.md](references/project-map.md) for repo topology and likely hotspot files.
- Read [references/audit-checklist.md](references/audit-checklist.md) for repo-specific audit checks and response shape.
- Read [references/maintenance-loop.md](references/maintenance-loop.md) for recurring optimization workflow.
- Read [references/codex-engineering-discipline.md](references/codex-engineering-discipline.md) for the project-specific adaptation of Karpathy-style coding-agent discipline.
- Read [references/priority-model.md](references/priority-model.md) for finding severity and maintenance target selection.
- Read [references/output-template.md](references/output-template.md) for reusable report shapes.
