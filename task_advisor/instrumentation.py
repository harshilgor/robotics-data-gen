"""Simulator-independent measured telemetry bridge. Distances are metres.

Adapters must supply post-action, pre-reset frames; no symbolic state is used
as a measurement. Physical evidence is an external attestation, not a proof.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from taskgen.core import fingerprint, validate
from .core import number, task_annotation, validate_episode

CHECKS = {"kinematics", "collision", "physics", "reset_stability"}


class SimulatorAdapter(Protocol):
    def frame(self, environment_id: str) -> dict:
        """Return measured state after action and before any automatic reset."""
        ...


class Recorder(Protocol):
    def record(self, annotation: dict, episode: dict) -> None: ...


class StoreRecorder:
    def __init__(self, store):
        self.store = store

    def record(self, annotation, episode):
        self.store.ingest([annotation], [episode])


def physical_evidence(task, instance, evidence):
    """Require separately supplied, versioned, exact-instance validation evidence."""
    if not isinstance(evidence, dict):
        raise ValueError("physical evidence required")
    if evidence.get("family_id") != fingerprint(task) or evidence.get("instance_id") != fingerprint(instance):
        raise ValueError("physical evidence does not match task instance")
    for name in ("validator_version", "simulator_version", "report_id"):
        if not isinstance(evidence.get(name), str) or not evidence[name]:
            raise ValueError(f"physical evidence requires {name}")
    checks = evidence.get("checks", {})
    if set(checks) != CHECKS or any(checks[c] is not True for c in CHECKS):
        raise ValueError("all physical checks must explicitly pass")


@dataclass(frozen=True)
class CompiledInstrumentation:
    task: dict
    instance: dict
    evidence: dict
    bindings: dict

    @property
    def annotation(self):
        return task_annotation(self.task)


def compile_instrumentation(task, instance, evidence, *, lift_height=.02):
    """Compile trusted predicate bindings only; does not create a physics scene."""
    if not validate(task).structurally_valid:
        raise ValueError("invalid TaskSpec")
    if instance.get("family_id") != fingerprint(task) or instance.get("revision") != task["revision"]:
        raise ValueError("instance family mismatch")
    for group in ("theta", "phi"):
        values = instance.get(group, {})
        if set(values) != set(task[group]):
            raise ValueError("instance parameter schema mismatch")
        for key, value in values.items():
            number(value, key, *task[group][key])
    physical_evidence(task, instance, evidence)
    number(lift_height, "lift_height", .000001)
    mapping = {"reach": "near", "grasp": "held", "lift": "lifted",
               "transport": "at_target", "push": "at_target", "release": "placed"}
    bindings = {n["id"]: mapping[n["skill"]] for n in task["task_graph"]}
    bindings["goal"] = task["success"]["predicate"]
    bindings["lift_height"] = lift_height
    return CompiledInstrumentation(deepcopy(task), deepcopy(instance), deepcopy(evidence), bindings)


def measured_predicates(frame, tolerance, lift_height):
    for key in ("eef_object_distance", "object_target_distance", "height_above_reset", "object_speed"):
        number(frame.get(key), key, 0 if key != "height_above_reset" else None)
    for key in ("grasp_contact", "gripper_closed", "target_support", "collision", "terminated", "truncated"):
        if type(frame.get(key)) is not bool:
            raise ValueError(f"{key} must be measured boolean")
    held = frame["grasp_contact"] and frame["gripper_closed"]
    at_target = frame["object_target_distance"] <= tolerance
    return {"near": frame["eef_object_distance"] <= tolerance, "held": held,
            "lifted": held and frame["height_above_reset"] >= lift_height,
            "at_target": at_target,
            "placed": at_target and not held and frame["target_support"] and frame["object_speed"] <= .01}


class EpisodeTracker:
    def __init__(self, compiled, *, episode_id, policy_version, source="training"):
        self.compiled = deepcopy(compiled)
        self.annotation = self.compiled.annotation
        for value in (episode_id, policy_version):
            if not isinstance(value, str) or not value:
                raise ValueError("episode and policy identifiers required")
        if source not in ("training", "development"):
            raise ValueError("sealed/test evidence forbidden")
        self.episode_id, self.policy_version, self.source = episode_id, policy_version, source
        self.results = {s["id"]: None for s in self.annotation["subgoals"]}
        self.frames = []
        self.reward = 0.0
        self.collisions = self.grasp_losses = 0
        self.was_collision = self.was_held = False
        self.last_time = None
        self.closed = False
        self.ready = None

    def observe(self, frame):
        if self.closed or self.ready is not None:
            raise ValueError("episode already terminal")
        frame = deepcopy(frame)
        if frame.get("episode_id") != self.episode_id:
            raise ValueError("frame belongs to another episode or post-reset state")
        if type(frame.get("step")) is not int or frame["step"] != len(self.frames) + 1:
            raise ValueError("steps must be contiguous and start at one")
        stamp = frame.get("timestamp")
        if not isinstance(stamp, str) or datetime.fromisoformat(stamp.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("frame timestamp requires timezone")
        number(frame.get("sim_time"), "sim_time", 0)
        if self.last_time is not None and frame["sim_time"] <= self.last_time:
            raise ValueError("simulation time must increase")
        number(frame.get("reward"), "reward")
        c = self.compiled
        predicates = measured_predicates(frame, c.instance["theta"]["tolerance"], c.bindings["lift_height"])
        stages = self.annotation["subgoals"]
        active = next((s for s in stages if self.results[s["id"]] is not True), None)
        # One stage per frame prevents one static observation completing a sequence.
        if active and all(self.results[d] is True for d in active["depends_on"]):
            self.results[active["id"]] = predicates[c.bindings[active["id"]]]
        intentional_release = active is not None and active["capability"] == "release"
        self.collisions += int(frame["collision"] and not self.was_collision)
        self.grasp_losses += int(self.was_held and not predicates["held"] and not intentional_release)
        self.was_collision, self.was_held = frame["collision"], predicates["held"]
        self.reward += frame["reward"]
        self.last_time = frame["sim_time"]
        self.frames.append(frame)
        horizon = len(self.frames) >= c.task["horizon"]
        if frame["terminated"] or frame["truncated"] or horizon:
            success = all(v is True for v in self.results.values()) and predicates[c.bindings["goal"]]
            failed_stage = next((s["id"] for s in stages if self.results[s["id"]] is False), None)
            ep = {"episode_id": self.episode_id, "policy_version": self.policy_version,
                "source": self.source, "task_instance_id": fingerprint(c.instance),
                "family_id": self.annotation["family_id"], "family_version": self.annotation["family_version"],
                "task_parameters": deepcopy(c.instance["theta"]), "timestamp": frame.get("timestamp"),
                "success": success, "reward": self.reward, "episode_length": len(self.frames),
                "completion_fraction": sum(v is True for v in self.results.values()) / len(self.results),
                "subgoal_results": deepcopy(self.results), "collisions": self.collisions,
                "grasp_losses": self.grasp_losses, "final_goal_error": frame["object_target_distance"],
                "timed_out": bool((frame["truncated"] or horizon) and not success),
                "failure_stage": failed_stage, "failure_type": None if success else "goal_not_maintained" if failed_stage is None else "predicate_not_achieved",
                "instrumentation": {"version": "1.0", "physical_evidence": c.evidence,
                    "bindings": c.bindings, "randomization": c.instance["phi"], "seed": c.instance["seed"],
                    "frames": deepcopy(self.frames),
                    "termination": {"terminated": frame["terminated"], "truncated": frame["truncated"], "horizon": horizon}}}
            validate_episode(ep, {(self.annotation["family_id"], self.annotation["family_version"]): self.annotation})
            self.ready = ep
        return deepcopy(self.ready)

    def finish(self, recorder):
        if self.closed or self.ready is None:
            raise ValueError("terminal episode required and can only be recorded once")
        recorder.record(self.annotation, deepcopy(self.ready))
        self.closed = True
        return deepcopy(self.ready)


class InstrumentedEnvironments:
    """Independent episode lifecycles for vectorized simulator adapters."""
    def __init__(self, recorder):
        self.recorder = recorder
        self.trackers = {}

    def start(self, environment_id, tracker):
        if environment_id in self.trackers:
            raise ValueError("finish existing environment episode before reset")
        self.trackers[environment_id] = tracker

    def step(self, environment_id, simulator):
        tracker = self.trackers[environment_id]
        if tracker.ready is None:
            tracker.observe(simulator.frame(environment_id))
        if tracker.ready is not None:
            record = tracker.finish(self.recorder)
            del self.trackers[environment_id]
            return record
        return None
