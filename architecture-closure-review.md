# Architecture implementation review

Goal: implement remaining architecture software, verify the complete supported
synthetic flow, and document genuine external validation limitations.

Base: main `bf80e2e63007ecf76a6e0cd447438b86a8f9a345`. The canonical
`original-architecture.md` and original engine briefs are preserved.
`architecture-final-audit.md` is the supplied, unchanged baseline audit.
This review supersedes earlier broad completion claims. **The whole architecture
is not complete:** the supported local factory is substantially expanded and
verified; the full governed physical worker integration remains software work.

## Required closures

| Request | Result and evidence | Limits |
|---|---|---|
| 1. Shared task semantics | Implemented for the supported grammar. `semantic-1.0` lowers to source-pinned execution 1.3. Registry predicates evaluate reset, source skill effects, conjunction goals, constraints, termination, reward and attribution. Compound inside/stable placement and two-object DAG execution are tested. | A single gripper serializes available object streams. Unordered conflicting writes/read-writes are rejected. Unsupported initial predicates and physical tasks fail explicitly; arbitrary parallel resource graphs are not claimed. Legacy 1.0/1.1/1.2 remain accepted. |
| 2. Real local realization | Procedural finite geometry realizes inside/above/beside/obstructs, container interiors, drawer-gated access, target capacity, shelf support, stacking, signed yaw, fit/contact, swept obstacle collision, mass/friction/grip effects. Typed geometry, count, layout, approach, appearance and disturbance bindings change modeled state or sensor output. Cyclic/conflicting placement and unsupported bindings fail. | This is a Cartesian surrogate with simplified contact and table support, not rigid-body dynamics or SO-101 kinematics. Appearance affects diagnostic RGB; it does not affect a state-only policy. Envelopes are two bound probes plus compulsory per-instance reference execution, not continuous certification. |
| 3. Discovery | Structural object/role expansion, obstacle/spatial/layout/approach/geometry mutation; bounded library-first discovery; goal, relation and constraint-topology novelty. Concrete HTTPS hosted JSON proposal provider and deterministic offline transport fixtures validate the same bounded allowlisted grammar. | No hosted call was made. Domain proposals remain subject to compiler, validator and governance. Structural mutation operates on execution tasks; semantic proposals can be lowered and published. No QD/evolution. |
| 4. Capability evidence | One conditional outcome per episode/capability, ancestor rollup, measured sequencing/long horizon, positional/orientation/contact precision, holding exposure and grasp-loss stability, slide/recovery task events. Advisor and transfer use the same rollup. | Ancestors and combined tasks are observational evidence, not isolated causal skill measurements. Sparse uncertainty and unresolved targets remain. Recovery disturbance is a controlled synthetic task, not robust physical recovery evidence. |
| 5. Funnel feedback | Request-keyed scheduler requested/generated/validated/scheduled/executed feedback and sampling diagnostics persist with directive/policy identity; Advisor consumes it and separately identified discovery runs. | Funnel diagnostics do not become capability trials. |
| 6. Held-out suite/transfer | Fourteen frozen cases in seven partitions: precision, contact, long horizon, unseen parameter interval, layout, object combination, composition. Reserve before demonstration generation; structure-based reservations survive metadata changes. Exact evaluation cases, families and reserved regions are excluded from training. Per-task/capability pre/post changes and training exposures persist each iteration. | Small development suite, not a statistical generalization benchmark; association only, no causal transfer. |
| 7. Adaptive loop/training | Immutable phase journal resumes across process restart. Advisor batches execute, accepted experience (including failures) trains each next checkpoint, same frozen suite evaluates each checkpoint. Bounded complete-action behavior cloning learns translation, gripper, orientation and drawer actions; trusted task predicates supply phase. Extensible trusted checkpoint schemas replace a single-gain-only contract. Process locks exclude simultaneous local executors and recover dead local leases without duplicate completions. | Unix process locking is the supported local runner. This imitation baseline is not PPO, general robotics, or proof of learning improvement. Concurrent distributed training orchestration is not implemented. |
| 8. Publication classification | Metadata-only patch, compatible domain extension minor, incompatible structure/schema/domain narrowing major; exact immutable versions, lineage, history, dependencies and artifact references remain governed. | The conservative classifier can require a major for changes a domain expert might migrate. |
| 9. Optional integrations/additional omissions | Configurable version-pinned SO-101 USD/joints/actuators, articulated drawer USD/joint bindings, procedural parallel Isaac scenes/contacts/reset/joint stepping, measured-Jacobian bounded DLS translation control, opt-in LeRobot transport; PostgreSQL store selectable in factory, content-addressed S3 transport with write opt-in and integrity/idempotency checks. | **Partial software:** the Isaac low-level runtime is not yet a complete `AssignmentEnvironments.ExecutionAdapter` with governed physical validation, calibrated contact attribution, full task predicate telemetry and terminal recording. It must not reuse synthetic validation approval. Live Isaac/Sim, USD dynamics, GPU, physical hardware, PostgreSQL, S3 and hosted LLM remain unvalidated here. |

