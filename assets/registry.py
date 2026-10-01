from copy import deepcopy
from taskgen.core import fingerprint


class ResourceRegistry:
    def __init__(self):
        self._items = {}

    def register(self, kind, name, version, definition):
        if kind not in {"asset", "scene", "robot"} or not name or not version:
            raise ValueError("resource kind/name/version required")
        key = (kind, name, version)
        value = {"kind": kind, "name": name, "version": version, "definition": deepcopy(definition)}
        value["digest"] = fingerprint(value)
        if key in self._items and self._items[key] != value:
            raise ValueError("immutable resource version conflict")
        self._items[key] = value
        return deepcopy(value)

    def get(self, kind, name, version):
        try:
            return deepcopy(self._items[kind, name, version])
        except KeyError as exc:
            raise ValueError("unknown exact resource version") from exc

    def resolve_role(self, requires, *, versions):
        return [self.get("asset", name, version) for name, version in sorted(versions.items())
                if set(requires) <= set(self.get("asset", name, version)["definition"]["affordances"])]

    def snapshot(self):
        entries = [deepcopy(value) for _, value in sorted(self._items.items())]
        return {"entries": entries, "digest": fingerprint(entries)}


def local_resources():
    resources = ResourceRegistry()
    for name, shape, affordances in (
        ("cube", "box", ["graspable", "pushable", "stackable"]),
        ("peg", "cylinder", ["graspable", "insertable"]),
        ("target", "support", ["target", "receptacle"]),
        ("tray", "container", ["receptacle"]),
        ("drawer", "prismatic_container", ["openable", "pullable", "container"]),
        ("obstacle", "box", ["obstacle", "collision_object"]),
    ):
        resources.register("asset", name, "1.0.0", {"shape": shape, "affordances": affordances,
            "geometry_source": "procedural", "collision_geometry": shape,
            "scale_bounds_m": [.005, .2], "mass_bounds_kg": [.001, 2.],
            "source": "local synthetic approximation; no measured SO-101 asset"})
    for name in ("tabletop", "tabletop_obstacles", "drawer", "shelf", "container", "multi_object"):
        resources.register("scene", name, "1.0.0", {"layout": name, "frame": "world",
            "units": "m", "workspace_radius": .35, "table_height": 0., "parameterized": True})
    resources.register("robot", "so101-surrogate", "1.0.0", {"embodiment": "so101",
        "runtime": "synthetic-cartesian", "workspace_radius": .35, "maximum_grasp_width": .055,
        "maximum_action_displacement": .012, "control_dt": .02,
        "notice": "Cartesian point surrogate; not SO-101 kinematics or dynamics"})
    return resources
