"""Hand-authored broad seed coverage; all local approvals remain synthetic."""
from copy import deepcopy
from .core import bootstrap_families, graph


def broad_bootstrap():
    tasks = bootstrap_families()
    for task in tasks:
        task["schema_version"] = "1.1"
        task["interfaces"] = {"observation": "local_cartesian_state_v1", "action": "local_cartesian_delta_v1"}
    base = deepcopy(tasks[-1])
    def create(name, sequence, goal, scene="tabletop", objects=None):
        task = deepcopy(base)
        task.update(schema_version="1.2", family=name, task_graph=graph(sequence), scene={"template": scene, "relations": []})
        task["success"]["predicate"] = goal
        if objects is not None:
            task["objects"] = objects
        task["provenance"] = {"engine": "bootstrap", "parents": []}
        return task
    precision = create("precision_place", ["reach", "grasp", "lift", "transport", "release"], "placed")
    precision["theta"]["tolerance"] = [.005, .01]
    tasks.append(precision)
    obstacles = create("transport_around_obstacle", ["reach", "grasp", "lift", "obstacle_transport", "release"], "placed", "tabletop_obstacles")
    obstacles["theta"]["target_distance"] = [.09, .16]
    tasks.append(obstacles)
    tasks.append(create("object_rotation", ["reach", "grasp", "rotate"], "oriented"))
    tasks.append(create("stack", ["reach", "grasp", "lift", "transport", "stack"], "stacked", objects={
        "object": {"requires": ["graspable", "stackable"]}, "target": {"requires": ["stackable"]}}))
    tasks.append(create("insert", ["reach", "grasp", "lift", "transport", "align", "insert"], "inserted", "container", {
        "object": {"requires": ["graspable", "insertable"]}, "target": {"requires": ["receptacle"]}}))
    tasks.append(create("retrieve_from_container", ["reach", "grasp", "lift", "transport", "release"], "placed", "container"))
    drawer = create("open_and_retrieve", ["reach", "articulate"], "opened", "drawer", {
        "object": {"requires": ["openable"]}, "target": {"requires": ["receptacle"]}, "movable": {"requires": ["graspable"]}})
    second = graph(["reach", "grasp", "lift", "transport", "release"])
    for index, node in enumerate(second, 2):
        node.update(id="s"+str(index), object="movable", depends_on=["s"+str(index-1)])
    drawer["task_graph"].extend(second)
    drawer["initial_state"]["movable"] = ["reachable", "free"]
    drawer["success"].update(object="movable", predicate="placed")
    tasks.append(drawer)
    rearrange = create("sequential_rearrangement", ["reach", "grasp", "lift", "transport", "release"], "placed", "multi_object")
    rearrange["objects"]["second_object"] = {"requires": ["graspable"]}
    rearrange["initial_state"]["second_object"] = ["reachable", "free"]
    second = graph(["reach", "grasp", "lift", "transport", "release"])
    for index, node in enumerate(second, 5):
        node.update(id="s"+str(index), object="second_object", depends_on=["s"+str(index-1)])
    rearrange["task_graph"].extend(second)
    rearrange["success"]["object"] = "second_object"
    tasks.append(rearrange)
    return tasks
