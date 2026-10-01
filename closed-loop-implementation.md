# Advisor closed loop, controlled evaluation and research

The software path is implemented with standard-library Python and existing
SQLite storage. It does not manufacture physical validation or train a robot.
Real simulation and learning remain supplied through the established adapters.

## Library and sampler handoff

`task_advisor.loop.Repository` shares the Advisor Store connection and adds
immutable family contracts, artifact descriptors, sampling requests, assignments
and completion records. Mutable execution state is separate from specifications.
`TaskLibrary.publish()` checks exact Generator family hash/revision, interface
schemas, artifact descriptor hash, supported controller, explicit parameter
types/units/application stages and an externally attested physical envelope.
Changing a published contract or artifact under its identity is rejected.
Structural acceptance is never physical approval. Contract hashes protect the
artifact descriptor; adapters must verify referenced binary artifacts themselves.

The V1 library exposes `get_family`, `get_sampling_contract`,
`list_eligible_families`, and `get_compiled_artifact`. It is an integration subset
of the broader Library brief: float-only existing taskgen parameters and active
execution contracts. A semantic ontology, full lifecycle administration,
categorical parameters and database search indexes are not claimed here.

`CurriculumSampler.sample()` consumes a frozen Advisor directive. It applies
largest-remainder quota rounding with lexical ties, resolves exact versions or
capability matches, intersects requested regions with validated envelopes,
stratifies numeric parameters, invokes allowlisted constructor/validator
callbacks, and persists accepted assignments. Build-time choices participate in
worker compatibility keys. Callbacks implement family-specific dependency,
geometry and reset constraints, with exact-instance physical evidence required
before an assignment is accepted. Rejections have bounded attempts and explicit
shortfalls. There are no silent fallbacks or range widening. Unsupported
capabilities remain unfulfilled requests. The library snapshot, algorithm and
request seed are recorded; replay returns the stored batch without rerunning
validation. Seed replay is not a claim of bitwise simulator determinism.

```python
from task_advisor.storage import Store
from task_advisor.loop import (
    Repository, TaskLibrary, CurriculumSampler, AssignmentScheduler,
    AssignmentRecorder, numeric_instance,
)

store = Store("robotics.sqlite3")
repo = Repository(store)
library = TaskLibrary(repo)
sampler = CurriculumSampler(repo, library,
    constructors={"numeric-v1": numeric_instance},
    validators={"numeric-v1": physical_validator})
# Publish trusted scene/compiler contracts before sampling.
# Save the Advisor snapshot before publishing directive-linked feedback.
batch = sampler.sample(directive, total=100, seed=42,
                       controller_id="controller-v1")
scheduler = AssignmentScheduler(repo, library)
```

The simulator worker resolves the assignment's exact artifact, applies its build
and reset parameters, captures realized reset state, and executes the selected
controller. Step-time parameter changes are not driven by this sampler.
`AssignmentRecorder` connects the existing `EpisodeTracker.finish()` or
`InstrumentedEnvironments` recorder interface to scheduler completion. It stores
assignment/attempt IDs, actual applied theta/phi, initial state and software
versions. Applied parameters must match the assignment; mismatches are execution
errors, not ordinary policy failures. The live recorder must capture pre-reset
terminal state. Purpose-tagged demonstration assignments can be constructed but
cannot enter the training completion path; demonstration quality/export remains
the data-production engine's responsibility.

## Execution and feedback

The scheduler leases assignments only to matching compatibility keys. It supports
lease renewal, expiration, explicit interruption, pending cancellation and retry
attempts. Leases are claimed under a SQLite write lock. Completion validates the
exact controller/checkpoint/instance and realized metadata, then commits the
episode and completion atomically. Idempotent completion cannot double-count
evidence; stale attempts cannot overwrite completed work. Interrupted attempts
are stored separately and do not become failed-policy episodes.

`scheduler.feedback(request_id)` reports requested, generated, validated,
ever-scheduled, completed episodes and interrupted attempts to the existing
Advisor feedback protocol. Generation and scheduling counts cannot create
capability evidence: only terminal episode records do that. Retry counts remain
separate from unique completed assignments. A new directive creates future work;
existing assignments retain their original request. Pending work can be cancelled
explicitly. Group assignments by `execution_compatibility_key` before dispatch.

