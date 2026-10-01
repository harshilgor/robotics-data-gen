# Task Library engine

The engine is `task_library.TaskLibrary`. It extends the existing execution
library rather than replacing its exact-hash contracts, so existing Advisor,
Sampler, benchmark and assignment APIs remain usable. Instantiate it with the
existing `task_advisor.loop.Repository` and pass it to those components.

## Implemented responsibilities

- Immutable canonical family IDs and semantic versions, with pinned DSL,
  predicate, capability and object dependencies.
- Structural signatures over goals, ordered skills/dependencies, object roles,
  scene constraints and initial-state requirements. Parameter bounds, task names
  and revision metadata do not create a different structural signature.
- Major-version requirements for semantic/dependency changes, minor-version
  requirements for compatible parameter-range extensions, and rejection of
  incompatible narrowing without a major version. Patch versions can change
  metadata or pinned execution implementation without altering task semantics.
- Append-only lifecycle events, contextual rejection/revalidation, archival and
  deprecation. ACTIVE requires a separately published execution contract.
- Context-specific valid/invalid/unknown parameter envelopes, report provenance,
  point queries and explicit conflicts. No whole-family physical approval is
  inferred from structural checks. Reports from another controller/robot/compiler
  context are not reused.
- SQLite indexes for structural signatures, capabilities, goals, object roles
  and parameters; deterministic structural-neighbor queries without embeddings.
- Provenance and exact-version parent references, recursive lineage and historical
  retrieval. Library records contain no episodes or policy performance.
- Advisor directive lookup that returns existing active versions or explicit
  generation requests. The Library does not generate tasks or infer capability.
- Existing exact execution contracts/artifact references remain immutable.
  Governed deprecated/archived versions are excluded from new sampler work;
  historical retrieval remains possible.

## Usage

```python
from task_advisor.storage import Store
from task_advisor.loop import Repository
from task_library import TaskLibrary
from taskgen.core import bootstrap_families

store = Store("robotics.sqlite3")
library = TaskLibrary(Repository(store))
task = bootstrap_families()[5]
library.register("pick_place", "1.0.0", task,
    dependencies={"task_dsl": "1.0", "predicate_library": "1.0",
                  "capability_ontology": "1.0", "object_ontology": "1.0"},
    provenance={"source": "human", "proposal_id": "bootstrap-1",
                "generator_version": "0.1.0", "parents": []})
library.transition("pick_place", "1.0.0", "STRUCTURALLY_ACCEPTED",
                   event_id="accept-bootstrap-1", reason="DSL and grammar checks")
print(library.search(capabilities=["grasp", "release"]))
store.close()
```

`register()` creates PROPOSED knowledge. `transition()` changes lifecycle through
the allowed graph. `add_validation()` stores external envelope evidence, and
`feasibility()` queries an exact parameter point in a complete context. Publish
execution contracts using `publish_version(family_id, version, contract, artifact,
context=context)` only after compiler/validator evidence exists; then activate the
canonical version. Raw `publish()` is rejected. Explicit `migrate_legacy()` brings
previous execution records under canonical governance.
Canonical IDs/semantic versions refer to reusable knowledge; execution uses the
Generator's exact TaskSpec hash/revision. This avoids rewriting historical
Advisor measurements or assignments when adding semantic versioning.

## Scope and verification

Storage uses the project's existing SQLite database rather than provisioning
PostgreSQL during software development. JSON payloads and indexed relational
identities can be migrated to PostgreSQL/JSONB when deployment requires it.
The engine supports the current trusted sequential TaskSpec DSL. New predicates,
robots, conditional/multi-object grammar and categorical schemas require the
respective compiler/DSL extension first. Signatures normalize node IDs but do not
prove arbitrary graph isomorphism or normalize renamed object roles. Similarity
is a heuristic for retrieval, not proof of semantic equivalence.

Physical reports are trusted externally supplied attestations. Real Isaac Lab
validation is deliberately deferred. Unknown space is implicit outside recorded
envelopes; conflicting evidence is never silently overwritten. Lifecycle/status
is event-derived and definition payloads remain immutable.

Run `python -m unittest discover -s tests -v`. Library tests cover immutable
versions, parameter-vs-structural identity, semantic bump enforcement, lineage,
indexed search, lifecycle rejection, context isolation and conflicting envelopes.
The existing generator/Advisor/sampler/instrumentation tests also run unchanged.

## Audit completion and governed APIs

`task_library/governance.py` adds the audited requirements. `reconcile(task)`
returns structural matches before generation or registration. A duplicate under a
new canonical ID is rejected unless `identity_override()` records a reason and
the registration references its decision ID. This keeps intentional exceptions
reviewable and does not silently fragment task space.

`supported_regions()` intersects requested intervals with context-specific valid
envelopes and subtracts invalid/unknown reports. Boundary points on rejected boxes
are excluded conservatively. It returns explicit remaining gaps. `compatibility`
classifies full coverage as compatible, incomplete coverage as partial, and no
supported coverage as unknown_or_rejected. Point queries retain a distinct
conflict status. `search(context=...)` and `resolve_directive(context=...)` use
those supported regions. Every context must be complete and version-pinned.

The library cannot determine arbitrary mathematical/physical equivalence from
skill labels. Structural reconciliation is exact within the supported DSL and
heuristic similarity remains a discovery aid. Unsupported TaskSpecs fail closed.

Immutable publication bindings pin semantic versions to execution revisions,
artifact references and execution contexts. Multiple patch implementations use
new TaskSpec execution revisions; an existing execution identity is never
overwritten. A version binds one execution configuration; multiple robot contexts
can have validation knowledge, and executing a new configuration needs its own
versioned publication. There is no implicit latest-version resolution.

The sampler checks each constructed instance with `assert_sample_allowed`; lease
acquisition checks again so later rejection/deprecation blocks pending work.
Library approval snapshots participate in sampling request identity. Existing
completed assignments remain retrievable. The canonical Library excludes legacy
contracts until explicitly migrated. Legacy-only `task_advisor.loop.TaskLibrary`
remains for older fixtures; production wiring should use `task_library.TaskLibrary`.

Publication, registration and lifecycle mutations acquire SQLite write locks
before read-modify-write. Nested operations use savepoints. Artifact/contract,
validation report and canonical binding publication are one transaction.
Snapshots omit episodes/assignments and include canonical definitions, search
indexes, ordered events, identity decisions, bindings and execution artifacts.
Checksums detect corruption; they do not authenticate an untrusted sender.
Restore checks schema version, row shape, TaskSpec content/identity, dependencies,
parent references, contexts, execution references and artifact hashes and rolls
back on failure. Only empty library stores can be restored.

CLI usage:

```powershell
python -m task_library --db robotics.sqlite3 search --capability grasp
python -m task_library --db robotics.sqlite3 export --output library-snapshot.json
python -m task_library --db restored.sqlite3 restore --input library-snapshot.json
```

The original eight audit items are addressed for the current local software
scope. SQLite is retained deliberately; a deployed PostgreSQL/JSONB backend has
not been built. Actual physical evidence and new compiler/DSL capabilities remain
for their respective later phases. No test here establishes real SO-101 feasibility.
