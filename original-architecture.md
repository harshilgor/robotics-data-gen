# SO-101 Robotics Data Factory
## Canonical Architecture and Engineering Context

This document defines the architecture that should be treated as the source of truth for the SO-101 Robotics Data Factory.

The system is a closed-loop synthetic robotics data generation platform built initially around the simulated SO-101 robot in Isaac Lab.

Its purpose is not merely to generate random simulation trajectories. The system should continuously determine what capabilities the current policy needs, identify or construct tasks that exercise those capabilities, instantiate those tasks across large parameterized distributions, collect trajectories, train the policy, evaluate the resulting capability changes, and use that evidence to decide what data to generate next.

The central loop is:

```text
                 POLICY
                   │
                   ▼
               EVALUATE
                   │
                   ▼
            EVIDENCE ENGINE
                   │
                   ▼
            CAPABILITY MODEL
                   │
                   ▼
              TASK ADVISOR
                   │
                   ▼
          ExplorationDirective
                   │
                   ▼
              TASK LIBRARY
                   │
          ┌────────┴─────────┐
          │                  │
   task coverage exists   coverage gap
          │                  │
          │                  ▼
          │            TASK GENERATOR
          │                  │
          │               TaskSpec
          │                  │
          │                  ▼
          │               COMPILER
          │                  │
          │                  ▼
          │               VALIDATOR
          │                  │
          │                  ▼
          │            TASK LIBRARY
          │
          └────────┬─────────┘
                   ▼
          CURRICULUM SAMPLER
                   │
                   ▼
          INSTANCE GENERATOR
                   │
                θ + φ
                   │
                   ▼
               COMPILER
                   │
                   ▼
              ISAAC LAB
                   │
                   ▼
             TRAJECTORIES
                   │
          ┌────────┴────────┐
          ▼                 ▼
   SYNTHETIC DATA      EPISODE RECORDS
          │                 │
          ▼                 │
   POLICY TRAINING          │
          │                 │
          └────────┬────────┘
                   ▼
            EVIDENCE ENGINE
                   │
                   └──────────────↺
```

The system therefore has two closely related outputs:

```text
1. robotics training data
2. evidence about what the robot can and cannot do
```

Both come from the same simulation experience.

---

# 1. Fundamental architecture principles

Several principles should remain true regardless of how individual algorithms evolve.

### Task semantics are separate from simulation implementation

A task should be represented declaratively using a formal `TaskSpec`.

The Task Generator must never directly produce arbitrary Isaac Lab Python code.

Instead:

```text
Task Generator
      ↓
   TaskSpec
      ↓
Task Compiler
      ↓
Isaac Lab
```

This keeps task generation simulator-independent and makes validation, versioning, reproducibility, and future simulator support much easier.

---

### Task families are separate from task instances

A task family represents a reusable class of robotic problems.

For example:

```text
retrieve object
→ transport around obstruction
→ place into target
```

A task instance represents one exact realization.

We describe a task instance approximately as:

\[
T=(F,\theta,\phi)
\]

where:

```text
F = Task Family

θ = task parameters

φ = environment/domain randomization
```

For example:

```yaml
family:
  constrained_pick_place

theta:
  placement_tolerance: 0.012
  obstacle_count: 2
  transport_distance: 0.31

phi:
  friction: 0.72
  object_mass: 0.18
  lighting_seed: 817
  texture_seed: 992

seed: 817392
```

The Generator discovers useful structures.

The Instance Generator creates volume.

The system should never require an LLM to invent millions of individual tasks.

---

### Difficulty is empirical, not a manually assigned number

There should not be a fundamental field like:

```yaml
difficulty: 8
```

Difficulty emerges from parameters such as:

```text
precision
sequence length
contact complexity
obstacle density
transport distance
object count
workspace constraints
target geometry
```

and ultimately from how the current policy performs.

The same task can be easy for one policy and difficult for another.

---

### The Advisor decides where to learn; the Generator decides what to create

This separation must remain strict.

```text
TASK ADVISOR

"What experience appears valuable next?"
```

versus:

```text
TASK GENERATOR

"What task structures could provide that experience?"
```

The Advisor does not invent tasks.

The Generator does not independently decide the curriculum.

---

### The Library stores task knowledge, not policy knowledge

Task Library owns:

```text
Task Families
TaskSpecs
versions
structural identity
capability annotations
validation envelopes
robot compatibility
provenance
lineage
```

It does not own:

```text
policy success rates
learning progress
failure distributions
capability estimates
regression statistics
```

Those belong to Task Intelligence.

---

# 2. Major system domains

The architecture can be understood as seven domains.

