"""Canonical capability annotations for the expanded execution grammar."""
from .registry import default_registry

STAGE_CAPABILITY = {"recover": "recovery", "release": "precision_placement", "stack": "precision_placement",
                    "obstacle_transport": "obstacle_avoidance"}


def capabilities_for(task):
    skills = {node["skill"] for node in task["task_graph"]}
    if task["schema_version"] not in ("1.2", "1.3"):
        return sorted(skills)
    registry = default_registry()
    tags = set(skills)
    for skill in skills:
        signal = STAGE_CAPABILITY.get(skill, skill)
        tags.discard("recover")
        tags.update(registry.ancestors(signal))
    if 'transport' in skills or 'obstacle_transport' in skills or 'lift' in skills:
        for tag in ('maintain_grasp', 'grasp_stability'):
            tags.update(registry.ancestors(tag))
    if 'release' in skills or 'stack' in skills:
        tags.update(registry.ancestors('positional_precision'))
    if 'align' in skills or 'rotate' in skills:
        tags.update(registry.ancestors('orientation_precision'))
    if 'insert' in skills:
        tags.update(registry.ancestors('contact_precision'))
    if len(task["task_graph"]) > 1:
        tags.update(registry.ancestors("sequencing"))
    if len(task["task_graph"]) >= 7:
        tags.update(registry.ancestors("long_horizon"))
    return sorted(tags)
