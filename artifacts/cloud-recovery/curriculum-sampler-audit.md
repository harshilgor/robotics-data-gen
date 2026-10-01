# Curriculum Sampler second-pass requirement audit

This review is independent of the initial green suite (70 tests). The authoritative
brief is `curriculum-sampler.md`; the pre-implementation map is
`curriculum-sampler-implementation.md`. Baseline 45 tests passed before changes.

## Review findings requiring software fixes before delivery

1. Completion must retain demonstration summaries when optional sensor/action
   payloads contain nonfinite or non-JSON values; trajectory rejection cannot
   abort completion merely because the rejected payload is unencodable.
2. Worker step exceptions and expired ownership must be handled explicitly, and
   interrupted records must remain clearly incomplete; recorder retry must not
   take another physics step.
3. Unknown parameter/filter names and ambiguous or malformed directives must fail
   validation, while legitimate unsatisfiable regions retain explicit shortfalls.
4. Diagnostics must provide explicit directive/category/family rollups as well as
   region rows, not require clients to infer aggregation and fallback accounting.
5. Fixed evaluation freeze/assignment operations must serialize held-out checks
   with training sampling; no different-seed physical duplicate can escape the
   exclusion. Evaluation callback constraints and checkpoint membership require
   explicit tests.
6. Add concurrent sampling/completion, exact idempotence/conflicting completion,
   geometry rejection, outside-envelope expensive validation, reference-controller
   failure, quality timing/nonfinite, interrupted reopen and categorical envelope
   conflict tests; green initial tests alone do not demonstrate these requirements.

All findings above are OPEN until closure evidence is recorded below. Live Isaac
Lab/SO-101 integration is intentionally deferred by the human, not substituted for
software omissions. No learning-performance or physical-validation claim is made.

## Closure and second requirement-by-requirement review

All six findings above are **CLOSED** in this branch. The review also added immutable
region definitions, one pinned batch per frozen directive budget, exact contextual
validator/simulator checks, and explicit unresolved Advisor targets. These fixes
were rerun in the full suite, not left as future work.

| Section | Reviewed implementation and evidence | Delivery status |
|---|---|---|
| 1 Architecture ownership | Existing loop classes delegate v2 helpers; canonical Library publication/approval; training completion to Store/Advisor. `test_detailed_feedback_and_advisor_only_completed_training`. | Delivered |
| 2 Library contract | `validate_contract`, execution `publish`, canonical `publish_version` bindings and unchanged exact retrieval APIs. Complete parameter/controller/artifact/interface/reward/validation fields; immutable conflicts and publication rollback. Contract, baseline governance, patch and reopen tests. | Delivered |
| 3 Parameters/lifecycle/constraints | `taskgen.parameters` + additive TaskSpec 1.1; Registry forbids strings, unknown callback/dependency IDs and cycles; joint dependencies require declared registered constraints. Typed sparse box algebra preserves context conflicts. Build/reset/step methods and realized capture are separate. Domain, registry, categorical-governance and parallel-stage tests. | Delivered |
| 4 Directives | Content/version IDs, policy/embodiment/purpose/budget, all three categories, exact allocations, exclusions, coverage floors, declared fallback, recording/seed/window/controller/diversity. Window immutability, one-batch budget and explicit expiry; unresolved capability targets retained. Malformed/controller/exclusion/quota/window/future/all-category tests. | Delivered |
| 5 Regions | Exact version, numeric restrictions/categorical filters, immutable region ID/version definitions; overlapping regions retain actual parameters and origin. No Cartesian expansion. Overlap, version-conflict and categorical subset tests. | Delivered |
| 6 Assignments | Complete immutable schema produced by `build_assignment`; artifact/structural key, controller/checkpoint, task/environment parameters, initial/goal specs, interfaces, recording and validation. Realized state stored separately; mismatch rejects execution. Full contract/reset mismatch/traceable smoke tests. | Delivered |
| 7 Ordered algorithm | Validate→resolve exact contracts→category/region quotas→build choices→registered construction→cheap/geometry/evidence checks→persist→compatibility groups. Hamilton lexical ties, numeric strata, categorical balance, declared uniqueness/repetition. Quota/stratum/category/diversity/replay/fresh-store/concurrent sampling tests. | Delivered |
| 8 Validation/fallback | Typed finite bounds, dependency callbacks, trusted DSL/assets/interfaces, constructor integrity, explicit state/goal shape, geometry, current context approval; policy-driven expensive check inside/outside published evidence. Four separate statuses; reference failure can retain unknown feasibility. Bounded attempt diagnostics, no range widening, explicit fallback origin and unresolved/coverage/remaining shortfall. Constraint/geometry/constructor/reference/outside-envelope/fallback tests. | Delivered |
| 9 Scheduler/adapters | Key covers declared scene pool, robot/actuator/sensors/interfaces/build values; exact artifact checked and context rechecked under lease writer lock. `ExecutionAdapter`/`AssignmentEnvironments` install before reset, apply correct stages, capture actual initial state, select controller, capture pre-reset frame, commit before finalization/next assignment. Independent IDs/counters/streams and goals. Stage/parallel/terminal/lease/expiry/recorder/finalize-ACK tests. | Delivered |
| 10 Outputs | `complete` validates measured EpisodeTracker results, creates lightweight complete summaries with versions/state/params/time/steps/reward/stages/status and trajectory references. Optional schema/units/frame/time/terminal checked trajectories; privileged state separated. Bad optional payloads get explicit loss-aware markers and retained rejected summaries. Execution errors, interruptions, policy failure and timeouts remain distinct. Summary-only, malformed frame, trajectory metadata, nonfinite demo and quality tests. | Delivered |
| 11 Reliability | Existing Repository/Store SQLite infrastructure; pending/leased/running/completed assignment state, cancellation/failure/window expiry and separate failed/expired/interrupted attempt states. Liveness renewal, stale lease rejection, explicit recovery, atomic completions and first-valid-completion retry evidence policy. Recorder retains terminal for retry. Frozen batch/windows require explicit future directives and cancellation. Concurrent first completion, race leasing/sampling, reopen/interruption/retry/idempotence/conflict tests. | Delivered |
| 12 Demonstration/evaluation | Demonstration quality: success, finite/schema-bound observations/actions, action limits, timing/terminal alignment, measured collision constraints, retained rejected summaries. BenchmarkRegistry fixed manifest/generation/assignments/checkpoint digests and distinct evaluation seed stream; registry constraints required for typed manifests. Parameter-based held-out exclusion independent of seed; normal exports exclude evaluation and privileged state; explicit export exception persisted. Demo rejection, registry/fixed distribution, policy mutation and evaluation-leak/export tests. | Delivered |
| 13 Observability | Region/version rows plus directive/category/family rollups: requested/generated/rejected reasons/accepted/scheduled/actual starts/completed/interrupted/expired/failed/cancelled, fallback and budget/coverage gaps, actual values/histograms, latency/wait. Retry attempts are separate from unique assignment evidence. Only completed training records enter Advisor. Feedback/rollup/wait/distribution tests and recorded smoke. | Delivered |
| 14 Acceptance/verification | All ten acceptance criteria individually mapped in implementation ledger; 45 original + 41 new tests. Recorded smoke has two governed approved synthetic families, three independent envs, one interrupted retry, eight completions/trajectories and full provenance. | Delivered |