| Domain | Responsibility |
|---|---|
| Task Semantics | Define what robotic tasks mean |
| Task Knowledge | Persist reusable task families |
| Task Intelligence | Determine what experience is valuable |
| Task Discovery | Discover new task structures |
| Task Construction | Turn task definitions into executable environments |
| Simulation & Data | Generate trajectories at scale |
| Learning & Evaluation | Improve the policy and measure real capability |

These domains should remain logically separate even if they live in the same repository.

This should initially be a modular monolith rather than dozens of microservices.

---

# 3. Task Semantics Layer

This is foundational.

Almost every other component depends on the representations defined here.

```text
task_semantics/
│
├── task_spec
├── predicates
├── object_ontology
├── capability_ontology
├── affordances
└── task_grammar
```

## TaskSpec

`TaskSpec` defines the semantic meaning of a task.

Conceptually:

```yaml
family:
  retrieve_around_obstacle

objects:

  movable:
    requires:
      - graspable

  target:
    requires:
      - receptacle

  obstacle:
    requires:
      - collision_object

initial_state:
  - reachable(robot, movable)
  - outside(movable, target)

goal:
  - inside(movable, target)
  - stable(movable)

constraints:
  - avoid_collision(robot, obstacle)

skill_graph:
  - reach
  - grasp
  - lift
  - transport
  - align
  - place

capabilities:
  - grasp
  - grasp_stability
  - transport
  - obstacle_avoidance
  - precision_placement
  - sequencing

task_parameters:

  placement_tolerance:
    type: continuous
    min: 0.005
    max: 0.050

  obstacle_count:
    type: integer
    min: 0
    max: 4

  transport_distance:
    type: continuous
    min: 0.10
    max: 0.60

randomization:

  friction:
    min: 0.4
    max: 1.1

success:
  all:
    - inside(movable, target)
    - stable(movable)

termination:
  - success
  - timeout
  - unrecoverable_failure
```

TaskSpec should stay semantic.

It should not contain arbitrary simulator code.

---

# 4. Predicate system

Tasks should be expressed using reusable predicates such as:

```text
reachable(robot, object)
grasped(object)
inside(object, target)
near(object, target)
aligned(object, target)
stable(object)
contact(object_a, object_b)
open(drawer)
collision(robot, obstacle)
```

These predicates serve several systems simultaneously.

They define:

```text
initial conditions
subgoals
success
termination
reward signals
failure attribution
evaluation metrics
```

This shared predicate layer is extremely important because it means the system understands task state consistently.

---

# 5. Object and affordance ontology

Objects should not simply be asset filenames.

The system should understand their functional properties.

Example:

```text
cube
→ graspable
→ pushable
→ stackable

peg
→ graspable
→ insertable

tray
→ receptacle

drawer
→ openable
→ pullable
→ container
```

A generated task should request object roles such as:

```text
graspable object
receptacle
insertable object
openable container
```

The Asset Registry determines which actual simulator assets satisfy those roles.

This prevents generated tasks from depending on specific asset names.

---

# 6. Capability ontology

The system also needs a formal vocabulary describing robotic capability.

This should be hierarchical rather than a flat list.

Example:

```text
Manipulation
│
├── Acquisition
│   ├── reach
│   ├── align
│   └── grasp
│
├── Object Control
│   ├── lift
│   ├── transport
│   ├── rotate
│   └── maintain_grasp
│
├── Contact Manipulation
│   ├── push
│   ├── slide
│   ├── articulate
│   └── insert
│
├── Precision
│   ├── positional_precision
│   ├── orientation_precision
│   └── contact_precision
│
└── Composition
    ├── sequencing
    ├── long_horizon
    └── recovery
```

Every TaskFamily identifies the capabilities it exercises.

The Task Advisor reasons through this ontology.

The ontology itself must be versioned.

---

# 7. Task Grammar

The Task Grammar constrains how task structures can be composed.

The Generator should not be allowed to arbitrarily concatenate verbs.

For example:

```text
grasp
→ lift
→ transport
→ place
```

can be structurally sensible.

Whereas an invalid dependency sequence should be rejected before expensive simulation.

The grammar operates on:

```text
preconditions
effects
skill dependencies
object affordances
goal relationships
```

It provides the first logical filter for candidate families.

---

# 8. Task Library

The Task Library is the durable source of truth for reusable robotic task knowledge.

Its mission is:

> Store, version, validate, organize, search, and reproduce Task Families.

It should not become a dumping ground for every piece of system state.

The Library contains:

```text
Family Registry
Structural Identity
Indexes
Validation Envelopes
Compatibility
Lineage
Provenance
Version Dependencies
```

