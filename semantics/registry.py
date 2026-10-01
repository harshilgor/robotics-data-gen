"""Declarative registries; task descriptions never contain executable code."""
from copy import deepcopy
import math

from taskgen.core import fingerprint


def predicate(name, *roles, **parameters):
    return {"predicate": name, "roles": list(roles), "parameters": parameters}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class SemanticRegistry:
    """Immutable identity bindings with explicit, pinned dependency versions.

    Handwritten trusted implementations live in the application. Definitions
    persisted in tasks can only reference registered symbols.
    """
    def __init__(self, version="1.0.0"):
        self.version = version
        self._definitions = {kind: {} for kind in ("capability", "object", "predicate", "skill", "execution_skill")}
        self._implementations = {}

    def register(self, kind, name, definition, implementation=None):
        if kind not in self._definitions or not isinstance(name, str) or not name:
            raise ValueError("invalid registry identity")
        value = deepcopy(definition)
        fingerprint(value)  # rejects non-JSON and non-finite definitions
        existing = self._definitions[kind].get(name)
        if existing is not None and existing != value:
            raise ValueError("immutable semantic symbol conflict")
        if implementation is not None:
            if kind != "predicate" or not callable(implementation):
                raise ValueError("only trusted predicate callables can be bound")
            prior = self._implementations.get(name)
            if prior is not None and prior is not implementation:
                raise ValueError("immutable predicate implementation conflict")
            self._implementations[name] = implementation
        self._definitions[kind][name] = value

    def get(self, kind, name):
        try:
            return deepcopy(self._definitions[kind][name])
        except KeyError as exc:
            raise ValueError(f"unknown {kind}: {name}") from exc

    def snapshot(self):
        result = {"version": self.version, "definitions": deepcopy(self._definitions)}
        return {**result, "digest": fingerprint(result)}

    def validate(self):
        for capability in self._definitions["capability"]:
            self.ancestors(capability)
        for name, definition in self._definitions["skill"].items():
            expected = {"roles", "capabilities", "preconditions", "effects", "delete_effects"}
            if set(definition) != expected or not definition["roles"]:
                raise ValueError(f"malformed skill: {name}")
            roles = {role: {"requires": affordances} for role, affordances in definition["roles"].items()}
            for capability in definition["capabilities"]:
                self.ancestors(capability)
            for kind in ("preconditions", "effects", "delete_effects"):
                for expression in definition[kind]:
                    self.validate_predicate(expression, roles)
        return self.snapshot()

    def ancestors(self, capability):
        result, seen = [], set()
        current = capability
        while current is not None:
            if current in seen:
                raise ValueError("capability ontology cycle")
            seen.add(current)
            entry = self.get("capability", current)
            result.append(current)
            current = entry.get("parent")
        return result

    def validate_predicate(self, expression, roles):
        if set(expression) != {"predicate", "roles", "parameters"}:
            raise ValueError("malformed predicate expression")
        definition = self.get("predicate", expression["predicate"])
        if len(expression["roles"]) != definition["arity"]:
            raise ValueError("predicate arity mismatch")
        if any(role not in roles for role in expression["roles"]):
            raise ValueError("predicate references unknown role")
        if set(expression["parameters"]) != set(definition.get("parameters", {})):
            raise ValueError("predicate parameter schema mismatch")
        for name, value in expression["parameters"].items():
            if not finite(value) or value < 0:
                raise ValueError("predicate thresholds must be finite and nonnegative")
        for role, requirements in zip(expression["roles"], definition.get("affordances", [])):
            if not set(requirements) <= set(roles[role]["requires"]):
                raise ValueError("predicate role lacks required affordance")

    def evaluate(self, expression, state, bindings):
        """Evaluate only measured runtime state through an allowlisted callable.

        Missing telemetry is an error, never a false policy outcome.
        """
        name = expression["predicate"]
        definition = self.get("predicate", name)
        if len(expression["roles"]) != definition["arity"]:
            raise ValueError("predicate arity mismatch")
        if set(expression["parameters"]) != set(definition.get("parameters", {})):
            raise ValueError("predicate parameter schema mismatch")
        if any(not finite(v) or v < 0 for v in expression["parameters"].values()):
            raise ValueError("invalid predicate threshold")
        if name not in self._implementations:
            raise ValueError("predicate has no runtime implementation")
        try:
            entities = [state[bindings[role]] for role in expression["roles"]]
        except KeyError as exc:
            raise ValueError("missing measured entity or role binding") from exc
        result = self._implementations[name](entities, expression["parameters"])
        if type(result) is not bool:
            raise ValueError("predicate implementation must return boolean")
        return result


