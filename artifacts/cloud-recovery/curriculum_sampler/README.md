# Curriculum Sampler software

The public package exports the existing `task_advisor.loop.CurriculumSampler`,
`AssignmentScheduler` and `AssignmentRecorder`. Its v2 implementation helpers are
`task_advisor/curriculum.py`, `execution.py` and `worker.py`. The production Library
is always `task_library.TaskLibrary`; legacy v1 APIs remain usable for old callers.

## Runnable synthetic smoke

Use a fresh database (the smoke deliberately exercises a new interruption/retry):

```sh
python -m curriculum_sampler --db smoke.sqlite3 --output smoke.json smoke
python -m unittest discover -s tests -v
```

`examples/curriculum-sampler-smoke.json` is the recorded delivery run: two approved
**synthetic fixture** families, three independent environments, eight completed
assignments, nine attempts including one interrupted attempt, eight recorded
trajectories and realized initial states. Approval/evidence labels explicitly say
synthetic; these are software fixtures, not Isaac or SO-101 measurements.

## Production wiring

Register/publish exact typed contracts through the canonical Library, following
its existing lifecycle/context procedures. TaskSpec `1.0` is unchanged. Additive
TaskSpec `1.1` permits signed numeric, integer and categorical extra parameters;
existing core physical dimensions remain positive float domains. Domain objects
are `{"type":"int","bounds":[0,3]}` or
`{"type":"categorical","values":["a","b"]}`. Typed execution contract `2.0`
requires names, units, explicit frame (null for nonspatial quantities), roles,
stages, dependencies, registered checks, validation policy, robot/actuator/sensor
configuration, trajectory schemas and demonstration quality bounds. See the
fully labeled example in `synthetic.contract_for`; substitute real attestations
and compiled artifact descriptors, never its synthetic validators.

```python
from task_advisor.storage import Store
from task_advisor.loop import Repository
from task_library import TaskLibrary
from curriculum_sampler import (
    Registry, make_directive, CurriculumSampler, AssignmentScheduler,
    AssignmentEnvironments,
)

store = Store("robotics.sqlite3")
repo = Repository(store)
library = TaskLibrary(repo)
registry = Registry()
# Register trusted, version-pinned constructor/constraint/geometry/validator
# callbacks matching each published contract. Callback dependencies are checked.
# No generated expression, import or eval is allowed by task/directive data.
directive = make_directive(
    advisor_snapshot["directive"], library, total=128, seed=42,
    controller_id="policy-controller", controller_version="1.0",
    window_id="window-001", starts_at=clock(), expires_at=training_boundary,
    recording_profile={"trajectory": False},
)
sampler = CurriculumSampler(repo, library, registry=registry)
batch = sampler.sample(directive, now=clock())
scheduler = AssignmentScheduler(repo, library)
bridge = AssignmentEnvironments(scheduler, real_adapter, clock=clock)
# Dispatch batch["groups"] to pools declaring each compatibility key.
# bridge.start(env, assignment_id, unique_attempt_id, worker_id=worker, ttl=30)
# bridge.step(env); bridge.renew(env, ttl=30); bridge.interrupt(env, reason=...)
```

`make_directive` resolves eligible exact family versions without reprioritizing
Advisor weights. Unresolved targets and unallocated region budgets are explicit.
Set minimum coverage, exclusions, one explicit fallback per source region and
requested diversity in the directive **before** computing its content ID.
Region definitions are immutable under `(region_id, region_version)`. The same
region may appear in multiple categories with different allocation weights.
Update a definition using a new region version. See the fixtures/tests for
manual directive construction and content hashing.

Minimum coverage reserves integer floors before Hamilton allocation of remaining
capacity. Lexical IDs break equal remainders. Category weights and within-category
region weights may sum below one; missing capacity becomes a shortfall, never a
new strategy. Bounded candidate rejection stays within its declared stratum and
region; joint constraints may therefore cause explicit shortfalls even when some
other stratum is feasible. Fallback assignments carry both source and destination
region IDs. Coverage shortfalls remain visible even if a fallback fills the total
budget. `unique_parameters` prevents duplicate selected dimensions within the
batch; `allow_repetition` permits repeated physical tasks with distinct assignment
and episode identities. Categorical balance holds for a fully accepted batch;
constraint shortfalls and distribution diagnostics expose departures.

