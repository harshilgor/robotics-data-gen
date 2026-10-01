"""Canonical capability annotations for the expanded execution grammar."""
from .registry import default_registry

STAGE_CAPABILITY = {"release": "precision_placement", "stack": "precision_placement",
                    "obstacle_transport": "obstacle_avoidance"}


def capabilities_for(task):
    skills = {node["skill"] for node in task["task_graph"]}
    if task["schema_version"] != "1.2":
        return sorted(skills)
    registry = default_registry()
    tags = set(skills)
    for skill in skills:
        signal = STAGE_CAPABILITY.get(skill, skill)
        tags.update(registry.ancestors(signal))
    if len(task["task_graph"]) > 1:
        tags.update(registry.ancestors("sequencing"))
    if len(task["task_graph"]) >= 7:
        tags.update(registry.ancestors("long_horizon"))
    return sorted(tags)
