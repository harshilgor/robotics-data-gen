from copy import deepcopy
import unittest
from taskgen.core import TaskGenerator, bootstrap_families, compose, mutate, novelty, validate

class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.families = bootstrap_families()

    def test_bootstrap_and_pending_physics(self):
        for task in self.families:
            report = validate(task)
            self.assertTrue(report.structurally_valid, report.errors)
            self.assertFalse(report.to_dict()["simulation_approved"])
            self.assertIn("physics", report.pending)

    def test_invalid_order_and_cycle_rejected(self):
        task = deepcopy(self.families[-1])
        task["task_graph"][0]["skill"] = "release"
        self.assertFalse(validate(task).structurally_valid)
        task = deepcopy(self.families[-1])
        task["task_graph"][0]["depends_on"] = ["s5"]
        self.assertFalse(validate(task).structurally_valid)

    def test_missing_affordance_and_false_goal(self):
        task = deepcopy(self.families[1])
        task["objects"]["object"]["affordances"] = []
        self.assertFalse(validate(task).structurally_valid)
        task = deepcopy(self.families[0])
        task["success"]["predicate"] = "placed"
        self.assertFalse(validate(task).structurally_valid)

    def test_schema_and_nonfinite_rejected(self):
        for change in ({"unexpected": 1}, {"horizon": -1}, {"theta": {"tolerance": [float("nan"), 1]}}):
            task = deepcopy(self.families[0])
            task.update(change)
            self.assertFalse(validate(task).structurally_valid)
        self.assertFalse(validate({}).structurally_valid)
        task = deepcopy(self.families[0])
        task["objects"] = []
        self.assertFalse(validate(task).structurally_valid)

    def test_composition_respects_symbolic_state(self):
        task = compose(self.families[1], ["lift", "transport", "release"], "new")
        self.assertTrue(validate(task).structurally_valid)
        with self.assertRaises(ValueError):
            compose(self.families[0], ["release"], "bad")

    def test_single_property_mutation_and_parent_immutable(self):
        original = deepcopy(self.families[-1])
        changed = mutate(original, "tolerance", 0.5)
        self.assertEqual(original, self.families[-1])
        self.assertEqual(changed["theta"]["tolerance"], [0.005, 0.02])
        self.assertEqual(changed["phi"], original["phi"])
        self.assertEqual(changed["task_graph"], original["task_graph"])
        with self.assertRaises(ValueError):
            mutate(original, "tolerance", 0)

    def test_novelty_distinguishes_parameters_from_composition(self):
        task = self.families[-1]
        self.assertTrue(all(v == 0 for v in novelty(task, [task]).values()))
        score = novelty(mutate(task, "tolerance", 0.5), [task])
        self.assertEqual(score["compositional"], 0)
        self.assertGreater(score["parameter"], 0)
        self.assertGreater(novelty(task, [self.families[0]])["compositional"], 0)

    def test_replay_registration_and_snapshot_isolation(self):
        a, b = TaskGenerator(123), TaskGenerator(123)
        task = self.families[-1]
        self.assertTrue(a.register(task))
        self.assertFalse(a.register(task))
        self.assertEqual(a.sample(task, 2), b.sample(task, 2))
        self.assertNotEqual(a.sample(task, 1)["theta"], a.sample(task, 2)["theta"])
        task["family"] = "changed"
        self.assertEqual(a.archive[0]["family"], "pick_place")
        with self.assertRaises(ValueError):
            a.sample(task, -1)

if __name__ == "__main__":
    unittest.main()