One directive/window pins one immutable batch and Library snapshot. Replays do
not spend its episode budget again after unrelated Library changes. New approval
reports/deprecation are checked at lease time and block unsafe pending work.
Use a new directive and future window to request replacement work; explicitly
cancel pending old assignments if needed. Expiry blocks new sampling/leasing,
renewal and starts. An already running episode may complete while its own lease
remains live; `expire(now=...)` explicitly retires expired windows/attempts.

The existing Store connection persists all assignments, attempts, summaries,
initial states, trajectory records, diagnostics and completion hashes. Reopen it
with the same Repository/Library and registered version IDs. Only the first valid
completion per assignment enters evidence; interruptions, failed attempts and
lease expiration never become policy failures or inflate coverage. Recorder
retries retain terminal measurements; duplicate ACKs are idempotent. Writer locks
serialize publication/sampling/lease/completion in the local SQLite engine.
Sampling holds that lock during bounded callback validation; integrations must
supply bounded local callbacks. This is a single application, not distributed
service provisioning or a throughput claim.

`ExecutionAdapter` defines build/install/reset/runtime application, realized-state
capture, selected-controller actions, measured pre-reset frames, frozen policy
digests and finalization/abandonment. Each environment has independent streams,
identity, goals and episode counter. No global reset RNG is reseeded. Artifact
hashes cover descriptors; real adapters must verify referenced binary assets and
pin their simulator/compiler versions. They must delay auto-reset or explicitly
capture the terminal frame/next observation before reset.

Demonstrations require trajectories. Success, approved observations/actions,
limits, timing/terminal alignment and measured physical collision limits gate
imitation dataset eligibility. Rejected trajectories retain summaries and safe,
explicit invalid-value markers where nonfinite values cannot be stored as JSON.
Privileged state is a separate stream; `export_dataset(repo)` strips it and rejects
evaluation/rejected recordings. Summary-only training does not persist frames.
A recorder/storage failure is retryable, not a fabricated terminal episode.

For fixed evaluation, use `BenchmarkRegistry.generate_cases(..., registry=...)`
and `freeze(..., registry=...)`, then register an immutable checkpoint and call
`assignments(manifest_id, checkpoint_id, controller_id=..., controller_version=...,
starts_at=..., expires_at=...)`. Assignments are derived only from fixed manifest
cases and evaluation seeds, independent of adaptive quotas. The bridge checks the
frozen digest before/after each action. Evaluation summaries remain outside
training evidence. Changing only an instance seed cannot bypass held-out physical
parameter exclusions. `export_dataset(..., include_evaluation=True, policy_id=...)`
is an explicit, persisted dataset-policy exception. Legacy controlled development
probes remain separate and may feed the Advisor as before; sealed tests remain
external.

CLI production sampling uses an explicitly supplied trusted registry factory:

```sh
python -m curriculum_sampler --db robotics.sqlite3 --output batch.json sample --directive directive.json --registry-factory my_integration:registry --now 100
python -m curriculum_sampler --db robotics.sqlite3 --output feedback.json feedback --request-id REQUEST_ID
```

This deployment-owned module factory is not read from generated task descriptions.
Detailed feedback includes directive/category/family rollups and versioned region
rows, rejections, fallback/coverage/remaining shortfalls, scheduling/actual starts,
unique completions, interruption/failure/expiry/cancellation counts, parameter
values/histograms and latency/wait metrics. Only completed training episodes enter
Advisor measurements. A seed identifies sampling replay, not bitwise physics
reproducibility across software or hardware versions.

Real Isaac Lab/SO-101 compiler, assets, physics validation, controllers and learning
performance remain deferred. No cloud services, credentials, PostgreSQL, learned
sampler, LLM loop or causal transfer model are introduced.
