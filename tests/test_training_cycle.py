from copy import deepcopy
import tempfile
import unittest

from factory import LocalFactory
from factory.__main__ import run_cycle
from training import CheckpointStore, MotionCloningBackend


class TrainingCycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.factory = LocalFactory(self.directory.name)

    def tearDown(self):
        self.factory.close()
        self.directory.cleanup()

    def test_complete_synthetic_cycle_frozen_suite_and_external_payloads(self):
        result = run_cycle(self.factory, episodes=6)
        self.assertEqual(result["families"], 6)
        self.assertEqual(result["before_evaluation"]["manifest_id"], result["after_evaluation"]["manifest_id"])
        self.assertEqual(result["before_evaluation"]["success_rate"], 0.)
        self.assertEqual(result["after_evaluation"]["success_rate"], 1.)
        self.assertEqual(result["demonstration_feedback"]["interrupted_attempts"], 1)
        self.assertEqual(result["dataset"]["episode_count"], 6)
        self.assertEqual(result["training_feedback"]["executed_episodes"], 6)
        self.assertEqual(len(self.factory.store.records("episodes")), 30)  # 24 fixed probes + 6 training
        evaluation_instances = {e["task_instance_id"] for e in self.factory.store.records("episodes") if e["source"] == "development"}
        training_instances = {e["task_instance_id"] for e in self.factory.store.records("episodes") if e["source"] == "training"}
        self.assertFalse(evaluation_instances & training_instances)
        self.assertTrue(all(e["purpose"] == "demonstration" for e in result["dataset"]["episodes"]))

    def test_checkpoint_immutable_and_weight_corruption_rejected(self):
        checkpoints = CheckpointStore(self.factory.repo)
        checkpoint = checkpoints.save("p0", {"gain": .001}, backend="test")
        self.assertEqual(checkpoints.load("p0")["gain"], .001)
        with self.assertRaisesRegex(ValueError, "immutable"):
            checkpoints.save("p0", {"gain": .002}, backend="test")
        path = self.factory.repo.payload_store._path(checkpoint["artifact"]["weights"]["sha256"])
        path.write_bytes(b"invalid")
        with self.assertRaisesRegex(ValueError, "integrity"):
            checkpoints.load("p0")

    def test_trainer_rejects_empty_or_evaluation_data(self):
        manifest = self.factory.catalog.create("empty", 1, [], created_at="2026-10-01T12:00:00Z")
        with self.assertRaisesRegex(ValueError, "demonstrations"):
            MotionCloningBackend().train(self.factory.catalog, manifest["dataset_id"])


if __name__ == "__main__":
    unittest.main()