## Family identity

A new task candidate must first answer:

> Is this genuinely a new TaskFamily or merely a new parameter region of an existing family?

Family identity should primarily depend on:

\[
F=(G,S,O,C)
\]

where:

```text
G = goal structure
S = skill/dependency structure
O = object-role structure
C = structural constraints
```

Changing:

```text
placement tolerance: 50 mm → 5 mm
```

does not automatically create a new family.

Changing:

```text
pick → place
```

into:

```text
pick → navigate obstruction → orient → insert
```

may represent a genuinely different family.

This prevents uncontrolled family proliferation.

---

# 9. Task family lifecycle

Families should move through a controlled lifecycle.

```text
PROPOSED
    ↓
STRUCTURALLY_ACCEPTED
    ↓
VALIDATING
    ↓
VALID
    ↓
ACTIVE
```

Additional states can include:

```text
REJECTED_CONTEXTUALLY
ARCHIVED
DEPRECATED
```

`VALID` means the task is semantically legitimate.

`ACTIVE` means the task is currently usable by the SO-101 curriculum.

Those are not identical.

---

# 10. Validation envelopes

Validation must not simply be:

```yaml
validated: true
```

A TaskFamily spans a parameter space.

Different regions may be feasible or infeasible.

The Library should therefore store something like:

```yaml
validation_envelope:

  robot:
    so101_v1

  confirmed_valid:

    - obstacle_count: [0,2]
      placement_tolerance: [0.010,0.050]
      transport_distance: [0.10,0.45]

  confirmed_invalid:

    - obstacle_count: [4,5]
      corridor_width: [0.00,0.06]

  unknown:
    ...
```

The Curriculum Sampler should normally sample from validated regions.

---

# 11. Robot compatibility

Semantic task validity must remain separate from SO-101 feasibility.

Example:

```text
peg insertion
```

may be a valid robotics task even if a particular SO-101 configuration cannot execute some instances.

Therefore:

```yaml
semantic_status:
  valid: true

compatibility:

  so101_v1:
    status: partial

  franka_v1:
    status: compatible
```

This keeps the task model reusable beyond one embodiment.

---

# 12. Provenance and versioning

Every TaskFamily should record how it came into existence.

Example:

```yaml
provenance:

  source:
    composition

  parents:
    - retrieve
    - obstacle_transport

  generator_version:
    8
```

Possible sources include:

```text
human
mutation
composition
LLM proposal
```

Families must also be versioned.

A semantic-style version scheme is appropriate:

```text
PATCH
metadata/implementation change

MINOR
compatible extension of the task parameter space

MAJOR
task semantics changed
```

Historical experiments must always reference an exact TaskFamily version.

---

# 13. Task Generator

The Task Generator is responsible for discovering new regions of task space.

It should be an orchestrator containing several generation mechanisms.

```text
TASK GENERATOR
│
├── Family Manager
├── Composition Engine
├── Mutation Engine
├── LLM Proposal Engine
├── Task Grammar
├── Novelty Checker
└── Task Library Interface
```

## Composition

Combines known structures.

Example:

```text
retrieve
+
obstacle transport
+
precision placement
```

may produce a candidate family requiring all three.

## Mutation

Systematically modifies existing families.

Examples include:

```text
add obstacle
tighten tolerance
increase sequence length
restrict approach direction
add object
modify goal geometry
add spatial constraint
```

Mutation is especially useful because it generates systematic exploration without repeatedly calling an LLM.

## LLM proposals

The LLM is used for semantic creativity.

It can propose genuinely different high-level problems.

It should not generate arbitrary simulator code.

The proposal must still pass through:

```text
Task Grammar
Structural Identity
Compiler
Validator
```

before entering the active Library.

## Novelty

Novelty should be structural rather than textual.

Compare:

```text
goal structure
skill graph
object relationships
constraint topology
parameter region
```

rather than descriptions or object names.

A red cube instead of a blue cube does not create meaningful task novelty.

---

# 14. What is intentionally NOT in the core Generator

The architecture should leave extension points for research, but the following are not required core subsystems:

```text
Evolutionary/QD task search
Adversarial task-generation agents
learned novelty models
arbitrary LLM reward-code generation
```

They can become experiments later if evidence shows they improve the system.

They should not complicate the foundational architecture now.

---

# 15. Task Compiler

The Compiler translates declarative TaskSpecs into executable simulation configuration.

The Generator describes what should happen.

The Compiler determines how that becomes an Isaac Lab environment.

The Compiler should produce:

```text
scene configuration
object configuration
initial-state sampling
observations
action interface
reward terms
success predicates
termination conditions
reference-plan hooks
Isaac Lab environment configuration
```

