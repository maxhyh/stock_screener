# Codex Engineering Discipline

This reference adapts the useful parts of the MIT-licensed
`forrestchang/andrej-karpathy-skills` guidance for this A-share quant project
and Codex workflows. It is not a Claude instruction file. It is a local
engineering contract for strategy, execution, promotion, and architecture work.

## Goal

Reduce the failure modes that are costly in this repository:

- silent assumptions that create fake alpha;
- broad refactors that break evidence lineage;
- profile tweaks that improve optics by lowering exposure;
- promotion arguments that outrun P2, shadow, and gate evidence;
- repeated rediscovery of known execution traps.

## 1. Think Before Changing

Before touching strategy, backtest, P2 execution, promotion, or memory logic:

- Re-read `memory/profile.md`, `memory/actives.md`, and, for execution or risk work, `memory/errors.md`.
- State the working assumption in one sentence when the task is ambiguous or high impact.
- If multiple interpretations can materially change behavior, surface the tradeoff before implementing.
- Push back on requests that would relax risk controls merely to improve NAV.
- Prefer local evidence over memory, docs, or prior conclusions when they conflict.

Codex default: keep moving when the next technical step is clear; ask only when a reasonable assumption would be risky.

## 2. Simplicity Before Cleverness

Use the smallest change that produces better evidence or removes a confirmed risk.

- Do not add new strategy parameters unless they answer a diagnosed bottleneck.
- Do not add abstractions for a one-off experiment.
- Do not create a new profile just because a metric can be nudged.
- Do not expand a report if the production path has an untested credibility risk.
- Remove only dead code introduced by your own patch unless the user explicitly asks for cleanup.

For this repo, a simple patch with a regression test beats a large optimizer rewrite without evidence.

## 3. Surgical Edits And Evidence Lineage

Every changed line should trace to the active request or to a test needed for that request.

- Preserve target-weight lineage: daily selection, portfolio engine, P2 broker, rolling replay, and promotion evidence must agree.
- Do not mix shared daily signals into profile-isolated replay.
- Do not compare a fixed candidate against stale main-profile evidence.
- Do not rewrite adjacent files, formatting, configs, or docs as drive-by cleanup.
- If unrelated dirty changes exist, work around them and leave them intact.

For profile work, prefer a new shadow profile over modifying `quality_regime` or any current default.

## 4. Goal-Driven Execution

Convert tasks into verifiable outcomes before coding.

Examples:

- "Fix execution gap" -> "Add a regression that proves P2 consumes upstream `target_weight`, then rerun a smoke replay."
- "Improve vNext" -> "Define the hypothesis, generate profile-isolated daily signals, run score/stage diagnostics, then decide whether P2 smoke is warranted."
- "Promotion review" -> "Run same-generation 60/90/120 P2 evidence and promotion gate artifacts; promotion is impossible without gate pass."

Use the lightest sufficient verification:

- docs-only changes: markdown/link sanity and relevant file inspection;
- helper logic: targeted tests;
- execution or risk logic: targeted tests plus P2 smoke when behavior changes;
- promotion/default-profile decisions: 60/90/120 P2, shadow diagnosis, and formal promotion review.

## 5. Quant-Specific Guardrails

Never accept an apparent improvement until these questions are answered:

- Did target exposure rise, fall, or silently become cash?
- Did NAV improve after cost, capacity, industry, style, T+1, suspension, ST, BJ/9-code, and limit constraints?
- Did the candidate beat the main profile under the same data-quality and execution口径?
- Is the alpha source raw prediction, industry/size/liquidity exposure, execution residual, or cash drag?
- Are blocked orders, executable-pool halts, empty signals, and broker tradability blocks separated?

If a candidate loses less by investing less, mark it as diagnostic only.

## 6. Expert Review Escalation

Do not request expert review as a routine checkpoint.

Escalate only when:

- fresh evidence supports incompatible strategic paths;
- a methodology flaw cannot be resolved locally;
- a candidate is near promotion/default-profile change;
- local artifacts contradict the current thesis and the next action is genuinely uncertain.

When escalation is needed, prepare a clean GitHub snapshot first and give the user a complete expert-review prompt with role, state, evidence paths, unresolved questions, and decisions needing review.

## Working Definition Of Done

A maintenance pass is done when:

- the patch is scoped and explainable;
- relevant tests or diagnostics pass;
- generated evidence is summarized with paths;
- durable findings or traps are written to memory when meaningful;
- the next local target is clear, or expert escalation is explicitly justified.
