# Optional deployment bindings

The local factory needs no external service. Import deployment modules only in
the deployment using their optional packages: `numpy` (DLS), `torch`/Isaac Lab
and Isaac Sim, `lerobot`, `psycopg[binary]`, or `boto3` as appropriate. Nothing
here installs packages, downloads USD assets, launches a paid worker, provisions
a bucket/database, or changes credentials.

`SO101Config` requires an existing versioned USD file, six ordered joint names,
calibrated limits/home, actuator settings and a unique end-effector body. The
compiled plan pins USD SHA-256 and API major/minor (2.1, 2.2 or 2.3); a mismatch
fails. Supply independently pinned articulated drawer assets through
`IsaacLabCompiler(..., articulated_assets={role: {...}})`; its constructor lists
all mandatory joint/actuator fields. Scene geometry, obstacles, interior walls,
mass/friction, parallel environment offsets and contact sensors are created via
real Isaac APIs. Unsupported physical variation is rejected explicitly.

Launch Isaac's `AppLauncher` before calling `instantiate(plan)`. Runtime reset
and `step(joint_targets, articulation_targets=...)` write actual joint state and
return measured joint/object/contact telemetry. `step_cartesian` uses actual
PhysX Jacobians and damped least squares for xyz translation, bounds the five
arm joints, commands the configured gripper target, and returns residual evidence
and measured end-effector positions. It does not promise arbitrary orientation
control, calibrated contact attribution or task solvability.

**This low-level runtime is not a full governed task-worker adapter.** Physical
assignments must have their own validation context and controller/action schema;
never attach synthetic approvals to real execution. Full task telemetry,
reference-plan governance and terminal recording through `ExecutionAdapter`
remain software work, followed by GPU validation.

`SO101Transport` requires `authorized=True` before creating/connecting the
LeRobot follower or sending an action. Values use the configured follower's
calibrated units; callers supply corresponding limits. It does not calibrate or
write credentials. Its transport is not a certified physical task executor.

`LocalFactory(root, postgres_dsn=...)` uses the optional existing-server store;
CLI `--postgres-dsn-env NAME` reads a supplied DSN. The live integration test
uses `ROBOTICS_TEST_POSTGRES_DSN`. No server binary was available here.
`data.s3.S3ObjectStore` uses an existing bucket/client and requires explicit
`allow_external_writes=True`; pass it as `payload_store` to `LocalFactory`.
Content-addressed uploads use conditional creation, and every read checks size
and digest. Deterministic fake transport tests do not establish live S3 behavior.

`taskgen.proposals.HostedProposalProvider` accepts an HTTPS endpoint, model,
credential environment-variable name and explicit inference opt-in. Its default
refuses inference before network/credential access. Supply it to `TaskDiscovery`;
fixtures run the same grammar/parameter checks. Never enable inference without
authorization for its cost. No hosted request was sent during this work.

API references used for bindings:
- https://isaac-sim.github.io/IsaacLab/v2.2.0/source/tutorials/01_assets/run_articulation.html
- https://isaac-sim.github.io/IsaacLab/v2.1.0/source/how-to/write_articulation_cfg.html
- https://huggingface.co/docs/lerobot/so101