def _position(entity):
    values = entity.get("position")
    if not isinstance(values, list) or len(values) != 3 or not all(finite(v) for v in values):
        raise ValueError("measured world position requires three finite metres")
    return values


def _distance(a, b):
    return math.dist(_position(a), _position(b))


def _near(entities, parameters):
    return _distance(*entities) <= parameters["tolerance"]


def _inside(entities, parameters):
    obj, target = entities
    size = target.get("interior_half_extents")
    radius = obj.get("radius")
    if not isinstance(size, list) or len(size) != 3 or not all(finite(v) and v > 0 for v in size):
        raise ValueError("receptacle requires measured positive interior extents")
    if not finite(radius) or radius < 0:
        raise ValueError("object requires measured nonnegative radius")
    return all(abs(a-b) + radius <= extent for a, b, extent in zip(_position(obj), _position(target), size))


def _stable(entities, parameters):
    speed = entities[0].get("speed")
    if not finite(speed) or speed < 0:
        raise ValueError("missing measured speed")
    return speed <= parameters["maximum_speed"]


def _aligned(entities, parameters):
    angles = [entity.get("yaw") for entity in entities]
    if not all(finite(value) for value in angles):
        raise ValueError("aligned predicate requires measured yaw in radians")
    error = abs((angles[0]-angles[1]+math.pi) % (2*math.pi)-math.pi)
    return error <= parameters["maximum_error"]


def _contact(entities, parameters):
    radii = [entity.get("radius") for entity in entities]
    if not all(finite(value) and value >= 0 for value in radii):
        raise ValueError("contact predicate requires measured geometry")
    return _distance(*entities) <= sum(radii)


def _collision(entities, parameters):
    radii = [entity.get("radius") for entity in entities]
    if not all(finite(value) and value >= 0 for value in radii):
        raise ValueError("collision predicate requires measured geometry")
    return _distance(*entities) < sum(radii)


def _flag(key):
    def check(entities, parameters):
        value = entities[0].get(key)
        if type(value) is not bool:
            raise ValueError(f"missing measured {key}")
        return value
    return check


