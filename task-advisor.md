Yes. After critiquing the previous Advisor design, I would simplify and strengthen it rather than adding more “intelligence.” The key change is this:

> **The Task Advisor should not ask “what task is hardest?” or even “where is learning progress highest?” It should maintain an evidence-based model of the robot’s current capabilities and allocate training across the places where additional experience is most valuable.**

That preserves the original separation where the Advisor identifies regions worth exploring and the Generator creates the actual tasks. Pasted text

The architecture I would now recommend is:

```text
                         TRAINING / ISAAC LAB
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │    EVIDENCE ENGINE     │
                    │                        │
                    │ training outcomes      │
                    │ fixed evaluations      │
                    │ trajectory metrics     │
                    │ failure attribution    │
                    └───────────┬────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │   CAPABILITY MODEL     │
                    │                        │
                    │ what can robot do?     │
                    │ where is it weak?      │
                    │ where is it learning?  │
                    │ what are we unsure of? │
                    └───────────┬────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │   TASK-SPACE STATE     │
                    │                        │
                    │ mastered               │
                    │ frontier               │
                    │ stalled                │
                    │ unknown                │
                    │ regressing             │
                    └───────────┬────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │   SELECTION POLICY     │
                    │                        │
                    │ learn                  │
                    │ explore                │
                    │ retain                 │
                    └───────────┬────────────┘
                                │
                                ▼
                    ┌────────────────────────┐
                    │ EXPLORATION DIRECTIVE  │
                    └───────────┬────────────┘
                                │
                                ▼
                         TASK GENERATOR
```

I think these **four internal pieces are enough**. I would not add more subsystems unless experiments later demonstrate the need.

## 1. Evidence Engine: establish what actually happened

The first problem with our old architecture was that something like:

```text
task failed
      ↓
precision score decreases
```

is too naive.

Instead, every episode should generate structured evidence.

Imagine this task:

```text
pick cube
→ transport around obstacle
→ place cube into 10 mm target
```

Instead of storing only:

```yaml
success: false
```

we store:

```yaml
task_family: constrained_pick_place

outcome:
  success: false
  completion: 0.78

stages:
  grasp:
    success: true

  transport:
    success: true

  placement:
    success: false

failure:
  type: alignment_error
  stage: placement
  residual_position_error: 0.018

metrics:
  collisions: 0
  completion_time: 5.4
  object_slip: false
```

Now the Advisor knows much more.

The failure was not:

> pick-and-place is weak.

It was:

> placement alignment under this particular geometry appears weak.

### How failure attribution works

I would **not create an LLM failure-analysis agent**.

We already know the structure of the task from TaskSpec.

If the goal graph is:

```text
grasp
  ↓
lift
  ↓
transport
  ↓
align
  ↓
place
```

we can instrument those predicates.

Then failure attribution becomes mostly deterministic:

```text
grasp predicate never achieved
→ grasp failure

grasp achieved, later lost
→ grasp stability failure

collision predicate triggered
→ routing/collision failure

target reached but tolerance missed
→ placement precision failure
```

That is much more reliable and cheaper than asking a model to interpret every trajectory.

---

## 2. Capability Model: estimate what the robot actually knows

This is the most important improvement.

The Advisor needs one canonical representation of current competence.

But I would **not** initially build a neural capability model or task embedding.

Start with a hierarchical capability graph:

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
│   └── maintain grasp
│
├── Contact Manipulation
│   ├── push
│   ├── slide
│   ├── insert
│   └── articulate
│
├── Precision
│   ├── positional
│   ├── orientation
│   └── contact precision
│
└── Composition
    ├── sequencing
    ├── long horizon
    └── recovery
```

Every TaskSpec declares what capabilities it exercises.

Then the capability model aggregates evidence.

For example:

| Capability | Success | Progress | Confidence |
|---|---:|---:|---:|
| Grasp | 94% | +1% | high |
| Transport | 87% | +4% | high |
| Precision placement | 53% | +11% | medium |
| Insertion | 21% | +3% | low |
| Grasp → precision | 38% | +13% | medium |

But **confidence is essential**.

Suppose insertion shows:

```text
success = 20%
```

after only five trials.

That is very different from:

```text
success = 20%
```

after 5,000 trials.

So the Capability Model should track uncertainty alongside performance.

A simple Beta-Binomial estimate is probably enough initially; we absolutely do not need a deep network for this.

---

## 3. Task-Space State: classify regions rather than assign “difficulty”

This replaces our previous simplistic frontier map.

Each region of task space gets one of roughly five states:

```text
                    TASK SPACE