## Supported semantic transformation

The compiler pins the complete semantic source and registry digest. It expands
transport into lift/transport and insert into align/insert. Source effects are
checked at the final expanded node. The execution chain preserves original
edges, prioritizes finishing an available object stream, and rejects unordered
same-object or object/target hazards. Targets shared by disjoint insertion streams
receive capacity-checked slots. It never changes a compound source goal into a
single success condition: the source conjunction and constraints determine
terminal success, and are independently replayed by episode instrumentation.

Supported initial realizations are reachable, near, stable, inside, outside,
aligned and open; reset verifies them. Outside/reachable/stable that cannot be
realized in the chosen scene fail validation. Declarative schema validation and
trusted predicate implementations remain separate from measured feasibility.
Unknown parameters and unsafe generated code are rejected.

## All 53 sections

“Local” means implemented within the explicitly supported synthetic contracts.
“Partial” identifies remaining software, rather than disguising it as external
validation. “External” requires real deployment evidence.

| Section | Review |
|---|---|
| 1 | Local ownership/portability; external physical semantics portability pending. |
| 2 | Local generation/intelligence/training separation preserved. |
| 3 | Local source-pinned role TaskSpec bridge; bounded grammar. |
| 4 | Local shared predicates across source-task lifecycle; trusted evaluator only. |
| 5 | Local affordance/resource resolution; external asset calibration. |
| 6 | Local hierarchy with deduplicated evidence and explicit uncertainty. |
| 7 | Local compound goals and resource-safe deterministic DAG lowering. |
| 8 | Local governed canonical library and exact lookup. |
| 9 | Local lifecycle, immutable history and activation rules retained. |
| 10 | Local contextual bound-probe envelopes and per-instance validation; external physical envelopes. |
| 11 | Local approved-context compatibility; physical contexts cannot inherit it. |
| 12 | Local patch/minor/major classification, exact dependencies and provenance. |
| 13 | Local structural generation/mutation/novelty; hosted implementation offline tested, external live call. |
| 14 | Non-goals respected. |
| 15 | Local semantic/compiler bindings; partial governed physical compiler-worker integration. |
| 16 | Local finite procedural resources; version/hash-pinned deployment USD binding, external dynamics. |
| 17 | Local realized layouts and constraints; optional Isaac procedural geometry, external execution. |
| 18 | Local trusted skills including slide/recovery; partial full physical skill plans. |
| 19 | Local layered/reference validation; partial governed measured physical validator. |
| 20 | Local task intelligence and policy-versioned evidence. |
| 21 | Local measured episode aggregation and held-out development separation. |
| 22 | Local replayed predicate/stage/constraint failure attribution; no causal claims. |
| 23 | Local hierarchy rollup, uncertainty and regional evidence. |
| 24 | Local sparse observed combinations, no independence assumption. |
| 25 | Local declarative task-space regions and contextual sampling. |
| 26 | Local empirical states, progress and uncertainty. |
| 27 | Local Advisor allocations and consumed funnel/discovery feedback. |
| 28 | Local typed directives and explicit unsupported targets. |
| 29 | Local bounded library-first discovery and coverage diagnostics. |
| 30 | Local governed sampler, retry and exact references. |
| 31 | Local typed instance realization and diagnostic appearance variation. |
| 32 | Local independent synthetic workers; optional real parallel Isaac scene/joint runtime; partial full governed Isaac worker bridge, external GPU. |
| 33 | Local immutable assignment identity, purpose and attempt ownership. |
| 34 | Local synchronized terminal recording, privileged separation and diagnostic sensor streams. |
| 35 | Local metadata/external payload separation and integrity; optional S3 transport. |
| 36 | Local curation and accepted failure experience; evaluation excluded. |
| 37 | Local immutable dataset manifests and exact lineage. |
| 38 | Local full-action task-conditioned imitation and extensible checkpoints; general robotic competence unproven. |
| 39 | Local representative frozen seven-partition development suite with leakage guards. |
| 40 | Local task/capability changes and exposure reports, explicitly observational. |
| 41 | Local requested-through-executed feedback persisted/consumed. |
| 42 | Local seeds, phase journal, checkpoint/payload/artifact identities; exact source checkout required. |
| 43 | Local SQLite/files verified; optional PostgreSQL/S3 software, external live validation. |
| 44 | Modular packages preserved, integration modules added. |
| 45 | Local schema compatibility/source-pinned semantics; partial full physical contract realization. |
| 46 | Local executed multi-iteration train/evaluate/adapt loop and restart recovery. |
| 47 | Local broad mechanics and measured coverage; no scene-name-only coverage claim. |
| 48 | Dependency order respected; physical governance remains next software dependency. |
| 49 | Ownership boundaries preserved, generator cannot approve physical feasibility. |
| 50 | Non-goals respected; no arbitrary generated reward code, QD/evolution, adversaries, graph/vector DB or learned transfer. |
| 51 | Local evidence factory objective represented; broad physical competence not established. |
| 52 | Local complete supported flow; partial full real-simulation flow. |
| 53 | Local adaptive factory implemented; complete physical/general-capability architecture not claimed. |