## Closure evidence for initial findings

1. `execution.rejected_payload` preserves invalid optional payloads safely;
   `test_demo_nonfinite_optional_payload_rejected_but_summary_durable` confirms
   summary retention and dataset rejection. No NaN is silently treated as valid.
2. Worker exceptions become failed retryable attempts; malformed measured frames
   never become policy evidence. Lease loss blocks action. Incomplete records are
   durable and survive restart; recorder/finalization ACK failures retain terminal
   ownership for retry. Dedicated worker/recovery/ACK tests cover these paths.
3. Versioned directives reject unknown/uninterpretable fields, malformed budgets,
   unsupported controllers, unknown parameters, wrong categorical filters,
   contradictions and infeasible coverage floors. Valid impossible regions retain
   bounded rejection/shortfall diagnostics. Region versions and frozen budgets
   are immutable; replay never spends a directive budget twice.
4. `scheduler.diagnostics` provides explicit hierarchical rollups and region
   distributions. Fallback request/acceptance is separately counted; top requested
   budget and remaining shortfall are not double-counted by fallback attempts.
5. Manifest freezing and sampling use the same SQLite writer transaction. Typed
   evaluation generation/freezing enforces registered cheap/geometry constraints;
   held-out identity uses exact family and physical parameters rather than seed.
   Fixed assignment dispatch is independent of adaptive quotas; policy digest
   changes interrupt before publishing misleading completed results.
6. Added the specified meaningful tests, including simultaneous first completion
   through two independent database connections (one evidence record), concurrent
   sampling (one frozen budget), actual lease racing, interrupted reopen/retry,
   expensive outside-envelope checks and categorical contextual rejection.

## Verified commands and recorded results

- `python -m unittest discover -s tests -v`: **86 tests passed**, including all
  **45 baseline tests unchanged** and **41 new sampler tests**.
- `python -m curriculum_sampler --db /tmp/curriculum-smoke-delivery.sqlite3 --output examples/curriculum-sampler-smoke.json smoke`:
  **8 accepted/completed assignments; 2 approved synthetic families; 3 independent
  environments; 9 attempts; 1 interrupted attempt followed by retry; 8 trajectories;
  8 realized initial states; 0 budget shortfall**. Each report/runtime is explicitly
  labeled synthetic. The JSON contains assignments, exact provenance, attempt
  lifecycle, summaries, recorded trajectories, feedback/distributions and adapter
  pre-reset/install/reset/finalization events.
- `python -m compileall -q curriculum_sampler task_advisor task_library taskgen tests`:
  passed. `git diff --check`: passed.
- All supplied architecture briefs are byte-for-byte unchanged from the baseline.

## Genuine upstream/live-integration limitations

- No real Isaac Lab/Isaac Sim scene compiler, SO-101 assets/actuator setup, physical
  validator, controller/teleoperator or learning runtime is installed or executed.
  The implemented adapter protocol must be supplied by the future pinned live
  integration; stage support and units/frames must match that implementation.
- External physical attestations, registered callback semantics and frozen-policy
  digests are trusted integration inputs. The software enforces identities and
  context/envelope/contracts; synthetic reports do not establish feasibility,
  simulator fidelity, solvability, learnability or training performance. Artifact
  hashes protect descriptors; live adapters must verify referenced binary assets.
- Deterministic assignments and recorded software versions support replay; equal
  seeds do not promise bitwise physics across hardware or runtime changes.
- SQLite is intentionally the existing local application backend. Bounded batch
  validation holds its writer lock for consistent approvals. No PostgreSQL,
  cloud worker services, credentials or object-store infrastructure is provisioned,
  and no high-throughput distributed deployment is claimed.
- The supported symbolic task grammar remains the existing sequential trusted
  tabletop DSL, with the implemented general numeric/categorical domain extension.
  New scene/predicate/robot grammars require their own upstream compiler/DSL work;
  this sampler accepts registered exact compiled contracts, not generated code.

No numbered software responsibility or acceptance criterion in the supplied
sampler brief remains intentionally deferred. The explicit boundaries above are
live/upstream integration and empirical claims, not relabeled sampler omissions.
