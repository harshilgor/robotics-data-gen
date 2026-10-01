from copy import deepcopy
import tempfile
import unittest

from factory import LocalFactory
from taskgen.bootstrap import broad_bootstrap
from taskgen.core import validate, fingerprint, novelty, mutate
from taskgen.discovery import TaskDiscovery


class ExtendedTaskTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.factory = LocalFactory(self.directory.name)

    def tearDown(self):
        self.factory.close()
        self.directory.cleanup()

    def test_broad_seed_coverage_role_assets_and_multiobject_execution(self):
        records = self.factory.seed(broad=True)
        self.assertEqual(len(records), 14)
        # Precision bounds reuse the structural pick/place family's identity.
        self.assertEqual(len(self.factory.library.search(family_id="local-pick_place")), 2)
        self.assertFalse(self.factory.library.search(family_id="local-precision_place"))
        batch = self.factory.sample(total=14, seed=12, policy_version="reference", window="broad")
        self.assertEqual(batch["shortfall"], 0)
        result = self.factory.execute(batch)
        self.assertTrue(all(s["success"] for s in result["summaries"]))
        self.assertEqual(len(result["summaries"]), 14)
        names = {self.factory.library.get_family(s["family_id"], s["family_version"])["task"]["family"] for s in result["summaries"]}
        self.assertIn("open_and_retrieve", names)
        self.assertIn("sequential_rearrangement", names)

    def directive(self, capability):
        directive = {"schema_version": "1.0", "policy_version": "policy", "previous_policy_version": None,
                     "budget": {"learn": 0., "explore": 1., "retain": 0.}, "unallocated_budget": 0.,
                     "learn_targets": [], "explore_targets": [{"capabilities": [capability], "parameters": {}, "weight": 1.}],
                     "retain_targets": [], "exclusions": []}
        directive["directive_id"] = fingerprint(directive)
        return directive

    def test_library_first_gap_closure_and_no_redundant_generation(self):
        self.factory.seed()
        directive = self.directive("insert")
        report = TaskDiscovery(self.factory).resolve(directive)
        self.assertEqual(len(report["accepted"]), 1)
        self.assertFalse(report["final_coverage"]["generation_requests"])
        second = TaskDiscovery(self.factory).resolve(directive)
        self.assertEqual(second["candidates_used"], 0)
        self.assertFalse(second["accepted"])
        self.assertTrue(self.factory.repo.records("discovery_run"))

    def test_unexecutable_proposal_is_rejected_with_budget_and_no_publication(self):
        class UnsafeProvider:
            def propose(self, request, vocabulary):
                return [{"code": "__import__('os')"}]
        report = TaskDiscovery(self.factory, proposals=UnsafeProvider()).resolve(self.directive("unsupported"), max_candidates=1)
        self.assertEqual(report["candidates_used"], 1)
        self.assertEqual(len(report["rejected"]), 1)
        self.assertEqual(len(report["unfulfilled"]), 1)
        self.assertFalse(self.factory.library.search())

    def test_extended_grammar_invalid_affordances_preconditions_and_rewards(self):
        insertion = next(t for t in broad_bootstrap() if t["family"] == "insert")
        self.assertTrue(validate(insertion).structurally_valid)
        for modify in (lambda t: t["objects"]["object"].update(requires=["graspable"]),
                       lambda t: t["task_graph"].pop(1),
                       lambda t: t["reward"].append({"term": "eval_python", "weight": 1.}),
                       lambda t: t["scene"].update(template="unknown")):
            task = deepcopy(insertion)
            modify(task)
            self.assertFalse(validate(task).structurally_valid)
        self.assertEqual(novelty(insertion, [deepcopy(insertion)])["structural"], 0.)
        self.assertTrue(validate(mutate(insertion, "tolerance", .5)).structurally_valid)

    def test_guided_composition_keeps_canonical_parent_lineage(self):
        parent = self.factory.seed()[0]
        # The Library has grasp coverage already; use a fresh Library containing
        # only reach so discovery must compose a grasp rather than resample.
        self.factory.close()
        import os
        self.factory = LocalFactory(os.path.join(self.directory.name, "composition"))
        parent = self.factory.publish(parent["task"], source="bootstrap")
        report = TaskDiscovery(self.factory).resolve(self.directive("grasp"))
        self.assertEqual(len(report["accepted"]), 1)
        child = next(r for r in self.factory.library.search() if r["provenance"]["source"] == "composition")
        self.assertEqual(child["provenance"]["source"], "composition")
        self.assertEqual(child["provenance"]["parents"], [{"family_id": "local-reach", "version": "1.0.0"}])


if __name__ == "__main__":
    unittest.main()
