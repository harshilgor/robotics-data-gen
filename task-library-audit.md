# Task Library completeness audit

Historical result: the original V1 did not satisfy the complete Task Library
brief. The software gaps listed below were subsequently addressed; see the
closure section at the end. Deployment/upstream deferrals remain explicit.

## Verified implementation

Immutable canonical version payloads, semantic version checks, pinned dependencies,
append-only lifecycle history, contextual validation reports, point feasibility
queries, capability/parameter/goal/role indexes, lineage, exact execution contract
retrieval and basic Advisor lookup are present.

## Remaining software requirements

1. **Identity reconciliation:** registration computes structural signatures but
   permits the same structure under unrelated canonical IDs. Add an explicit
   matching/publication decision that distinguishes existing-family task-space
   variants from new structures, with recorded alias or override decisions.
2. **Region-aware Advisor lookup:** `resolve_directive()` currently checks skills
   and status, but not parameter restrictions or requested execution context.
   Return supported intersections and quantified/explicit coverage gaps, including
   previously rejected regions, before asking the Generator for new families.
3. **Envelopes governing execution:** feasibility reports can return invalid or
   conflict, but `list_eligible_families()` only considers lifecycle and capability
   tags. The sampler still consumes its separately published single contract
   envelope. Connect context-specific valid/invalid/unknown knowledge to eligible
   sampling regions; conflicting evidence must block affected assignments.
4. **Compatibility search:** add robot/gripper/controller/compiler-filtered search
   and compatibility summaries with partial/compatible/unknown status. Multiple
   contexts are stored in reports but not searchable through the current API.
5. **Publication/version bridge:** explicit canonical semantic version to immutable
   execution artifact mapping is missing. Multiple implementation artifacts for
   the same TaskSpec content cannot currently be published under the existing
   exact-hash/revision execution key. Require a new execution revision or versioned
   contract identity, preserving historical assignments and measurements.
6. **Lifecycle enforcement:** execution contracts can be published independently
   of canonical registration; legacy ungoverned contracts remain eligible. Add a
   governed production path, explicit migration for legacy records and atomic
   lifecycle checks/publication. Keep old records available for replay.
7. **Reproducibility export and recovery:** provide snapshot/import verification,
   schema migrations and persistence/reopen tests. Existing retrieval preserves
   payloads but there is no complete portable library snapshot contract.
8. **Verification:** add integration tests proving contextual envelopes and
   exclusions govern sampling, duplicate resolution, compatibility filters,
   artifact-version replay, concurrent lifecycle mutations and restore behavior.

## Deliberately deferred infrastructure and upstream extensions

Real physical attestations and compiled scenes depend on the later Isaac Lab/SO-101
setup. SQLite is the current local persistence implementation; the brief's
PostgreSQL/JSONB deployment backend is not implemented. New robots, categorical
parameters and richer task grammars require corresponding DSL/compiler extensions.
These deferrals must remain explicit rather than called completed capabilities.

## Curriculum Sampler readiness

The supplied specification is `curriculum-sampler.md`. An initial sampler and
scheduler exist in `task_advisor/loop.py`; they are not the complete engine from
that specification. In addition to the Library issues above, the full sampler
requires versioned training-window directives, categorical/constraint schemas,
explicit fallbacks and coverage rules, demonstration quality/summary recording,
evaluation assignment integration and fuller observability. Do not label that
engine complete merely by exposing the existing sampler under a new package.

## Closure of audited software gaps

1. Identity reconciliation and recorded overrides: `reconcile`,
   `identity_override`, duplicate rejection in `register`.
2. Region/context-aware lookup: `supported_regions`, context-filtered `search`,
   and supported intersections/explicit gaps in `resolve_directive`.
3. Envelope enforcement: valid boxes minus invalid/unknown boxes;
   `assert_sample_allowed` is called during sampling and lease acquisition.
4. Compatibility queries: `compatibility` and exact-context search. Contexts
   include robot, gripper, controller, compiler, validator and simulator versions.
5. Version bridge: immutable `publish_version` bindings connect canonical semantic
   versions to exact execution hashes/revisions and artifact hashes. Changed
   implementations need a new execution revision, preserving historical replay.
6. Governed path: raw publication is rejected in the canonical Library;
   `migrate_legacy` explicitly imports old contracts. Ungoverned contracts are
   excluded from new work. Writer locks cover read-modify-write mutations.
7. Recovery: schema-version tracking, checksum snapshots, atomic restore into an
   empty registry, reference/content validation and CLI export/restore.
8. Verification: tests cover rejection/conflict gates, duplicate handling,
   context isolation, artifact versions, concurrent mutations, rollback,
   disk reopen and updated approval invalidating future leases.

The current sequential-DSL/local-SQLite software path can now be used to build
the Curriculum Sampler. PostgreSQL deployment, new DSLs/robots and actual physical
validation remain the explicit deferred work above; this is not a claim that
those have been implemented or that all conceivable requirements are covered.