## Verification and reproducibility

Final verification: `python -m unittest discover -s tests -q` ran **135 tests**
in 53.696 seconds: 134 passed, one live PostgreSQL test skipped.
`git diff --check` and module compilation also passed.

The original 118 tests remain. New regressions exercise semantic publication and
execution, compound placement, shared-constraint failure, actual disjoint DAG
execution, drawer access, container fit, layout cycles, geometry/grip effects,
unknown bindings, slide/recovery telemetry, hierarchy deduplication, proposals,
immutable semantic publication, optional scene plans, bounded IK, S3 corruption
and retries, in-flight worker restart, two iterations across database reopening,
frozen membership, training exclusion, complete-action checkpoint contents and
repeat idempotency. Live PostgreSQL test skips without an explicitly supplied DSN.

```bash
python -m unittest discover -s tests -q
python -m factory --root /tmp/robotics-architecture-final --iterations 3 --episodes 28 --seed 42 --job architecture-demo
# Same target count resumes, rather than adding three more iterations:
python -m factory --root /tmp/robotics-architecture-final --iterations 3 --episodes 28 --seed 42 --job architecture-demo
```

Recorded example: `examples/adaptive-three-iterations.json`. Three iterations
executed 17, 21 and 24 guided episodes from 28 requested each (shortfalls 11, 7,
4). With 28 bootstrap demonstrations this produced 90 durable completions and
four policy checkpoints. Every fixed-suite evaluation scored 8/14; no learning
improvement is claimed. Repeated invocation retained identical canonical report
content and completion count. SQLite integrity check returned `ok`.

One earlier live database in the synchronized cloud workspace reported index
corruption and a readonly-write failure; that output was preserved, not used as
verification. The successful example used `/tmp` for the active database. Keep a
live SQLite database on a local filesystem, then copy/backup it only when closed;
do not synchronize its individual database/journal files during execution.

No PostgreSQL server, initdb, Docker, Isaac Lab/Sim, SO-101 USD deployment or
physical hardware was available. No paid services were provisioned, external
inference called, storage written externally, credentials changed, or physical
actuation performed. Optional API calls need deployment verification against
configured Isaac 2.1/2.2/2.3 and calibrated USD/joint mappings. DLS residuals are
linearized estimates, never robot-feasibility approvals.