Conceptually:

```text
TaskSpec
   ↓
Compiler
   ↓
CompiledTask
```

The Compiler should use shared libraries rather than generated arbitrary Python wherever possible.

---

# 16. Asset Registry

The Asset Registry stores simulation assets and their metadata.

Example information:

```text
geometry
collision geometry
mass
physics properties
scale limits
affordances
graspability
asset source
version
```

TaskSpecs request roles.

The registry provides concrete assets.

---

# 17. Scene Library

The Scene Library provides reusable parameterized scene structures.

Examples:

```text
tabletop
tabletop + obstacles
drawer
shelf
container workspace
multi-object workspace
```

Scenes should themselves support parameterized layouts.

The Scene Library is an implementation resource for the Compiler and Instance Generator, not a replacement for TaskFamily.

---

# 18. Skill Library

The Skill Library provides reusable reference capabilities for task compilation, validation, and potentially reward shaping.

A skill definition can include:

```text
preconditions
effects
reference controller/planner
termination predicates
required affordances
```

Examples:

```text
reach
grasp
lift
transport
push
pull
rotate
place
insert
```

Skill definitions must not be confused with policy capability estimates.

The Skill Library describes the semantics/reference execution of a skill.

The Capability Model describes whether the learned policy can currently perform it.

---

# 19. Task Validator

Validation protects expensive training compute from invalid task distributions.

The Validator should check several layers.

```text
logical validity
        ↓
affordance compatibility
        ↓
workspace / IK feasibility
        ↓
collision feasibility
        ↓
physical simulation validity
        ↓
reference-plan execution
```

The result is not just pass/fail.

The output should be a `ValidationReport` and contribute to a `ValidationEnvelope`.

Reference planning is particularly important.

We should empirically establish that SO-101 can execute representative instances rather than relying only on an LLM or symbolic checks.

---

# 20. Task Intelligence

Task Intelligence answers:

> What training experience should we generate next?

The core pipeline is:

```text
EpisodeRecords
+
Fixed Evaluation
      ↓
Evidence Engine
      ↓
Capability Model
      ↓
Task-Space State
      ↓
Selection Policy
      ↓
ExplorationDirective
```

This is deliberately not an LLM-based agent system.

The intelligence should primarily come from structured empirical evidence.

---

# 21. Evidence Engine

Every episode generates a canonical `EpisodeRecord`.

Example:

```yaml
episode_id: 83924

policy_version:
  checkpoint_120

task:
  family: constrained_pick_place
  family_version: 2.1.0

theta:
  placement_tolerance: 0.012
  obstacle_count: 2

phi:
  friction: 0.72

success: false

subgoals:
  grasp: true
  lift: true
  transport: true
  align: false
  place: false

failure:
  type: alignment_error
  stage: placement

metrics:
  collisions: 0
  grasp_losses: 0
  final_position_error: 0.021
```

The Evidence Engine aggregates records into useful statistics.

Examples:

```text
success
attempts
completion
goal error
failure distribution
collisions
grasp losses
learning progress
evaluation performance
```

---

# 22. Failure attribution

Task failure should not directly imply capability failure.

Because TaskSpec already exposes subgoals and predicates, many failures can be classified deterministically.

Example:

```text
grasp ✓
lift ✓
transport ✓
align ✗
place ✗
```

means the likely failure stage is alignment/placement rather than grasping.

Other signals can identify:

```text
object dropped
→ grasp stability

collision event
→ routing/collision

target reached but tolerance missed
→ precision

timeout before progress
→ horizon/control
```

No LLM should be required for the standard failure classification path.

---

# 23. Capability Model

The Capability Model estimates what the current SO-101 policy can actually do.

A capability state might include:

```yaml
capability:
  precision_placement

success_estimate:
  0.58

confidence:
  0.91

learning_progress:
  0.11

failure_distribution:
  alignment: 0.68
  grasp_loss: 0.14

evaluation:
  current: 0.55
  previous: 0.48

regression_score:
  0.0

sample_count:
  4318
```

Performance should include uncertainty.

For binary success observations, a simple Bayesian Beta estimate is sufficient initially.

The system should never treat:

```text
2 successes / 2 attempts
```

as equivalent evidence to:

```text
920 successes / 1000 attempts
```

---

# 24. Capability combinations

Interaction effects matter.

A policy may succeed at:

```text
grasp = high
transport = high
```

but fail at:

```text
grasp → transport → precision_place
```

However, the system should not enumerate every possible capability combination.

Combination nodes should be created from combinations that actually appear in TaskSpecs and accumulated experience.

