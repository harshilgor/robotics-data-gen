# Task Generator implementation

This plan interprets the supplied `original-architecture.md` and `task-generator.md`. Those source documents remain unchanged. It treats their research references as conceptual influences, rather than verified implementation specifications.

## Components and build decisions

| Component in the brief | How to build it | Delivery stage |
| --- | --- | --- |
| Task-space exploration | Identify a family by content hash and revision; store task/difficulty ranges separately from environment randomization ranges. Sample concrete instances with replayable seeds. | V1 implemented |
| Task grammar and skill graph | Use trusted skill definitions with preconditions, add/delete effects and required affordances. Replay symbolic state along a complete dependency chain. Later add branching with explicit branch semantics and graph-state analysis. | Sequential V1 implemented; conditional and multi-object graphs later |
| Counterfactual mutation | Change one named parameter distribution at a time, retain parent hash and mutation details, and rerun validation. Add obstacle, object-count and approach constraints only after their scene/compiler support exists. | Range mutation implemented; scene mutations later |
| Compositional novelty | Compare ordered skill structure, skill/transition compositions, asset affordances, difficulty ranges and randomization ranges against accepted candidates. Exact duplicates have zero distance. Use these scores as descriptors, not learning-value estimates. | V1 implemented |
| Capability-gap guidance | Consume Advisor requests identifying skill intersections and parameter regions, with provenance and supported scope. Generation should propose candidates within that guidance; curriculum sampling remains a separate engine. | Next phase |
| Frontier | Aggregate checkpoint-tagged success estimates, sample counts and learning progress by family/region. Use uncertainty and empirical results; failure does not prove impossibility. Keep sealed evaluation evidence inaccessible. | After simulation and Advisor |
| Automatic family invention | Accept structured proposals containing known assets, skills, parameter ranges, success predicates and trusted rewards. Validate candidate definitions before registering them. Unsupported primitives need an explicit compiler/registry extension. | LLM phase |
| Creative engines | Standardize candidate specification plus provenance. Start with hand-written templates, composition and mutation; add LLM proposals, then QD search using measured quality and behavior descriptors. | First two engines implemented |
| Reward and success | Keep a separate success predicate and a list of allowlisted reward terms. A future compiler binds these to trusted sensor/state functions. Check reward scale and hacking behavior through rollout experiments. | Declarative specification implemented; evaluation pending |
| Adversarial generation | Apply supported harder mutations under bounded budgets. Validate every variant; classify it using empirical probes instead of assuming harder is better. | After empirical validation |
| Task/object/scene graphs | Store skills, dependencies, object identities/affordances, scene template and spatial relations in the DSL. V1 uses one manipulated cube and one target on a tabletop. | V1 subset implemented |
| Validator | Reject malformed schemas, unsupported skills/assets, invalid parameter ranges, broken dependency chains, missing affordances and goals not established symbolically. Physical checks need separate simulator-backed evidence. | Structural V1 implemented |
| Family library and instance generator | Keep independent family snapshots, hash identities, revision and lineage. Generate instance-addressed seeds so replay does not depend on call order. CLI exports family specs and instances together. Connect persistent Task Library through its own API next. | In-memory registry and JSON export implemented |
| Compiler and Isaac Lab | Define an adapter that takes a validated family and sampled instance, resolves registries and binds trusted reset/reward/success implementations. Produce separately versioned IK, collision, reset-stability and rollout evidence. | Pending; no simulator adapter claimed |

## Runnable V1

The Python implementation uses only the standard library. Run from the project directory:

```powershell
python -m unittest discover -s tests -v
python -m taskgen --seed 42 --instances-per-family 3 --output generated-tasks.json
```

Six bootstrap families cover reach, grasp, push, lift, transport and pick-place. The CLI also exports a composed family and a tighter-tolerance variant. Skills are symbolic descriptions, not executable robot controllers. Asset sizes, masses and distances are exploratory ranges, not certified SO-101 limits.

Every instance includes sampled theta/phi, its family hash, generator version, seed and validation status. Every status explicitly leaves kinematics, collision, physics, solvability and RL learnability pending. Structural acceptance must never be used as permission to train or label a task physically feasible.

## Build sequence

1. Establish the DSL, symbolic grammar, six templates, composition/mutation, novelty and replay. This is the implemented baseline.
2. Connect the Task Library contract, persist candidate/rejection evidence, add instance-level validation and a versioned Isaac Lab adapter with SO-101 assets. Test resets and independent success checks before training.
3. Train a baseline on accepted task instances and collect development evidence. Compare proposed exploration against uniform sampling with equal simulation budgets and multiple seeds.
4. Integrate Advisor requests and an empirical frontier; measure improvements before expanding complexity.
5. Add constrained LLM family proposals using the same DSL and validation path. Never execute generated code.
6. Add QD/evolution and adversarial search once quality, feasibility and transfer measurements exist.

V1 intentionally does not train PPO, provision cloud infrastructure, certify robot capability, execute rewards, or implement the other engines.
