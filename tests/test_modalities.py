from copy import deepcopy
import tempfile
import unittest
from factory import LocalFactory
from simulation.camera import capture
from data.modalities import validate_frame


class ModalityTests(unittest.TestCase):
    def test_synchronized_external_sensors_curated_and_corruption_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = LocalFactory(directory)
            try:
                factory.seed()
                batch = factory.sample(total=1, seed=17, policy_version="p0", window="sensors",
                    recording_profile={"trajectory": True, "modalities": ["rgb", "depth"]})
                result = factory.execute(batch)
                self.assertTrue(result["summaries"][0]["success"])
                manifest = factory.catalog.create("sensors", 1, [batch["assignments"][0]["assignment_id"]],
                    created_at="2026-10-01T12:00:00Z")
                self.assertEqual(manifest["episode_count"], 1)
                trajectory = list(factory.catalog.records(manifest["dataset_id"]))[0]["trajectory"]
                self.assertNotIn("privileged_state", trajectory)
                self.assertEqual(len(trajectory["modalities"]), len(trajectory["samples"]))
                ref = trajectory["modalities"][0]["depth"]["payload_reference"]
                factory.repo.payload_store._path(ref["sha256"], ref["media_type"]).write_bytes(b"corrupt")
                with self.assertRaisesRegex(ValueError, "integrity"):
                    list(factory.catalog.records(manifest["dataset_id"]))
                rejected = factory.catalog.create("sensors", 2, [batch["assignments"][0]["assignment_id"]],
                    created_at="2026-10-01T12:00:00Z")
                self.assertEqual(rejected["episode_count"], 0)
            finally:
                factory.close()

    def test_malformed_sensor_timing_shape_encoding_rejected(self):
        environment = {"eef": [0., 0., 0.], "object": [.1, 0., .02], "target": [.2, 0., .02]}
        for name, measured in capture(environment, ["rgb", "depth"], .02).items():
            payload = measured.pop("payload")
            validate_frame(name, measured, payload, .02)
            for key, value in (("timestamp", .04), ("shape", [0, 32]), ("units", "unknown")):
                bad = deepcopy(measured)
                bad[key] = value
                with self.assertRaises(ValueError): validate_frame(name, bad, payload, .02)
            with self.assertRaises(ValueError): validate_frame(name, measured, payload[:-2], .02)
