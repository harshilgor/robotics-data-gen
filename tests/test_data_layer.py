from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from data import LocalObjectStore, DatasetCatalog, integrity_report
from curriculum_sampler.synthetic import setup, SyntheticAdapter
from task_advisor.storage import Store
from task_advisor.worker import AssignmentEnvironments
from taskgen.core import fingerprint


class DataLayerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.objects = LocalObjectStore(self.root / "objects")
        self.store = Store(str(self.root / "metadata.sqlite3"))
        self.repo, self.library, self.sampler, self.scheduler, self.directive = setup(self.store)
        self.repo.payload_store = self.objects
        self.catalog = DatasetCatalog(self.repo, self.library)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def execute(self, purpose="training", failure=False):
        directive = deepcopy(self.directive)
        directive["episode_purpose"] = purpose
        directive["window"]["window_id"] = "data-" + purpose
        directive.pop("directive_id")
        directive["directive_id"] = fingerprint(directive)
        assignment = self.sampler.sample(directive, now=0.)["assignments"][0]
        bridge = AssignmentEnvironments(self.scheduler, SyntheticAdapter(fail_goal=failure), clock=lambda: 1.)
        bridge.start("env", assignment["assignment_id"], "attempt-" + purpose, worker_id="worker", ttl=100.)
        while "env" in bridge.sessions:
            bridge.step("env")
        return assignment

    def create(self, ids, **kwargs):
        return self.catalog.create("fixture-data", 1, ids, created_at="2026-10-01T12:00:00Z", **kwargs)

    def test_external_payload_metadata_and_reopen_checksum(self):
        assignment = self.execute()
        summary = self.repo.get("episode_summary", assignment["assignment_id"])
        reference = summary["trajectory_reference"]
        stored = json.loads(self.repo.db.execute("SELECT payload FROM loop_records WHERE kind='trajectory' AND identity=?", (reference,)).fetchone()[0])
        self.assertEqual(set(stored), {"external_payload"})
        self.assertLess(len(json.dumps(stored)), 300)
        trajectory = self.repo.get("trajectory", reference)
        from task_advisor.loop import Repository
        self.assertEqual(trajectory, Repository(self.store, payload_store=self.objects).get("trajectory", reference))
        with self.assertRaisesRegex(ValueError, "configured"):
            Repository(self.store).get("trajectory", reference)
        path = self.objects._path(stored["external_payload"]["sha256"])
        path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.repo.get("trajectory", reference)

    def test_manifest_exact_provenance_replay_and_privileged_exclusion(self):
        assignment = self.execute()
        manifest = self.create([assignment["assignment_id"]])
        self.assertEqual(manifest["episode_count"], 1)
        self.assertEqual(manifest, self.create([assignment["assignment_id"]]))
        entry = manifest["episodes"][0]
        self.assertEqual(entry["family_version"], "1.0.0")
        self.assertIn("predicate_library", entry["semantic_dependencies"])
        self.assertEqual(entry["task_instance"], assignment["instance"])
        records = list(self.catalog.records(manifest["dataset_id"]))
        self.assertNotIn("privileged_state", records[0]["trajectory"])
        output = self.root / "dataset.jsonl"
        self.catalog.export_jsonl(manifest["dataset_id"], output)
        self.assertEqual(len(output.read_text().splitlines()), 1)
        with self.assertRaises(FileExistsError):
            self.catalog.export_jsonl(manifest["dataset_id"], output)
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.catalog.create("fixture-data", 1, [], created_at="2026-10-01T12:00:00Z")

    def test_failures_retained_and_demonstration_rejections_not_exported(self):
        training = self.execute(failure=True)
        demonstration = self.execute(purpose="demonstration", failure=True)
        manifest = self.create([training["assignment_id"], demonstration["assignment_id"]])
        self.assertEqual(manifest["episode_count"], 1)
        self.assertFalse(manifest["episodes"][0]["success"])
        self.assertEqual(manifest["excluded"][0]["reasons"], ["recording_not_accepted"])
        self.assertEqual(len(self.repo.records("episode_summary")), 2)

    def test_integrity_detects_bad_timing_schema_and_terminal(self):
        assignment = self.execute()
        summary = self.repo.get("episode_summary", assignment["assignment_id"])
        contract = self.library.get_sampling_contract(assignment["family_id"], assignment["family_version"])
        trajectory = self.repo.get("trajectory", summary["trajectory_reference"])
        for mutate in (lambda t: t["samples"][0].update(next_observation_time=-1.),
                       lambda t: t["samples"][-1].update(terminal=False),
                       lambda t: t.update(schema={}),
                       lambda t: t["samples"][0]["actions"].update(joint_target=float("nan"))):
            bad = deepcopy(trajectory)
            mutate(bad)
            self.assertFalse(integrity_report(bad, summary, assignment, contract)["valid"])

    def test_evaluation_policy_required_and_missing_payload_excluded(self):
        with self.assertRaisesRegex(ValueError, "evaluation"):
            self.create([], purposes=("evaluation",))
        assignment = self.execute()
        summary = self.repo.get("episode_summary", assignment["assignment_id"])
        row = json.loads(self.repo.db.execute("SELECT payload FROM loop_records WHERE kind='trajectory' AND identity=?", (summary["trajectory_reference"],)).fetchone()[0])
        self.objects._path(row["external_payload"]["sha256"]).unlink()
        manifest = self.create([assignment["assignment_id"]])
        self.assertEqual(manifest["episode_count"], 0)
        self.assertIn("missing", manifest["excluded"][0]["reasons"][0])

    def test_object_store_idempotence_and_path_traversal(self):
        reference = self.objects.put({"frames": [1, 2, 3]})
        self.assertEqual(reference, self.objects.put({"frames": [1, 2, 3]}))
        self.assertEqual(self.objects.get(reference), {"frames": [1, 2, 3]})
        with self.assertRaises(ValueError):
            self.objects.get({**reference, "sha256": "../outside"})


if __name__ == "__main__":
    unittest.main()
