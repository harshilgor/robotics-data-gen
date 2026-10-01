# Task Advisor implementation

## Scope and boundaries

This first version implements the supplied `TaskSpec -> EpisodeRecord -> CapabilityState -> ExplorationDirective` contract as a deterministic Python pipeline. It recommends capability and parameter regions. The Task Library resolves existing families; the Generator supplies missing families; the Curriculum Sampler chooses concrete assignments. This package does not execute tasks, modify generator families, or claim any measured robotics performance.

The architecture briefs are preserved. The supplied Advisor brief describes fixed evaluations feeding decisions, while the overall architecture isolates held-out evaluation. This implementation resolves that boundary with a frozen **development** benchmark that may feed Advisor decisions and a **sealed test** benchmark that must stay external. Only explicitly labelled `training` and `development` evidence is accepted. This is an input-contract safeguard, not a security boundary against a caller relabelling sealed data.

## Component reasoning and implementation

1. **Task observability:** register an exact family ID and version with capability tags and ordered, dependency-linked subgoals. `task_annotation()` adapts the existing Generator's trusted sequential DSL without modifying its strict schema. Skill tags come directly from graph nodes. Precision, stability and composition tags require future explicit predicates rather than guessing them from a task's name. General dependency graphs can be supplied in topological order.
2. **Episode contract:** validate identity, current checkpoint, exact family version, finite parameters and trajectory summaries, timezone-aware timestamp, source, terminal success and subgoal results. A subgoal is `true`, `false` or `null`: null means not observed/attempted. A failed prerequisite requires downstream results to be null. This prevents a placement failure from counting successful grasping as failure, or an early grasp failure from counting unattempted placement as failure.
3. **Evidence Engine:** group by exact family version, configurable parameter bins, source and checkpoint. Keep the latest bounded window by timestamp; aggregate success counts, completion, collisions, residual errors and failure counts. Deterministic event rules prefer grasp loss, collision and timeout; otherwise retain an explicitly supplied failure label or use the first failed predicate. Failure labels remain observed evidence, not causal proof.
4. **Capability Model:** use a Beta(1,1) prior plus observed binary stage outcomes. Expose posterior mean, standard deviation, successes and sample count. `confidence = 1 - 2*posterior_std` is a documented uncertainty score, not a calibrated probability of competence. Do not infer competence for ontology parent categories. Only observed stages contribute to primitive estimates. These estimates are conditional on tasks in which the stage was reached.
5. **Sparse combinations:** create only graph sequences exercised by real records, after a configurable minimum number of episodes. Estimate full-sequence completion rather than inventing every possible combination.
6. **Regionization:** use configurable numeric cuts with lower-inclusive, upper-exclusive intervals and open tails encoded as null. An exact family version participates in region identity. Parameters absent from a record are absent from its region descriptor. Known but unmeasured capabilities become coverage-gap requests rather than synthetic measured regions.
7. **Progress:** compare distinct explicitly selected checkpoint windows only when both reach the minimum sample count, within the same family version and bins. Do not pool old checkpoints into current competence. Development remains separately aggregated. No positive delta is claimed from tiny samples. Matching bins reduces distribution confounding but cannot eliminate shifts inside a bin or in unbinned nuisance variables; controlled probes are needed for stronger conclusions.
8. **Task-space states:** insufficient evidence is UNKNOWN; sufficient regression is REGRESSING; confidently high competence is MASTERED; positive measured progress is FRONTIER; sufficiently sampled, persistently weak, flat performance is STALLED. Remaining cases are UNKNOWN rather than inventing a sixth difficulty state. A stalled region is not asserted impossible.
9. **Selection policy:** rank using positive progress, uncertainty, competence gap and regression with explicit state gating. Frontier targets go to learn; unknown regions and unsupported ontology capabilities go to explore; regressions go to retain. Mastered/stalled targets are soft deprioritization constraints, with stalled requests suggesting easier supporting regions. The sampler remains responsible for a maintenance/exploration floor.
10. **Budget contract:** default learn/explore/retain fractions are 0.65/0.25/0.10. Target weights sum to one *within their channel*. A channel with no target receives zero, and unused capacity is explicit `unallocated_budget`; no silent reassignment or sample generation occurs. Unsupported capabilities clearly require Library or Generator support.
11. **Generator feedback:** persist a directive-linked immutable record of requested, generated, validated, scheduled tasks and executed episodes. Enforce nonnegative counts and scheduled <= validated <= generated. Requested may differ from generated because generation can oversupply. Feedback alone does not count as successful execution evidence or increase capability estimates.
12. **Persistence:** SQLite stores immutable task versions, episode IDs, feedback and complete historical snapshots; identical writes are idempotent, conflicting writes fail. Batch ingestion is transactional. No external database is necessary for V1.
13. **Orchestration and CLI:** `Advisor.advise()` joins measurements and emits a reproducible JSON snapshot and directive. The CLI ingests a JSON batch, reads prior persisted records, computes one requested checkpoint, saves a snapshot and writes JSON. It exposes no sealed evaluator or simulator integration.

