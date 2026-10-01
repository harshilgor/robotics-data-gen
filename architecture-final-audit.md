# Architecture completeness audit — October 1, 2026

Audited source: `original-architecture.md`, sections 1–53. Implementation baseline:
Git commit `bf80e2e63007ecf76a6e0cd447438b86a8f9a345`. This is a source review
against the architecture, not a restatement of the previous delivery ledger.

**Conclusion: the local synthetic pipeline runs, but the entire architecture is
not fully implemented.** Most subsystem boundaries exist. Some provide only a
restricted implementation or an injection interface. The earlier completion
claim was too broad. The user's synthetic-runtime-first choice explicitly defers
real simulation; it does not erase the local software gaps below.

## Components and remaining scope

| Architectural component | Existing implementation | Assessment |
|---|---|---|
| Task semantics | `semantics/`, `taskgen/core.py` | Partial: separate semantic DAG and execution DSL contracts; richer semantic tasks cannot pass through the local compiler |
| Task Library | `task_library/` | Working governed local implementation; factory version selection is narrower than architectural semantic versioning |
| Task Generator | `taskgen/discovery.py`, composition/mutation/novelty helpers | Partial: numerical range mutation and a few single-object skill suffixes; hosted LLM provider is an interface |
| Task Compiler | `task_compiler/compiler.py` | Working for supported local tasks; five bound parameters, one robot resource and sequential execution only |
| Asset/Scene/Skill libraries | `assets/registry.py`, semantic/execution skill definitions and local controller | Partial procedural resources; scene labels do not provide complete layouts or constraints |
| Task Validator | `task_validator/validator.py` | Working surrogate checks; no real IK/dynamics and limited envelope evidence |
| Evidence Engine | `task_advisor/instrumentation.py`, `core.py`, `storage.py` | Working measured stage/event aggregation for supported tasks |
| Capability Model | `task_advisor/core.py` | Working stage estimates; hierarchy tags are not aggregated into evidence-backed ancestor estimates |
| Task Advisor | `task_advisor/core.py` | Working allocation logic; local orchestration omits execution/discovery feedback inputs |
| Curriculum Sampler | `task_advisor/curriculum.py`, `loop.py`, `execution.py` | Working typed, governed sampling and diagnostics; requested coverage can remain unresolved |
| Instance Generator | registered constructor, `taskgen` sampling, runtime reset | Partial: theta/phi/seed supported; broad asset/layout/domain randomization is not |
| Simulation/workers | `simulation/local.py`, `task_advisor/worker.py` | Working local surrogate and independent sessions; actual Isaac Lab/SO-101 implementation absent by user-selected scope |
| Data/curation/catalog | `data/`, recording bridge | Working local external payloads, integrity, manifests and privileged separation |
| Policy training/checkpoints | `training/baseline.py` | Runnable single-gain motion calibration, with a trusted stage planner; not general policy optimization |
| Fixed evaluation | `task_advisor/evaluation.py`, `evaluation/local.py` | Working freeze/probe/ingest; default cases do not cover the full held-out challenge matrix |
| Transfer measurement | `task_advisor/research.py` | Comparison APIs exist; normal factory CLI reports a global change and does not run capability/task transfer analysis |
| Persistence | SQLite/local files; `data/postgres.py` | Local path verified; optional PostgreSQL live integration unverified |
| Operating loop | `factory/__main__.py` | One demonstration/training/Advisor pass, ending in an unexecuted next batch; no resumable repeated adaptive loop |

## Concrete findings

1. **Richer semantic TaskSpecs do not compile to execution (sections 3–4, 7, 15,
   45).** `semantics/registry.py:247` validates `semantic-1.0` with role predicates,
   goals, constraints and DAGs. `task_compiler/compiler.py:20` instead calls
   `taskgen.validate`, which accepts execution schemas 1.0/1.1/1.2. The extended
   execution grammar requires one sequential chain and a single success predicate
   (`semantics/task_spec.py`). Reward terms are limited to progress/time/collision.
   The general predicate registry is not the shared evaluator of arbitrary
   initial conditions, constraints, rewards and termination in the runtime.