This keeps the representation sparse.

---

# 25. Task-space regions

The Advisor should not reason about every exact numeric task independently.

Important parameters are grouped into meaningful regions.

Example:

```text
placement tolerance:

0–5 mm
5–10 mm
10–20 mm
20–40 mm
40+ mm
```

Then:

```yaml
region:

  family:
    constrained_pick_place

  placement_tolerance:
    10-20mm

  transport_distance:
    medium

  obstacle_count:
    1-2
```

can accumulate its own performance statistics.

---

# 26. Task-space states

Each sufficiently defined region is classified as:

```text
MASTERED
FRONTIER
STALLED
UNKNOWN
REGRESSING
```

### MASTERED

Strong performance with high confidence.

### FRONTIER

Not mastered, but showing productive learning progress.

### STALLED

Repeated poor performance with little progress.

### UNKNOWN

Insufficient evidence.

### REGRESSING

Performance was previously stronger but is degrading.

There is intentionally no generic `HARD` state.

A hard task could be frontier, stalled, or unknown.

Those distinctions are more actionable.

---

# 27. Task Advisor

The Task Advisor consumes the Task-Space State and decides how the next training budget should be allocated.

The Advisor should not select one single task.

It allocates across three goals:

```text
LEARN
→ productive frontier regions

EXPLORE
→ unknown / undercovered regions

RETAIN
→ capabilities showing regression
```

Conceptually:

```yaml
training_allocation:

  learn:
    fraction: 0.65

  explore:
    fraction: 0.25

  retain:
    fraction: 0.10
```

These percentages are examples, not architectural constants.

The important concept is allocating a distribution rather than choosing one winner.

---

# 28. ExplorationDirective

The Advisor communicates with downstream components through a typed `ExplorationDirective`.

Example:

```yaml
policy_version:
  checkpoint_120

learn:

  - capabilities:
      - precision_placement
      - sequencing

    parameters:
      placement_tolerance: [0.008,0.020]
      sequence_length: [3,4]

    weight: 0.55

explore:

  - capabilities:
      - constrained_insertion

    weight: 0.20

  - capabilities:
      - object_rotation

    weight: 0.10

retain:

  - capabilities:
      - grasp_stability

    weight: 0.15

avoid:

  - capability:
      basic_grasp

    reason:
      mastered
```

This is one of the system's major formal interfaces.

---

# 29. Library lookup before generation

Receiving an ExplorationDirective must not immediately trigger task generation.

The system first asks:

> Do existing TaskFamilies already satisfy this request?

```text
Advisor
   ↓
ExplorationDirective
   ↓
Task Library
   │
   ├── sufficient coverage
   │        ↓
   │ Curriculum Sampler
   │
   └── coverage gap
            ↓
       Task Generator
```

This avoids generating redundant families.

---

# 30. Curriculum Sampler

The Curriculum Sampler turns Advisor guidance into the distribution from which training tasks are actually selected.

Its job is:

```text
choose TaskFamily
choose validated θ region
respect learn/explore/retain allocation
maintain appropriate coverage
avoid prohibited/invalid regions
```

It does not create new TaskFamilies.

It does not perform high-level capability analysis.

It performs sampling.

---

# 31. Instance Generator

Once a family and task-space region are selected, the Instance Generator produces exact concrete episodes.

It samples:

```text
θ
task challenge parameters

φ
domain/environment randomization

assets
scene layout
seed
```

Output:

```yaml
family_id:
  constrained_pick_place

family_version:
  2.1.0

theta:
  placement_tolerance: 0.013
  transport_distance: 0.29
  obstacle_count: 1

phi:
  friction: 0.71
  object_mass: 0.184
  lighting_seed: 821
  texture_seed: 192

seed:
  728291
```

Cross-parameter constraints must be enforced.

For example:

```text
object_width < gripper_max_width

target_width >
object_width + placement_tolerance
```

Independent random sampling must not produce physically nonsensical combinations.

---

# 32. Isaac Lab simulation

Compiled instances run in Isaac Lab using the simulated SO-101.

The simulation layer should support many parallel environments.

Conceptually:

```text
GPU worker

├── env 1
├── env 2
├── env 3
├── ...
└── env N
```

Workers should operate mostly independently.

Large-scale execution can later use multiple workers coordinated by a scheduler.

The task architecture should not depend on one specific cluster implementation.

---

# 33. Episode Assignment

Every simulator worker should receive an explicit assignment.

Conceptually:

```yaml
assignment_id: ...
policy_version: ...
task_family: ...
family_version: ...
theta: ...
phi: ...
seed: ...
compiler_version: ...
robot_config: ...
recording_config: ...
```