## Frozen development probes

`task_advisor.evaluation.BenchmarkRegistry` freezes a named version containing
exact family versions, instances, physical evidence and separate probe seeds.
`generate_cases()` uses a distinct development seed stream. Freeze rejects
instances already used in training or assigned for training. The controlled
Store subsequently rejects training records for reserved development instances,
and rejects development records with incorrect manifest membership, seed,
parameters or checkpoint provenance. Sealed sources remain unsupported.

Register an immutable checkpoint descriptor with `register_checkpoint()`.
`run(manifest_id, policy_version, runtime)` loads a frozen policy, checks its
digest before/after probes, runs every fixed case through EpisodeTracker, and
atomically records the complete suite. Replaying a completed checkpoint/suite
returns the stored evaluation result. Interrupted or changing-policy runs do not
publish partial results. The runtime implements `load_frozen_policy`,
`policy_digest`, `begin_probe`, and `step`; it must verify loaded weights against
the checkpoint descriptor and forbid training updates. Digest checking depends
on that trusted adapter, not on a claim of cryptographic control over arbitrary
runtime code. Advisor development progress requires matching manifest and exact
case membership across checkpoint windows; mismatched suites have no delta.

```python
from task_advisor.evaluation import BenchmarkRegistry

registry = BenchmarkRegistry(repo, library)
cases = registry.generate_cases(exact_family_versions, seed=7001,
                               per_family=20, validator=physical_validator)
manifest = registry.freeze("development", 1, cases, seed=7001)
registry.register_checkpoint("checkpoint_001", checkpoint_descriptor)
run = registry.run(manifest["manifest_id"], "checkpoint_001", frozen_runtime)
```

Initialize Repository before importing development episodes to activate
membership enforcement. Legacy standalone Store/Advisor APIs remain available
for fixtures and old V1 data; direct `Advisor.advise()` inputs are caller-controlled
and are not a security boundary. All controlled runs should use this repository
and registry, and never relabel sealed results as development data.

## Budget-matched multi-seed research

`task_advisor.research.ResearchLedger.plan()` freezes the development manifest,
library snapshot, at least two seeds, comparison arms and a per-trial executed
control-step budget. `uniform_directive()` constructs the explicit uniform-family
baseline independent of adaptive scores. Uniform-arm blocks must actually use
those allocations. Adaptive directives still come from the Advisor.

`run_experiment()` evaluates a seed's frozen initial checkpoint, delegates the
training trial to a supplied trainer, evaluates its final checkpoint on the same
manifest, and records the training block. The trainer implements
`train_trial(arm, seed, initial_checkpoint, step_budget, experiment_id)` and returns
policy_version, artifact and completed assignment_ids. It must initialize each
arm from the seed's same initial checkpoint, use experiment-tagged sampler
assignments, and stop at the requested budget. Overruns/shortfalls, mismatched
seeds/library snapshots and repeated executions across trials are rejected.
Incomplete plans cannot produce comparison reports. Completed trials are skipped
on rerun. Intermediate trainer recovery is delegated to the trainer.

Training blocks include focus by family, actual executed steps, checkpoint and
manifest references, and per-family before/after development deltas. The report
gives paired arm-minus-baseline differences, mean and sample standard deviation
across seeds. These are observed associations and exploratory transfer evidence,
not causal estimates or statistical-significance claims. Control steps are not
wall-clock/GPU cost; add separate accounting before making compute-cost claims.
There is no learned transfer predictor, neural embedding or LLM advisor.

## Verification

Run `python -m unittest discover -s tests -v`.

The synthetic integration smoke test uses two approved fixture families, two
independent environments, a worker interruption/retry, recorded reset/terminal
metadata and feedback. Other tests cover immutability, quota replay, bounded
shortfalls, stale leases, idempotent completion, fixed development membership,
training exclusion, changing checkpoint rejection and two-seed budget-matched
trial orchestration. Synthetic physical reports/runtime/trainer are test fixtures,
not real robot results. Concrete Isaac Lab and PPO adapters remain necessary to
run empirical robotic experiments; this phase delivers their orchestration path.
