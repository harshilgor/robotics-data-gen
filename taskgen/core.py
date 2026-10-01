"""JSON-compatible task DSL and trusted symbolic generation primitives.

Symbolic acceptance is not evidence of physical feasibility or learnability.
"""
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from hashlib import sha256
import json
import math
import random
from .parameters import validate_domain, draw

SCHEMA_VERSION = "1.0"
SKILLS = {
    "reach": ({"reachable"}, {"near"}, set(), None),
    "grasp": ({"near", "free"}, {"held"}, {"free"}, "graspable"),
    "lift": ({"held"}, {"lifted"}, set(), "graspable"),
    "transport": ({"held", "lifted"}, {"at_target"}, set(), "graspable"),
    "release": ({"held", "at_target"}, {"placed", "free"}, {"held", "lifted"}, "graspable"),
    "push": ({"near", "free"}, {"at_target"}, set(), "pushable"),
}
ASSETS = {"cube": ["graspable", "pushable"], "target": ["target"], "obstacle": ["obstacle"]}
THETA = {"target_distance": [0.04, 0.16], "tolerance": [0.01, 0.04], "object_size": [0.02, 0.04]}
PHI = {"mass": [0.03, 0.15], "friction": [0.3, 0.8]}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)

def fingerprint(value):
    return sha256(canonical(value).encode()).hexdigest()

def graph(sequence):
    return [{"id": f"s{i}", "skill": skill, "object": "object", "target": "target",
             "depends_on": [] if i == 0 else [f"s{i-1}"]}
            for i, skill in enumerate(sequence)]

def family(name, sequence, goal):
    return {"schema_version": SCHEMA_VERSION, "family": name, "revision": 1,
            "embodiment": "so101", "scene": {"template": "tabletop", "relations": []},
            "objects": {"object": {"asset": "cube", "affordances": ASSETS["cube"][:]},
                        "target": {"asset": "target", "affordances": ["target"]}},
            "initial_state": {"object": ["reachable", "free"]}, "task_graph": graph(sequence),
            "theta": deepcopy(THETA), "phi": deepcopy(PHI),
            "success": {"object": "object", "predicate": goal, "tolerance_parameter": "tolerance"},
            "reward": [{"term": "progress", "weight": 1.0}, {"term": "time", "weight": -0.01}],
            "horizon": 300, "interfaces": {"observation": "state_v1", "action": "joint_target_v1"},
            "provenance": {"engine": "bootstrap", "parents": []}}

def bootstrap_families():
    return [family("reach", ["reach"], "near"),
            family("grasp", ["reach", "grasp"], "held"),
            family("push", ["reach", "push"], "at_target"),
            family("lift", ["reach", "grasp", "lift"], "lifted"),
            family("transport", ["reach", "grasp", "lift", "transport"], "at_target"),
            family("pick_place", ["reach", "grasp", "lift", "transport", "release"], "placed")]

@dataclass
class Validation:
    errors: list = field(default_factory=list)
    pending: list = field(default_factory=lambda: ["kinematics/IK", "collision", "physics", "solvability", "RL learnability"])

    @property
    def structurally_valid(self):
        return not self.errors

    def to_dict(self):
        return {**asdict(self), "structurally_valid": self.structurally_valid, "simulation_approved": False}

