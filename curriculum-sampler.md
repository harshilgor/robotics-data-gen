Curriculum Sampler — Architecture and Implementation Brief
Objective
Build a curriculum sampler that converts the Task Advisor’s allocations into concrete, valid episode assignments drawn from the Task Family Library.
The sampler must support three purposes:
- Training: episodes executed by the current policy.
- Demonstration generation: episodes executed by a reference controller, planner, or teleoperator.
- Evaluation: episodes executed by a frozen policy checkpoint against a controlled evaluation distribution.
The implementation must be complete across contracts, persistence, validation, worker assignment, and feedback. These responsibilities can be implemented as modules within the existing application; they do not require separate services.
1. Position in the architecture
The Task Family Library stores approved, versioned families and their compiled execution artifacts.
The Task Advisor decides which capabilities and regions deserve practice. The sampler chooses concrete instances within those allocations. The scheduler routes assignments to compatible simulator workers.
Episode results return to the Evidence Engine, which supplies measurements to the Advisor.
Component	Owns
Task Family Library	Family definitions, versions, parameter schemas, constraints, execution artifacts, approval status
Task Advisor	Strategic allocations, target regions, exclusions, evidence interpretation
Curriculum Sampler	Concrete parameter selection, diversity, instance checks, reproducible assignments
Scheduler	Worker compatibility, capacity, assignment delivery
Simulator adapter	Applying assignments and handling episode lifecycle
Controller	Producing robot actions
Recorder	Capturing trajectories and outcomes
Evidence Engine	Measuring capability, progress, uncertainty, and regressions


Do not duplicate the Advisor’s capability inference inside the sampler.
2. Task Family Library contract
Each approved family version must expose a sampling contract:
TaskFamilyVersion
  family_id
  family_version
  status
  capability_tags
  supported_embodiments

  parameter_schema
  constraints
  instance_constructor_id

  compiled_artifact_reference
  compiled_artifact_hash
  execution_compatibility_key

  observation_schema_id
  action_schema_id
  success_predicate_version
  reward_version

  validation_evidence
  supported_controller_references

Family versions must be immutable once published. Changing parameters, constraints, reward behavior, or execution artifacts creates a new version.
Assignments must reference an exact version and artifact hash. They must never resolve implicitly to “the latest family.”
The library must expose:
get_family(family_id, family_version)
list_eligible_families(filters)
get_sampling_contract(family_id, family_version)
get_compiled_artifact(reference)

The sampler reads these contracts. It does not rewrite families or generate simulator code.
3. Parameter definitions and application lifecycle
Each parameter must declare:
name
type
units
coordinate_frame, when applicable
allowed_values_or_bounds
sampling_role
application_stage
dependencies

sampling_role distinguishes task variation from environment variation. application_stage describes when the simulator can apply it:
Stage	Meaning
Build	Requires worker initialization or environment rebuild
Reset	Can change between episodes through a supported reset operation
Step	Can change during execution through a supported runtime operation


Classify parameters according to the pinned Isaac Lab/Sim integration. Do not assume mass, friction, geometry, or sensors can change safely at every reset.
Dependencies must express joint constraints. For example, independently valid object sizes and corridor widths may produce an invalid combination.
Use approved, typed constraint functions and instance constructors. Do not execute arbitrary expressions from generated task descriptions.
4. Advisor-to-sampler directive
Define a versioned directive:
CurriculumDirective
  directive_id
  directive_version
  policy_checkpoint_id
  embodiment_id
  episode_purpose

  total_episode_budget
  category_allocations
  family_region_allocations

  exclusions
  minimum_coverage_requirements
  allowed_fallbacks

  recording_profile
  seed
  expiry_or_training_boundary