MASTERED       FRONTIER       STALLED       UNKNOWN
   │               │              │             │
   │               │              │             │
high success    learning       failing       insufficient
stable          strongly       repeatedly     evidence

                    +
                REGRESSING
                    │
             capability used to
             work but is declining
```

That distinction solves several problems.

### Mastered

```text
success ≈ high
learning progress ≈ low
confidence = high
```

Don't spend much compute here.

---

### Frontier

```text
success = moderate
learning progress = positive
confidence = reasonable
```

Prime curriculum territory.

This preserves one of the strongest ideas in the original architecture: target regions that are not mastered but appear learnable. Pasted text

Prioritized Level Replay similarly prioritizes environments based on estimated future learning potential rather than sampling levels uniformly. [arXiv](https://arxiv.org/abs/2010.03934?utm_source=chatgpt.com) Recent robotics work on LP-ACRL also argues that complex task spaces need not have a manually specified difficulty ordering and instead adapts sampling using observed learning progress. [arXiv](https://arxiv.org/abs/2601.17428?utm_source=chatgpt.com)

---

### Stalled

Something like:

```text
success = 5%
progress = 0%
trials = many
```

That's important information.

Instead of blindly training there:

```text
deprioritize
      ↓
perhaps Generator creates easier
supporting tasks around it
```

---

### Unknown

Perhaps:

```text
articulated manipulation
trials = 2
```

We simply don't know.

This is important because otherwise the Advisor can become trapped around known task families.

---

### Regressing

Suppose:

```text
grasp:
93% → 92% → 88% → 81%
```

That's different from a weak capability.

It was learned and is being forgotten.

Teacher-Student Curriculum Learning explicitly considered both positive learning progress and negative progress/forgetting when deciding what the student should revisit. [arXiv](https://arxiv.org/abs/1707.00183?utm_source=chatgpt.com)

So regressions should trigger targeted replay.

---

# 4. Selection Policy: don't choose one frontier—allocate a curriculum

This is the other major conceptual change I would make.

Previously, we effectively imagined:

```text
Advisor
   ↓
find best region
   ↓
Generator
```

I would **not do that**.

Instead:

```text
Advisor
   ↓
allocate next training budget
```

across three objectives:

```text
             NEXT TRAINING BUDGET
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
      LEARN        EXPLORE       RETAIN
        │            │            │
    frontier        unknown     regressions
```

These three are enough.

### LEARN

Spend most training on productive frontiers.

Examples:

```text
precision placement:
10–20 mm

transport:
1–2 obstacles

sequence length:
3–4 skills
```

---

### EXPLORE

Occasionally probe unknown regions.

For example:

```text
rotation
drawer manipulation
insertion
constrained grasping
```

This prevents the robot from spending its entire life doing increasingly difficult pick-and-place tasks.

OMNI's authors make a related observation: learning progress alone does not determine which of many learnable tasks is actually worth pursuing; their framework combines learnability with a notion of interestingness. [arXiv](https://arxiv.org/abs/2306.01711?utm_source=chatgpt.com)

For our architecture, I would **not add another foundation model inside the Advisor to score “interestingness.”**

We already have something cleaner:

```text
capability ontology
+
coverage
+
unknown regions
+
Task Generator novelty
```

That's sufficient initially.

---

### RETAIN

Small amounts of training should revisit capabilities that are degrading.

Not all mastered tasks.

Only meaningful regressions.

That deals with forgetting without wasting massive amounts of compute on things the robot already knows.

---

# How does the Advisor choose among them?

I would keep the scoring mechanism simple.

For each task-space region \(r\), compute something roughly like:

\[
Priority(r)=
w_L L(r)
+
w_U U(r)
+
w_G G(r)
+
w_R R(r)
\]

where:

- \(L(r)\) = learning progress
- \(U(r)\) = uncertainty
- \(G(r)\) = capability/coverage gap
- \(R(r)\) = regression signal

with penalties for regions that are clearly mastered or repeatedly unlearnable.

I would **not hard-code one universal score and assume we solved curriculum learning**.

The score is simply a scheduling heuristic.

And initially I would make those terms interpretable.

For example:

```yaml
precision_placement_10mm:

  success: 0.51
  learning_progress: 0.14
  uncertainty: 0.12
  coverage_gap: 0.38
  regression: 0.00

  state: FRONTIER

  priority_reason:
    - strong recent learning
    - important capability gap