2. **Scene and domain realization is incomplete even locally (sections 16–17,
   31–32).** `assets/registry.py` registers six scene labels with common workspace
   metadata. `simulation/local.py:53` builds a generic point layout; only
   `tabletop_obstacles` gets a special collision obstacle later. Declarative
   `scene.relations` are not realized or checked by the runtime. Drawer opening
   increments a scalar, but access to another object is not gated by the drawer;
   container retrieval has no enclosing container geometry. Initial flags such
   as `opened` are not realized: reset initializes opening fractions to zero.
   Mass/friction are captured in parameters but do not affect motion/contact.
   `task_compiler/compiler.py:68` binds only distance, tolerance, size, mass and
   friction. Counts, target geometry, lighting/texture and approach constraints
   are unsupported, not implemented randomizations.

3. **Discovery is narrower than the stated mechanisms (sections 13, 29).**
   `taskgen/core.py:161` mutates numeric ranges; it cannot add an object/obstacle,
   spatial constraint, approach restriction or change goal geometry. Discovery
   composes only three suffix choices for single-object chains. Its optional
   ProposalProvider has no concrete hosted implementation. `novelty` at line 183
   compares skills/compositions/object affordances/parameter ranges, but not goal
   structure, scene relationships or constraint topology. Library structural
   identity does include more structure; that does not supply the missing novelty
   or generation mechanisms.

4. **Hierarchical capability evidence and exercise coverage are incomplete
   (sections 6, 23–24, 27–29).** `capabilities_for` adds ancestor tags, sequencing
   and long-horizon tags to families. `Advisor.advise` at `task_advisor/core.py:275`
   accumulates outcomes only for each stage's exact capability. Ancestor and
   sequence tags do not gain measurements through hierarchy rollup. The Advisor
   therefore requests some already-exercised category tags as coverage gaps.
   Other vocabulary entries genuinely have no generation support. In the saved
   broad cycle, discovery leaves contact_precision, grasp_stability,
   maintain_grasp, orientation_precision, positional_precision, recovery and
   slide unfulfilled; the next batch fills 3/14 slots with 11 shortfalls. Failure
   events are recorded, but, for example, grasp-loss evidence is not converted
   into a distinct grasp-stability capability estimate. Shortfalls are explicit,
   which is correct; they are not evidence that coverage is complete.

5. **Full-funnel feedback is not wired back into the local Advisor (section 41).**
   Scheduler/discovery diagnostics exist, and `Advisor.advise` accepts `feedback`.
   However, `factory/local.py:135` calls it with only tasks/episodes/policy versions.
   The CLI puts feedback in its report rather than passing the requested/generated/
   validated/scheduled/executed funnel into the Advisor snapshot. Outcome evidence
   does arrive; funnel feedback is a separate missing connection.

6. **Frozen evaluation is implemented; evaluation breadth and transfer reporting
   are partial (sections 39–40).** The default CLI creates two parameter samples
   per seed configuration. It does not create dedicated unseen scene, unseen
   object-combination or held-out composition partitions. Broad seed tasks are
   also training candidates. Exact cases can be supplied manually, but that is
   not a built representative suite. `ResearchLedger` can record family-level
   changes and training focus; the normal cycle does not invoke it or produce a
   capability-to-task transfer report. Fixed evaluation DOES enter the Evidence
   Engine through `BenchmarkRegistry.run` and is consumed separately as
   development evidence; this integration is present, not a missing component.

7. **The standard loop is a single-pass demo, not continuous adaptive training
   (sections 38, 46, 53).** The CLI trains once from uniform demonstrations, executes
   uniform training experience with that checkpoint, then generates but does not
   execute the next Advisor-guided batch. It does not train again on adaptive
   experience or resume policy/iteration state. Checkpoint saving/loading is tied
   to a numeric gain and the local controller; a general backend needs a broader
   weight/algorithm contract. PPO specifically is an example in the architecture,
   not a mandatory algorithm, but the current fitted gain should not be counted
   as complete robotic policy learning.