Categories are:
- LEARN: practice in regions identified as useful learning opportunities.
- EXPLORE: gather evidence in eligible regions with insufficient coverage.
- RETAIN: maintain learned capabilities and investigate regressions.
The Advisor owns these allocations. The sampler may fulfill them within declared constraints, but must not silently replace them with its own strategy.
Reject malformed directives, contradictory exclusions, incompatible controller requests, and budgets that cannot be interpreted.
5. Parameter-region representation
Represent regions using a family version and explicit parameter restrictions:
TaskRegion
  region_id
  region_version
  family_id
  family_version
  parameter_restrictions
  categorical_filters

Start with bounded intervals, categorical subsets, and family constraints.
Avoid constructing a full Cartesian grid across every parameter: its size grows rapidly and most cells may receive little evidence.
Regions may overlap. Every assignment must retain its originating region and actual parameter values so analysis does not confuse allocation membership with physical task identity.
The sampler consumes region definitions; the Advisor and Evidence Engine own their interpretation and revision.
6. Episode assignment contract
Sampling produces an immutable assignment:
EpisodeAssignment
  assignment_id
  sampling_request_id

  directive_id
  directive_version
  category
  episode_purpose

  family_id
  family_version
  region_id
  compiled_artifact_hash
  execution_compatibility_key

  embodiment_id
  controller_id
  controller_version
  policy_checkpoint_id, when applicable

  task_parameters
  environment_parameters
  initial_state_specification
  goal_specification

  observation_schema_id
  action_schema_id
  recording_profile

  sampling_seed
  validation_result

Distinguish the specification from the realized simulator state. The worker must record the actual initial state and applied parameters after reset.
A seed helps repeat sampling, but does not by itself guarantee identical simulation across hardware and software versions.
7. Sampling algorithm
Implement batch sampling in this order:
1. Resolve and validate the directive.
2. Load eligible, exact family versions.
3. Convert category allocations into integer episode quotas.
4. Allocate quotas across requested family regions.
5. Select compatible build-time configurations.
6. Generate concrete parameters through the family’s instance constructor.
7. Apply cheap instance checks.
8. Persist accepted assignments and sampling diagnostics.
9. Return assignments grouped by execution compatibility.
Use deterministic quota rounding with a documented tie-breaking rule.
Within continuous regions, use stratified sampling across selected important dimensions. Use balanced selection for categorical parameters when requested.
Avoid enforcing exact uniqueness across every task. Controlled repetition is useful for learning and evaluation. Instead, prevent accidental duplicates where the directive requests diversity.
Sampling must be reproducible from the directive, library versions, algorithm version, and seed.
8. Validation and fallback behavior
Every instance must pass inexpensive checks such as:
- Parameter types, bounds, and dependencies.
- Workspace constraints.
- Family-specific geometry checks.
- Compatible observation/action schemas.
- Supported assets and controller.
- Initial-state constraints.
Expensive feasibility checks should be invoked according to the family’s validation policy, particularly for configurations outside previously supported evidence.
Store separate results for:
instantiation_validity
geometric_or_kinematic_checks
reference_controller_evidence
feasibility_status

A reference-controller failure must not automatically classify a task as impossible.
Use bounded candidate attempts. When a requested quota cannot be fulfilled:
1. Record the rejection reasons and unfulfilled quantity.
2. Apply only an explicitly allowed fallback.
3. Record fallback assignments separately.
4. Return the remaining shortfall.
Do not widen parameter ranges or substitute easier regions without recording the change.
9. Scheduler and simulator integration
The sampler returns assignments; it does not step physics.
The scheduler groups assignments by a compatibility key covering the structural requirements of execution, including:
- Compiled scene and asset configuration.
- Robot and actuator configuration.
- Observation/action interfaces.
- Required sensors.
- Build-time parameter choices.
Different task families may share a worker pool when their compiled implementations support it.
The simulator adapter must:
1. Install an assignment before the corresponding reset.
2. Apply supported reset-time parameters.
3. Initialize robot/object states and goal buffers.
4. Capture realized initial state and applied parameters.
5. Execute the selected controller through the environment’s action interface.
6. Capture final outcomes before automatic reset.
7. Finalize the episode record.
8. Install the next assignment.
Parallel environments need independent assignment identities and episode counters. Resetting one environment must not change another environment’s goal or metadata.
Do not reseed a global random generator on every individual environment reset. Use controlled sampling streams so asynchronous reset order does not unintentionally change assignments.
10. Output contracts
Every completed episode produces a lightweight summary:
EpisodeSummary
  episode_id
  assignment_id
  execution_attempt_id

  controller_or_policy_version
  simulator_and_environment_versions

  realized_parameters
  initial_state_reference

  success
  termination_reason
  elapsed_simulation_time
  control_step_count
  reward_summary
  stage_outcomes

  execution_status
  recording_status
  trajectory_reference, when recorded

