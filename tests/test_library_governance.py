import json
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from contextlib import contextmanager
import uuid


@contextmanager
def workspace_database():
    # Avoid tempfile's restrictive chmod on Windows managed workspaces.
    path = Path.cwd() / ("library-test-" + uuid.uuid4().hex + ".sqlite3")
    try: yield str(path)
    finally:
        for suffix in ("", "-journal", "-wal", "-shm"):
            candidate = Path(str(path) + suffix)
            if candidate.exists(): candidate.unlink()

from taskgen.core import bootstrap_families, fingerprint, mutate
from task_advisor.storage import Store
from task_advisor.loop import Repository, TaskLibrary as LegacyLibrary, CurriculumSampler, numeric_instance, AssignmentScheduler
from task_advisor.research import uniform_directive
from task_library import TaskLibrary
from test_closed_loop import publish, evidence
from test_task_library import DEPS, PROVENANCE


def context(contract):
    return {"robot": "so101", "gripper": "fixture-gripper", "controller": "fixture-controller-v1",
        "compiler_version": contract["compiler_version"], "validator_version": "fixture-v1", "simulator_version": "synthetic-v1"}


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:"); self.repo = Repository(self.store)
        self.library = TaskLibrary(self.repo); self.task = bootstrap_families()[5]
        # Explicit migration tests historical legacy storage without making it
        # eligible merely because it exists.
        self.execution = publish(LegacyLibrary(self.repo), self.task)
        self.ctx = context(self.execution["contract"])
        self.library.migrate_legacy(fingerprint(self.task), 1, family_id="pick_place", version="1.0.0",
            dependencies=DEPS, provenance=PROVENANCE, context=self.ctx)
        self.library.transition("pick_place", "1.0.0", "ACTIVE", event_id="activate", reason="fixture")

    def tearDown(self): self.store.close()

    def test_duplicate_reconciliation_and_recorded_override(self):
        altered = mutate(self.task, "tolerance", .5)
        self.assertEqual(self.library.reconcile(altered)["decision"], "existing_family")
        with self.assertRaises(ValueError): self.library.register("duplicate", "1.0.0", altered, dependencies=DEPS, provenance=PROVENANCE)
        decision = self.library.identity_override(altered, family_id="intentional", reason="explicit separate research identity", decision_id="override")
        record = self.library.register("intentional", "1.0.0", altered, dependencies=DEPS, provenance=PROVENANCE, identity_decision=decision)
        self.assertEqual(record["family_id"], "intentional")

    def test_context_coverage_and_sampler_enforcement(self):
        bounds = {**self.task["theta"], **self.task["phi"]}
        self.assertEqual(self.library.compatibility("pick_place", "1.0.0", self.ctx)["status"], "compatible")
        other = {**self.ctx, "controller": "other"}
        self.assertFalse(self.library.search(context=other))
        blocked = deepcopy(bounds); blocked["tolerance"][1] = .02
        self.library.add_validation("pick_place", "1.0.0", context=self.ctx, regions=[blocked], outcome="invalid",
            report_id="blocked", evidence_reference="synthetic-negative")
        coverage = self.library.supported_regions("pick_place", "1.0.0", self.ctx)
        self.assertTrue(coverage["gaps"])
        self.assertTrue(all(r["tolerance"][0] > .02 for r in coverage["supported"]))
        directive = uniform_directive("p1", [self.execution])
        directive["learn_targets"][0]["parameters"] = {"tolerance": {"lower": .01, "upper": .02}}
        del directive["directive_id"]; directive["directive_id"] = fingerprint(directive)
        result = self.library.resolve_directive(directive, context=self.ctx)
        self.assertTrue(result["generation_requests"]); self.assertFalse(result["resolved"])
        sampler = CurriculumSampler(self.repo, self.library, {"numeric-v1": numeric_instance}, {"numeric-v1": evidence})
        batch = sampler.sample(directive, total=4, seed=2, controller_id="fixture-controller-v1")
        self.assertEqual(batch["shortfall"], 4)
        self.assertFalse(batch["assignments"])

    def test_governed_publication_and_artifact_patch_replay(self):
        with self.assertRaises(ValueError): self.library.publish(self.task, self.execution["contract"], {"fixture_scene": "pick_place"})
        patch_task = deepcopy(self.task); patch_task["revision"] = 2
        self.library.register("pick_place", "1.0.1", patch_task, dependencies=DEPS, provenance=PROVENANCE)
        for state in ("STRUCTURALLY_ACCEPTED", "VALIDATING", "VALID"):
            self.library.transition("pick_place", "1.0.1", state, event_id="patch-"+state, reason="new implementation")
        contract = deepcopy(self.execution["contract"])
        artifact = {"fixture_scene": "new-artifact"}
        contract.update(family_id=fingerprint(patch_task), family_version=2,
            compiled_artifact_reference="new-reference", compiled_artifact_hash=fingerprint(artifact))
        contract["validation_evidence"]["family_id"] = fingerprint(patch_task)
        self.library.publish_version("pick_place", "1.0.1", contract, artifact, context=self.ctx)
        self.assertNotEqual(self.library.binding("pick_place", "1.0.0")["artifact_hash"], self.library.binding("pick_place", "1.0.1")["artifact_hash"])
        self.assertEqual(self.library.get_compiled_artifact(self.library.binding("pick_place", "1.0.0")["artifact_reference"]), {"fixture_scene": "pick_place"})
        self.library.transition("pick_place", "1.0.0", "DEPRECATED", event_id="deprecate", reason="replacement")
        self.assertFalse(self.library.list_eligible_families())
        self.library.transition("pick_place", "1.0.1", "ACTIVE", event_id="patch-active", reason="replacement")
        self.assertEqual(len(self.library.list_eligible_families()), 1)

    def test_snapshot_restore_checksum_and_reopen(self):
        snapshot = self.library.snapshot()
        with workspace_database() as path:
            store = Store(path); restored = TaskLibrary(Repository(store))
            bad = deepcopy(snapshot); bad["digest"] = "bad"
            with self.assertRaises(ValueError): restored.restore(bad)
            self.assertEqual(restored.restore(snapshot), snapshot)
            store.close()
            store = Store(path); restored = TaskLibrary(Repository(store))
            self.assertEqual(restored.snapshot(), snapshot)
            self.assertEqual(restored.binding("pick_place", "1.0.0")["context"], self.ctx)
            store.close()

    def test_atomic_publication_rollback_and_legacy_exclusion(self):
        legacy = publish(LegacyLibrary(self.repo), bootstrap_families()[0])
        self.assertEqual(len(self.library.list_eligible_families()), 1)
        bad = deepcopy(self.execution["contract"]); bad["compiler_version"] = "wrong"
        before = self.library.snapshot()
        with self.assertRaises(ValueError): self.library.publish_version("pick_place", "1.0.0", bad, {"fixture_scene": "pick_place"}, context=self.ctx)
        self.assertEqual(before, self.library.snapshot())

    def test_new_assignments_and_leases_respect_updated_approval(self):
        sampler = CurriculumSampler(self.repo, self.library, {"numeric-v1": numeric_instance}, {"numeric-v1": evidence})
        directive = uniform_directive("p1", [self.execution])
        batch = sampler.sample(directive, total=2, seed=42, controller_id="fixture-controller-v1")
        self.assertEqual(len(batch["assignments"]), 2)
        assignment = batch["assignments"][0]
        bounds = {**self.task["theta"], **self.task["phi"]}
        self.library.add_validation("pick_place", "1.0.0", context=self.ctx, regions=[bounds], outcome="invalid",
            report_id="invalidate-all", evidence_reference="fixture")
        scheduler = AssignmentScheduler(self.repo, self.library)
        with self.assertRaises(ValueError): scheduler.lease(assignment["assignment_id"], "w", "attempt", now=0, ttl=10,
                compatibility_key=assignment["execution_compatibility_key"])
        second = sampler.sample(directive, total=2, seed=42, controller_id="fixture-controller-v1")
        self.assertNotEqual(batch["request_id"], second["request_id"])
        self.assertFalse(second["assignments"])

    def test_restore_corruption_rolls_back(self):
        snapshot = self.library.snapshot()
        snapshot["tables"]["library_bindings"][0][5] = json.dumps({"family_id": "missing", "version": "1.0.0"})
        payload = deepcopy(snapshot); payload.pop("digest")
        snapshot["digest"] = fingerprint(payload)
        store = Store(":memory:"); restored = TaskLibrary(Repository(store))
        try:
            with self.assertRaises(ValueError): restored.restore(snapshot)
            self.assertFalse(restored.search())
            self.assertFalse(restored.repo.records("family"))
        finally: store.close()

    def test_concurrent_lifecycle_mutations(self):
        with workspace_database() as path:
            store = Store(path); library = TaskLibrary(Repository(store)); library.restore(self.library.snapshot()); store.close()
            barrier, results = threading.Barrier(2), []
            def mutate_state(state):
                store = Store(path); library = TaskLibrary(Repository(store))
                try:
                    barrier.wait()
                    library.transition("pick_place", "1.0.0", state, event_id=state, reason="concurrent-test")
                    results.append("ok")
                except ValueError: results.append("rejected")
                finally: store.close()
            threads = [threading.Thread(target=mutate_state, args=(s,)) for s in ("DEPRECATED", "ARCHIVED")]
            for thread in threads: thread.start()
            for thread in threads: thread.join(timeout=10)
            self.assertEqual(len(results), 2)
            store = Store(path); library = TaskLibrary(Repository(store))
            self.assertIn(library.get_version("pick_place", "1.0.0")["status"], {"ARCHIVED", "DEPRECATED"})
            store.close()


if __name__ == "__main__": unittest.main()