This makes jobs reproducible and allows the Advisor to compare requested curriculum with actual execution.

---

# 34. Synthetic trajectory recording

Each rollout may record:

```text
robot state
observations
actions
rewards
RGB
depth
task predicates
contacts
collisions
subgoal events
success
failure
timing
task metadata
policy version
```

Not every dataset has to contain every modality.

Recording configuration should determine which modalities are persisted.

This avoids unnecessary storage overhead.

---

# 35. Data layer

The data layer has two distinct concepts.

### Episode metadata

Small structured records.

Stored in a database.

### Trajectory payloads

Potentially large tensors, images, depth streams, and state sequences.

Stored in object/file storage.

The relational catalog references the large data.

Do not store massive trajectory tensors directly inside the Task Library.

---

# 36. Dataset curation

The old architecture had a large Data Quality Engine responsible for too many decisions.

The new dataset curation layer should be narrower.

It handles things like:

```text
trajectory integrity
missing/corrupt frames
NaNs
invalid timestamps
metadata completeness
duplicate data
distribution summaries
dataset manifests
```

It may preserve both successful and failed trajectories.

Failure episodes can be highly valuable.

Whether an experience is educationally useful belongs primarily to Task Intelligence, not dataset-cleaning code.

---

# 37. Dataset catalog and manifests

Generated datasets should have reproducible manifests.

A manifest should record:

```text
dataset ID
creation timestamp
episode IDs
task family versions
task distribution
policy versions
simulator version
robot configuration
compiler version
observation modalities
curation filters
```

The dataset itself should be reproducible from the recorded episode assignments wherever practical.

---

# 38. Policy training

The synthetic dataset and online simulation experience feed the policy-training system.

The architecture should not be coupled permanently to one algorithm.

The first training backend can use a practical baseline such as PPO where appropriate.

Later experiments may use:

```text
behavior cloning
offline RL
imitation learning
diffusion policies
other task-conditioned policies
```

None of those should require rewriting TaskSpec, Library, Advisor, Generator, or Instance Generator.

That separation is intentional.

---

# 39. Fixed Evaluation Suite

Training performance must not be treated as the sole measure of capability.

Maintain a frozen evaluation suite.

It should contain representative held-out challenges such as:

```text
seen families with unseen θ
unseen scene configurations
unseen object combinations
precision tests
contact tasks
long-horizon compositions
held-out task compositions
```

These evaluation instances must not adapt merely because the Advisor changes the training curriculum.

The purpose is to distinguish:

```text
curriculum performance improved
```

from:

```text
actual robot capability improved
```

Evaluation results feed the Evidence Engine and Capability Model.

---

# 40. Transfer measurement

Transfer should initially be measured empirically rather than predicted by a complicated learned model.

After a training block:

```text
what capabilities/tasks received training?
```

is compared against:

```text
what changed across the fixed evaluation suite?
```

Over time the system can construct evidence such as:

```text
training precision placement
→ +12% precision evaluation
→ +6% insertion
→ +4% unseen placement
```

Only after sufficient evidence exists should a learned transfer predictor be considered.

---

# 41. Feedback integrity

The Advisor must know what actually reached simulation.

Suppose it requests:

```text
100 insertion-like tasks
```

but:

```text
Generator creates 81
Validator accepts 31
Curriculum schedules 20
Simulation executes 18
```

The Advisor must see that full funnel.

Therefore track:

```text
requested
generated
validated
scheduled
executed
```

Otherwise the Advisor may incorrectly believe it explored a region that never actually received training compute.

---

# 42. Reproducibility

Every important artifact should reference versions.

At minimum an episode should make it possible to recover:

```text
TaskFamily ID
TaskFamily version
TaskSpec schema version
capability ontology version
object ontology version
predicate library version

θ
φ
seed

SO-101 configuration
compiler version
simulator version
policy checkpoint
```

This is essential for both research and debugging.

---

# 43. Persistence architecture

A reasonable initial production structure is:

```text
PostgreSQL
│
├── Task Families
├── validation metadata
├── ontology versions
├── EpisodeRecords
├── CapabilityState
├── Advisor history
├── dataset manifests
└── experiment metadata

Object Storage
│
├── trajectories
├── RGB
├── depth
├── checkpoints
└── large artifacts
```

JSONB can be used for flexible structured fields.

Do not introduce a graph database or vector database until actual scaling requirements justify it.

---

# 44. Suggested repository structure

A coherent repository might look approximately like:

