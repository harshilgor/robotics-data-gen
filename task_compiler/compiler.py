"""Compile trusted TaskSpecs into versioned local environment configurations."""
from copy import deepcopy

from assets import local_resources
from semantics import default_registry
from taskgen.core import fingerprint, validate
from taskgen.parameters import domain

NOTICE = "SYNTHETIC CARTESIAN SURROGATE: not Isaac Lab, SO-101 physics or robot learning evidence"


class TaskCompiler:
    version = "local-compiler-1.0"

    def __init__(self, resources=None, semantics=None):
        self.resources = resources or local_resources()
        self.semantics = semantics or default_registry()

    def compile(self, task):
        report = validate(task)
        if not report.structurally_valid:
            raise ValueError("TaskSpec rejected: " + "; ".join(report.errors))
        # V1's hardcoded choices are resolved to exact resources, never imported
        # as task-provided Python or implicitly resolved to a latest version.
        objects = {}
        asset_versions = {entry["name"]: entry["version"] for entry in self.resources.snapshot()["entries"] if entry["kind"] == "asset"}
        for role, value in task["objects"].items():
            if "asset" in value:
                objects[role] = self.resources.get("asset", value["asset"], "1.0.0")
            else:
                matches = self.resources.resolve_role(value["requires"], versions=asset_versions)
                if not matches:
                    raise ValueError("no exact resource satisfies object role")
                objects[role] = matches[0]
        scene = self.resources.get("scene", task["scene"]["template"], "1.0.0")
        robot = self.resources.get("robot", "so101-surrogate", "1.0.0")
        observations = {}
        for prefix in ("eef", "object", "target"):
            for axis in "xyz":
                observations[prefix + "_" + axis] = {"type": "float", "bounds": [-.5, .5],
                    "units": "m", "coordinate_frame": "world"}
        observations.update(gripper_closed={"type": "categorical", "values": [False, True], "units": "1", "coordinate_frame": None},
                            held={"type": "categorical", "values": [False, True], "units": "1", "coordinate_frame": None},
                            stage={"type": "int", "bounds": [0, len(task["task_graph"])], "units": "index", "coordinate_frame": None})
        actions = {"delta_" + axis: {"type": "float", "bounds": [-.012, .012],
                    "units": "m", "coordinate_frame": "world"} for axis in "xyz"}
        actions["close_gripper"] = {"type": "categorical", "values": [False, True], "units": "1", "coordinate_frame": None}
        if task["schema_version"] == "1.2":
            observations.update(orientation_error={"type": "float", "bounds": [0., 4.], "units": "rad", "coordinate_frame": "object"},
                                drawer_open_fraction={"type": "float", "bounds": [0., 1.], "units": "1", "coordinate_frame": None})
            actions.update(delta_angle={"type": "float", "bounds": [-.12, .12], "units": "rad", "coordinate_frame": "object"},
                           drawer_delta={"type": "float", "bounds": [0., .1], "units": "1", "coordinate_frame": None})
        configuration = {"schema_version": "compiled-task-1.0", "compiler_version": self.version,
            "task_hash": fingerprint(task), "task": deepcopy(task), "notice": NOTICE,
            "scene": scene, "objects": objects, "robot": robot,
            "semantic_registry": self.semantics.snapshot(), "resource_registry_digest": self.resources.snapshot()["digest"],
            "initial_state_sampling": "tabletop-layout-1.0", "reference_plan": deepcopy(task["task_graph"]),
            "success": deepcopy(task["success"]), "termination": ["success", "timeout", "workspace_violation"],
            "rewards": deepcopy(task["reward"]),
            "trajectory_schema": {"schema_id": "local-cartesian-trajectory-1.0", "observations": observations, "actions": actions},
            "observation_schema_id": task["interfaces"]["observation"], "action_schema_id": task["interfaces"]["action"]}
        configuration["compiled_id"] = fingerprint(configuration)
        return configuration

    def contract(self, task, compiled, validation_evidence, *, controller="local-reference@1.0"):
        if compiled != self.compile(task):
            raise ValueError("compiled artifact does not match pinned inputs")
        units = {"target_distance": "m", "tolerance": "m", "object_size": "m", "mass": "kg", "friction": "1"}
        schema = {}
        for group in ("theta", "phi"):
            for name, value in task[group].items():
                if name not in units:
                    raise ValueError("compiler has no declared application binding for parameter: " + name)
                schema[name] = {**deepcopy(domain(value)), "name": name, "units": units[name],
                    "coordinate_frame": "world" if units[name] == "m" else None,
                    "spatial": units[name] == "m", "sampling_role": group,
                    "application_stage": "build" if name in ("object_size", "mass", "friction") else "reset",
                    "dependencies": []}
        from semantics.capabilities import capabilities_for
        return {"schema_version": "2.0", "family_id": fingerprint(task), "family_version": task["revision"],
            "status": "active", "capability_tags": capabilities_for(task),
            "supported_embodiments": [task["embodiment"]], "supported_controller_references": [controller],
            "parameter_schema": schema, "constraints": [],
            "geometry_checks": [{"id": "local-geometry-1.0", "dependencies": sorted(schema)}],
            "validation_policy": {"mode": "always", "validator_id": "local-validator-1.0"},
            "instance_constructor_id": "local-instance-1.0", "compiled_artifact_reference": compiled["compiled_id"],
            "compiled_artifact_hash": fingerprint(compiled), "execution_compatibility_key": fingerprint([compiled["scene"], compiled["objects"], compiled["trajectory_schema"]]),
            "robot_configuration": compiled["robot"], "actuator_configuration": {"mode": "cartesian_delta", "dt": .02},
            "sensor_configuration": {"policy_state": "local-cartesian-state-1.0", "privileged": "separate"},
            "observation_schema_id": compiled["observation_schema_id"], "action_schema_id": compiled["action_schema_id"],
            "success_predicate_version": "measured-tabletop-1.0", "reward_version": "trusted-progress-1.0",
            "compiler_version": self.version, "validation_evidence": deepcopy(validation_evidence),
            "trajectory_schema": deepcopy(compiled["trajectory_schema"]),
            "demonstration_quality": {"max_collisions": 0, "max_step_seconds": .021}}