def validate(task):
    """Fail closed on malformed DSL; support only totally ordered V1 skill graphs."""
    report = Validation()
    try:
        canonical(task)
        if task.get('schema_version') == '1.3':
            from semantics.execution import lower
            from semantics import default_registry
            expected = lower(task['semantic'], default_registry())
            for key in ('objects','initial_state','task_graph','success','interfaces'):
                if task[key] != expected[key]:
                    raise ValueError('semantic lowering identity mismatch: '+key)
            from semantics.task_spec import validate_extended
            executable = deepcopy(task)
            executable.pop('semantic')
            executable['schema_version'] = '1.2'
            validate_extended(executable)
            return report
        if task.get("schema_version") == "1.2":
            from semantics.task_spec import validate_extended
            validate_extended(task)
            return report
        required = {"schema_version", "family", "revision", "embodiment", "scene", "objects", "initial_state",
                    "task_graph", "theta", "phi", "success", "reward", "horizon", "interfaces", "provenance"}
        if set(task) != required:
            raise ValueError("DSL fields missing or unknown")
        if task["schema_version"] not in (SCHEMA_VERSION, "1.1") or task["embodiment"] != "so101":
            raise ValueError("unsupported schema or embodiment")
        if task["scene"]["template"] != "tabletop":
            raise ValueError("unsupported scene")
        if not isinstance(task["family"], str) or not task["family"] or type(task["revision"]) is not int or task["revision"] < 1:
            raise ValueError("invalid family identity")
        if type(task["horizon"]) is not int or task["horizon"] <= 0:
            raise ValueError("invalid horizon")
        supported_interfaces = [{"observation": "state_v1", "action": "joint_target_v1"}]
        if task["schema_version"] == "1.1":
            supported_interfaces.append({"observation": "local_cartesian_state_v1", "action": "local_cartesian_delta_v1"})
        if task["interfaces"] not in supported_interfaces:
            raise ValueError("unsupported interfaces")
        for kind, expected in (("theta", THETA), ("phi", PHI)):
            if (set(task[kind]) != set(expected) if task["schema_version"] == "1.0" else not set(expected) <= set(task[kind])):
                raise ValueError(f"unknown or missing {kind} parameters")
            for key, bounds in task[kind].items():
                if task["schema_version"] == "1.1":
                    spec = validate_domain(bounds)
                    if key in expected and (spec["type"] != "float" or spec["bounds"][0] <= 0):
                        raise ValueError("core physical dimensions require positive float bounds")
                    continue
                if not isinstance(bounds, list) or len(bounds) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds):
                    raise ValueError(f"invalid range: {key}")
                if not 0 < bounds[0] <= bounds[1]:
                    raise ValueError(f"non-positive or reversed range: {key}")
        for obj, spec in task["objects"].items():
            if spec["asset"] not in ASSETS or set(spec["affordances"]) != set(ASSETS[spec["asset"]]):
                raise ValueError(f"untrusted asset/affordances: {obj}")
        states = {obj: set(values) for obj, values in task["initial_state"].items()}
        if states != {"object": {"reachable", "free"}}:
            raise ValueError("unsupported initial symbolic state")
        if not task["task_graph"]:
            raise ValueError("empty task graph")
        seen = []
        for node in task["task_graph"]:
            if node["id"] in seen or node["depends_on"] != ([] if not seen else [seen[-1]]):
                raise ValueError("graph must have unique IDs and a complete sequential dependency chain")
            seen.append(node["id"])
            pre, effects, delete, affordance = SKILLS[node["skill"]]
            obj = node["object"]
            if node["target"] not in task["objects"] or "target" not in task["objects"][node["target"]]["affordances"]:
                raise ValueError("invalid target reference")
            if obj not in task["objects"] or obj not in states:
                raise ValueError("invalid object reference")
            if affordance and affordance not in task["objects"][obj]["affordances"]:
                raise ValueError("skill requires missing affordance")
            if not pre <= states[obj]:
                raise ValueError(f"unsatisfied preconditions for {node['skill']}: {sorted(pre-states[obj])}")
            states[obj].difference_update(delete)
            states[obj].update(effects)
        success = task["success"]
        if success["predicate"] not in states[success["object"]] or success["tolerance_parameter"] != "tolerance":
            raise ValueError("goal is not established by the skill graph")
        if not task["reward"]:
            raise ValueError("missing reward")
        for term in task["reward"]:
            if term["term"] not in {"progress", "time", "collision"} or type(term["weight"]) not in (int, float) or not math.isfinite(term["weight"]):
                raise ValueError("unsupported reward term or weight")
    except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        report.errors.append(str(exc))
    return report

def compose(base, suffix, name):
    """Append skills to one object's stateful chain; invalid compositions reject."""
    result = deepcopy(base)
    result["family"] = name
    result["task_graph"] = graph([n["skill"] for n in base["task_graph"]] + list(suffix))
    final = suffix[-1] if suffix else result["task_graph"][-1]["skill"]
    goals = {"reach": "near", "grasp": "held", "lift": "lifted", "transport": "at_target", "release": "placed", "push": "at_target"}
    if base["schema_version"] == "1.2":
        goals.update(recover="recovered", slide="at_target", rotate="oriented", align="aligned", insert="inserted", articulate="opened", obstacle_transport="avoided_obstacle", stack="stacked")
    result["success"]["predicate"] = goals[final]
    result["provenance"] = {"engine": "composition", "parents": [fingerprint(base)]}
    report = validate(result)
    if not report.structurally_valid:
        raise ValueError(report.errors)
    return result

