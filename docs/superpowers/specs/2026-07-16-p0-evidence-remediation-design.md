# P0 Evidence-Chain Remediation Design

## Status And Scope

This design governs the repair sequence after the independent review of commit
`8bb8a5ed606551a9fe71d4ac9d335461b8c0b859`. It supersedes any implication in
the earlier ODS migration design that successful read access is sufficient for
research or promotion evidence.

The repository remains an A-share research and paper-execution platform. The
default profile remains `quality_regime`, but profile, capacity, P2 performance,
and promotion work are frozen until this design's upstream gates pass.

The project may read `/Users/max/Data/ashare-source-data`; it must never modify,
repair, backfill, freeze, or otherwise mutate the shared data root.

## Decisions On The External Review

The following findings are accepted as blocking defects:

- unadjusted OHLC is used for research features and open-to-open labels;
- window-end instrument metadata is joined across historical windows;
- snapshot visibility, manifest integrity, multipart reads, and freeze status
  are not enforced;
- train/validation/test boundaries are not purged for forward label horizons;
- model feature, horizon, price, and data-lineage mismatches fail open;
- P2 removes upstream per-security target weights and recomputes a portfolio;
- open execution uses same-day high/low and current-day amount information;
- hard-blocked candidates can be restored by a non-strict fallback;
- the research backtest can skip or aggregate away per-security sell traps;
- promotion does not enforce global evidence-generation health.

The following review prescriptions are adopted with modifications:

- Data contracts must pass on every fold and artifact. Investment returns do
  not need to be positive in every fold. The raw-model gate uses preregistered
  folds, purged labels, statistical stability, worst-fold floors, and residual
  alpha tests without mechanically requiring 7/7 positive absolute returns.
- Daily-bar session fallback is permitted only for explicitly labelled
  diagnostic runs. Formal model, P2, and promotion evidence requires a complete
  authoritative calendar contract.
- Material blocked sells must continue to consume gross, industry, style, and
  target-position budgets. A full buy freeze is required only when the remaining
  risk budget is infeasible or a configured trapped-weight threshold is crossed.
- Lineage starts with a minimum sufficient immutable contract. Additional IDs
  are introduced only when they close a demonstrated ambiguity.

## Evidence State Machine

Every run belongs to exactly one evidence state:

1. `P0_BLOCKED`: one or more mandatory upstream contracts are missing or invalid.
2. `DIAGNOSTIC_ONLY`: data can be read and software behavior can be tested, but
   snapshot/calendar/PIT/freeze requirements are insufficient for investment
   evidence.
3. `RAW_MODEL_ELIGIBLE`: ODS, calendar, PIT, price, label, split, and model-input
   contracts pass on one immutable generation.
4. `EXECUTION_ELIGIBLE`: the raw-model gate passes and target/execution contracts
   are valid, allowing capacity and P2 diagnostics.
5. `PROMOTION_ELIGIBLE`: 60/90/120 P2 evidence is regenerated on one compatible
   generation/model/profile/execution contract and all hard gates pass.

No component may infer a higher state from the presence of files named
`latest`. State transitions require a machine-readable gate artifact.

## Architecture

### 1. Read-Only ODS Generation Validator

Add a validator above `AShareOdsLoader`; do not turn the loader into a large
policy object. The validator receives dataset names, date/session ranges, a
replay cutoff, and evidence mode. It returns an immutable generation contract
or a structured failure.

For every selected partition it validates:

- manifest presence and parseability;
- dataset, trade date, snapshot, and path agreement;
- `available_at` and `visible_at` against the replay cutoff;
- `freeze_status` according to evidence mode;
- all parquet parts, not only `part-0000`;
- row count, declared columns, schema hash, response/file integrity where the
  manifest contract supports it;
- primary-key uniqueness and non-empty required partitions;
- stable canonical ordering before digest calculation.

`diagnostic` mode may consume `freeze_pending` snapshots and incomplete calendar
coverage, but it must emit `DIAGNOSTIC_ONLY` and cannot feed promotion. `formal`
mode requires the supplier's frozen/visible contract and fails closed. The
project never changes a supplier manifest.

Minimum lineage fields are:

- `generation_id` and partition-manifest digests;
- evidence mode/state and replay cutoff;
- code commit and environment lock hash;
- calendar, price, universe, feature, label, split, model, profile, and execution
  contract IDs when those stages exist.

