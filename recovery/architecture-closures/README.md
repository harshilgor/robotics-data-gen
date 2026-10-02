# Preserved cloud delivery

This directory preserves the completed Architecture Software cloud job, including
its exact Git history, all 41 changed source files and saved synthetic factory
state. The original cloud commit is `ce0bbedcfab47e0a11419eef0a7460c50b030983`.
Its branch is retained as `codex/architecture-closures` and merged into main,
alongside the previously uncommitted local architecture audit.

`robotics-architecture-recovery.zip` is the complete original package, recovered
through 636 recorded chunks and verified against its original SHA256:
`ed5d256cceee73440ea00dc8c0d46222da043203acdddce6857abe03c9ba0c8f`.
Its 142 entries include the Git bundle, patch, exact sources, manifests, all
closed factory-state files, checkpoints, episode payloads and draft PR text.
SQLite integrity returned `ok`. Source hashes match `manifest.json` and all
41 source files match the original Git commit byte for byte.

Extract the package into a new recovery directory. Use the recovered
`factory-state` directory as the factory root. The saved job is
`architecture-demo`, with three completed iterations and 90 durable completions.
Passing the same iteration target resumes that job without adding iterations;
increase the target only when intentionally continuing training. Keep active
SQLite files on a local filesystem and back them up only when closed.

The cloud source required two Windows compatibility fixes during integration:
portable nonblocking process locking and explicit repository test-package
resolution. The original cloud commit remains unchanged in the retained branch.
Local verification ran 135 tests: 134 passed, one live PostgreSQL test skipped.
A separate process check verified Windows lock contention and release.

The architecture remains incomplete. See `architecture-closure-review.md` for
the section-by-section assessment and remaining governed physical-worker work.
The recovered historical baseline audit is preserved separately from that review.
