# SO-101 Robotic Data Factory

Runnable local synthetic runtime for a closed-loop robotics experience factory:
task generation, capability-based advice, versioned task knowledge, curriculum
assignments, measured episode recording and controlled development evaluation.

## Run

Python 3.12 or later; the local runtime uses the standard library. Optional
integration tests for DLS use NumPy; deployment extras are documented separately.

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

The adaptive runner executes Advisor-guided experience, trains each subsequent
checkpoint, evaluates the same frozen suite, persists transfer/funnel feedback
and resumes its saved phase journal:

```bash
python -m factory --root /tmp/robotics-demo --iterations 3 --episodes 28 --seed 42 --job demo
# Repeat to resume the same target; increase --iterations to continue.
python -m factory --root /tmp/robotics-demo --iterations 3 --episodes 28 --seed 42 --job demo
```

The runnable Unix baseline learns complete actions through bounded
task-conditioned behavior cloning; task predicates still identify phase. The
local model realizes finite layouts, container/drawer access, support, orientation,
contact, obstacle counts, typed geometry, friction/mass effects and diagnostic
appearance. It is a Cartesian surrogate, not SO-101 dynamics. Legacy one-pass
commands above remain available. Keep active SQLite files on a local filesystem
that does not synchronize database/journal files while running.

See [architecture-closure-review.md](architecture-closure-review.md) for the
requirement-by-requirement and all-53-section review, explicit supported grammar,
verification and remaining software gaps. The supplied correction is preserved
in [architecture-final-audit.md](architecture-final-audit.md). Earlier delivery
ledgers are historical; they do not establish full architecture completion.
[examples/adaptive-three-iterations.json](examples/adaptive-three-iterations.json)
records a three-iteration run and its explicit shortfalls; it claims no measured
learning improvement.

Optional [deployment bindings](integrations/README.md) include concrete
version-configurable Isaac scenes/joints/Jacobian control and SO-101 transport,
hosted declarative proposals, PostgreSQL and S3. They require optional dependencies
and supplied deployment resources. The complete governed physical task-worker
bridge remains partial. No GPU/hardware/service validation is claimed, and no
services, credentials or charged inference are configured automatically.

SQLite plus content-addressed local files is the tested default. Set
`ROBOTICS_TEST_POSTGRES_DSN` only for an authorized existing local server to run
the optional live test. None was available in this workspace.

The cloud sampler's 21-file delivery was recovered and checked against its
recorded Git tree. `python tools/verify_cloud_recovery.py` verifies the archived
sources in `artifacts/cloud-recovery/`; active source includes subsequent changes.
