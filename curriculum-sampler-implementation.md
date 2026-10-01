# Curriculum Sampler implementation plan and delivery ledger

Baseline: `9af272e37f8ea7fd32aae1355ac076b6ca2275c2`; 45 tests verified with
`python -m unittest discover -s tests -v`. No AGENTS.md is present in the checkout
or its workspace parent. All supplied architecture briefs remain unchanged.

This ledger was created before implementation. Each row is initially PLANNED;
final delivery evidence and review will be recorded here and in
`curriculum-sampler-audit.md`. APIs extend the existing loop, governed Library,
Store and measured EpisodeTracker; no second Advisor or physics engine.

| Brief requirement (all numbered sections) | Concrete API/module | Verification evidence | Status |
|---|---|---|---|
| 1 ownership, Library→Advisor→sampler→scheduler→adapter→evidence | loop.CurriculumSampler, canonical TaskLibrary, sampler adapter | `test_detailed_feedback_and_advisor_only_completed_training`, `test_unresolved_advisor_allocations_are_explicit_shortfalls` | DELIVERED; verified |
| 2 all family fields, immutable exact versions/artifacts, four Library APIs | execution publication + canonical bindings, typed contract validator | `test_complete_contract_and_immutable_publication`, baseline Library tests, persistence/reopen test | DELIVERED; verified |
| 3 types, units, frames, bounds/subsets, roles, build/reset/step, dependencies, safe registry | taskgen.parameters, sampler Registry, adapter stage methods | `test_baseline_compatible_and_typed_task_dsl`, `test_registry_cannot_execute_generated_strings_or_missing_dependencies`, `test_parallel_environment_reset_isolation_terminal_order_and_stage_methods` | DELIVERED; verified |
| 4 all directive fields, categories, exclusions, minimum coverage, fallbacks, seed, expiry, frozen window | sampler directives + existing sample dispatch | `test_malformed_directives_and_controller_rejected`, `test_exclusions_and_capability_contradiction`, `test_window_freeze_expiry_and_future_directives` | DELIVERED; verified |
| 5 exact versioned regions, bounded intervals/categories, overlap provenance | directive region validation, assignment origin | `test_overlapping_regions_retain_origin_and_exact_version`, `test_immutable_region_versions_and_all_three_categories` | DELIVERED; verified |
| 6 complete immutable assignments, specification vs realized state | sampler assignment builder, recorder | `test_complete_contract_and_immutable_publication`, `test_realized_mismatch_fails_initialization_without_policy_evidence` | DELIVERED; verified |
| 7 ordered batch resolution/quotas/build/construction/checks/persistence/grouping, deterministic ties/stratification/balance/diversity/repetition | existing quotas + sampler batch helpers | `test_quota_ties_minimum_coverage_and_unallocated`, `test_constraint_rejections_and_stratified_categorical_balance`, `test_requested_diversity_vs_controlled_repetition` | DELIVERED; verified |
| 8 cheap checks, policy-driven expensive checks, four separate statuses, bounded attempts, explicit fallback and shortfall | Registry + validation_result + diagnostics | `test_registered_geometry_rejections_and_constructor_parameter_integrity`, `test_outside_envelope_validation_policy_and_reference_failure`, `test_explicit_fallback_and_no_silent_region_widening` | DELIVERED; verified |
| 9 structural compatibility, install/reset/apply/state/action/pre-reset finalize/next, independent parallel streams | AssignmentScheduler + worker adapter bridge | `test_compatibility_and_context_approval_at_lease`, parallel reset/terminal test, recorded smoke | DELIVERED; verified |
| 10 all summary fields, failure distinctions, optional timed/schema/unit/frame trajectory and privileged separation | purpose recorder and trajectory validator | `test_summary_only_and_policy_failure_are_completed_execution`, `test_trajectory_timing_units_frames_and_observation_schema_quality`, nonfinite demo test | DELIVERED; verified |
| 11 persistence/lifecycle/leases/liveness/interrupted/failed/expired/cancelled/completed, atomic idempotence, retry evidence, frozen windows | existing scheduler extension and shared SQLite | `test_parallel_sampling_reuses_frozen_budget`, `test_reopen_interrupted_attempt_and_retry_then_concurrent_completion`, `test_exact_idempotent_completion_and_conflicting_retry_rejected` | DELIVERED; verified |
| 12 fixed evaluation manifest/separate randomness/held-out/training separation, demo quality with rejected summary retention | existing BenchmarkRegistry extension + purpose recorder/export | `test_fixed_evaluation_assignments_frozen_policy_and_training_dataset_exclusion`, `test_demonstration_quality_rejections_retained_and_privileged_separation` | DELIVERED; verified |
| 13 all per-directive/category/family/region counts, reasons, actual distributions, latency, wait, fallback/shortfall | scheduler diagnostics and Advisor feedback | `test_detailed_feedback_and_advisor_only_completed_training`, `test_rollups_fallback_accounting_and_wait_metrics` | DELIVERED; verified |
| 14 meaningful full verification and recorded two-family parallel interruption smoke | tests/test_curriculum_sampler.py + runnable CLI | 86 tests pass (45 original + 41 new); `examples/curriculum-sampler-smoke.json` | DELIVERED; verified |

