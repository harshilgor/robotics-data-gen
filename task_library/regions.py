"""Closed interval box algebra. Shared boundaries are conservatively excluded."""
from copy import deepcopy
import math


def intersect(a, b):
    if set(a) != set(b): raise ValueError("region dimensions differ")
    result = {k: [max(a[k][0], b[k][0]), min(a[k][1], b[k][1])] for k in a}
    return None if any(lo > hi for lo, hi in result.values()) else result


def subtract(box, exclusion):
    overlap = intersect(box, exclusion)
    if overlap is None: return [deepcopy(box)]
    pieces, middle = [], deepcopy(box)
    for key in sorted(box):
        lo, hi = overlap[key]
        if middle[key][0] < lo:
            piece = deepcopy(middle); piece[key][1] = math.nextafter(lo, -math.inf)
            pieces.append(piece); middle[key][0] = lo
        if middle[key][1] > hi:
            piece = deepcopy(middle); piece[key][0] = math.nextafter(hi, math.inf)
            pieces.append(piece); middle[key][1] = hi
    return [p for p in pieces if all(lo <= hi for lo, hi in p.values())]


def remove(boxes, exclusions):
    result = deepcopy(boxes)
    for exclusion in exclusions: result = [p for b in result for p in subtract(b, exclusion)]
    return result
