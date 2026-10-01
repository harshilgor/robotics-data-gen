from copy import deepcopy
import unittest
from taskgen.core import bootstrap_families, mutate
from task_advisor.storage import Store
from task_advisor.loop import Repository
from task_library import TaskLibrary, structural_signature

DEPS = dict.fromkeys(("task_dsl", "predicate_library", "capability_ontology", "object_ontology"), "1")
CONTEXT = dict.fromkeys(("robot", "gripper", "controller", "compiler_version", "validator_version", "simulator_version"), "fixture-v1")
PROVENANCE = {"source": "human", "parents": [], "proposal_id": "fixture", "generator_version": "1"}


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.library = TaskLibrary(Repository(self.store))
        self.task = bootstrap_families()[5]
        self.library.register("pick_place", "1.0.0", self.task, dependencies=DEPS, provenance=PROVENANCE)

    def tearDown(self): self.store.close()

    def test_structural_identity_and_immutable_versions(self):
        changed = mutate(self.task, "tolerance", .5)
        self.assertEqual(structural_signature(changed), structural_signature(self.task))
        with self.assertRaises(ValueError):
            self.library.register("pick_place", "1.0.0", changed, dependencies=DEPS, provenance=PROVENANCE)
        with self.assertRaises(ValueError):
            self.library.register("pick_place", "1.1.0", changed, dependencies=DEPS, provenance=PROVENANCE)
        self.library.register("pick_place", "2.0.0", changed, dependencies=DEPS, provenance=PROVENANCE)
        self.assertEqual(len(self.library.search()), 2)

    def test_semver_major_minor_patch_and_lineage(self):
        with self.assertRaises(ValueError):
            self.library.register("pick_place", "1.0.1", mutate(self.task, "tolerance", 2), dependencies=DEPS, provenance=PROVENANCE)
        provenance = {**PROVENANCE, "source": "mutation", "parents": [{"family_id": "pick_place", "version": "1.0.0"}]}
        extension = mutate(self.task, "tolerance", 2)
        extension["theta"]["tolerance"][0] = self.task["theta"]["tolerance"][0]
        self.library.register("pick_place", "1.1.0", extension, dependencies=DEPS, provenance=provenance)
        self.assertEqual(len(self.library.lineage("pick_place", "1.1.0")), 2)
        self.assertEqual(len(self.library.search(capabilities=["grasp", "release"], parameters=["mass"])), 2)
        self.assertEqual(self.library.nearest(self.task)[0]["distance"], 0)

    def test_lifecycle_contextual_rejection_and_no_fake_activation(self):
        l = self.library
        for index, state in enumerate(("STRUCTURALLY_ACCEPTED", "VALIDATING", "REJECTED_CONTEXTUALLY", "VALIDATING", "VALID")):
            l.transition("pick_place", "1.0.0", state, event_id=str(index), reason="fixture", context=CONTEXT)
        with self.assertRaises(ValueError): l.transition("pick_place", "1.0.0", "ACTIVE", event_id="active", reason="fixture")
        l.transition("pick_place", "1.0.0", "ARCHIVED", event_id="archive", reason="fixture")
        self.assertEqual(l.get_version("pick_place", "1.0.0")["status"], "ARCHIVED")
        with self.assertRaises(ValueError): l.transition("pick_place", "1.0.0", "VALID", event_id="revive", reason="fixture")

    def test_validation_envelopes_context_conflicts_and_unknown(self):
        bounds = {**self.task["theta"], **self.task["phi"]}
        params = {k: sum(v)/2 for k, v in bounds.items()}
        l = self.library
        self.assertEqual(l.feasibility("pick_place", "1.0.0", params, CONTEXT)["status"], "unknown")
        l.add_validation("pick_place", "1.0.0", context=CONTEXT, regions=[bounds], outcome="valid", report_id="pass",
            evidence_reference="synthetic-only", checks=dict.fromkeys(("kinematics", "collision", "physics", "reset_stability"), True))
        self.assertEqual(l.feasibility("pick_place", "1.0.0", params, CONTEXT)["status"], "valid")
        l.add_validation("pick_place", "1.0.0", context=CONTEXT, regions=[bounds], outcome="invalid", report_id="fail", evidence_reference="fixture")
        self.assertEqual(l.feasibility("pick_place", "1.0.0", params, CONTEXT)["status"], "conflict")
        other = {**CONTEXT, "controller": "new-controller"}
        self.assertEqual(l.feasibility("pick_place", "1.0.0", params, other)["status"], "unknown")

    def test_dependencies_and_sparse_generation_requests(self):
        with self.assertRaises(ValueError): self.library.register("bad", "1.0.0", self.task, dependencies={}, provenance=PROVENANCE)
        result = self.library.resolve_directive({"learn_targets": [{"capabilities": ["insert"]}], "explore_targets": [], "retain_targets": []})
        self.assertEqual(len(result["generation_requests"]), 1)


if __name__ == "__main__": unittest.main()
