# SO-101 Robotic Data Factory

Software foundations for a closed-loop simulated robotics experience factory:
task generation, capability-based advice, versioned task knowledge, curriculum
assignments, measured episode recording and controlled development evaluation.

## Run

Python 3.12 or later; current code uses the standard library.

```powershell
python -m unittest discover -s tests -v
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

The full Curriculum Sampler engine is the next software component. Existing
sampler code is an initial implementation, not completion of its entire brief.
Actual Isaac Lab/SO-101 scenes, physical validation and PPO runtime integration
are deferred. Example results and test approvals are synthetic; they do not
establish robot feasibility or empirical learning performance. Persistence is
currently SQLite; a deployed PostgreSQL backend is not implemented.