```

That makes debugging the Advisor much easier.

---

# Fixed evaluation must sit outside the curriculum

There's one extremely important addition.

Training results alone cannot be trusted.

Suppose the Generator starts producing lots of easier tasks.

The Advisor sees:

```text
success:
61% → 73% → 86%
```

and concludes:

> Great. The robot is improving.

But perhaps the tasks just became easier.

Therefore:

```text
                       POLICY
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
       curriculum tasks      FIXED EVALUATION
              │                     │
      training signal        capability truth
```

The fixed evaluation suite should never change simply because the Advisor changes its curriculum.

This was already one of the stable principles in the architecture. Pasted text

We'd maintain benchmark instances across things like:

```text
grasp
transport
precision
insertion
sequencing
compositional generalization
unseen objects
unseen configurations
```

Then we can distinguish:

```text
training performance ↑

versus

actual capability ↑
```

Those are not always the same.

---

# We also need one small but important feedback check

There was another subtle problem in the old architecture.

Suppose the Advisor requests:

```text
explore precision + sequencing
```

Generator creates 100 tasks.

But:

```text
100 requested candidates
     ↓
62 pass grammar
     ↓
31 pass validation
     ↓
19 actually sampled
     ↓
most happen to be easy placements
```

The Advisor shouldn't assume its request was fulfilled.

So each cycle records:

```text
requested task distribution
          ↓
generated distribution
          ↓
validated distribution
          ↓
actually trained distribution
```

I would **not make this another architecture component**.

It's simply telemetry attached to the Advisor/Generator interface.

But it matters because otherwise the Advisor may think it explored a region that never actually reached the robot.

---

# What about transfer?

This is the hardest issue from the previous critique.

We ultimately care about:

\[
\text{Did training here make the robot better elsewhere?}
\]

We should measure it—but I would resist building a sophisticated transfer predictor right now.

Instead, use the fixed evaluation suite.

If training on:

```text
precision pick-and-place
```

also improves:

```text
insertion
rearrangement
unseen-object placement
```

we have evidence of transfer.

Over time we can record:

```text
training family A
       ↓
Δ performance on evaluation families B,C,D...
```

giving us an empirical transfer matrix:

```text
                Improvement on →
Train ↓       grasp  place  insert  route
------------------------------------------
grasp            —     +3      0      +1
precision        +1     —     +8      +2
routing           0     +1      0       —
insertion        +2     +5      —      +1
```

Only once we have enough data would I consider learning a model that predicts transfer.

**Don't build the predictor before we have the evidence.**

---

# The resulting Task Advisor

So I would settle on exactly this:

```text
                    ┌───────────────────────┐
                    │ TRAINING EXPERIENCE   │
                    └───────────┬───────────┘
                                │
                         + FIXED EVAL
                                │
                                ▼
                ┌───────────────────────────┐
                │      EVIDENCE ENGINE      │
                │                           │
                │ outcomes                  │
                │ subgoal completion        │
                │ failure attribution       │
                │ trajectory metrics        │
                └─────────────┬─────────────┘
                              ▼
                ┌───────────────────────────┐
                │     CAPABILITY MODEL      │
                │                           │
                │ performance               │
                │ learning progress         │
                │ uncertainty               │
                │ regressions               │
                └─────────────┬─────────────┘
                              ▼
                ┌───────────────────────────┐
                │     TASK-SPACE STATE      │
                │                           │
                │ mastered                  │
                │ frontier                  │
                │ stalled                   │
                │ unknown                   │
                │ regressing                │
                └─────────────┬─────────────┘
                              ▼
                ┌───────────────────────────┐
                │     SELECTION POLICY      │
                │                           │
                │ LEARN    → frontier       │
                │ EXPLORE  → unknown        │
                │ RETAIN   → regressions    │
                └─────────────┬─────────────┘
                              ▼
                ┌───────────────────────────┐
                │   EXPLORATION DIRECTIVE   │
                └─────────────┬─────────────┘
                              ▼
                       TASK GENERATOR