```text
robotics_data_factory/
│
├── semantics/
│   ├── task_spec/
│   ├── predicates/
│   ├── object_ontology/
│   ├── capability_ontology/
│   └── grammar/
│
├── task_library/
│   ├── registry/
│   ├── identity/
│   ├── indexing/
│   ├── validation/
│   ├── provenance/
│   └── storage/
│
├── task_generator/
│   ├── family_manager/
│   ├── composition/
│   ├── mutation/
│   ├── llm_proposals/
│   └── novelty/
│
├── task_compiler/
│   ├── scene/
│   ├── objects/
│   ├── observations/
│   ├── actions/
│   ├── rewards/
│   └── isaac_lab/
│
├── task_validator/
│   ├── logical/
│   ├── kinematics/
│   ├── collision/
│   ├── physics/
│   └── reference_execution/
│
├── curriculum/
│   ├── sampler/
│   ├── instance_generator/
│   └── assignment/
│
├── advisor/
│   ├── evidence/
│   ├── capability/
│   ├── task_space/
│   ├── selection/
│   └── directives/
│
├── assets/
│   ├── registry/
│   └── scenes/
│
├── simulation/
│   ├── so101/
│   ├── workers/
│   └── episode_logging/
│
├── evaluation/
│   ├── benchmark_registry/
│   └── evaluator/
│
├── data/
│   ├── trajectory_writer/
│   ├── curation/
│   ├── catalog/
│   └── manifests/
│
└── training/
    ├── policy/
    ├── checkpoints/
    └── hooks/
```

These should be modules, not necessarily independent services.

---

# 45. Canonical data contracts

The system should revolve around a small number of strongly typed contracts.

### `TaskSpec`

Defines what a robotic task means.

### `TaskFamily`

Versioned reusable family wrapping a TaskSpec plus library metadata.

### `ValidationReport`

Reports results of logical, kinematic, collision, physics, and reference-execution validation.

### `ValidationEnvelope`

Describes known feasible, infeasible, and unknown parameter regions.

### `ExplorationDirective`

Communicates Advisor priorities.

### `TaskInstance`

One concrete:

\[
(F,\theta,\phi,\text{seed})
\]

configuration.

### `EpisodeAssignment`

Defines exactly what a simulator worker should execute.

### `CompiledTask`

Executable environment configuration produced by the Compiler.

### `EpisodeRecord`

Compact structured description of what happened.

### `CapabilityState`

Current evidence-backed capability estimate.

### `DatasetManifest`

Defines exactly which episodes and configurations form a dataset.

These contracts matter more than internal implementation details.

---

# 46. The standard operating loop

Once the factory is running, a normal cycle should be:

```text
CURRENT POLICY
      ↓
FIXED EVALUATION
+
TRAINING EXPERIENCE
      ↓
EVIDENCE ENGINE
      ↓
CAPABILITY MODEL
      ↓
TASK-SPACE STATE
      ↓
TASK ADVISOR
      ↓
ExplorationDirective
      ↓
TASK LIBRARY SEARCH
      ↓
┌────────────────────────────┐
│                            │
existing coverage       coverage gap
│                            │
│                       TASK GENERATOR
│                            │
│                         TaskSpec
│                            │
│                         Compiler
│                            │
│                         Validator
│                            │
│                       Task Library
│                            │
└─────────────┬──────────────┘
              ↓
      CURRICULUM SAMPLER
              ↓
      INSTANCE GENERATOR
              ↓
       EpisodeAssignments
              ↓
          ISAAC LAB
              ↓
          EXPERIENCE
              ↓
 ┌────────────┴────────────┐
 ↓                         ↓
DATASET                EVIDENCE
 ↓                         ↓
TRAIN POLICY        CAPABILITY MODEL
 ↓                         │
NEW POLICY                │
 └─────────────────────────┘
```

That is the complete closed loop.

---

# 47. Bootstrap strategy

Although the architecture is designed for open-ended generation, the initial system should not depend on autonomous generation.

Seed the Library with a deliberately broad set of carefully designed TaskFamilies.

Examples might include:

```text
reach
grasp
pick_and_place
push_to_target
precision_place
transport_around_obstacle
object_rotation
stack
insert
retrieve_from_container
open_and_retrieve
sequential_rearrangement
```

The exact number is less important than conceptual coverage.

This allows the complete pipeline to be validated before relying on LLM-generated task families.

---

# 48. Build-order dependency

The architecture should support everything described here, but implementation should follow dependency order.

The critical foundation is:

```text
TaskSpec / DSL
        ↓
Ontologies / predicates
        ↓
hand-written TaskFamilies
        ↓
Task Library
        ↓
Compiler
        ↓
Validator
        ↓
Curriculum + Instance Generator
        ↓
Isaac Lab
        ↓
EpisodeRecord / Dataset
        ↓
Evidence Engine
        ↓
Capability Model
        ↓
Task Advisor
```