## Run the labeled example

`examples/task-advisor-input.json` contains **synthetic test fixtures**, not robot measurements. Its `example_notice` explains that distinction. The example output is equally synthetic.

```powershell
python -m task_advisor --input examples/task-advisor-input.json --policy example_checkpoint_002 --previous-policy example_checkpoint_001 --db task-advisor.sqlite3 --output advisor-state.json
python -m unittest discover -s tests -v
```

Custom configuration is a JSON object matching `Config` fields, supplied with `--config`. For production, choose bins, confidence thresholds and minimum samples before evaluating comparative runs. Save the configuration with every snapshot.

## Build phases

- **Completed V1:** contracts, taskgen adapter, evidence summaries, conditional Beta capability estimates, sparse combinations, region states, budgeted directives, feedback persistence, SQLite history, CLI, synthetic fixture and tests.
- **Instrumentation interfaces implemented:** trusted predicate bindings, measured-frame adapter protocol, per-environment episode tracking, event telemetry, terminal success checks and SQLite recording. Separate exact-instance physical evidence is mandatory; Generator structural validation cannot approve execution. See `instrumentation.md`. Concrete Isaac Lab/SO-101 compiler, physical validator and rollout integration remain pending.
- **Closed-loop software implemented:** immutable exact-version execution contracts, bounded reproducible sampling, lease/attempt lifecycle, atomic episode completion, realized-state provenance and requested/generated/validated/scheduled/completed feedback. No scheduling counts become episode evidence.
- **Controlled development software implemented:** immutable manifests and checkpoint descriptors, fixed-instance seeded probe runner, Store membership/training-exclusion checks and matched-suite progress comparisons. Sealed test results remain external.
- **Research orchestration implemented:** frozen experiment plans, actual control-step budgets, multi-seed trial execution through a trainer adapter, explicit uniform-family baseline, training blocks and paired development-change reports. No learned transfer predictor, neural embeddings, autonomous LLM advisor or causal claim. See `closed-loop-implementation.md` for contracts, usage, tests and concrete-runtime limitations.

## Verification

Tests cover partial-stage attribution, unattempted-stage exclusion, Bayesian uncertainty, minimum samples, all five region states, checkpoint/bin isolation, sealed-input rejection, separate development metrics, sparse combinations, channel weights, determinism, invalid contracts, transactional ingestion, immutable records and generator-feedback persistence. Existing Generator tests run in the same suite.

Capability states additionally expose failure counts, per-region stage posteriors, sample-gated learning progress and regression. Progress averages checkpoint deltas equally over matched regions so changes in the number of episodes allocated to each region do not manufacture a capability-level improvement. It remains an observational measure rather than a causal transfer estimate. Full snapshots use a separate content hash from directives so different evidence producing the same recommendations can coexist in history.