## Acceptance criteria (section 14, individually tracked)

| Acceptance criterion | API | Test evidence | Status |
|---|---|---|---|
| Exact versions resolve compatible artifacts | Library + lease | exact contract, canonical publication and compatibility/context tests | DELIVERED; verified |
| Valid quotas fulfilled or explicit shortfall | sample | quota, explicit fallback, coverage and all-category tests | DELIVERED; verified |
| Joint constraints prevent invalid combinations | Registry | registered constraint, geometry, constructor-integrity and fixed-distribution tests | DELIVERED; verified |
| Same input reproduces same assignments | sample | persistence/reopen/fresh-database replay and concurrent sampling tests | DELIVERED; verified |
| Environments retain separate goals/episode IDs | worker bridge | parallel environment/reset isolation test; three-env smoke | DELIVERED; verified |
| Terminal captured before reset | EpisodeTracker + bridge | trajectory timing/terminal tests; recorder/finalization ACK retry tests | DELIVERED; verified |
| Retries do not duplicate evidence | complete | interruption/recovery, stale lease, exact idempotence and concurrent completion tests | DELIVERED; verified |
| Purpose/controller provenance distinct | recorder | purpose-specific demonstration and fixed evaluation tests | DELIVERED; verified |
| Requested/executed distributions comparable | diagnostics | detailed feedback and rollup/wait/distribution tests | DELIVERED; verified |
| Episode traces to directive/family/parameters/controller/software | summary + immutable records | recorded smoke plus persistent restart/concurrent completion test | DELIVERED; verified |

## Boundary

Only synthetic adapters/attestations are used for verification. Real Isaac Lab,
SO-101 setup, physical validation and learning performance are explicitly outside
this change. No external infrastructure, credentials, learned sampler or LLM loop.

## Delivered contract details and reproducibility

All section-2 fields are validated on exact immutable publication. The v2 contract
pins typed schemas, named registered callbacks, structural configurations,
artifact hashes, observation/action schemas, reward/success versions, external
physical evidence and controllers. All section-4 fields are present in the
versioned directive; unresolved Advisor targets remain explicit. All section-6
assignment fields are present, including region version/origin, specifications,
recording profile, seed and four separate validation statuses. All section-10
summary fields are persisted under the assignment, with realized initial-state
references, purpose/controller/checkpoint/software identities and quality status.
Trajectory schemas/time/units/frame/interface/terminal boundaries are validated,
and privileged state is separate and excluded from normal dataset exports.

New typed domain support extends TaskSpec/Library/Advisor/instrumentation rather
than bypassing governance. The original float-only v1 API remains compatible.
One window pins one batch; region definitions require new versions when changed.
Context invalidation is rechecked at lease. Only actual starts/completions appear
in execution metrics, and only completed training records enter Advisor evidence.

Verification command: `python -m unittest discover -s tests -v` — **86 passed**.
Recorded smoke command:
`python -m curriculum_sampler --db /tmp/curriculum-smoke-delivery.sqlite3 --output examples/curriculum-sampler-smoke.json smoke`.
Result: **8 assignments, 8 completions, 2 approved synthetic families, 3 independent
environments, 9 attempts, 1 interruption/retry, 8 trajectories, 0 shortfall**.
Additional checks: `git diff --check`; Python `compileall` for source/tests.

The requirement-by-requirement second review and genuine live-integration
limitations are in `curriculum-sampler-audit.md`; runnable/wiring documentation is
`curriculum_sampler/README.md`. No supplied architecture brief was edited.