```

And the Generator might receive:

```yaml
advisor_directive:

  learn:
    target:
      - precision_placement
      - sequencing

    regions:
      placement_tolerance: [0.008, 0.020]
      sequence_length: [3, 4]

    priority: high

  explore:
    capabilities:
      - constrained_insertion
      - object_rotation

    priority: medium

  retain:
    capabilities:
      - grasp_stability

    priority: low

  avoid:
    - basic_grasp
    - large_tolerance_placement
```

The Generator then figures out **which actual task families and instances satisfy that directive**.

---

## What I deliberately would NOT add

This is as important as what we add.

I would not currently add:

- an LLM inside the Advisor;
- a neural task embedding;
- a learned capability predictor;
- meta-RL to train the Advisor;
- evolutionary/QD search;
- an adversarial curriculum agent;
- a causal inference system for every failure;
- a learned transfer predictor;
- a separate “interestingness agent.”

Those may become legitimate research experiments later.

But none is necessary to make the core system work.

### So the final division becomes extremely clean

```text
EVIDENCE ENGINE
"What happened?"

        ↓

CAPABILITY MODEL
"What can the robot currently do?"

        ↓

TASK-SPACE STATE
"Where are we mastered, learning, stuck,
uncertain, or forgetting?"

        ↓

SELECTION POLICY
"Where should training effort go next?"

        ↓

TASK GENERATOR
"What actual tasks can provide that experience?"

        ↓

COMPILER + VALIDATOR
"Can those tasks actually be executed?"

        ↓

ISAAC LAB
"Train."

        ↓

EVIDENCE
```

That is the Task Advisor architecture I would build. It addresses the major shortcomings we identified while only adding one genuinely new conceptual layer compared with the original design—the **Capability Model between raw measurements and curriculum decisions**. Everything else is essentially a cleaner organization of functionality we already needed.

---

I would build the Task Advisor as a **data pipeline plus a decision policy**, not as an autonomous agent. The implementation should be deliberately boring in the right places: structured episode logging, deterministic metrics, a capability database, then a small curriculum-selection layer. The intelligence comes from the closed loop, not from having another LLM.

The build order I’d use is:

```text
1. Instrument tasks and episodes
        ↓
2. Build the Evidence Engine
        ↓
3. Build the Capability Model
        ↓
4. Build the Task-Space State
        ↓
5. Build the Selection Policy
        ↓
6. Define Advisor → Generator API
        ↓
7. Close the training loop
        ↓
8. Add fixed evaluation + transfer measurement
```

This fits the architecture we established, where the Advisor recommends *regions of task space* rather than specific tasks. Pasted text

## 1. First, make TaskSpec observable

Before building the Advisor, every TaskSpec needs enough metadata for the Advisor to understand what capabilities the task exercises.

Something like:

```yaml
task_family: constrained_pick_place

capabilities:
  - grasp
  - grasp_stability
  - transport
  - obstacle_avoidance
  - precision_placement
  - sequencing

subgoals:
  - id: grasp_object
    success: grasped(object)

  - id: transport_object
    success: near(object, target)

  - id: place_object
    success: inside(object, target)

parameters:
  placement_tolerance: 0.012
  obstacle_count: 2
  transport_distance: 0.34
  sequence_length: 4
```

This should come from the TaskSpec/DSL, not be reconstructed afterward.

That means every generated task is already annotated with:

```text
what capabilities it tests
what subgoals exist
what parameters define it
what success means
```

This is essential because the Advisor depends on the formal task representation the architecture already defines. Pasted text

---

# 2. Build a standard Episode Record

Every Isaac Lab rollout should produce one canonical record.

For example:

```python
EpisodeRecord {
    episode_id
    policy_version

    task_family
    task_instance_id

    task_parameters

    capabilities

    success
    reward
    completion_fraction
    episode_length

    subgoal_results

    failure_type
    failure_stage

    collisions
    grasp_losses
    final_goal_error

    timestamp
}
```

A concrete record could look like:

```yaml
episode_id: 83924
policy_version: checkpoint_120

