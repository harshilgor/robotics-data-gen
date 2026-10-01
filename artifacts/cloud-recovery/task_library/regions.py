"""Sparse typed box algebra; rejected numeric boundaries excluded conservatively."""
from copy import deepcopy
import math
from taskgen.parameters import domain, intersect_domain, contains


def intersect(a, b):
    if set(a) != set(b): raise ValueError("region dimensions differ")
    result = {k: intersect_domain(a[k], b[k]) for k in a}
    return None if any(v is None for v in result.values()) else result


def subtract(box, exclusion):
    overlap = intersect(box, exclusion)
    if overlap is None: return [deepcopy(box)]
    pieces, middle = [], deepcopy(box)
    for key in sorted(box):
        spec, cut = domain(middle[key]), domain(overlap[key])
        if spec["type"] == "categorical":
            outside = [v for v in spec["values"] if not contains(cut, v)]
            if outside:
                piece = deepcopy(middle); piece[key] = {"type": "categorical", "values": outside}; pieces.append(piece)
            middle[key] = deepcopy(overlap[key]); continue
        lo, hi = cut["bounds"]
        step_lo = lo-1 if spec["type"] == "int" else math.nextafter(lo, -math.inf)
        step_hi = hi+1 if spec["type"] == "int" else math.nextafter(hi, math.inf)
        def replace(value, bounds):
            return bounds if isinstance(value, list) else {"type": spec["type"], "bounds": bounds}
        a, b = spec["bounds"]
        if a < lo:
            piece = deepcopy(middle); piece[key] = replace(middle[key], [a, step_lo]); pieces.append(piece)
        if b > hi:
            piece = deepcopy(middle); piece[key] = replace(middle[key], [step_hi, b]); pieces.append(piece)
        middle[key] = replace(middle[key], [lo, hi])
    return pieces


def remove(boxes, exclusions):
    result = deepcopy(boxes)
    for exclusion in exclusions: result = [p for b in result for p in subtract(b, exclusion)]
    return result