def default_registry():
    registry = SemanticRegistry()
    parents = {"manipulation": None, "acquisition": "manipulation", "object_control": "manipulation",
               "contact": "manipulation", "precision": "manipulation", "composition": "manipulation"}
    groups = {"acquisition": ("reach", "align", "grasp"),
              "object_control": ("lift", "transport", "rotate", "maintain_grasp", "grasp_stability"),
              "contact": ("push", "slide", "articulate", "insert"),
              "precision": ("positional_precision", "orientation_precision", "contact_precision", "precision_placement"),
              "composition": ("sequencing", "long_horizon", "recovery")}
    for name, parent in parents.items():
        registry.register("capability", name, {"parent": parent})
    for parent, names in groups.items():
        for name in names:
            registry.register("capability", name, {"parent": parent})
    for name, parent in {"release": "precision", "stack": "precision", "obstacle_avoidance": "object_control",
                         "obstacle_transport": "object_control"}.items():
        registry.register("capability", name, {"parent": parent})
    for name, affordances in {"cube": ["graspable", "pushable", "stackable"],
                              "peg": ["graspable", "insertable"], "tray": ["receptacle"],
                              "drawer": ["openable", "pullable", "container"],
                              "obstacle": ["collision_object"], "robot": ["manipulator"]}.items():
        registry.register("object", name, {"affordances": affordances})
    for name, arity, parameters, affordances, implementation in (
        ("near", 2, {"tolerance": "m"}, [[], []], _near),
        ("inside", 2, {}, [[], ["receptacle"]], _inside),
        ("stable", 1, {"maximum_speed": "m/s"}, [[]], _stable),
        ("elevated", 1, {"minimum_height":"m"}, [[]], lambda entities,parameters: _position(entities[0])[2]-entities[0]['reset_height'] >= parameters['minimum_height']),
        ("grasped", 1, {}, [["graspable"]], _flag("grasped")),
        ("open", 1, {}, [["openable"]], _flag("open")),
        ("reachable", 1, {}, [[]], _flag("reachable")),
        ("aligned", 2, {"maximum_error": "rad"}, [[], []], _aligned),
        ("contact", 2, {}, [[], []], _contact),
        ("collision", 2, {}, [[], []], _collision),
        ("avoid_collision", 2, {}, [[], []], lambda entities, parameters: not _collision(entities, parameters)),
        ("outside", 2, {}, [[], ["receptacle"]], lambda entities, parameters: not _inside(entities, parameters)),
    ):
        registry.register("predicate", name, {"arity": arity, "parameters": parameters,
                                               "affordances": affordances}, implementation)
    near = predicate("near", "robot", "object", tolerance=.03)
    held = predicate("grasped", "object")
    at_target = predicate("near", "object", "target", tolerance=.03)
    definitions = {
        "reach": ({"robot": ["manipulator"], "object": []}, ["reach"], [predicate("reachable", "object")], [near], []),
        "grasp": ({"robot": ["manipulator"], "object": ["graspable"]}, ["grasp"], [near], [held], []),
        "transport": ({"object": ["graspable"], "target": []}, ["transport"], [held], [at_target], []),
        "push": ({"robot": ["manipulator"], "object": ["pushable"], "target": []}, ["push"], [near], [at_target], []),
        "insert": ({"object": ["graspable", "insertable"], "target": ["receptacle"]}, ["insert"], [held, at_target], [predicate("inside", "object", "target")], []),
        "open": ({"object": ["openable"]}, ["articulate"], [predicate("reachable", "object")], [predicate("open", "object")], []),
    }
    definitions.update({
        'lift': ({'object':['graspable']}, ['lift'], [held], [predicate('elevated','object',minimum_height=.02)], []),
        'rotate': ({'object':['graspable'],'target':[]}, ['rotate'], [held], [predicate('aligned','object','target',maximum_error=.05)], []),
        'align': ({'object':['graspable'],'target':[]}, ['align'], [held,at_target], [predicate('aligned','object','target',maximum_error=.05)], []),
        'place': ({'object':['graspable'],'target':['receptacle']}, ['precision_placement'], [held,at_target],
            [at_target,predicate('inside','object','target'),predicate('stable','object',maximum_speed=.01)], [held]),
        'slide': ({'robot':['manipulator'],'object':['pushable'],'target':[]}, ['slide'], [near], [at_target], []),
    })
    for name, (roles, capabilities, preconditions, effects, deletes) in definitions.items():
        registry.register("skill", name, {"roles": roles, "capabilities": capabilities,
                                          "preconditions": preconditions, "effects": effects, "delete_effects": deletes})
    from .task_spec import EXTENDED_SKILLS
    bindings = {"reach": "near", "grasp": "held", "lift": "lifted", "transport": "at_target",
                "release": "placed", "push": "at_target", "slide": "at_target", "recover": "recovered", "rotate": "oriented", "align": "aligned",
                "insert": "inserted", "articulate": "opened", "obstacle_transport": "avoided_obstacle", "stack": "stacked"}
    for name, (preconditions, effects, deletes, affordance) in EXTENDED_SKILLS.items():
        registry.register("execution_skill", name, {"preconditions": sorted(preconditions), "effects": sorted(effects),
            "delete_effects": sorted(deletes), "required_affordance": affordance, "measured_predicate": bindings[name]})
    registry.validate()
    return registry