task_family: constrained_pick_place

task_parameters:
  placement_tolerance: 0.012
  obstacle_count: 2
  transport_distance: 0.34

success: false

subgoals:
  grasp_object: true
  lift_object: true
  transport_object: true
  align_object: false
  place_object: false

failure:
  type: alignment_error
  stage: placement

metrics:
  collisions: 0
  grasp_losses: 0
  final_position_error: 0.021
  completion_fraction: 0.82
```

Store these records in a simple database.

You don't need anything exotic initially.

PostgreSQL/SQLite/Parquet would all work depending on scale.

---

# 3. Build the Evidence Engine

The Evidence Engine converts thousands of raw EpisodeRecords into useful statistics.

Think of it as:

```text
raw episodes
    ↓
aggregation
    ↓
evidence
```

For each capability/task region, calculate:

```text
success rate
attempt count
mean completion
failure distribution
mean goal error
collision rate
learning progress
evaluation performance
```

For example:

```yaml
precision_placement:
  attempts: 4218

  success_rate: 0.54
  previous_success_rate: 0.42

  learning_progress: +0.12

  failures:
    alignment_error: 0.61
    object_slip: 0.18
    timeout: 0.12
    collision: 0.09
```

### The important part: automatically classify failure

You already have the task graph.

So derive failure from the last successful predicate.

Example:

```text
grasp ✓
lift ✓
transport ✓
align ✗
place ✗
```

Therefore:

```text
failure_stage = alignment
```

Then inspect related events:

```text
large orientation residual
→ orientation_alignment

object dropped
→ grasp_stability

collision event
→ collision

timeout
→ horizon/control
```

I would build this as a deterministic rule system first.

No LLM.

---

# 4. Build the Capability Model

Now create a persistent table representing what the robot appears capable of.

Conceptually:

```python
CapabilityState {
    capability_id

    success_estimate
    confidence
    learning_progress

    failure_distribution

    last_evaluation_score
    regression_score

    sample_count
}
```

For example:

```yaml
capability: precision_placement

success_estimate: 0.58
confidence: 0.91

learning_progress: 0.11

sample_count: 4318

failure_distribution:
  alignment: 0.68
  grasp_loss: 0.14
  collision: 0.07

evaluation_score:
  current: 0.55
  previous: 0.48

regression_score: 0.0
```

### Don't just use raw percentage

Use a simple Bayesian estimate.

If the robot has:

```text
2 successes / 2 attempts
```

don't claim:

```text
100% capable
```

Whereas:

```text
920 successes / 1000 attempts
```

is strong evidence.

A Beta distribution is enough:

\[
p \sim \operatorname{Beta}(\alpha+s,\beta+f)
\]

where:

- \(s\) = successes
- \(f\) = failures

Then we get:

```text
estimated success
+
uncertainty
```

This gives the Advisor one of the most valuable signals: **what we don't know yet.**

---

# 5. Track capability combinations—but only when observed

We don't want the combinatorial explosion we discussed.

Do not generate every possible combination:

```text
grasp + transport
grasp + insertion
grasp + transport + precision
...
```

Instead create combination nodes only when real TaskSpecs exercise them frequently.

For example:

```text
grasp
transport
precision

grasp → transport
transport → precision
grasp → transport → precision
```

The capability graph grows from actual experience.

That keeps it sparse.

---

# 6. Partition task space into regions

The Advisor cannot reason about every unique numerical TaskSpec separately.

So discretize important parameters.

Example:

```text
placement tolerance

0–5 mm
5–10 mm
10–20 mm
20–40 mm
40+ mm
```

Transport:

```text
short
medium
long
```

Obstacle density:

```text
0
1–2
3–5
5+
```

Then a task-space region could be:

```yaml
family: constrained_pick_place

region:
  placement_tolerance: 10-20mm
  transport_distance: medium
  obstacle_count: 1-2
