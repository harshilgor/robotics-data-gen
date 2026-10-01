"""A measured, action-driven Cartesian surrogate for exercising factory software.

It models point motion, simple contact/grasp and tabletop support. It is explicitly
not an SO-101 dynamics model and provides no robot feasibility guarantees.
"""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import math
import random

from taskgen.core import fingerprint
from taskgen.parameters import check_values
from task_advisor.instrumentation import measured_predicates


class LocalSimulationAdapter:
    simulator_version = "local-cartesian-simulator-1.0"
    environment_version = "local-tabletop-1.0"
    software_versions = {"adapter": "local-measured-adapter-1.0", "controller": "local-stage-controller-1.0"}

    def __init__(self, *, policies=None):
        self.environments = {}
        self.configurations = {}
        self.policies = deepcopy(policies or {})
        self.events = []

    def configure(self, environment_id, artifact, compatibility_key, build_parameters):
        content = deepcopy(artifact)
        claimed = content.pop("compiled_id", None)
        if claimed != fingerprint(content) or artifact.get("schema_version") != "compiled-task-1.0":
            raise ValueError("invalid compiled artifact digest/schema")
        if artifact["robot"]["definition"]["runtime"] != "synthetic-cartesian":
            raise ValueError("unsupported robot runtime")
        if artifact["action_schema_id"] != "local_cartesian_delta_v1":
            raise ValueError("Cartesian runtime cannot execute joint-target action interfaces")
        self.configurations[environment_id] = {"artifact": deepcopy(artifact), "key": compatibility_key,
                                              "build_parameters": deepcopy(build_parameters)}
        self.events.append([environment_id, "configure", compatibility_key])

    def install(self, environment_id, assignment, episode_id):
        if environment_id in self.environments:
            raise ValueError("terminal capture/finalization required before installing next assignment")
        configuration = self.configurations[environment_id]
        if fingerprint(configuration["artifact"]) != assignment["compiled_artifact_hash"]:
            raise ValueError("assignment compiled artifact mismatch")
        self.environments[environment_id] = {"assignment": deepcopy(assignment), "episode_id": episode_id,
            "parameters": deepcopy(configuration["build_parameters"]), "step": 0, "stage": 0, "closed": False}
        self.events.append([environment_id, "install", assignment["assignment_id"]])

    def apply_reset(self, environment_id, parameters):
        self.environments[environment_id]["parameters"].update(deepcopy(parameters))

    def reset(self, environment_id, initial_state, goal):
        environment = self.environments[environment_id]
        assignment = environment["assignment"]
        parameters = environment["parameters"]
        expected = {**assignment["task_parameters"], **assignment["environment_parameters"]}
        if parameters != expected:
            raise ValueError("runtime parameter application does not match assignment")
        rng = random.Random(assignment["sampling_seed"])
        radius = parameters["object_size"] / 2
        object_position = [.08 + rng.uniform(-.005, .005), rng.uniform(-.005, .005), radius]
        target_position = [object_position[0] + parameters["target_distance"], object_position[1], radius]
        environment.update(eef=[0., 0., radius], object=object_position, target=target_position,
                           reset_height=radius, held=False, gripper_closed=False, collision=False, speed=0., terminal=False)
        artifact = self.configurations[environment_id]["artifact"]
        task = artifact["task"]
        environment["role_positions"] = {}
        for index, role in enumerate(task["objects"]):
            manipulated = any(node["object"] == role for node in task["task_graph"])
            environment["role_positions"][role] = ([object_position[0], object_position[1] + .03*index, radius]
                                                 if manipulated else deepcopy(target_position))
        environment.update(orientation_error=.4 if task["schema_version"] == "1.2" else 0.,
                           drawer_open_fraction=0., insertion_depth=0., clearance=.1, obstacle_seen=False,
                           transported_above=False)
        environment["role_orientations"] = {role: .4 for role in task["objects"]}
        environment["role_openings"] = {role: 0. for role in task["objects"]}
        self._bind_roles(environment_id)
        environment["initial_state"] = {"eef_position": deepcopy(environment["eef"]),
            "object_position": deepcopy(object_position), "target_position": deepcopy(target_position),
            "requested_initial_state": deepcopy(initial_state), "requested_goal": deepcopy(goal),
            "role_positions": deepcopy(environment["role_positions"]), "evidence_label": "synthetic-cartesian"}
        self.events.append([environment_id, "reset"])
        return self.capture_initial(environment_id)

    def apply_step(self, environment_id, parameters):
        if parameters:
            raise ValueError("local runtime declares no step-stage parameters")

    def capture_initial(self, environment_id):
        environment = self.environments[environment_id]
        return {"initial_state": deepcopy(environment["initial_state"]),
                "realized_parameters": deepcopy(environment["parameters"])}

    def observations(self, environment_id):
        environment = self.environments[environment_id]
        self._bind_roles(environment_id)
        result = {prefix + "_" + axis: environment[key][i]
                  for prefix, key in (("eef", "eef"), ("object", "object"), ("target", "target"))
                  for i, axis in enumerate("xyz")}
        result.update(gripper_closed=environment["gripper_closed"], held=environment["held"], stage=environment["stage"])
        if self.configurations[environment_id]["artifact"]["task"]["schema_version"] == "1.2":
            result.update(orientation_error=environment["orientation_error"], drawer_open_fraction=environment["drawer_open_fraction"])
        return result

    def _bind_roles(self, environment_id):
        environment = self.environments[environment_id]
        graph = self.configurations[environment_id]["artifact"]["task"]["task_graph"]
        node = graph[min(environment["stage"], len(graph)-1)]
        environment["object"] = environment["role_positions"][node["object"]]
        environment["target"] = environment["role_positions"][node["target"]]
        environment["orientation_error"] = environment["role_orientations"][node["object"]]
        environment["drawer_open_fraction"] = environment["role_openings"][node["object"]]
        environment["support_height"] = environment["reset_height"]
        if any(n["skill"] == "stack" and n["object"] == node["object"] for n in graph):
            environment["target"] = deepcopy(environment["target"])
            environment["target"][2] += environment["parameters"]["object_size"]
            environment["support_height"] = environment["target"][2]

    def controller_action(self, environment_id, observations, controller):
        environment = self.environments[environment_id]
        artifact = self.configurations[environment_id]["artifact"]
        if controller["id"] != "local-reference":
            raise ValueError("unknown controller")
        policy = self.policies.get(controller.get("policy_checkpoint_id"), {"gain": .008})
        gain = policy["gain"]
        if not isinstance(gain, (int, float)) or not math.isfinite(gain) or not 0 <= gain <= .012:
            raise ValueError("invalid policy action gain")
        graph = artifact["task"]["task_graph"]
        skill = graph[min(environment["stage"], len(graph)-1)]["skill"]
        eef = [observations["eef_" + a] for a in "xyz"]
        obj = [observations["object_" + a] for a in "xyz"]
        target = [observations["target_" + a] for a in "xyz"]
        close = observations["gripper_closed"]
        if skill == "reach":
            desired, close = obj, False
        elif skill == "grasp":
            desired, close = obj, True
        elif skill == "lift":
            desired, close = [obj[0], obj[1], environment["reset_height"] + .025], True
        elif skill in ("transport", "align", "insert"):
            desired, close = target, True
            if skill == "insert":
                desired = [target[0], target[1], target[2]-.012]
        elif skill in ("release", "stack"):
            desired, close = target, False
        elif skill == "rotate":
            desired, close = obj, True
        elif skill == "articulate":
            desired, close = obj, False
        elif skill == "obstacle_transport":
            safe_height = environment["reset_height"] + .07
            if not environment["transported_above"] and obj[2] < safe_height-.002:
                desired = [obj[0], obj[1], safe_height]
            elif abs(obj[0]-target[0]) > .001:
                environment["transported_above"] = True
                desired = [target[0], target[1], safe_height]
            else:
                desired = target
            close = True
        elif skill == "push":
            # Keep the end effector in contact while translating along the table.
            desired, close = target, False
        else:
            raise ValueError("compiled reference skill lacks controller")
        differences = [b-a for a, b in zip(eef, desired)]
        distance = math.sqrt(sum(v*v for v in differences))
        scale = min(1., gain/distance) if distance else 0.
        result = {**{"delta_" + axis: differences[i]*scale for i, axis in enumerate("xyz")}, "close_gripper": close}
        if artifact["task"]["schema_version"] == "1.2":
            result.update(delta_angle=-min(.1, observations["orientation_error"]) if skill in ("rotate", "align") else 0.,
                          drawer_delta=.1 if skill == "articulate" and math.dist(eef, obj) <= environment["parameters"]["tolerance"] else 0.)
        return result

    def step(self, environment_id, action):
        environment = self.environments[environment_id]
        self._bind_roles(environment_id)
        if environment["terminal"]:
            raise ValueError("terminal state must be recorded before reset")
        artifact = self.configurations[environment_id]["artifact"]
        check_values(artifact["trajectory_schema"]["actions"], action)
        old_object = deepcopy(environment["object"])
        old_eef = deepcopy(environment["eef"])
        environment["eef"] = [value + action["delta_" + axis] for value, axis in zip(old_eef, "xyz")]
        environment["gripper_closed"] = action["close_gripper"]
        tolerance = environment["parameters"]["tolerance"]
        graph = artifact["task"]["task_graph"]
        skill = graph[min(environment["stage"], len(graph)-1)]["skill"]
        if artifact["task"]["schema_version"] == "1.2":
            if environment["held"] and skill in ("rotate", "align"):
                environment["orientation_error"] = max(0., environment["orientation_error"] + action["delta_angle"])
            if skill == "articulate" and math.dist(environment["eef"], environment["object"]) <= tolerance:
                environment["drawer_open_fraction"] = max(0., min(1., environment["drawer_open_fraction"] + action["drawer_delta"]))
            role = graph[min(environment["stage"], len(graph)-1)]["object"]
            environment["role_orientations"][role] = environment["orientation_error"]
            environment["role_openings"][role] = environment["drawer_open_fraction"]
        contact = math.dist(environment["eef"], environment["object"]) <= min(tolerance, .01)
        if environment["gripper_closed"] and contact:
            environment["held"] = True
        if not environment["gripper_closed"]:
            environment["held"] = False
        if environment["held"]:
            environment["object"] = deepcopy(environment["eef"])
        elif skill == "push" and math.dist(old_eef, old_object) <= tolerance + .001:
            environment["object"] = [old_object[i] + action["delta_" + axis] for i, axis in enumerate("xyz")]
        if not environment["held"]:
            at_support = math.dist(environment["object"][:2], environment["target"][:2]) <= tolerance
            environment["object"][2] = environment["support_height"] if at_support else environment["reset_height"]
        node = graph[min(environment["stage"], len(graph)-1)]
        environment["role_positions"][node["object"]] = environment["object"]
        environment["insertion_depth"] = max(0., environment["target"][2] - environment["object"][2])
        environment["speed"] = math.dist(old_object, environment["object"]) / .02
        environment["collision"] = any(math.sqrt(sum(v*v for v in environment[k])) > .35 for k in ("eef", "object"))
        if artifact["task"]["scene"]["template"] == "tabletop_obstacles":
            # One deterministic raised obstacle; clearance is measured from the
            # surrogate's current object position, rather than a success flag.
            center = [environment["initial_state"]["object_position"][0] + environment["parameters"]["target_distance"]/2,
                      environment["target"][1], environment["reset_height"]]
            environment["clearance"] = math.dist(environment["object"], center) - .025
            if environment["clearance"] < 0:
                environment["collision"] = True
        environment["step"] += 1
        frame = self._frame(environment_id)
        predicates = measured_predicates(frame, tolerance, .02)
        mapping = {"reach": "near", "grasp": "held", "lift": "lifted", "transport": "at_target", "release": "placed", "push": "at_target"}
        if artifact["task"]["schema_version"] == "1.2":
            mapping = {name: definition["measured_predicate"] for name, definition in
                       artifact["semantic_registry"]["definitions"]["execution_skill"].items()}
        if environment["stage"] < len(graph) and predicates[mapping[skill]]:
            environment["stage"] += 1
        success = environment["stage"] == len(graph) and predicates[artifact["task"]["success"]["predicate"]]
        timeout = environment["step"] >= artifact["task"]["horizon"]
        environment["terminal"] = success or timeout or environment["collision"]
        frame.update(terminated=bool(success or environment["collision"]), truncated=bool(timeout and not success))
        previous_error = math.dist(old_object, environment["target"])
        terms = {"progress": previous_error - frame["object_target_distance"], "time": .02, "collision": float(environment["collision"])}
        frame["reward"] = sum(term["weight"] * terms[term["term"]] for term in artifact["task"]["reward"])
        self.events.append([environment_id, "pre_reset_frame", environment["step"]])
        from .camera import capture
        return {"frame": frame, "next_observations": self.observations(environment_id),
            "modalities": capture(environment, environment["assignment"].get("recording_profile", {}).get("modalities", []), frame["sim_time"]),
            "privileged_state": {"contact": contact, "synthetic_model": "cartesian-point-1.0"}}

    def _frame(self, environment_id):
        environment = self.environments[environment_id]
        timestamp = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(seconds=environment["step"] * .02)
        frame = {"episode_id": environment["episode_id"], "step": environment["step"], "sim_time": environment["step"]*.02,
            "timestamp": timestamp.isoformat(), "reward": 0.,
            "eef_object_distance": math.dist(environment["eef"], environment["object"]),
            "object_target_distance": math.dist(environment["object"], environment["target"]),
            "height_above_reset": environment["object"][2] - environment["reset_height"],
            "object_speed": environment["speed"], "grasp_contact": environment["held"],
            "gripper_closed": environment["gripper_closed"],
            "target_support": abs(environment["object"][2]-environment["support_height"]) < 1e-9,
            "collision": environment["collision"], "terminated": False, "truncated": False}
        if self.configurations[environment_id]["artifact"]["task"]["schema_version"] == "1.2":
            frame["extended_measurements"] = {"orientation_error": environment["orientation_error"],
                "insertion_depth": environment["insertion_depth"], "required_insertion_depth": .01,
                "drawer_open_fraction": environment["drawer_open_fraction"],
                "obstacle_clearance": max(0., environment["clearance"]),
                "stack_support": frame["target_support"]}
        return frame

    def policy_digest(self, environment_id):
        checkpoint = self.environments[environment_id]["assignment"].get("policy_checkpoint_id")
        policy = self.policies.get(checkpoint)
        return None if policy is None else policy.get("checkpoint_digest")

    def finalized(self, environment_id):
        if not self.environments[environment_id]["terminal"]:
            raise ValueError("cannot finalize an unterminated environment")
        self.events.append([environment_id, "finalized"])
        del self.environments[environment_id]

    def abandon(self, environment_id):
        self.events.append([environment_id, "abandoned"])
        self.environments.pop(environment_id, None)