### 2. Calendar And PIT Universe Contract

Formal evidence obtains next/previous sessions from a complete authoritative
calendar. Missing calendar coverage is a failure, not a non-trading-day
inference. A bars-derived session list remains available for diagnostic tooling
and is labelled in lineage.

Historical eligibility is produced from point-in-time security state. Required
fields include listing/delisting status, exchange/board, ST/risk-warning status,
industry where industry constraints are enabled, and suspension/trading status.
Every state must be effective and visible by the signal cutoff.

If the shared ODS cannot supply a required historical field, the project fails
closed for the dependent use case. It does not manufacture a PIT table from the
current master. Display names may use current metadata only when explicitly
marked descriptive and excluded from eligibility logic.

### 3. Four Price Domains

The data layer exposes distinct contracts:

- `research_adjusted`: signal-date-safe adjusted OHLC for features;
- `label_total_return`: adjusted entry/exit prices available only after the
  label exit session;
- `execution_raw`: raw OHLC and cash/NAV prices;
- `execution_official_state`: official pre-close, upper/lower limits,
  suspension/trading status, board, lot, and tick semantics.

Feature construction may not access factors visible after the signal cutoff.
Labels may use exit factors only after `label_available_at`; that information
never enters features. Corporate-action invariance tests determine the actual
factor direction rather than assuming a qfq/hfq convention.

### 4. Temporal Model Contract

Every labelled row carries `label_entry_date`, `label_exit_date`, and
`label_available_at`. Split construction purges rows whose outcomes cross the
next boundary and applies a preregistered embargo. Feature selection and IC
selection use training data only.

The model package becomes self-describing and fail-closed. At minimum it binds:

- generation, price, universe, feature-schema, label, and split IDs;
- exact feature names, order, dtypes, missing-value policy, and direction;
- objective, horizon, seed, code commit, environment lock, and model hash.

Inference rejects missing features, dtype/order mismatches, incompatible
horizons, and generation mismatches. It never silently fills a missing model
feature with zero.

### 5. Raw-Universe Gate

The gate uses seven fixed, complete, non-overlapping OOS folds with purged
outcomes. Ascending score direction remains diagnostic only.

Mandatory data/method conditions pass 7/7. Investment acceptance requires:

- positive pooled and fold-stable residual RankIC and top-minus-pool spread;
- at least 6/7 folds with the preregistered alpha direction;
- no critical fold below a preregistered after-cost loss/spread floor;
- confidence intervals or block-bootstrap evidence that accounts for serial
  dependence;
- explicit industry, size, liquidity, beta, and momentum residual attribution;
- preregistered weak-regime deploy/no-trade behavior rather than an ex-post veto;
- multiple-experiment tracking so repeated model variants do not reset the gate.

Exact numerical thresholds are registered before the first rebuilt run and
cannot be changed based on those results. A failed gate returns to model
diagnosis; it never creates a profile.

### 6. Immutable Target Instruction And Execution Transforms

Daily selection emits one immutable per-security target instruction containing
scores/ranks, target weights, effective profile/config digest, constraint digest,
generation/model IDs, signal cutoff, and target checksum.

P2, pretrade, and broker may not silently recompute that instruction. A valid
change creates a child instruction with:

- parent checksum;
- deterministic transform type and parameters;
- affected securities and reasons;
- child checksum and resulting cash/constraint diagnostics.

Reserve replacement, capacity clipping, industry clipping, lot rounding, and
blocked-order handling are transforms, not undocumented reranking.

Open execution uses only information available at the modeled execution time.
With daily data and an open-order model, `open == official up_limit` blocks buys
and `open == official down_limit` blocks sells. A later intraday unlock cannot
produce an open-price fill. Trade-day full amount and high/low are post-trade
TCA fields; pre-open capacity uses information through the signal date.

Blocked positions remain in NAV and consume all relevant risk budgets. The
post-trade portfolio, including trapped holdings, must satisfy gross, industry,
style, and cash constraints or freeze/reject new buys.

### 7. Backtest And Promotion Evidence

The research backtest is either rebuilt on the canonical event/broker kernel or
explicitly labelled `research_only_non_executable`. It may not support promotion
while it can skip whole trades whose constituents have different exit states.