```

And that region gets statistics:

```yaml
success: 0.48
learning_progress: +0.13
confidence: 0.88
attempts: 931
```

You can later replace manual bins with something more continuous if needed.

I would not start there.

---

# 7. Build the Task-Space State classifier

Now classify each region.

Something like:

```python
if success > mastered_threshold and confidence > minimum_confidence:
    MASTERED

elif regression_detected:
    REGRESSING

elif learning_progress > progress_threshold:
    FRONTIER

elif attempts < minimum_samples:
    UNKNOWN

elif success_low and learning_progress_small:
    STALLED
```

Conceptually:

```text
MASTERED
high performance + confident

FRONTIER
not mastered + improving

UNKNOWN
insufficient evidence

STALLED
low performance + enough evidence + no progress

REGRESSING
previously better, now getting worse
```

Notice something important:

**There is no HARD state.**

Because "hard" tells us almost nothing.

A region could be:

```text
hard but learnable
→ FRONTIER

hard because impossible
→ STALLED

hard because we haven't tried it
→ UNKNOWN
```

Much more useful.

---

# 8. Build learning-progress measurement carefully

Don't compare individual episodes.

Too noisy.

Use rolling windows.

For example:

\[
LP(r)=P_{\text{recent}}(r)-P_{\text{previous}}(r)
\]

where:

```text
previous = episodes 101–200
recent   = episodes 201–300
```

Or exponentially weighted estimates.

Example:

```text
precision placement

previous success = 39%
recent success   = 57%

LP = +18%
```

Also calculate a minimum sample requirement before trusting it.

Otherwise:

```text
0/1 → 1/1
```

looks like gigantic learning progress.

---

# 9. Add fixed evaluation as a separate pipeline

Every N training cycles/checkpoints:

```text
checkpoint
    ↓
run frozen evaluation suite
    ↓
Capability Model
```

For example:

```text
eval/
├── grasp/
├── transport/
├── precision/
├── insertion/
├── obstacle_routing/
├── sequential/
└── compositional_generalization/
```

These tasks never change because of the Advisor.

That gives us:

```text
curriculum performance
vs
real benchmark performance
```

The architecture already identified fixed evaluation as a core requirement rather than relying solely on curriculum statistics. Pasted text

---

# 10. Build the Selection Policy

Now the Advisor actually makes decisions.

I would not train a model initially.

Use a transparent scheduler.

Something like:

\[
S(r)
=
w_p P(r)
+
w_u U(r)
+
w_c C(r)
+
w_r R(r)
\]

where:

```text
P = learning progress
U = uncertainty
C = capability/coverage gap
R = regression
```

Then apply state-specific behavior.

### FRONTIER

High priority.

```text
exploit learning opportunity
```

### UNKNOWN

Moderate exploration.

```text
collect enough evidence
```

### REGRESSING

Schedule retention tasks.

### MASTERED

Very low sampling.

### STALLED

Deprioritize.

Possibly ask the Generator for easier related tasks.

---

# 11. Allocate budgets, not individual tasks

This distinction is important.

The Advisor should output something like:

```yaml
training_allocation:

  learn:
    fraction: 0.65

  explore:
    fraction: 0.25

  retain:
    fraction: 0.10
```

Those numbers should eventually adapt, but fixed defaults are perfectly reasonable initially.

Then underneath:

```yaml
learn:
  regions:
    - precision_placement:
        tolerance: 8-20mm

    - constrained_transport:
        obstacle_count: 1-2

explore:
  capabilities:
    - object_rotation
    - insertion

retain:
  capabilities:
    - grasp_stability
```

The Task Generator decides how to instantiate that.

That preserves the clean separation between Advisor and Generator.

---

# 12. Define the Advisor → Generator contract

I'd make this an actual typed object.

Something approximately like:

```python
class ExplorationDirective:
    policy_version: str

    learn_targets: list[TargetRegion]
    explore_targets: list[CapabilityTarget]
    retain_targets: list[CapabilityTarget]

    exclusions: list[TaskConstraint]

    budget:
        learn: float
        explore: float
        retain: float
```

Example output:

```yaml
policy_version: checkpoint_120

