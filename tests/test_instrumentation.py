import unittest
from copy import deepcopy
from taskgen.core import bootstrap_families, TaskGenerator, fingerprint
from task_advisor.core import Advisor
from task_advisor.storage import Store
from task_advisor.instrumentation import (compile_instrumentation, EpisodeTracker,
    StoreRecorder, InstrumentedEnvironments)


def fixture(index=0):
    task = bootstrap_families()[5]
    instance = TaskGenerator(42).sample(task, index)
    evidence = {"family_id": fingerprint(task), "instance_id": fingerprint(instance),
        "validator_version": "fixture-validator", "simulator_version": "fixture-only",
        "report_id": "synthetic-test", "checks": dict.fromkeys(
            ["kinematics", "collision", "physics", "reset_stability"], True)}
    return task, instance, evidence


def frame(step, episode="ep", **changes):
    value = {"episode_id": episode, "step": step, "sim_time": step * .02,
        "timestamp": "2026-10-01T00:00:00Z", "reward": 1.,
        "eef_object_distance": 0., "object_target_distance": 0.,
        "height_above_reset": .05, "object_speed": 0., "grasp_contact": True,
        "gripper_closed": True, "target_support": False, "collision": False,
        "terminated": False, "truncated": False}
    value.update(changes)
    return value


class InstrumentationTests(unittest.TestCase):
    def tracker(self, episode="ep", index=0):
        return EpisodeTracker(compile_instrumentation(*fixture(index)),
                              episode_id=episode, policy_version="p1")

    def test_structural_status_cannot_approve_physics(self):
        task, instance, evidence = fixture()
        with self.assertRaises(ValueError):
            compile_instrumentation(task, instance, instance["validation"])
        for key in evidence["checks"]:
            bad = deepcopy(evidence)
            bad["checks"][key] = False
            with self.assertRaises(ValueError):
                compile_instrumentation(task, instance, bad)
        with self.assertRaises(ValueError):
            compile_instrumentation(task, TaskGenerator(42).sample(task, 2), evidence)

    def test_success_end_to_end_sqlite_advisor(self):
        tracker = self.tracker()
        for step in range(1, 5):
            self.assertIsNone(tracker.observe(frame(step)))
        episode = tracker.observe(frame(5, grasp_contact=False, gripper_closed=False,
                                       target_support=True, terminated=True))
        self.assertTrue(episode["success"])
        self.assertEqual(episode["grasp_losses"], 0)
        store = Store(":memory:")
        try:
            tracker.finish(StoreRecorder(store))
            snapshot = Advisor().advise("p1", store.records("tasks"), store.records("episodes"))
            self.assertEqual(snapshot["evidence_ids"], ["ep"])
            self.assertTrue(all(v is True for v in episode["subgoal_results"].values()))
            with self.assertRaises(ValueError):
                tracker.finish(StoreRecorder(store))
        finally:
            store.close()

    def test_unreached_stages_and_high_reward_failure(self):
        tracker = self.tracker()
        ep = tracker.observe(frame(1, eef_object_distance=10., reward=1000., terminated=True))
        self.assertFalse(ep["success"])
        self.assertEqual(list(ep["subgoal_results"].values()), [False, None, None, None, None])

    def test_collision_edges_grasp_loss_and_terminal_goal(self):
        tracker = self.tracker()
        tracker.observe(frame(1, collision=True))
        tracker.observe(frame(2, collision=True))
        ep = tracker.observe(frame(3, grasp_contact=False, collision=False, truncated=True))
        self.assertEqual(ep["collisions"], 1)
        self.assertEqual(ep["grasp_losses"], 1)
        self.assertTrue(ep["timed_out"])
        tracker = self.tracker()
        for i in range(1, 5):
            tracker.observe(frame(i))
        tracker.observe(frame(5, grasp_contact=False, target_support=True))
        ep = tracker.observe(frame(6, object_target_distance=10., terminated=True))
        self.assertFalse(ep["success"])
        self.assertEqual(ep["failure_type"], "goal_not_maintained")

    def test_bad_frames_no_mutation(self):
        for changes in ({"step": 2}, {"episode_id": "post-reset"},
                        {"object_speed": float("nan")}, {"collision": 1},
                        {"timestamp": "invalid"}):
            tracker = self.tracker()
            with self.assertRaises(ValueError):
                sample = frame(1)
                sample.update(changes)
                tracker.observe(sample)
            self.assertEqual(tracker.frames, [])

    def test_environment_isolation_and_retry(self):
        class Sink:
            def __init__(self): self.records = []
            def record(self, annotation, episode): self.records.append(episode)
        class Adapter:
            def frame(self, env): return frame(1, episode=env, terminated=True)
        sink = Sink()
        bridge = InstrumentedEnvironments(sink)
        for env in ("a", "b"):
            bridge.start(env, self.tracker(env))
        with self.assertRaises(ValueError): bridge.start("a", self.tracker("a"))
        self.assertEqual(bridge.step("a", Adapter())["episode_id"], "a")
        self.assertIn("b", bridge.trackers)
        bridge.step("b", Adapter())
        self.assertEqual(len(sink.records), 2)

    def test_failed_recorder_retries_same_terminal_record(self):
        class Flaky:
            def __init__(self): self.count = 0
            def record(self, annotation, episode):
                self.count += 1
                if self.count == 1: raise OSError("temporary recorder failure")
        tracker = self.tracker()
        tracker.observe(frame(1, terminated=True))
        sink = Flaky()
        with self.assertRaises(OSError): tracker.finish(sink)
        self.assertFalse(tracker.closed)
        self.assertEqual(len(tracker.finish(sink)["instrumentation"]["frames"]), 1)


if __name__ == "__main__":
    unittest.main()