Promotion begins with a global evidence-health gate applied to main and
candidate profiles. Missing mandatory artifacts, mixed IDs, absent raw-model
evidence, checksum inequality, or `DIAGNOSTIC_ONLY` data fails the review before
performance comparison. The main profile remains the configured default, but
is not automatically declared evidence-valid.

## Delivery Phases And Stop Conditions

This design is intentionally decomposed into five implementation plans rather
than one cross-repository mega-plan. Each plan produces a usable gate artifact,
tests, documentation, Skill guidance, and memory updates. Plans 2-5 may be
written in advance for dependency visibility, but they are not executed until
the preceding phase reports a passing state.

### Phase 1: Generation And Calendar Validation

Deliver the ODS validator, evidence modes, complete-part reads, environment/code
lineage, and calendar contract.

Stop if formal frozen/visible snapshots or authoritative calendar coverage are
unavailable. Continue only diagnostic software work while blocked.

### Phase 2: PIT And Price Contracts

Deliver PIT eligibility/state adapters, four price domains, official execution
limits, and corporate-action tests.

Stop if historical ST/listing/industry/trading states cannot be obtained for a
requested use case. Do not approximate them from current names or a window-end
master.

### Phase 3: Model Temporal Integrity

Deliver label availability, purged splits, train-only feature selection, model
contracts, and fail-closed inference.

Stop if any incompatible model can write a daily signal or any outcome crosses
a split boundary.

### Phase 4: Target And Execution Integrity

Deliver immutable target instructions, declared transforms, official open
tradability, signal-date capacity inputs, blocked-sell budget accounting, and a
canonical per-security replay path.

Stop if any unexplained target checksum difference or risk-budget overrun is
possible.

### Phase 5: Evidence Rebuild

Register thresholds, train H=8/H=10 candidates, and run the full raw-universe
gate on one generation. Only a passing model proceeds to RMB 1,000,000 capacity
analysis, profile-isolated daily signals, 20-day execution smoke, 60/90/120 P2,
shadow diagnosis, and formal promotion review.

Any data/lineage/execution failure invalidates affected downstream artifacts.
A pure performance failure remains valid negative evidence and does not permit
parameter relaxation or threshold changes.

## Test Strategy

Tests are organized by invariant rather than by script:

- manifest visibility, freeze, multipart, row-count, schema/hash, and primary key;
- complete versus diagnostic calendar behavior;
- PIT listing/ST/industry/status transitions and delisted-name retention;
- corporate-action feature invariance and total-return label reconciliation;
- label boundary purge and embargo;
- model generation/horizon/schema/order/dtype mismatch failures;
- hard-blocked candidates never returning through fallback;
- daily/pretrade/P2/broker checksum equality and explicit transforms;
- official-limit open blocking without same-day high/low leakage;
- signal-date ADV calculation excluding the execution day's amount;
- trapped holdings consuming gross, industry, style, and cash budgets;
- per-security partial exits in the canonical event path;
- promotion rejection for missing, diagnostic, mixed-generation, or mismatched
  evidence.

All commands run in Conda `stock`. Tests use synthetic fixtures or read-only ODS
smoke access and never mutate the shared root.

## Documentation, Skill, And Memory Updates

The implementation plan must update:

- `README.md`, `docs/PROJECT_INDEX.md`, `docs/WORKFLOW.md`,
  `docs/ML_TRAINING.md`, and `docs/EXPERT_REVIEW_BRIEF.md` with the evidence
  state machine and current stop point;
- the repo-local audit Skill and its checklist/project map/maintenance loop with
  purge, official-open semantics, immutable target lineage, and calibrated
  fold-stability rules;
- `memory/profile.md`, `memory/errors.md`, and `memory/learnings.md`, followed by
  `scripts/quant_memory_evolve.py` to refresh active memory.

Historical v7-v29 and pre-ODS artifacts remain available for failure-mode
diagnosis but are never relabelled as current evidence.

The master remediation plan owns cross-phase sequencing. Each phase plan owns
only the files and invariants required for that phase, preventing concurrent
edits to the same execution-critical modules without an explicit dependency.

## Non-Goals

- No shared ODS mutation or supplier-side freeze repair.
- No new profile, risk relaxation, P2 performance refresh, or promotion.
- No claim that module count, test count, or governance documents prove alpha.
- No requirement that every OOS fold have positive long-only absolute return.
- No attempt to fabricate missing historical PIT state from current snapshots.
- No large unrelated architecture refactor while a narrower contract boundary
  can close the defect.