def validate_task(task, registry):
    """Validate role-based semantic TaskSpecs, including executable DAG order.

    This verifies declarations only. It cannot establish physical feasibility.
    """
    required = {"schema_version", "family", "roles", "initial", "goal", "constraints",
                "skill_graph", "capabilities", "dependencies"}
    if set(task) != required or task["schema_version"] != "semantic-1.0":
        raise ValueError("unsupported semantic TaskSpec schema")
    fingerprint(task)
    registry.validate()
    if not isinstance(task["family"], str) or not task["family"]:
        raise ValueError("family name required")
    if task["dependencies"] != {"semantic_registry": registry.snapshot()["digest"]}:
        raise ValueError("semantic registry dependency mismatch")
    roles = task["roles"]
    if not isinstance(roles, dict) or not roles:
        raise ValueError("object roles required")
    vocabulary = {a for obj in registry.snapshot()["definitions"]["object"].values() for a in obj["affordances"]}
    for name, role in roles.items():
        if not name or set(role) != {"requires"} or not isinstance(role["requires"], list):
            raise ValueError("malformed object role")
        if len(role["requires"]) != len(set(role["requires"])) or not set(role["requires"]) <= vocabulary:
            raise ValueError("unknown or duplicate required affordance")
    for kind in ("initial", "goal", "constraints"):
        if not isinstance(task[kind], list) or (kind == "goal" and not task[kind]):
            raise ValueError("predicate lists and nonempty goals required")
        for expression in task[kind]:
            registry.validate_predicate(expression, roles)
    capabilities = task["capabilities"]
    if not isinstance(capabilities, list) or not capabilities or len(capabilities) != len(set(capabilities)):
        raise ValueError("distinct capabilities required")
    for capability in capabilities:
        registry.ancestors(capability)
    if not isinstance(task["skill_graph"], list) or not task["skill_graph"]:
        raise ValueError("skill graph required")
    nodes = {}
    for node in task["skill_graph"]:
        if set(node) != {"id", "skill", "roles", "depends_on"} or not node["id"] or node["id"] in nodes:
            raise ValueError("malformed or duplicate skill node")
        definition = registry.get("skill", node["skill"])
        if not set(definition["capabilities"]) <= set(capabilities):
            raise ValueError("TaskSpec omits exercised skill capabilities")
        if set(node["roles"]) != set(definition["roles"]):
            raise ValueError("skill role schema mismatch")
        for local, global_role in node["roles"].items():
            if global_role not in roles or not set(definition["roles"][local]) <= set(roles[global_role]["requires"]):
                raise ValueError("skill role lacks required affordance")
        if not isinstance(node["depends_on"], list) or len(node["depends_on"]) != len(set(node["depends_on"])):
            raise ValueError("invalid skill dependencies")
        nodes[node["id"]] = node
    order, visiting, visited = [], set(), set()
    def visit(identity):
        if identity not in nodes or identity in visiting:
            raise ValueError("unknown dependency or cyclic skill graph")
        if identity in visited:
            return
        visiting.add(identity)
        for dependency in nodes[identity]["depends_on"]:
            visit(dependency)
        visiting.remove(identity)
        visited.add(identity)
        order.append(identity)
    for identity in sorted(nodes):
        visit(identity)
    # Each node sees only ancestor effects, not effects from unrelated branches.
    initial = {fingerprint(p) for p in task["initial"]}
    available, removed = {}, {}
    def bind(expression, node):
        result = deepcopy(expression)
        result["roles"] = [node["roles"][r] for r in result["roles"]]
        registry.validate_predicate(result, roles)
        return fingerprint(result)
    for identity in order:
        node = nodes[identity]
        definition = registry.get("skill", node["skill"])
        state = set(initial) if not node["depends_on"] else set()
        deleted = set()
        for dependency in node["depends_on"]:
            state |= available[dependency]
            deleted |= removed[dependency]
        state -= deleted
        if not {bind(p, node) for p in definition["preconditions"]} <= state:
            raise ValueError("unsatisfied symbolic skill preconditions")
        current_deletes = {bind(p, node) for p in definition.get("delete_effects", [])}
        effects = {bind(p, node) for p in definition["effects"]}
        state -= current_deletes
        state |= effects
        deleted |= current_deletes
        deleted -= effects
        available[identity] = state
        removed[identity] = deleted
    leaves = set(nodes) - {d for node in nodes.values() for d in node["depends_on"]}
    # A goal must hold in at least one complete terminal branch state.
    goals = {fingerprint(p) for p in task["goal"]}
    if not goals <= set().union(*(available[leaf] for leaf in leaves)) :
        raise ValueError("goal not established by terminal skill state")
    return {"structurally_valid": True, "physical_status": "unknown", "order": order,
            "registry_digest": registry.snapshot()["digest"]}