Execution failures, validation rejections, timeouts, and policy failures must remain distinguishable.
Full trajectories are optional according to the recording profile. When recorded, they must preserve observation/action timing, terminal boundaries, units, frames, and interface schemas.
Keep privileged simulator state separate from policy-visible observations.
Reference-controller results and policy results must remain distinguishable throughout storage and analysis.
11. Assignment persistence and execution reliability
Use the existing database and job infrastructure where available.
Maintain an assignment lifecycle:
pending → leased → running → completed

Also support cancellation and failed/expired attempts.
An assignment may have multiple execution attempts after worker failure. Each attempt needs its own identity. Completion handling must be idempotent, and evidence aggregation must have an explicit policy for retries so they do not accidentally inflate coverage.
Workers must renew leases or otherwise report liveness. Interrupted episodes must be marked incomplete, not reported as ordinary policy failures.
Freeze the active directive for a defined training window. New directives apply to future assignments; cancellation of pending work must be explicit.
12. Evaluation and demonstration rules
Evaluation uses a versioned manifest of fixed task specifications or a fixed sampling distribution, independent of adaptive training allocations.
Use separate evaluation randomness and held-out instances. Keep evaluation trajectories out of training datasets unless an explicit dataset policy changes that separation.
Demonstration generation must apply quality checks beyond success, including valid observations, action limits, timing, and applicable physical constraints.
Always retain episode summaries even when trajectories are rejected from the imitation dataset.
13. Observability
Report these quantities by directive, category, family, and region:
- Requested assignments.
- Generated candidates.
- Validation rejections and reasons.
- Accepted assignments.
- Scheduled and executed assignments.
- Completed and interrupted episodes.
- Fallback usage and budget shortfalls.
- Actual parameter distributions.
- Sampling latency and worker waiting time.
This makes it possible to detect when the intended curriculum differs from what the robot actually practiced.
14. Verification and acceptance criteria
The implementation is complete when:
- Exact family versions resolve to compatible execution artifacts.
- Sampling fulfills valid quotas or returns explicit shortfalls.
- Constraint-aware construction prevents invalid parameter combinations.
- Identical sampling inputs reproduce identical assignments.
- Multiple simulator environments retain independent goals and episode identities.
- Terminal data is captured before reset.
- Worker retries do not duplicate evidence accidentally.
- Controller provenance distinguishes demonstrations, training, and evaluation.
- Requested and executed distributions can be compared.
- A recorded episode can be traced back to its directive, family, parameters, controller, and software versions.
Test these behaviors with meaningful constraint, lifecycle, and integration tests. Include an end-to-end smoke run using at least two approved families, multiple parallel environments, one worker interruption, and recorded outputs.
Implementation guidance for the coding agent
Inspect the existing Task Library, Advisor contracts, simulator integration, and persistence first. Extend existing abstractions where they already express these responsibilities.
Build the sampler as a policy-independent orchestration module, with family-specific construction behind registered interfaces. Keep parameter selection outside the physics stepping loop and prepare bounded batches ahead of execution.
Do not add a learned sampling model, an LLM sampling loop, or a separate distributed service without a demonstrated requirement. The required intelligence already comes from the Advisor; the sampler’s value comes from faithfully producing valid, diverse, measurable practice.