def mutate(base, parameter, factor):
    """One counterfactual range mutation, with immutable parent lineage."""
    if parameter not in base["theta"] and parameter not in base["phi"]:
        raise ValueError("unsupported mutation parameter")
    if type(factor) not in (int, float) or not math.isfinite(factor) or factor <= 0 or factor == 1:
        raise ValueError("mutation factor must be positive, finite and change the range")
    result = deepcopy(base)
    kind = "theta" if parameter in base["theta"] else "phi"
    from .parameters import domain
    parameter_spec = domain(result[kind][parameter])
    if parameter_spec["type"] == "categorical":
        raise ValueError("range mutation cannot change categorical values")
    bounds = [v * factor for v in parameter_spec["bounds"]]
    if parameter_spec["type"] == "int":
        bounds = [int(v) for v in bounds]
    result[kind][parameter] = bounds if isinstance(result[kind][parameter], list) else {**parameter_spec, "bounds": bounds}
    result["revision"] += 1
    result["provenance"] = {"engine": "mutation", "parents": [fingerprint(base)], "parameter": parameter, "factor": factor}
    if not validate(result).structurally_valid:
        raise ValueError("invalid mutation")
    return result

def novelty(candidate, archive):
    """Nearest-neighbor distances, not claims of learning value."""
    def features(task):
        skills = [n["skill"] for n in task["task_graph"]]
        structure = set(enumerate(skills))
        composition = set(zip(skills, skills[1:])) | {(s,) for s in skills}
        objects = {(s.get("asset", "role"), a) for s in task["objects"].values() for a in s.get("affordances", s.get("requires", []))}
        goals = {canonical(task['success'])}
        if 'semantic' in task: goals.update(canonical(p) for p in task['semantic']['goal'])
        relationships = {canonical(r) for r in task['scene']['relations']}
        topology = {(n['skill'],len(n['depends_on'])) for n in task['task_graph']}
        return structure, composition, objects, goals, relationships, topology
    def jaccard(a, b):
        return 0.0 if not a | b else 1 - len(a & b) / len(a | b)
    if not archive:
        return {"structural": 1.0, "compositional": 1.0, "objects": 1.0, "parameter": 1.0, "distributional": 1.0, "goal": 1.0, "spatial": 1.0, "constraint_topology": 1.0}
    feature = features(candidate)
    distances = []
    for old in archive:
        values = [jaccard(a, b) for a, b in zip(feature, features(old))]
        for kind in ("theta", "phi"):
            parts = []
            for key, bounds in candidate[kind].items():
                other = old[kind].get(key)
                if not isinstance(bounds, list) or not isinstance(other, list):
                    parts.append(float(bounds != other))
                    continue
                parts.extend(abs(a-b) / max(abs(a), abs(b), 1e-9) for a, b in zip(bounds, other))
            values.append(sum(parts) / len(parts))
        distances.append(values)
    return dict(zip(('structural','compositional','objects','goal','spatial','constraint_topology','parameter','distributional'),
                    (min(row[i] for row in distances) for i in range(8))))

class TaskGenerator:
    def __init__(self, seed=0):
        self.seed = seed
        self.rng = random.Random(seed)
        self.archive = []

    def register(self, task):
        report = validate(task)
        if not report.structurally_valid:
            raise ValueError(report.errors)
        identity = fingerprint(task)
        if any(fingerprint(t) == identity for t in self.archive):
            return False
        self.archive.append(deepcopy(task))
        return True

    def sample(self, task, index=0):
        if type(index) is not int or index < 0:
            raise ValueError("instance index must be a nonnegative integer")
        if not validate(task).structurally_valid:
            raise ValueError("cannot sample invalid family")
        # Instance address makes replay independent of sampling order.
        seed = int(fingerprint([self.seed, fingerprint(task), index])[:16], 16)
        rng = random.Random(seed)
        values = {kind: {key: draw(bounds, rng) for key, bounds in sorted(task[kind].items())} for kind in ("theta", "phi")}
        return {"schema_version": SCHEMA_VERSION, "family_id": fingerprint(task), "family": task["family"],
                "revision": task["revision"], "seed": seed, "index": index, **values,
                "provenance": {"generator_seed": self.seed, "generator_version": "0.1.0"},
                "validation": validate(task).to_dict()}
