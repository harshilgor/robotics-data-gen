# Measured episode instrumentation

`task_advisor/instrumentation.py` binds the existing sequential TaskSpec to
measured predicates and emits the existing Advisor episode contract. It does
not construct a simulator scene or supply robot controllers.

## Interfaces

1. A scene compiler/physical validator supplies the exact generated instance and
   separate evidence identifying its family hash, instance hash, validator and
   simulator versions, and report ID. Kinematics, collision feasibility, physics,
   and reset stability must each pass explicitly. Generator validation cannot
   substitute for this evidence. The evidence is a trusted external attestation;
   this package does not independently establish feasibility or learnability.
2. `compile_instrumentation(task, instance, evidence)` creates versioned bindings
   and validates sampled parameter ranges. Lift height is configurable in metres.
   Bindings refer to the manipulated object and target in the validated TaskSpec.
3. A `SimulatorAdapter.frame(environment_id)` returns a post-action frame before
   automatic reset. Required fields: episode_id, contiguous integer step,
   increasing sim_time, timezone-aware timestamp, reward, eef_object_distance,
   object_target_distance, height_above_reset, object_speed, grasp_contact,
   gripper_closed, target_support, collision, terminated and truncated.
   Distances/heights are metres, speed metres/second, time seconds. Contact,
   support and collision flags must come from the simulator's measured state;
   action commands and symbolic effects are not evidence. `collision` represents
   unwanted contacts, excluding expected grasp/table/target support contacts.
4. `EpisodeTracker.observe(frame)` evaluates reach, grasp, lift, transport/push
   and release predicates, tracking one sequential stage per frame. Reached but
   incomplete stages are false; unreached stages remain null. Completed stages
   latch as achievements, but terminal success also requires the current goal
   predicate. High rewards do not establish success. Release requires target
   support and object speed <= 0.01 m/s. These are initial operational definitions,
   to be calibrated against real scenes rather than claimed universal detectors.
5. `InstrumentedEnvironments` routes each environment independently and records
   terminal state before permitting its next episode. `StoreRecorder` writes
   annotations and episodes atomically through existing SQLite storage. Recorder
   failures preserve the terminal record for retry. The simulator's reset should
   happen only after successful recording; auto-reset adapters must capture the
   terminal frame explicitly and supply it instead of the reset observation.

Example wiring (requires a real compiler, validator and simulator adapter):

```python
from task_advisor.instrumentation import (
    compile_instrumentation, EpisodeTracker, InstrumentedEnvironments, StoreRecorder,
)
from task_advisor.storage import Store

store = Store("episodes.sqlite3")
compiled = compile_instrumentation(task, instance, physical_report)
bridge = InstrumentedEnvironments(StoreRecorder(store))
bridge.start("env0", EpisodeTracker(compiled, episode_id="run1-env0-episode0",
                                    policy_version="checkpoint_001"))
# Call after each physics/control step, before reset:
record = bridge.step("env0", simulator_adapter)
if record is not None:
    pass  # reset env0 and start a new tracker with a new episode ID
store.close()
```

Episode records retain bindings, validation provenance, randomization, seed,
termination flags and measured frames for inspection. Collision counts measure
contact onsets, not every contact timestep. Grasp losses measure held-to-unheld
transitions outside the release stage. These event summaries do not prove causal
failure attribution. For high-throughput production, move frame payloads to
trajectory shards and retain their immutable references in the episode record.

## Verification and remaining work

Run `python -m unittest discover -s tests -v`. Synthetic measured frames test
compiler binding, exact-instance approval gates, successful and failed episodes,
stage attribution, terminal-goal loss, edge-counted events, invalid frames,
environment isolation, recorder retries and SQLite-to-Advisor ingestion.

No Isaac Lab runtime, SO-101 scene compiler or physical validator is currently
implemented in this project. Connecting those concrete implementations and
validating predicates against actual simulated rollouts remains required before
claiming real simulator instrumentation is operational. Fixture physical reports
in tests are explicitly synthetic and never production approval.
