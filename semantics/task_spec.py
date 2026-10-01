"""Extended declarative DSL validation, preserving the legacy 1.0/1.1 grammar."""
from .registry import default_registry
from taskgen.parameters import validate_domain


EXTENDED_SKILLS = {
    "reach": ({"reachable"}, {"near"}, set(), None),
    "grasp": ({"near", "free"}, {"held"}, {"free"}, "graspable"),
    "lift": ({"held"}, {"lifted"}, set(), "graspable"),
    "transport": ({"held", "lifted"}, {"at_target"}, set(), "graspable"),
    "release": ({"held", "at_target"}, {"placed", "free"}, {"held", "lifted"}, "graspable"),
    "push": ({"near", "free"}, {"at_target"}, set(), "pushable"),
    "rotate": ({"held"}, {"oriented"}, set(), "graspable"),
    "align": ({"held", "at_target"}, {"aligned"}, set(), "graspable"),
    "insert": ({"held", "aligned"}, {"inserted"}, set(), "insertable"),
    "articulate": ({"near", "free"}, {"opened"}, set(), "openable"),
    "obstacle_transport": ({"held", "lifted"}, {"at_target", "avoided_obstacle"}, set(), "graspable"),
    "stack": ({"held", "at_target"}, {"stacked", "free"}, {"held", "lifted"}, "stackable"),
}


def validate_extended(task):
    required = {"schema_version", "family", "revision", "embodiment", "scene", "objects", "initial_state",
                "task_graph", "theta", "phi", "success", "reward", "horizon", "interfaces", "provenance"}
    if set(task) != required or task["schema_version"] != "1.2":
        raise ValueError("malformed extended TaskSpec")
    if task["embodiment"] not in {"so101", "synthetic_cartesian"}:
        raise ValueError("unregistered robot embodiment")
    if not isinstance(task["family"], str) or not task["family"] or type(task["revision"]) is not int or task["revision"] < 1:
        raise ValueError("invalid exact task identity")
    if task["scene"]["template"] not in {"tabletop", "tabletop_obstacles", "drawer", "shelf", "container", "multi_object"}:
        raise ValueError("unknown scene template")
    if set(task["scene"]) != {"template", "relations"} or not isinstance(task["scene"]["relations"], list):
        raise ValueError("malformed declarative scene")
    for relation in task["scene"]["relations"]:
        if set(relation) != {"relation", "roles"} or relation["relation"] not in {"above", "inside", "beside", "obstructs"}:
            raise ValueError("unknown spatial relation")
        if len(relation["roles"]) != 2 or not set(relation["roles"]) <= set(task["objects"]):
            raise ValueError("unknown spatial role")
    if type(task["horizon"]) is not int or task["horizon"] < 1:
        raise ValueError("positive horizon required")
    if task["interfaces"] != {"observation": "local_cartesian_state_v1", "action": "local_cartesian_delta_v1"}:
        raise ValueError("unsupported extended action/observation bindings")
    for group, base in (("theta", {"target_distance", "tolerance", "object_size"}), ("phi", {"mass", "friction"})):
        if not base <= set(task[group]):
            raise ValueError("core physical parameter domains required")
        for name, value in task[group].items():
            spec = validate_domain(value)
            if name in base and (spec["type"] != "float" or spec["bounds"][0] <= 0):
                raise ValueError("positive physical dimensions required")
    from assets import local_resources
    resources = local_resources()
    roles = {}
    for role, description in task["objects"].items():
        if not isinstance(role, str) or not role or not isinstance(description, dict):
            raise ValueError("invalid object role")
        if set(description) == {"requires"}:
            requires = description["requires"]
            if not isinstance(requires, list) or not requires or len(requires) != len(set(requires)):
                raise ValueError("distinct object affordances required")
            matches = resources.resolve_role(requires, versions={entry["name"]: entry["version"]
                for entry in resources.snapshot()["entries"] if entry["kind"] == "asset"})
            if not matches:
                raise ValueError("no asset satisfies requested role")
            roles[role] = set(requires)
        elif set(description) == {"asset", "affordances"}:
            actual = resources.get("asset", description["asset"], "1.0.0")["definition"]["affordances"]
            if not set(description["affordances"]) <= set(actual):
                raise ValueError("false asset affordance claim")
            roles[role] = set(description["affordances"])
        else:
            raise ValueError("object role must request affordances or pin an asset")
    if not roles:
        raise ValueError("object roles required")
    states = {}
    for role, flags in task["initial_state"].items():
        if role not in roles or not isinstance(flags, list) or not set(flags) <= {"reachable", "free", "opened"}:
            raise ValueError("invalid initial symbolic state")
        states[role] = set(flags)
    seen = []
    registry = default_registry()
    if not task["task_graph"]:
        raise ValueError("nonempty skill graph required")
    for node in task["task_graph"]:
        if set(node) != {"id", "skill", "object", "target", "depends_on"}:
            raise ValueError("unknown skill graph fields")
        if not isinstance(node["id"], str) or not node["id"] or node["id"] in seen:
            raise ValueError("invalid skill identity")
        if node["depends_on"] != ([] if not seen else [seen[-1]]):
            raise ValueError("execution DSL currently requires a complete sequential dependency chain")
        seen.append(node["id"])
        if node["skill"] not in EXTENDED_SKILLS:
            raise ValueError("unregistered skill")
        definition = registry.get("execution_skill", node["skill"])
        preconditions, effects, deletes = (set(definition[key]) for key in ("preconditions", "effects", "delete_effects"))
        affordance = definition["required_affordance"]
        obj, target = node["object"], node["target"]
        if obj not in states or target not in roles:
            raise ValueError("unknown skill object/target binding")
        if affordance and affordance not in roles[obj]:
            raise ValueError("skill requires unavailable affordance")
        if node["skill"] == "insert" and "receptacle" not in roles[target]:
            raise ValueError("insertion target must be a receptacle")
        if node["skill"] == "stack" and "stackable" not in roles[target]:
            raise ValueError("stack target must be stackable")
        if not preconditions <= states[obj]:
            raise ValueError("unsatisfied symbolic preconditions")
        states[obj] -= deletes
        states[obj] |= effects
    success = task["success"]
    if set(success) != {"object", "predicate", "tolerance_parameter"} or success["tolerance_parameter"] != "tolerance":
        raise ValueError("unknown success predicate fields")
    if success["object"] not in states or success["predicate"] not in states[success["object"]]:
        raise ValueError("goal is not established by skill graph")
    if not isinstance(task["reward"], list) or not task["reward"]:
        raise ValueError("reward terms required")
    import math
    for reward in task["reward"]:
        if set(reward) != {"term", "weight"} or reward["term"] not in {"progress", "time", "collision"}:
            raise ValueError("unregistered reward term")
        if type(reward["weight"]) not in (int, float) or not math.isfinite(reward["weight"]):
            raise ValueError("invalid reward scale")
    if not isinstance(task["provenance"], dict) or not {"engine", "parents"} <= set(task["provenance"]):
        raise ValueError("generation provenance required")
    return True
