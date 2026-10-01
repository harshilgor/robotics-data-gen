"""Synthetic fixtures test orchestration, not simulated robot capability."""
from copy import deepcopy
import unittest

from taskgen.core import bootstrap_families, fingerprint
from task_advisor.core import Advisor
from task_advisor.storage import Store
from task_advisor.loop import Repository, TaskLibrary, CurriculumSampler, AssignmentScheduler, AssignmentRecorder, numeric_instance, quotas
from task_advisor.evaluation import BenchmarkRegistry
from task_advisor.research import ResearchLedger, uniform_directive
from task_advisor.instrumentation import compile_instrumentation, EpisodeTracker
from task_advisor.instrumentation import InstrumentedEnvironments


def evidence(task, instance=None):
    data = {"family_id": fingerprint(task), "report_id": "synthetic-fixture-only",
        "validator_version": "fixture-v1", "simulator_version": "synthetic-v1",
        "checks": dict.fromkeys(("kinematics", "collision", "physics", "reset_stability"), True)}
    if instance is None: data["envelope"] = {**task["theta"], **task["phi"]}
    else: data["instance_id"] = fingerprint(instance)
    return data


def publish(library, task):
    artifact = {"fixture_scene": task["family"]}
    contract = {"family_id": fingerprint(task), "family_version": task["revision"], "status": "active",
        "supported_embodiments": ["so101"], "supported_controller_references": ["fixture-controller-v1"],
        "compiled_artifact_reference": "fixture-"+fingerprint(task), "compiled_artifact_hash": fingerprint(artifact),
        "execution_compatibility_key": "fixture-"+task["family"], "compiler_version": "fixture-v1",
        "success_predicate_version": "1", "reward_version": "1", "instance_constructor_id": "numeric-v1",
        "observation_schema_id": task["interfaces"]["observation"], "action_schema_id": task["interfaces"]["action"],
        "validation_evidence": evidence(task), "parameter_schema": {}}
    for group in ("theta", "phi"):
        for key, bounds in task[group].items():
            contract["parameter_schema"][key] = {"type": "float", "units": "fixture-units",
                "bounds": bounds, "sampling_role": group, "application_stage": "build" if key == "object_size" else "reset"}
    return library.publish(task, contract, artifact)


class Runtime:
    """Synthetic measured runtime explicitly used only in tests."""
    def __init__(self, fail=False, mutate=False): self.fail, self.mutate = fail, mutate
    def load_frozen_policy(self, checkpoint): self.digest = checkpoint["digest"]
    def policy_digest(self): return self.digest
    def begin_probe(self, family, instance, *, seed): self.step_number = 0
    def step(self, episode_id):
        self.step_number += 1
        if self.mutate: self.digest = "changed"
        return {"episode_id": episode_id, "step": self.step_number, "sim_time": self.step_number*.02,
            "timestamp": "2026-10-01T10:00:00Z", "reward": 1., "eef_object_distance": 5. if self.fail else 0.,
            "object_target_distance": 0., "height_above_reset": 0., "object_speed": 0.,
            "grasp_contact": False, "gripper_closed": False, "target_support": True,
            "collision": False, "terminated": self.fail or self.step_number >= 2, "truncated": False}


class ClosedLoopTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.repo = Repository(self.store)
        self.library = TaskLibrary(self.repo)
        self.families = [publish(self.library, bootstrap_families()[i]) for i in (0, 2)]
        self.sampler = CurriculumSampler(self.repo, self.library, {"numeric-v1": numeric_instance}, {"numeric-v1": evidence})
        self.scheduler = AssignmentScheduler(self.repo, self.library)
        self.registry = BenchmarkRegistry(self.repo, self.library)
        self.directive = uniform_directive("p0", self.families)
        snapshot = {"directive": self.directive, "snapshot_id": "baseline-fixture"}
        self.store.save_snapshot(snapshot)

    def tearDown(self): self.store.close()

    def sample(self, **kwargs):
        return self.sampler.sample(self.directive, total=4, seed=42, controller_id="fixture-controller-v1", **kwargs)

    def execute(self, assignment, attempt, fail=False):
        identity = assignment["assignment_id"]
        self.scheduler.lease(identity, "worker", attempt, now=0, ttl=20,
                             compatibility_key=assignment["execution_compatibility_key"])
        self.scheduler.start(identity, attempt, now=1)
        task = self.library.get_family(assignment["family_id"], assignment["family_version"])["task"]
        tracker = EpisodeTracker(compile_instrumentation(task, assignment["instance"], assignment["physical_evidence"]),
            episode_id=attempt, policy_version=assignment["policy_checkpoint_id"])
        runtime = Runtime(fail=fail)
        runtime.begin_probe({}, {}, seed=0)
        while tracker.ready is None: tracker.observe(runtime.step(attempt))
        recorder = AssignmentRecorder(self.scheduler, identity, attempt,
            realized_parameters={**assignment["instance"]["theta"], **assignment["instance"]["phi"]},
            initial_state={"fixture_reset": True}, simulator_version="synthetic-v1",
            environment_version="fixture-v1", clock=lambda: 2)
        tracker.finish(recorder)
        return self.repo.get("completion", identity)["episode"]

    def manifest(self):
        cases = self.registry.generate_cases([(f["contract"]["family_id"], 1) for f in self.families], seed=123, per_family=2, validator=evidence)
        return self.registry.freeze("development-fixture", 1, cases, seed=123)

    def test_library_immutable_exact_artifact_and_copy(self):
        task = bootstrap_families()[0]
        family = self.library.get_family(fingerprint(task), 1)
        bad = deepcopy(family["contract"])
        bad["compiler_version"] = "changed"
        with self.assertRaises(ValueError): self.library.publish(task, bad, {"fixture_scene": "reach"})
        family["task"]["family"] = "changed"
        self.assertEqual(self.library.get_family(fingerprint(task), 1)["task"]["family"], "reach")
        with self.assertRaises(ValueError): self.library.get_family(fingerprint(task), 2)

    def test_sampling_replay_quotas_and_no_execution_evidence(self):
        batch = self.sample()
        self.assertEqual(batch, self.sample())
        self.assertEqual(len(batch["assignments"]), 4)
        self.assertEqual(quotas({"learn": .5, "explore": .5}, 3)["explore"], 2)
        feedback = self.scheduler.feedback(batch["request_id"])
        self.assertEqual(feedback["executed_episodes"], 0)
        self.assertEqual(self.store.records("episodes"), [])
        self.assertEqual({a["family_id"] for a in batch["assignments"]}, {f["contract"]["family_id"] for f in self.families})

    def test_shortfall_and_no_silent_fallback(self):
        directive = deepcopy(self.directive)
        directive["learn_targets"][0]["parameters"] = {"tolerance": {"lower": 10., "upper": 20.}}
        del directive["directive_id"]
        directive["directive_id"] = fingerprint(directive)
        batch = self.sampler.sample(directive, total=4, seed=2, controller_id="fixture-controller-v1")
        self.assertEqual(batch["shortfall"], 2)
        self.assertEqual(batch["fallbacks"], [])
        self.assertTrue(batch["diagnostics"][0]["reasons"])

    def test_interruption_retry_idempotent_completion_and_feedback(self):
        batch = self.sample()
        assignment = batch["assignments"][0]
        aid = assignment["assignment_id"]
        self.scheduler.lease(aid, "worker-a", "interrupted", now=0, ttl=10,
                             compatibility_key=assignment["execution_compatibility_key"])
        self.scheduler.start(aid, "interrupted", now=1)
        self.scheduler.interrupt(aid, "interrupted", now=2, reason="worker_disconnect")
        self.assertEqual(self.store.records("episodes"), [])
        episode = self.execute(assignment, "retry")
        self.scheduler.complete(aid, "retry", episode, now=4)
        with self.assertRaises(ValueError): self.scheduler.complete(aid, "interrupted", episode, now=4)
        self.assertEqual(len(self.store.records("episodes")), 1)
        self.assertEqual(self.scheduler.feedback(batch["request_id"])["executed_episodes"], 1)
        snapshot = Advisor().advise("p0", self.store.records("tasks"), self.store.records("episodes"))
        self.assertEqual(len(snapshot["evidence_ids"]), 1)

    def test_lease_expiration_and_worker_compatibility(self):
        a = self.sample()["assignments"][0]; aid = a["assignment_id"]
        with self.assertRaises(ValueError): self.scheduler.lease(aid, "w", "a", now=0, ttl=1, compatibility_key="wrong")
        self.scheduler.lease(aid, "w", "a", now=0, ttl=1, compatibility_key=a["execution_compatibility_key"])
        with self.assertRaises(ValueError): self.scheduler.start(aid, "a", now=2)
        self.scheduler.lease(aid, "w2", "b", now=2, ttl=10, compatibility_key=a["execution_compatibility_key"])
        self.scheduler.renew(aid, "b", now=3, ttl=20)
        with self.assertRaises(ValueError): self.scheduler.renew(aid, "a", now=3, ttl=20)

    def test_parallel_smoke_two_families_with_worker_interruption(self):
        batch = self.sample()
        assignments = [batch["assignments"][0], batch["assignments"][2]]
        first = assignments[0]
        self.scheduler.lease(first["assignment_id"], "lost-worker", "lost-attempt", now=0, ttl=10,
            compatibility_key=first["execution_compatibility_key"])
        self.scheduler.start(first["assignment_id"], "lost-attempt", now=1)
        self.scheduler.interrupt(first["assignment_id"], "lost-attempt", now=2, reason="worker_lost")
        recorders, runtimes = {}, {}
        class Router:
            def record(self, annotation, episode): recorders[episode["episode_id"]].record(annotation, episode)
        class Adapter:
            def frame(self, env): return runtimes[env].step(env)
        bridge = InstrumentedEnvironments(Router())
        for index, assignment in enumerate(assignments):
            env = f"parallel-{index}"
            aid = assignment["assignment_id"]
            self.scheduler.lease(aid, "parallel-worker", env, now=3, ttl=10, compatibility_key=assignment["execution_compatibility_key"])
            self.scheduler.start(aid, env, now=4)
            task = self.library.get_family(assignment["family_id"], assignment["family_version"])["task"]
            tracker = EpisodeTracker(compile_instrumentation(task, assignment["instance"], assignment["physical_evidence"]), episode_id=env, policy_version="p0")
            recorders[env] = AssignmentRecorder(self.scheduler, aid, env,
                realized_parameters={**assignment["instance"]["theta"], **assignment["instance"]["phi"]},
                initial_state={"fixture_env": index}, simulator_version="synthetic-v1", environment_version="fixture-v1", clock=lambda: 5)
            runtimes[env] = Runtime(); runtimes[env].begin_probe({}, {}, seed=index)
            bridge.start(env, tracker)
        for _ in range(2):
            for env in list(bridge.trackers): bridge.step(env, Adapter())
        self.assertFalse(bridge.trackers)
        episodes = self.store.records("episodes")
        self.assertEqual(len(episodes), 2)
        self.assertEqual(len({e["family_id"] for e in episodes}), 2)
        self.assertEqual(self.scheduler.feedback(batch["request_id"])["executed_episodes"], 2)

    def test_frozen_development_probe_membership_and_no_training_leak(self):
        manifest = self.manifest()
        self.registry.register_checkpoint("p0", {"synthetic_weights": 0})
        run = self.registry.run(manifest["manifest_id"], "p0", Runtime())
        self.assertEqual(run["sample_count"], 4)
        self.assertEqual(run, self.registry.run(manifest["manifest_id"], "p0", Runtime(fail=True)))
        self.assertTrue(all(e["source"] == "development" for e in self.store.records("episodes")))
        ep = deepcopy(self.store.records("episodes")[0])
        ep["episode_id"] = "tampered"
        with self.assertRaises(ValueError): self.store.ingest(episodes=[ep])
        ep["source"] = "training"
        with self.assertRaises(ValueError): self.store.ingest(episodes=[ep])
        ep["source"] = "sealed"
        with self.assertRaises(ValueError): self.store.ingest(episodes=[ep])
        changed = deepcopy(manifest["cases"])
        changed[0]["probe_seed"] += 1
        with self.assertRaises(ValueError): self.registry.freeze("development-fixture", 1, changed, seed=123)

    def test_mutating_policy_probe_is_rejected_atomically(self):
        manifest = self.manifest()
        self.registry.register_checkpoint("p0", {"weights": 0})
        with self.assertRaises(ValueError): self.registry.run(manifest["manifest_id"], "p0", Runtime(mutate=True))
        self.assertEqual(self.store.records("episodes"), [])
        self.assertEqual(self.repo.records("evaluation_run"), [])

    def test_multi_seed_budget_matched_research_orchestration(self):
        manifest = self.manifest()
        self.registry.register_checkpoint("p0", {"weights": 0})
        ledger = ResearchLedger(self.repo)
        ledger.plan("experiment", manifest["manifest_id"], [11, 22], control_steps=4)
        outer = self
        class Trainer:
            def train_trial(self, *, arm, seed, initial_checkpoint, step_budget, experiment_id):
                directive = uniform_directive(initial_checkpoint, outer.families)
                batch = outer.sampler.sample(directive, total=2, seed=seed,
                    controller_id="fixture-controller-v1", experiment={"experiment_id": experiment_id, "arm": arm, "seed": seed})
                for i, assignment in enumerate(batch["assignments"]): outer.execute(assignment, f"{arm}-{seed}-{i}")
                return {"policy_version": f"{arm}-{seed}", "artifact": {"weights": f"{arm}-{seed}"},
                    "assignment_ids": [a["assignment_id"] for a in batch["assignments"]]}
        report = ledger.run_experiment("experiment", self.registry, Runtime, Trainer(), {11: "p0", 22: "p0"})
        self.assertEqual(len(self.repo.records("training_block")), 4)
        self.assertTrue(all(r["seed_count"] == 2 for r in report["comparisons"]))
        self.assertTrue(all(r["mean_difference"] == 0 for r in report["comparisons"]))
        self.assertEqual(report, ledger.run_experiment("experiment", self.registry, Runtime, Trainer(), {11: "p0", 22: "p0"}))
        with self.assertRaises(ValueError): ledger.plan("one-seed", manifest["manifest_id"], [1], control_steps=4)


if __name__ == "__main__": unittest.main()