8. **Publication version selection is limited (section 12).** The governed
   Library supports exact semantic-style versions, but `factory/local.py:61`
   always allocates the next major version for a new publication, including
   parameter-only changes. Patch/minor/major classification is not automated in
   this path.

## Deferred integration rather than accidental omissions

- Actual Isaac Lab environment compilation, SO-101 joint/actuator/sensor assets,
  GPU simulation, real IK/collision/dynamics checks and physical reference plans
  remain unbuilt. This matches the explicit synthetic-first instruction.
- PostgreSQL transport exists, but no live server is connected. Local object/file
  storage satisfies the local data layer; a hosted object-store adapter is not
  configured. The architecture presents PostgreSQL/object storage as a reasonable
  production structure, not an instruction to provision paid infrastructure.
- Hosted LLM proposals have an injection boundary; no provider is configured.
- Evolutionary/QD search, adversarial generation, learned novelty/transfer, graph
  databases, vector databases and arbitrary generated reward code are explicit
  non-goals. Their absence is correct.

## All-section coverage map

Here, working means implemented for the supported local contracts. Partial means
an architectural responsibility remains beyond those contracts. Principles and
non-goals do not require a separate package.

| Sections | Review result |
|---|---|
| 1–2 | Ownership/modular separation present; semantics portability partial |
| 3–4 | Partial: semantic representation and shared runtime predicates |
| 5 | Role/affordance resolution working locally |
| 6–7 | Partial: hierarchy reasoning and general grammar-to-execution bridge |
| 8–11 | Governed Library/lifecycle/envelopes/contextual compatibility working locally |
| 12 | Exact lineage/version storage working; factory version classification partial |
| 13 | Partial discovery, structural mutations, LLM execution and novelty dimensions |
| 14 | Non-goals respected |
| 15–19 | Local compiler/resources/validation working within restricted surrogate; richer scenes/parameters partial, real simulator deferred |
| 20–22 | Supported episode evidence and deterministic failure attribution working |
| 23–24 | Stage estimates and sparse combinations working; broader hierarchy/capability evidence partial |
| 25–28 | Regions/states/distributions/directives working; unsupported coverage remains |
| 29–30 | Library-first discovery and governed sampler working within supported coverage |
| 31 | Numeric instance generation working; assets/layout/domain realization partial |
| 32 | Synthetic execution working; actual Isaac Lab deferred |
| 33–37 | Assignments, recording, payload storage, curation and manifests working locally |
| 38 | Motion baseline/checkpoints working; general policy optimization partial |
| 39–40 | Frozen evaluation and comparison APIs working; representative held-outs/integrated transfer partial |
| 41 | Diagnostics working; Advisor feedback connection missing locally |
| 42 | Supported artifact provenance/replay working; scene/domain realization limits reproducible scope |
| 43 | SQLite/files working; PostgreSQL live verification deferred |
| 44–45 | Modular contracts present; generalized semantic contract integration partial |
| 46 | One pass working; repeated adaptive loop incomplete |
| 47 | Broad seed names present; scene mechanics limits actual conceptual coverage |
| 48–50 | Build order and non-goals respected; broad completion claim needs correction |
| 51–53 | Research objective represented; general-capability/continuous factory outcome not yet achieved |

## Verification and follow-through

Re-ran `python -m unittest discover -s tests -q`: **118 tests ran, 117 passed,
one live PostgreSQL integration test skipped**. Passing tests establish supported
behavior, not missing architecture features. Findings above come from source
inspection and the recorded broad-cycle coverage diagnostics.

Suggested implementation order: unify semantic/execution bindings; realize local
scene/parameter constraints; broaden generation and capability measurements;
connect funnel feedback; add held-out evaluation partitions/transfer reports;
then implement resumable adaptive iterations. Real simulator work follows with
its own resource bindings, runtime, validation contexts and evidence.

This audit changes documentation only. It does not claim to fix these gaps or
publish new code. `architecture-implementation.md` remains the previous delivery
ledger and should be read with this completeness correction.
