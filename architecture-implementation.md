# Canonical architecture implementation ledger

**Completeness correction:** the final source audit found partial implementations
and missing local integrations. This table records delivered scope, not full
architecture completion. See `architecture-final-audit.md` for the remaining
semantic/compiler bridge, scene/domain realization, discovery/capability coverage,
Advisor feedback, held-out evaluation, repeated adaptive loop and versioning gaps.

Source: user-updated `original-architecture.md`, all 53 sections. First runtime:
local synthetic, as requested. Existing APIs and supplied briefs are preserved.

| Sections | Delivered local implementation | Verification |
|---|---|---|
| 1–2 | Modular packages; factory orchestrates existing Library/Advisor/generator/sampler engines | Complete factory cycle and legacy regressions |
| 3–7 | Versioned `semantics` registry, measured predicates, object roles, capability hierarchy, symbolic DAG grammar and sequential execution TaskSpec 1.2 | Immutable definitions, unknown symbols, role/precondition/units checks |
| 8–12 | Governed Library identity, lifecycle, contextual envelopes, versioned resources, compatibility and parent lineage | Publication, recovery, lifecycle and guided composition tests |
| 13–14 | Library-first bounded discovery; trusted composition/mutation/templates; injectable declarative proposal provider; novelty scores | Gap closure, redundant generation avoidance, unsafe proposals, parent resolution |
| 15 | Hashed CompiledTask with exact resources, schemas/units/frames, reward/success/termination and reference plan | Compilation determinism, artifact tamper rejection, complete contracts |
| 16–18 | Immutable procedural asset/scene/robot resources and trusted synthetic reference skills/controllers | Affordance resolution and broad reference executions |
| 19 | Structural/logical/affordance/geometry and surrogate kinematic/collision/physics/reset/reference validator layers | Unsafe size rejection and reference failure distinguished from infeasibility |
| 20–28 | Existing measured evidence, attribution, region/capability models and Advisor; shared default ontology | Advisor regressions and measured training evidence |
| 29 | Directive coverage lookup before generation; all new tasks compiled, validated and governed | Coverage closure and explicit unresolved targets |
| 30–31 | Recovered full cloud sampler: typed parameters, constraints, quotas, diversity, fixed windows, exact instances and explicit shortfalls | 41 imported sampler tests rerun locally; broader integration |
| 32–33 | Exact assignment leases, independent environments, actual reset state, pre-reset terminal capture and durable retry; action-driven local runtime | Three environments, interruption/retry, isolation and terminal order |
| 34–35 | Configurable state/action/reward plus synchronized RGB/depth; separate privileged measurements; external JSON/binary payloads | Shape/units/encoding/timing checks, checksums, persistence/reopen |
| 36–37 | Integrity curation, retained failures, deduplication, distribution/exclusion reports, immutable dataset manifests and export | Corrupt/missing/nonfinite rejection, historical binding replay, evaluation exclusion, privileged stream removal |
| 38 | Replaceable TrainingBackend, demonstration motion calibration, training records and hashed checkpoint objects | Dataset-derived gain and checkpoint corruption rejection |
| 39–40 | Frozen BenchmarkRegistry, exact cases/independent seeds, frozen policy checks, actual local before/after probes; existing ResearchLedger comparisons | Fixed manifest/policy tests and measured local suite comparison |
| 41 | Requested/generated/rejected/validated/scheduled/executed funnel with per-category/family/region counts, distributions, reasons and shortfalls | Detailed sampler diagnostics and full cycle report |
| 42 | Exact semantic/resource/compiler/controller/software/checkpoint/assignment dependencies and initial-state/payload references | Reopen/replay, tamper rejection and historical manifests |
| 43 | Verified SQLite metadata plus local object storage; optional PostgreSQL transport with writer transactions and restored event identities | SQLite integration, PostgreSQL transport checks; live PG test opt-in |
| 44–45 | Shared validated contracts and safe registries; runtime/training/proposal boundaries extend existing engines | Legacy compatibility and new integration tests |
| 46–48 | Runnable publish/evaluate/demo/curate/train/evaluate/evidence/advise/discover/sample cycle; 14 broad seed configurations | CLI broad smoke and training-cycle tests |
| 49–50 | Arbitrary generated code, QD/evolution/adversarial search and learned transfer prediction excluded | Unsafe proposals and callback registry rejection |
| 51–53 | Robot-neutral roles and replaceable runtime/training boundaries; broad manipulation task coverage | Insertion, articulation, obstacles, stacking and multi-object execution |

## Verification

Baseline: 45 tests. The cloud delivery added 41 sampler tests, all rerun locally.
The recovered source archive reproduces Git tree
`253e0f6152b1d6bffdd5dd37f7adb2b25768d045` for reported cloud commit
`42123af55c3781880b16585b7afbe770338b1e1d`. Verify with
`python tools/verify_cloud_recovery.py`. The archive preserves the imported
delivery; active sources include subsequent architecture work.

Run `python -m unittest discover -s tests -v` for all checks. Run
`python -m factory --root artifacts/my-cycle --episodes 14 --broad` for the full
cycle; add `--modalities rgb depth` for sensor payloads. Choose a fresh root.

Final broad smoke: `artifacts/factory-final/cycle-report.json` contains 14 curated
demonstrations with RGB/depth, three environment workers, an interrupted retry,
and 28 fixed evaluation cases. Initial motion gain succeeded on 0/28; the fitted
gain succeeded on 28/28 against the same frozen suite. This is a synthetic
integration result with a trusted task-stage prior, not general robot learning.
The next Advisor window requested 14 episodes and produced 3 assignments with
11 explicit coverage shortfalls. Unsupported or uncovered capability requests
are retained as diagnostics; generation never silently widens their constraints.
Final verification: 118 tests ran, 117 passed and one live PostgreSQL integration
test skipped. Python compilation and Git whitespace checks passed.

## Runtime and model boundaries

- No Isaac Lab/SO-101 runtime was connected. `ExecutionAdapter` is the integration
  contract. The local model approximates point motion, contact, grasp and support;
  it has no robot joints, real IK, calibrated dynamics or realistic cameras.
  Procedural assets/scene categories do not certify arbitrary physical layouts.
- General semantic DAG validation and sequential execution TaskSpec are distinct.
  The local compiler executes supported sequential TaskSpecs 1.1/1.2, not
  concurrent semantic DAGs. Unbound parameters and unsupported interfaces reject.
- The policy baseline learns one motion gain using a trusted task-stage prior.
  Frozen results do not establish causal transfer or physical generalization.
  Extra held-out scenes/object combinations/compositions can be registered as
  exact cases; default CLI evaluation varies independent seed-task parameters.
- Hosted LLM generation is an injectable ProposalProvider. No model service is
  configured; deterministic trusted generation is runnable locally.
- PostgreSQL transport is implemented with unit checks. Its live test requires
  psycopg 3 and `ROBOTICS_TEST_POSTGRES_DSN`; it is skipped without a server.
  SQLite and external local files are verified end to end.

Older engine ledgers describe their earlier deliveries. This ledger and README
describe the integrated local runtime. Synthetic validation is explicitly scoped
to the surrogate; a real adapter needs its own validation context and evidence.
