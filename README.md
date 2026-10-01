# SO-101 Robotic Data Factory

Runnable local synthetic runtime for a closed-loop robotics experience factory:
task generation, capability-based advice, versioned task knowledge, curriculum
assignments, measured episode recording and controlled development evaluation.

## Run

Python 3.12 or later; current code uses the standard library.

```powershell
python -m unittest discover -s tests -v
python -m factory --root artifacts/my-cycle --episodes 14 --broad
python -m factory --root artifacts/my-camera-cycle --episodes 14 --broad --modalities rgb depth
python -m taskgen --seed 42 --instances-per-family 3 --output generated-tasks.json
```

## Components and specifications

- `taskgen/`: task DSL, bootstrap families, composition, mutation and novelty.
- `task_advisor/`: evidence, capability estimates, directives, instrumentation,
  initial sampling/scheduling, development evaluation and research bookkeeping.
- `task_library/`: canonical versions, lifecycle, contextual validation envelopes,
  governed publication, lookup and recovery.
- `tests/`: software verification, including explicitly synthetic runtime fixtures.
- `original-architecture.md`: overall user-supplied architecture and revisions.
- `task-generator.md`, `task-advisor.md`, `task-library.md`,
  `curriculum-sampler.md`: user-supplied engine specifications.
- `*-implementation.md` and `instrumentation.md`: implemented scope and contracts.
- `task-library-audit.md`: audit findings and software closure notes.

The complete local cycle publishes and validates 14 broad task configurations,
executes independent environments with interrupted retry, records demonstrations,
curates a versioned dataset, fits a motion baseline, saves checkpoints, compares
them on the same frozen evaluation suite, updates the Advisor and closes coverage
gaps before sampling the next batch. Choose a fresh root for each cycle; it holds
`metadata.sqlite3`, external `objects/` payloads and `cycle-report.json`.

New packages: `semantics/` (shared registries and grammar), `assets/` (exact
resources), `task_compiler/`, `task_validator/`, `simulation/`, `data/`,
`training/`, `evaluation/` and `factory/`. Discovery and the recovered complete
Curriculum Sampler extend the existing engines. See `architecture-implementation.md`
for coverage and verification of all 53 architecture sections.

The baseline learns a motion gain from demonstrations while retaining a trusted
task-stage controller. The local model approximates Cartesian motion, contact,
grasp and support; RGB/depth use a diagnostic orthographic camera. These runs
establish software integration, not SO-101 physical feasibility or general policy
learning. Isaac Lab, real IK/dynamics and hardware require a separately validated
`ExecutionAdapter` implementation. Hosted LLM proposals are an optional injected
provider; deterministic trusted discovery works locally.

SQLite plus local content-addressed files is the verified default. An optional
`data.postgres.PostgresStore` requires psycopg 3 and a supplied server. Set
`ROBOTICS_TEST_POSTGRES_DSN` to enable its live integration test; it was skipped
locally because no server is connected. No service or credentials are provisioned.

The cloud sampler's 21-file delivery was recovered and checked against its
recorded Git tree. `python tools/verify_cloud_recovery.py` verifies the archived
sources in `artifacts/cloud-recovery/`; active source includes subsequent changes.
