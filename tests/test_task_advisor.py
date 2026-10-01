from copy import deepcopy
import unittest
from taskgen.core import bootstrap_families
from task_advisor import Advisor, Config, Store, task_annotation


def task():
    return task_annotation(bootstrap_families()[1])


def episode(i, success=True, policy="new", source="training"):
    t = task()
    return {"episode_id": f"{policy}-{source}-{i}", "policy_version": policy, "source": source,
        "family_id": t["family_id"], "family_version": 1, "task_instance_id": f"instance-{i}",
        "task_parameters": {"tolerance": .015}, "success": success, "reward": float(success),
        "completion_fraction": float(success), "episode_length": 30,
        "subgoal_results": {"s0": True, "s1": success}, "timestamp": f"2026-09-30T12:{i//60:02}:{i%60:02}+00:00"}


class AdvisorTests(unittest.TestCase):
    def test_stage_attribution(self):
        output = Advisor().advise("new", [task()], [episode(1, False)])
        caps = {c["capability_id"]: c for c in output["capabilities"]}
        self.assertEqual(caps["reach"]["successes"], 1)
        self.assertEqual(caps["grasp"]["successes"], 0)
        ep = episode(2, False)
        ep["subgoal_results"] = {"s0": False, "s1": None}
        output = Advisor().advise("new", [task()], [ep])
        self.assertEqual(next(c for c in output["capabilities"] if c["capability_id"] == "grasp")["sample_count"], 0)
        self.assertTrue(any(t["capabilities"] == ["grasp"] and t["reason"] == "coverage_gap"
                            for t in output["directive"]["explore_targets"]))
        ep["subgoal_results"]["s1"] = False
        with self.assertRaises(ValueError):
            Advisor().advise("new", [task()], [ep])

    def test_beta_and_small_sample_unknown(self):
        output = Advisor().advise("new", [task()], [episode(1), episode(2)])
        r = output["regions"][0]
        self.assertEqual(r["state"], "UNKNOWN")
        self.assertEqual(r["success_estimate"], .75)
        self.assertIsNone(r["learning_progress"])

    def test_state_progress_and_retention(self):
        for old_count, new_count, state in ((5, 20, "FRONTIER"), (25, 5, "REGRESSING"), (30, 30, "MASTERED"), (0, 0, "STALLED")):
            records = [episode(i, i<old_count, "old") for i in range(30)] + [episode(i, i<new_count) for i in range(30)]
            output = Advisor().advise("new", [task()], records, "old")
            self.assertEqual(output["regions"][0]["state"], state)
            if state == "REGRESSING":
                self.assertEqual(len(output["directive"]["retain_targets"]), 1)

    def test_sealed_rejected_and_development_separate(self):
        for source in ("sealed", "test", "evaluation"):
            with self.assertRaises(ValueError):
                Advisor().advise("new", [task()], [episode(1, source=source)])
        records = [episode(i, source="development") for i in range(30)]
        output = Advisor().advise("new", [task()], records)
        self.assertEqual(output["regions"][0]["sample_count"], 0)
        self.assertEqual(output["regions"][0]["development_score"]["sample_count"], 30)

    def test_distribution_and_versions_not_pooled(self):
        records = [episode(i, False, "old") for i in range(30)] + [episode(i, True) for i in range(30)]
        for ep in records[30:]:
            ep["task_parameters"]["tolerance"] = .03
        records += [episode(1, policy="irrelevant")]
        output = Advisor().advise("new", [task()], records, "old")
        self.assertTrue(all(r["learning_progress"] is None for r in output["regions"]))
        self.assertNotIn("irrelevant-training-1", output["evidence_ids"])

    def test_sparse_combinations_and_directive_weights(self):
        few = Advisor().advise("new", [task()], [episode(1)])
        self.assertEqual(few["combinations"], [])
        many = Advisor().advise("new", [task()], [episode(i) for i in range(30)])
        self.assertEqual(len(many["combinations"]), 1)
        for name in ("learn", "explore", "retain"):
            targets = few["directive"][name+"_targets"]
            if targets:
                self.assertAlmostEqual(sum(t["weight"] for t in targets), 1)
        self.assertAlmostEqual(sum(few["directive"]["budget"].values()) + few["directive"]["unallocated_budget"], 1)
        self.assertEqual(few, Advisor().advise("new", [task()], [episode(1)]))

    def test_store_atomic_immutable_and_feedback(self):
        store = Store(":memory:")
        self.addCleanup(store.close)
        store.ingest([task()], [episode(1)])
        store.ingest([task()], [episode(1)])
        self.assertEqual(len(store.records("episodes")), 1)
        bad = episode(1)
        bad["reward"] = 99
        with self.assertRaises(ValueError):
            store.ingest(episodes=[episode(2), bad])
        self.assertEqual(len(store.records("episodes")), 1)
        snap = Advisor().advise("new", store.records("tasks"), store.records("episodes"))
        store.save_snapshot(snap)
        store.save_snapshot(snap)
        feedback = {"feedback_id": "f1", "directive_id": snap["directive"]["directive_id"],
            "requested": 100, "generated": 80, "validated": 50, "scheduled": 40, "executed_episodes": 0}
        store.ingest(feedback=[feedback])
        self.assertEqual(store.records("feedback")[0]["validated"], 50)
        changed = deepcopy(snap)
        changed["regions"] = []
        with self.assertRaises(ValueError):
            store.save_snapshot(changed)

    def test_malformed_evidence_and_config(self):
        for field, value in (("success", 1), ("reward", float("nan")), ("timestamp", "bad"), ("episode_length", -1), ("completion_fraction", 1.1)):
            ep = episode(1)
            ep[field] = value
            with self.assertRaises(ValueError):
                Advisor().advise("new", [task()], [ep])
        with self.assertRaises(ValueError):
            Advisor(Config(budget={"learn": 1, "explore": 1, "retain": 1}))
        with self.assertRaises(ValueError):
            Advisor().advise("new", [task()], [episode(1), episode(1)])


if __name__ == "__main__":
    unittest.main()
