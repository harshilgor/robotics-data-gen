"""Semantic declarations cannot establish measured robot feasibility."""
from copy import deepcopy
import unittest

from semantics import default_registry, predicate, validate_task


def semantic_task(registry):
    return {"schema_version": "semantic-1.0", "family": "role_based_insertion",
            "roles": {"arm": {"requires": ["manipulator"]},
                      "movable": {"requires": ["graspable", "insertable"]},
                      "destination": {"requires": ["receptacle"]}},
            "initial": [predicate("reachable", "movable")],
            "goal": [predicate("inside", "movable", "destination")], "constraints": [],
            "capabilities": ["reach", "grasp", "transport", "insert"],
            "skill_graph": [
                {"id": "r", "skill": "reach", "roles": {"robot": "arm", "object": "movable"}, "depends_on": []},
                {"id": "g", "skill": "grasp", "roles": {"robot": "arm", "object": "movable"}, "depends_on": ["r"]},
                {"id": "t", "skill": "transport", "roles": {"object": "movable", "target": "destination"}, "depends_on": ["g"]},
                {"id": "i", "skill": "insert", "roles": {"object": "movable", "target": "destination"}, "depends_on": ["t"]}],
            "dependencies": {"semantic_registry": registry.snapshot()["digest"]}}


class SemanticsTests(unittest.TestCase):
    def setUp(self):
        self.registry = default_registry()
        self.task = semantic_task(self.registry)

    def test_role_based_task_and_exact_registry_pin(self):
        result = validate_task(self.task, self.registry)
        self.assertTrue(result["structurally_valid"])
        self.assertEqual(result["physical_status"], "unknown")
        self.assertEqual(result["order"], ["r", "g", "t", "i"])
        self.task["dependencies"]["semantic_registry"] = "latest"
        with self.assertRaises(ValueError):
            validate_task(self.task, self.registry)

    def test_unknown_affordance_cycle_and_missing_skill_capability(self):
        for change in (lambda t: t["roles"]["movable"]["requires"].append("magical"),
                       lambda t: t["skill_graph"][0]["depends_on"].append("i"),
                       lambda t: t["capabilities"].remove("insert")):
            task = deepcopy(self.task)
            change(task)
            with self.assertRaises(ValueError):
                validate_task(task, self.registry)

    def test_unrelated_branch_does_not_supply_precondition(self):
        self.task["skill_graph"][2]["depends_on"] = ["r"]
        with self.assertRaisesRegex(ValueError, "preconditions"):
            validate_task(self.task, self.registry)

    def test_measured_predicates_reject_missing_and_invalid_telemetry(self):
        expression = predicate("inside", "movable", "destination")
        bindings = {"movable": "peg1", "destination": "tray1"}
        state = {"peg1": {"position": [0., 0., 0.], "radius": .01},
                 "tray1": {"position": [0., 0., 0.], "interior_half_extents": [.02, .02, .02]}}
        self.assertTrue(self.registry.evaluate(expression, state, bindings))
        state["peg1"]["position"][0] = .03
        self.assertFalse(self.registry.evaluate(expression, state, bindings))
        del state["peg1"]["radius"]
        with self.assertRaises(ValueError):
            self.registry.evaluate(expression, state, bindings)
        with self.assertRaises(ValueError):
            self.registry.evaluate(predicate("near", "movable", "destination", tolerance=float("nan")), state, bindings)

    def test_registry_immutability_snapshot_and_ontology_cycle(self):
        before = self.registry.snapshot()
        copy = self.registry.get("object", "cube")
        copy["affordances"].append("made_up")
        self.assertEqual(before, self.registry.snapshot())
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.registry.register("object", "cube", copy)
        self.registry.register("capability", "cycle_a", {"parent": "cycle_b"})
        self.registry.register("capability", "cycle_b", {"parent": "cycle_a"})
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.registry.validate()

    def test_unestablished_goal_is_rejected(self):
        self.task["goal"].append(predicate("stable", "movable", maximum_speed=.01))
        with self.assertRaisesRegex(ValueError, "goal"):
            validate_task(self.task, self.registry)


if __name__ == "__main__":
    unittest.main()