Once this closed loop works reliably:

```text
Task Generator
```

can begin expanding the Library autonomously.

This is not a reduced architectural version.

It is simply dependency-aware construction of the full system.

---

# 49. Critical ownership boundaries

The coding agent should preserve the following boundaries.

| Component | Owns |
|---|---|
| TaskSpec | Task semantics |
| Task Library | Reusable task knowledge |
| Task Generator | New task discovery |
| Compiler | Simulator realization |
| Validator | Feasibility evidence |
| Advisor | Curriculum strategy |
| Curriculum Sampler | Training distribution |
| Instance Generator | Concrete episode configurations |
| Evidence Engine | Outcome aggregation |
| Capability Model | Policy competence estimates |
| Isaac Lab | Simulation execution |
| Data Layer | Trajectory persistence |
| Training Engine | Policy optimization |
| Fixed Eval | Independent capability measurement |

If functionality seems to belong to multiple components, preserve these ownership rules rather than duplicating decision logic.

---

# 50. Explicit architectural non-goals

Several patterns should be avoided.

Do not let the Task Generator output arbitrary Isaac Lab code.

Do not put policy performance inside the Task Library.

Do not have the Generator independently maintain the curriculum frontier.

Do not have the Advisor invent individual task implementations.

Do not assign arbitrary human difficulty scores.

Do not treat family validation as a single boolean.

Do not treat a rejection under one robot/configuration as universal task invalidity.

Do not create a separate family for every parameter variation.

Do not introduce evolutionary search, adversarial agents, neural novelty systems, graph databases, vector databases, or learned transfer models until actual evidence shows they are necessary.

Do not collapse TaskFamily and TaskInstance into one abstraction.

Do not use training performance as a substitute for frozen evaluation.

---

# 51. What the architecture is ultimately optimizing

The factory is trying to produce experience that improves general robotic capability efficiently.

At the Task Generator level, useful candidate families should expand:

\[
\text{Novelty}
+
\text{Coverage}
+
\text{Learnability}
+
\text{Potential Transfer}
\]

The Task Advisor then decides where additional experience appears useful based on actual policy evidence.

The curriculum therefore evolves as the policy evolves.

---

# 52. Final mental model

Each major subsystem answers one question.

```text
TASKSPEC / DSL
"What exactly is this robotic problem?"

TASK LIBRARY
"What task knowledge do we already possess?"

TASK ADVISOR
"What should SO-101 learn next?"

TASK GENERATOR
"What new task structures could teach it that?"

TASK COMPILER
"How do I turn the task into an executable environment?"

TASK VALIDATOR
"Can this task actually work, and where?"

CURRICULUM SAMPLER
"Which task region should receive training compute?"

INSTANCE GENERATOR
"What exact environment should this episode use?"

ISAAC LAB
"What happens when the robot actually tries it?"

EVIDENCE ENGINE
"What happened across all those attempts?"

CAPABILITY MODEL
"What can the current SO-101 policy actually do?"

DATA FACTORY
"Which trajectories should be persisted as synthetic robotics data?"

POLICY TRAINING
"How do we improve the policy using that experience?"

FIXED EVALUATION
"Did the robot genuinely become more capable?"
```

---

# 53. Final system definition

The SO-101 Robotics Data Factory is a closed-loop platform that:

```text
measures the current robot
        ↓
identifies valuable capability gaps
        ↓
finds or constructs tasks targeting those gaps
        ↓
validates the feasible task space
        ↓
procedurally generates large task distributions
        ↓
executes them in parallel simulation
        ↓
records structured robotics trajectories
        ↓
trains the policy
        ↓
evaluates the resulting capability change
        ↓
uses that evidence to determine what experience to generate next
```

The ultimate architecture is therefore:

\[
\boxed{
\text{Measure}
\rightarrow
\text{Advise}
\rightarrow
\text{Retrieve/Create Tasks}
\rightarrow
\text{Validate}
\rightarrow
\text{Sample}
\rightarrow
\text{Simulate}
\rightarrow
\text{Collect}
\rightarrow
\text{Train}
\rightarrow
\text{Measure}
}
\]

The central research idea is not merely automated task generation.

It is **automated experience generation**:

> Build a system capable of continuously discovering what experience a robot needs, generating that experience synthetically at scale, measuring what the robot learned from it, and using those measurements to improve the next generation of data.

SO-101 is the initial embodiment.

The architecture should be designed so that the task semantics, Library, Advisor, Generator, and data system can eventually support additional robots without fundamental redesign.