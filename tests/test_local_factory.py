from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from assets import local_resources
from factory import LocalFactory
from taskgen.core import TaskGenerator, fingerprint
from simulation import LocalSimulationAdapter


class LocalFactoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.factory = LocalFactory(self.directory.name)
        self.families = self.factory.seed()

    def tearDown(self):
        self.factory.close()
        self.directory.cleanup()

    def test_six_governed_families_compile_validate_execute_and_catalog(self):
        self.assertEqual(len(self.families), 6)
        batch = self.factory.sample(total=6, seed=3, policy_version="p0", window="test")
        self.assertEqual(batch["shortfall"], 0)
        result = self.factory.execute(batch, environments=3, interrupt_first=True)
        self.assertEqual(len(result["summaries"]), 6)
        self.assertTrue(all(s["success"] for s in result["summaries"]))
        self.assertEqual(result["feedback"]["interrupted_attempts"], 1)
        self.assertEqual(result["feedback"]["executed_episodes"], 6)
        manifest = self.factory.catalog.create("local-recordings", 1,
            [a["assignment_id"] for a in batch["assignments"]], created_at="2026-10-01T12:00:00Z", deduplicate=False)
        self.assertEqual(manifest["episode_count"], 6)
        self.assertEqual(len(list(self.factory.catalog.records(manifest["dataset_id"]))), 6)
        self.assertTrue(self.factory.advise("p0")["regions"])
        self.assertEqual(self.factory.seed(), self.families)

    def test_validator_layers_and_reference_failure_is_unknown(self):
        task = self.families[-1]["task"]
        instance = TaskGenerator(2).sample(task)
        report = self.factory.validator.validate(task, instance, max_reference_steps=1)
        self.assertTrue(all(report["layers"].values()))
        self.assertEqual(report["reference_controller_evidence"]["status"], "failed")
        self.assertEqual(report["feasibility_status"], "unknown")
        self.assertEqual(report["validation_scope"], "synthetic_model_only")
        bad = deepcopy(instance)
        bad["theta"]["object_size"] = .08
        rejected = self.factory.validator.validate(task, bad)
        self.assertEqual(rejected["feasibility_status"], "rejected_contextually")
        self.assertFalse(rejected["checks"]["physics"])

    def test_compiler_pinned_resources_and_artifact_tampering(self):
        task = self.families[0]["task"]
        compiled = self.factory.compiler.compile(task)
        self.assertEqual(compiled, self.factory.compiler.compile(task))
        self.assertIn("semantic_registry", compiled)
        self.assertIn("collision_geometry", compiled["objects"]["object"]["definition"])
        modified = deepcopy(compiled)
        modified["robot"]["definition"]["workspace_radius"] = 100.
        with self.assertRaisesRegex(ValueError, "digest"):
            LocalSimulationAdapter().configure("env", modified, "key", {})

    def test_motion_failure_and_environment_isolation(self):
        batch = self.factory.sample(total=2, seed=5, policy_version="stalled", window="failure")
        from task_advisor.worker import AssignmentEnvironments
        adapter = LocalSimulationAdapter(policies={"stalled": {"gain": 0.}})
        bridge = AssignmentEnvironments(self.factory.scheduler, adapter, clock=lambda: 1.)
        for i, assignment in enumerate(batch["assignments"]):
            bridge.start(str(i), assignment["assignment_id"], "attempt-" + str(i), worker_id="worker", ttl=100.)
        before = deepcopy(adapter.environments["1"])
        bridge.step("0")
        self.assertEqual(before, adapter.environments["1"])
        while "0" in bridge.sessions:
            summary = bridge.step("0")
        self.assertFalse(summary["success"])
        self.assertEqual(summary["termination_reason"], "timeout")
        self.assertEqual(summary["control_step_count"], 300)
        bridge.interrupt("1", reason="finish isolation test")

    def test_resource_role_lookup_and_immutable_versions(self):
        resources = local_resources()
        assets = resources.resolve_role(["insertable"], versions={"cube": "1.0.0", "peg": "1.0.0"})
        self.assertEqual([a["name"] for a in assets], ["peg"])
        with self.assertRaisesRegex(ValueError, "immutable"):
            resources.register("asset", "peg", "1.0.0", {"shape": "unknown"})


if __name__ == "__main__":
    unittest.main()