learn:
  - capabilities:
      - precision_placement
      - sequencing

    parameters:
      placement_tolerance: [0.008, 0.020]
      sequence_length: [3, 4]

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
  - capability: basic_grasp
    reason: mastered
```

This becomes the formal interface.

---

# 13. Make Generator feedback part of the protocol

After the Generator receives the directive, it should return:

```yaml
directive_result:

  requested:
    precision_tasks: 100

  generated:
    precision_tasks: 87

  validated:
    precision_tasks: 52

  scheduled:
    precision_tasks: 48
```

Then after training:

```yaml
executed:
  episodes: 48000
```

This lets the Advisor know what actually happened.

Without this, the Advisor can say:

> explore insertion

while the Validator silently rejects 95% of insertion tasks.

The Advisor would incorrectly believe that insertion was explored.

---

# 14. Store everything historically

This matters enormously.

Maintain snapshots:

```text
checkpoint_001
    capability_state
    task_space_state
    directive

checkpoint_002
    capability_state
    task_space_state
    directive

checkpoint_003
...
```

Then we can answer:

```text
What changed?
Why did the Advisor choose these tasks?
Did that decision improve anything?
```

This is invaluable for debugging and research.

---

# 15. Eventually measure transfer

But don't complicate the first implementation.

Once the fixed evaluation suite exists, record:

```text
training block
      ↓
which capabilities were emphasized?
      ↓
change in evaluation
```

Example:

```yaml
training_block:
  focus:
    precision_placement: 0.62

evaluation_delta:
  precision_placement: +0.18
  insertion: +0.07
  unseen_pick_place: +0.09
```

Over many training blocks we start building empirical evidence of transfer.

Only then should we consider a learned transfer model.

---

# The codebase I would actually create

Something roughly like:

```text
task_advisor/
│
├── schemas/
│   ├── episode_record.py
│   ├── capability.py
│   ├── task_region.py
│   └── directive.py
│
├── evidence/
│   ├── aggregator.py
│   ├── failure_classifier.py
│   ├── progress_tracker.py
│   └── evaluation_ingestor.py
│
├── capability/
│   ├── ontology.py
│   ├── estimator.py
│   ├── combinations.py
│   └── regression.py
│
├── task_space/
│   ├── regionizer.py
│   ├── state_classifier.py
│   └── coverage.py
│
├── selection/
│   ├── priority.py
│   ├── budget_allocator.py
│   └── directive_builder.py
│
├── evaluation/
│   ├── benchmark_registry.py
│   └── evaluator.py
│
├── storage/
│   ├── episode_store.py
│   ├── capability_store.py
│   └── advisor_history.py
│
└── advisor.py
```

And `advisor.py` should actually be surprisingly small:

```python
def advise(policy_version):

    evidence = evidence_engine.aggregate(policy_version)

    capabilities = capability_model.update(evidence)

    task_space = task_space_model.update(
        capabilities,
        evidence,
    )

    priorities = selection_policy.rank(task_space)

    directive = directive_builder.build(priorities)

    save_advisor_state(
        policy_version,
        evidence,
        capabilities,
        task_space,
        directive,
    )

    return directive
```

That is a good sign.

**The central orchestrator should be simple because the complexity belongs in measurable components.**

---

# How the whole system operates

Once everything is connected:

```text
1. Generator creates TaskSpecs
          ↓
2. Compiler creates Isaac Lab environments
          ↓
3. Validator approves them
          ↓
4. Policy trains
          ↓
5. Episodes generate structured evidence
          ↓
6. Fixed evaluation runs periodically
          ↓
7. Evidence Engine aggregates results
          ↓
8. Capability Model updates robot competence
          ↓
9. Task-space regions become:
       mastered
       frontier
       stalled
       unknown
       regressing
          ↓
10. Selection Policy allocates training
          ↓
11. Advisor emits ExplorationDirective
          ↓
12. Generator creates the next curriculum
          ↓
                    ↺
```

That is the system I would actually implement.

The most important practical recommendation is **not to begin by coding the Advisor's priority equation**. Start with the data contract:

**`TaskSpec → EpisodeRecord → CapabilityState → ExplorationDirective`.**

If those four structures are well designed, the curriculum algorithm can evolve substantially without forcing you to rewrite the rest of the robotics platform.