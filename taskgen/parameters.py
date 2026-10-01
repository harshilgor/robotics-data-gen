"""Typed finite domains; only data, never executable strings or expressions."""
from copy import deepcopy
import math


def domain(value):
    return {"type": "float", "bounds": value} if isinstance(value, list) else value


def validate_domain(value):
    spec = domain(value)
    if not isinstance(spec, dict) or spec.get("type") not in {"float", "int", "categorical"}:
        raise ValueError("unknown parameter type")
    if spec["type"] == "categorical":
        values = spec.get("values")
        if not isinstance(values, list) or not values or any(type(v) not in (str, bool, int) for v in values):
            raise ValueError("categorical values must be nonempty scalar list")
        if len({(type(v), v) for v in values}) != len(values): raise ValueError("duplicate categories")
    else:
        bounds = spec.get("bounds")
        if not isinstance(bounds, list) or len(bounds) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds) or bounds[0] > bounds[1]:
            raise ValueError("invalid numeric bounds")
        if spec["type"] == "int" and any(type(v) is not int for v in bounds): raise ValueError("integer bounds required")
    return spec


def contains(value, point):
    spec = validate_domain(value)
    if spec["type"] == "categorical": return any(type(point) is type(v) and point == v for v in spec["values"])
    return (type(point) is int if spec["type"] == "int" else type(point) in (int, float)) and math.isfinite(point) and spec["bounds"][0] <= point <= spec["bounds"][1]


def check_values(schema, values):
    if not isinstance(values, dict) or set(values) != set(schema): raise ValueError("parameter keys differ from schema")
    for name, spec in schema.items():
        if not contains(spec, values[name]): raise ValueError("parameter type/range mismatch: " + name)


def intersect_domain(a, b):
    sa, sb = validate_domain(a), validate_domain(b)
    if sa["type"] != sb["type"]: raise ValueError("domain types differ")
    if sa["type"] == "categorical":
        values = [v for v in sa["values"] if contains(sb, v)]
        return {"type": "categorical", "values": values} if values else None
    lo, hi = max(sa["bounds"][0], sb["bounds"][0]), min(sa["bounds"][1], sb["bounds"][1])
    if lo > hi: return None
    return [lo, hi] if isinstance(a, list) else {"type": sa["type"], "bounds": [lo, hi]}


def restrict(value, restriction):
    spec = deepcopy(validate_domain(value))
    if spec["type"] == "categorical":
        subset = restriction.get("values") if isinstance(restriction, dict) else restriction
        candidate = {"type": "categorical", "values": subset}
    else:
        if isinstance(restriction, list): lo, hi = restriction
        else:
            lo, hi = restriction.get("lower"), restriction.get("upper")
            if hi is not None and not restriction.get("upper_inclusive", True):
                hi = hi-1 if spec["type"] == "int" else math.nextafter(hi, -math.inf)
        lo = spec["bounds"][0] if lo is None else lo
        hi = spec["bounds"][1] if hi is None else hi
        candidate = {"type": spec["type"], "bounds": [lo, hi]}
    result = intersect_domain(value, candidate)
    if result is None: raise ValueError("empty region intersection")
    return result


def draw(value, rng, fraction=None):
    spec = validate_domain(value)
    if spec["type"] == "categorical": return rng.choice(spec["values"])
    lo, hi = spec["bounds"]
    if fraction is None: fraction = rng.random()
    return min(hi, lo+int(fraction*(hi-lo+1))) if spec["type"] == "int" else lo+(hi-lo)*fraction


def schema_contract(schema):
    if not isinstance(schema, dict) or not schema: raise ValueError("nonempty parameter schema required")
    for name, spec in schema.items():
        validate_domain(spec)
        if spec.get("name", name) != name: raise ValueError("parameter name mismatch")
        if not isinstance(spec.get("units"), str) or not spec["units"]: raise ValueError("units required")
        if "coordinate_frame" not in spec: raise ValueError("explicit coordinate_frame (or null) required")
        if spec["coordinate_frame"] is not None and (not isinstance(spec["coordinate_frame"], str) or not spec["coordinate_frame"]): raise ValueError("invalid frame")
        if spec.get("spatial", False) and spec["coordinate_frame"] is None: raise ValueError("spatial parameter needs frame")
        if spec.get("sampling_role") not in ("theta", "phi") or spec.get("application_stage") not in ("build", "reset", "step"): raise ValueError("invalid role/stage")
        deps = spec.get("dependencies")
        if not isinstance(deps, list) or len(set(deps)) != len(deps) or not set(deps) <= set(schema): raise ValueError("unknown dependencies")
    visiting, done = set(), set()
    def visit(name):
        if name in visiting: raise ValueError("cyclic parameter dependencies")
        if name in done: return
        visiting.add(name)
        for dep in schema[name]["dependencies"]: visit(dep)
        visiting.remove(name); done.add(name)
    for name in schema: visit(name)
