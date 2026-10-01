"""Synthetic software contracts: these tests establish no physical feasibility."""
from copy import deepcopy
from pathlib import Path
import json
import tempfile
import threading
import unittest

from taskgen.core import fingerprint, TaskGenerator, validate
from taskgen.parameters import check_values, schema_contract
from task_advisor.storage import Store
from task_advisor.loop import Repository, CurriculumSampler, AssignmentScheduler
from task_advisor.curriculum import Registry, validate_directive, region_quotas
from task_advisor.evaluation import BenchmarkRegistry
from task_advisor.execution import export_dataset, trajectory_quality
from task_advisor.core import Advisor
from task_advisor.worker import AssignmentEnvironments
from task_library import TaskLibrary
from curriculum_sampler.synthetic import setup, evidence, fixture_task, contract_for, SyntheticAdapter, smoke


def seal(d):
    d = deepcopy(d); d.pop("directive_id",None); d["directive_id"] = fingerprint(d); return d


class SamplerTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.repo,self.library,self.sampler,self.scheduler,self.directive = setup(self.store)
    def tearDown(self): self.store.close()
    def sample(self,d=None): return self.sampler.sample(d or self.directive,now=0.)
    def changed_directive(self,**changes):
        d = deepcopy(self.directive); d.update(changes); return seal(d)
    def point(self):
        d = deepcopy(self.directive)
        for regions in d["family_region_allocations"].values():
            for r in regions:
                c = self.library.get_sampling_contract(r["family_id"],r["family_version"])
                r["parameter_restrictions"] = {k:[.07,.07] if k=="corridor_width" else [v["bounds"][0],v["bounds"][0]] for k,v in c["parameter_schema"].items() if v["type"] != "categorical"}
                r["categorical_filters"] = {"surface":["mat"]}
        return seal(d)
    def execute(self,a,*,adapter=None,attempt="attempt",bridge=None,env="env"):
        adapter = adapter or SyntheticAdapter()
        bridge = bridge or AssignmentEnvironments(self.scheduler,adapter,clock=lambda:1.)
        bridge.start(env,a["assignment_id"],attempt,worker_id="worker",ttl=20.)
        result = None
        while result is None: result = bridge.step(env)
        return result,bridge

    def test_baseline_compatible_and_typed_task_dsl(self):
        t = fixture_task(0)
        self.assertTrue(validate(t).structurally_valid)
        i = TaskGenerator(1).sample(t)
        check_values(t["theta"],i["theta"]); check_values(t["phi"],i["phi"])
        bad = deepcopy(t); bad["phi"]["surface"]["values"] = ["mat","mat"]
        self.assertFalse(validate(bad).structurally_valid)
        bad = deepcopy(t); bad["theta"]["obstacle_count"]["bounds"] = [0,.5]
        self.assertFalse(validate(bad).structurally_valid)

    def test_complete_contract_and_immutable_publication(self):
        batch = self.sample()
        self.assertTrue(batch["assignments"])
        required = {"directive_version","embodiment_id","controller_version","region_version","origin_region","task_parameters","environment_parameters","initial_state_specification","goal_specification","validation_result","observation_schema_id","action_schema_id"}
        self.assertTrue(required <= set(batch["assignments"][0]))
        contract = self.library.get_sampling_contract(batch["assignments"][0]["family_id"],1)
        task = self.library.get_family(contract["family_id"],1)["task"]
        from task_advisor.curriculum import validate_contract
        for field in ("units","coordinate_frame","dependencies","application_stage"):
            bad = deepcopy(contract); bad["parameter_schema"]["mass"].pop(field)
            with self.assertRaises(ValueError,msg=field): validate_contract(task,bad)
        bad = deepcopy(contract); bad["parameter_schema"]["mass"]["dependencies"] = ["friction"]
        bad["parameter_schema"]["friction"]["dependencies"] = ["mass"]
        with self.assertRaises(ValueError): validate_contract(task,bad)
        c = deepcopy(contract); c["reward_version"] = "changed"
        binding = next(b for b in self.library.search() if b["task_content_hash"]==contract["family_id"])
        context = self.library.binding(binding["family_id"],binding["version"])["context"]
        with self.assertRaises(ValueError): self.library.publish_version(binding["family_id"],binding["version"],c,self.library.get_compiled_artifact(c["compiled_artifact_reference"]),context=context)
        self.assertEqual(self.library.get_sampling_contract(contract["family_id"],1),contract)

    def test_malformed_directives_and_controller_rejected(self):
        for update in ({"total_episode_budget":True},{"category_allocations":{"learn":1.1,"explore":0.,"retain":0.}},{"max_candidate_attempts":0},{"controller_version":"wrong"},{"episode_purpose":"evaluation"},{"recording_profile":{}},{"diversity":{"mode":"unique_parameters","dimensions":["unknown"],"balanced_categorical":True}}):
            with self.assertRaises(ValueError,msg=str(update)): self.sample(self.changed_directive(**update))
        d = deepcopy(self.directive); d["family_region_allocations"]["learn"][0].pop("family_version")
        with self.assertRaises(ValueError): self.sample(seal(d))
        d = deepcopy(self.directive); d["family_region_allocations"]["learn"][0]["parameter_restrictions"] = {"unknown":[0,1]}
        with self.assertRaises(ValueError): self.sample(seal(d))

    def test_exclusions_and_capability_contradiction(self):
        r = self.directive["family_region_allocations"]["learn"][0]
        for exclusion in ({"region_id":r["region_id"]},{"family_id":r["family_id"]},{"capabilities":["reach"]}):
            with self.assertRaises(ValueError): self.sample(self.changed_directive(exclusions=[exclusion]))

    def test_registry_cannot_execute_generated_strings_or_missing_dependencies(self):
        registry = Registry().register("constructor","typed-instance-v1",lambda *a: {})
        sampler = CurriculumSampler(self.repo,self.library,registry=registry)
        with self.assertRaises(ValueError): sampler.sample(self.directive,now=0.)
        with self.assertRaises(ValueError): Registry().register("constraint","x","eval(unsafe)")
        registry = Registry().register("constraint","x",lambda p:True,dependencies=["unknown"])
        with self.assertRaises(ValueError): registry.resolve("constraint","x",{"mass":{}})
        with self.assertRaises(ValueError): registry.register("constraint","x",lambda p:False)

    def test_constraint_rejections_and_stratified_categorical_balance(self):
        d = deepcopy(self.directive)
        for regions in d["family_region_allocations"].values():
            for r in regions:
                r["parameter_restrictions"] = {"corridor_width":[.07,.08]}
        b = self.sample(seal(d)); self.assertEqual(b["shortfall"],0)
        by_family = {}
        for a in b["assignments"]:
            by_family.setdefault(a["family_id"],[]).append(a)
            self.assertGreaterEqual(a["task_parameters"]["corridor_width"],a["task_parameters"]["object_size"]+.005)
        for rows in by_family.values():
            self.assertEqual(sum(a["environment_parameters"]["surface"]=="mat" for a in rows),2)
            bins = {int((a["task_parameters"]["target_distance"]-.04)/.12*4) for a in rows}
            self.assertEqual(bins,{0,1,2,3})
        bad = deepcopy(d); bad["window"]["window_id"] = "invalid-joint-region"
        for r in bad["family_region_allocations"]["learn"]:
            r["parameter_restrictions"]["corridor_width"] = [.025,.025]; r["region_version"] = 2
        b = self.sample(seal(bad)); self.assertEqual(b["shortfall"],8)
        self.assertTrue(all("constraint: corridor-clearance-v1" in diag["reasons"] for diag in b["diagnostics"]))
        self.assertEqual(self.store.records("episodes"),[])

    def test_quota_ties_minimum_coverage_and_unallocated(self):
        regions = [{"region_id":"b","weight":.5},{"region_id":"a","weight":.5}]
        self.assertEqual(region_quotas(regions,[],3),{"b":1,"a":2})
        self.assertEqual(region_quotas(regions,[{"region_id":"b","minimum":2}],3),{"b":2,"a":1})
        d = deepcopy(self.directive); r = d["family_region_allocations"]["learn"][0]
        d["minimum_coverage_requirements"] = [{"category":"learn","region_id":r["region_id"],"minimum":9}]
        with self.assertRaises(ValueError): self.sample(seal(d))
        d["minimum_coverage_requirements"][0]["minimum"] = 3
        b = self.sample(seal(d)); self.assertGreaterEqual(next(x for x in b["diagnostics"] if x["region_id"]==r["region_id"])["requested"],5)
        d = self.changed_directive(category_allocations={"learn":.5,"explore":0.,"retain":0.})
        d["window"]["window_id"] = "unallocated"; d = seal(d)
        b = self.sample(d); self.assertEqual(b["category_quotas"]["unallocated"],4); self.assertGreaterEqual(b["shortfall"],4)

    def test_requested_diversity_vs_controlled_repetition(self):
        point = self.point()
        b = self.sample(point); self.assertEqual(len(b["assignments"]),8)
        self.assertEqual(len({a["assignment_id"] for a in b["assignments"]}),8)
        values = {(a["family_id"],json.dumps(a["task_parameters"],sort_keys=True)) for a in b["assignments"]}
        self.assertEqual(len(values),2)
        unique = deepcopy(point); unique["window"]["window_id"] = "unique"
        unique["diversity"]["mode"] = "unique_parameters"
        b = self.sample(seal(unique)); self.assertEqual(len(b["assignments"]),2); self.assertEqual(b["shortfall"],6)
        self.assertTrue(any("requested diversity duplicate" in d["reasons"] for d in b["diagnostics"]))

    def test_explicit_fallback_and_no_silent_region_widening(self):
        d = deepcopy(self.directive); source = d["family_region_allocations"]["learn"][0]
        fallback = deepcopy(source); fallback["region_id"] = "fallback-region"
        fallback["parameter_restrictions"] = {"corridor_width":[.07,.08]}
        source["parameter_restrictions"] = {"corridor_width":[.025,.025]}
        d["allowed_fallbacks"] = [{"category":"learn","from_region_id":source["region_id"],"to_region":fallback}]
        b = self.sample(seal(d))
        self.assertEqual(b["fallbacks"][0]["accepted"],4)
        rows = [a for a in b["assignments"] if a["fallback_from_region_id"]]
        self.assertEqual(len(rows),4); self.assertTrue(all(a["region_id"]=="fallback-region" for a in rows))
        self.assertTrue(all(a["task_parameters"]["corridor_width"]>=.07 for a in rows))
        d["allowed_fallbacks"] = []; d["window"]["window_id"] = "no-fallback"
        b = self.sample(seal(d)); self.assertGreaterEqual(b["shortfall"],4); self.assertFalse(b["fallbacks"])

    def test_overlapping_regions_retain_origin_and_exact_version(self):
        d = self.point(); d = deepcopy(d)
        first = d["family_region_allocations"]["learn"][0]
        second = deepcopy(first); second["region_id"] = "overlap"
        d["family_region_allocations"]["learn"] = [first,second]
        b = self.sample(seal(d))
        self.assertEqual({a["region_id"] for a in b["assignments"]},{first["region_id"],"overlap"})
        self.assertTrue(all(a["origin_region"]["family_version"]==1 for a in b["assignments"]))

    def test_window_freeze_expiry_and_future_directives(self):
        b = self.sample()
        with self.assertRaises(ValueError): self.sampler.sample(self.directive,now=100.)
        changed = self.changed_directive(seed=43)
        with self.assertRaises(ValueError): self.sample(changed)
        changed["window"]["window_id"] = "future"; changed = seal(changed)
        self.assertNotEqual(b["request_id"],self.sample(changed)["request_id"])
        a = b["assignments"][0]
        with self.assertRaises(ValueError): self.scheduler.lease(a["assignment_id"],"w","a",now=100.,ttl=2.,compatibility_key=a["execution_compatibility_key"])
        self.scheduler.expire(now=100.)
        self.assertEqual(self.repo.db.execute("SELECT state FROM assignment_state WHERE identity=?",(a["assignment_id"],)).fetchone()[0],"expired")

    def test_compatibility_and_context_approval_at_lease(self):
        b = self.sample(); a = b["assignments"][0]
        with self.assertRaises(ValueError): self.scheduler.lease(a["assignment_id"],"w","a",now=1.,ttl=2.,compatibility_key="wrong")
        binding = next(r for r in self.library.search() if r["task_content_hash"]==a["family_id"])
        context = self.library.binding(binding["family_id"],binding["version"])["context"]
        bounds = {**binding["task_spec"]["theta"],**binding["task_spec"]["phi"]}
        self.library.add_validation(binding["family_id"],binding["version"],context=context,regions=[bounds],outcome="invalid",report_id="synthetic-block-all",evidence_reference="synthetic")
        with self.assertRaises(ValueError): self.scheduler.lease(a["assignment_id"],"w","a",now=1.,ttl=2.,compatibility_key=a["execution_compatibility_key"])
        new = deepcopy(self.directive); new["window"]["window_id"] = "after-invalidation"
        self.assertTrue(self.sample(seal(new))["shortfall"])

    def test_separate_validation_status_reference_failure_not_impossibility(self):
        c,_ = contract_for(fixture_task(0)); c["reference_check_id"] = "reference-failed-v1"
        from task_advisor.curriculum import build_assignment
        a = self.sample()["assignments"][0]; record = self.library.get_family(a["family_id"],1)
        e = deepcopy(a["physical_evidence"]); e["reference_controller_evidence"] = {"status":"failed","reason":"synthetic-controller-limitation"}; e["feasibility_status"] = "unknown"
        rebuilt = build_assignment(record,a["origin_region"],a["instance"],{**a["task_parameters"],**a["environment_parameters"]},e,request_id="r",directive=self.directive,category="learn",sampling_seed=1,ordinal=0)
        self.assertEqual(rebuilt["validation_result"]["reference_controller_evidence"]["status"],"failed")
        self.assertEqual(rebuilt["validation_result"]["feasibility_status"],"unknown")
        self.assertEqual(set(rebuilt["validation_result"])-{"report_id"},{"instantiation_validity","geometric_or_kinematic_checks","reference_controller_evidence","feasibility_status"})

    def test_leases_renew_interrupt_retry_fail_cancel_and_idempotence(self):
        b = self.sample(); a = b["assignments"][0]; aid = a["assignment_id"]
        self.scheduler.lease(aid,"w","lost",now=0.,ttl=10.,compatibility_key=a["execution_compatibility_key"])
        self.scheduler.start(aid,"lost",now=1.); self.scheduler.renew(aid,"lost",now=2.,ttl=20.)
        with self.assertRaises(ValueError): self.scheduler.lease(aid,"w","steal",now=3.,ttl=5.,compatibility_key=a["execution_compatibility_key"])
        self.scheduler.interrupt(aid,"lost",now=3.,reason="worker-interrupted")
        result,bridge = self.execute(a,attempt="retry")
        completion = self.repo.get("completion",aid)
        self.assertEqual(result["execution_attempt_id"],"retry")
        self.assertEqual(len(self.store.records("episodes")),1)
        # Recorder retry uses original measured terminal input, not a stripped record.
        with self.assertRaises(ValueError): self.scheduler.complete(aid,"lost",completion["episode"],now=4.)
        other = b["assignments"][1]
        self.scheduler.lease(other["assignment_id"],"w","failure",now=0.,ttl=10.,compatibility_key=other["execution_compatibility_key"])
        self.scheduler.fail(other["assignment_id"],"failure",now=1.,reason="adapter-error")
        with self.assertRaises(ValueError): self.scheduler.lease(other["assignment_id"],"w","retry-forbidden",now=2.,ttl=10.,compatibility_key=other["execution_compatibility_key"])
        self.scheduler.cancel(b["assignments"][2]["assignment_id"])
        feedback = self.scheduler.feedback(b["request_id"])
        self.assertEqual(feedback["executed_episodes"],1); self.assertEqual(feedback["interrupted_attempts"],1)

    def test_expired_lease_recovery_stale_attempt_and_liveness(self):
        a = self.sample()["assignments"][0]; aid = a["assignment_id"]
        self.scheduler.lease(aid,"w","expired",now=0.,ttl=1.,compatibility_key=a["execution_compatibility_key"])
        self.scheduler.start(aid,"expired",now=.1)
        self.assertEqual(self.scheduler.expire(now=2.),[aid])
        with self.assertRaises(ValueError): self.scheduler.renew(aid,"expired",now=2.,ttl=10.)
        self.execute(a,attempt="recovered")
        self.assertEqual(len(self.store.records("episodes")),1)

    def test_parallel_environment_reset_isolation_terminal_order_and_stage_methods(self):
        b = self.sample(); a,c = b["assignments"][:2]
        adapter = SyntheticAdapter(); bridge = AssignmentEnvironments(self.scheduler,adapter,clock=lambda:1.)
        bridge.start("a",a["assignment_id"],"a1",worker_id="w",ttl=20.)
        bridge.start("b",c["assignment_id"],"b1",worker_id="w",ttl=20.)
        bridge.step("b"); before = deepcopy(adapter.envs["b"])
        bridge.step("a"); summary = bridge.step("a")
        self.assertEqual(adapter.envs["b"],before)
        self.assertIn("b",bridge.sessions); self.assertEqual(summary["control_step_count"],2)
        events = [e[1] for e in adapter.events if e[0]=="a"]
        self.assertLess(events.index("install"),events.index("reset")); self.assertEqual(events[-2:],["pre_reset_frame","finalized"])
        for env,event,*data in adapter.events:
            if event=="build": self.assertIn("mass",data[0]); self.assertNotIn("sensor_gain",data[0])
            if event=="apply_reset": self.assertNotIn("mass",data[0])
            if event=="apply_step": self.assertEqual(set(data[0]),{"sensor_gain"})
        bridge.step("b")
        self.assertEqual(len({s["episode_id"] for s in self.repo.records("episode_summary")}),2)

    def test_recorder_failure_retry_retains_terminal_without_new_physics(self):
        a = self.sample()["assignments"][0]; adapter = SyntheticAdapter()
        bridge = AssignmentEnvironments(self.scheduler,adapter,clock=lambda:1.)
        bridge.start("env",a["assignment_id"],"retry-record",worker_id="w",ttl=20.)
        bridge.step("env"); recorder = bridge.sessions["env"]["recorder"]; real = recorder.record
        recorder.record = lambda *args: (_ for _ in ()).throw(RuntimeError("disk fixture failure"))
        with self.assertRaises(RuntimeError): bridge.step("env")
        frames = sum(e[1]=="pre_reset_frame" for e in adapter.events)
        self.assertIn("env",bridge.sessions)
        recorder.record = real; bridge.step("env")
        self.assertEqual(sum(e[1]=="pre_reset_frame" for e in adapter.events),frames)
        self.assertEqual(len(self.store.records("episodes")),1)
        # The same recorder may retry exact terminal input after a lost ACK.
        summary = self.repo.get("episode_summary",a["assignment_id"])
        self.assertEqual(summary["execution_attempt_id"],"retry-record")
        self.assertEqual(len(self.repo.records("completion")),1)

    def test_realized_mismatch_fails_initialization_without_policy_evidence(self):
        class BadReset(SyntheticAdapter):
            def reset(self,*args):
                state = super().reset(*args); state["realized_parameters"]["mass"] = 99.; self.envs[args[0]]["realized"] = state; return state
        a = self.sample()["assignments"][0]
        with self.assertRaises(ValueError): self.execute(a,adapter=BadReset())
        self.assertFalse(self.store.records("episodes")); self.assertTrue(self.repo.records("execution_failure"))

    def test_demonstration_quality_rejections_retained_and_privileged_separation(self):
        d = self.changed_directive(episode_purpose="demonstration",policy_checkpoint_id=None)
        b = self.sample(d)
        accepted,_ = self.execute(b["assignments"][0],attempt="demo-good")
        rejected,_ = self.execute(b["assignments"][1],adapter=SyntheticAdapter(bad_action=True),attempt="demo-bad")
        self.assertEqual(accepted["recording_status"],"accepted"); self.assertEqual(rejected["recording_status"],"rejected")
        self.assertTrue(rejected["success"]); self.assertTrue(rejected["quality_rejection_reasons"])
        self.assertEqual(len(self.repo.records("episode_summary")),2); self.assertFalse(self.store.records("episodes"))
        exported = export_dataset(self.repo)
        self.assertEqual(len(exported),1); self.assertNotIn("privileged_state",exported[0]["trajectory"])
        bad,_ = self.execute(b["assignments"][2],adapter=SyntheticAdapter(collisions=True),attempt="demo-collision")
        self.assertIn("demonstration physical constraint/collision limit",bad["quality_rejection_reasons"])
        self.assertFalse(self.store.records("episodes"))

    def test_trajectory_timing_units_frames_and_observation_schema_quality(self):
        b = self.sample(); a = b["assignments"][0]; summary,_ = self.execute(a)
        trajectory = self.repo.get("trajectory",summary["trajectory_reference"])
        c = self.library.get_sampling_contract(a["family_id"],a["family_version"])
        # Construct timing-only quality episode from the recorded trajectory.
        ep = {"episode_length":2,"success":True,"instrumentation":{"frames":[{"sim_time":.02},{"sim_time":.04}]}}
        for change in ("units","frame","timing","privileged_leak","terminal"):
            bad = deepcopy(trajectory)
            if change=="units": bad["schema"]["actions"]["joint_target"]["units"] = "m"
            elif change=="frame": bad["schema"]["observations"]["position"]["coordinate_frame"] = "robot"
            elif change=="timing": bad["samples"][0]["action_time"] = .1
            elif change=="terminal": bad["samples"][0]["terminal"] = True
            else: bad["samples"][0]["observations"]["secret"] = 1.
            self.assertTrue(trajectory_quality(bad,a,c,ep),change)

    def test_summary_only_and_policy_failure_are_completed_execution(self):
        d = self.changed_directive(recording_profile={"trajectory":False})
        b = self.sample(d); summary,_ = self.execute(b["assignments"][0],adapter=SyntheticAdapter(fail_goal=True))
        self.assertEqual(summary["execution_status"],"completed"); self.assertEqual(summary["termination_reason"],"policy_failure")
        self.assertEqual(summary["recording_status"],"not_requested"); self.assertFalse(self.repo.records("trajectory"))
        self.assertNotIn("frames",self.store.records("episodes")[0]["instrumentation"])

    def test_fixed_evaluation_assignments_frozen_policy_and_training_dataset_exclusion(self):
        registry = BenchmarkRegistry(self.repo,self.library)
        families = [(r["contract"]["family_id"],1) for r in self.library.list_eligible_families()]
        # Generate bounded valid exact cases through the registered constraint checks.
        cases = []
        for fid,version in families:
            task = self.library.get_family(fid,version)["task"]
            for seed in range(100):
                instance = TaskGenerator(seed).sample(task)
                if instance["theta"]["corridor_width"] >= instance["theta"]["object_size"]+.005:
                    cases.append({"family_id":fid,"family_version":version,"instance":instance,"physical_evidence":evidence(task,instance),"probe_seed":500+seed}); break
        manifest = registry.freeze("held-out-synthetic",1,cases,seed=500,registry=self.sampler.registry)
        checkpoint = registry.register_checkpoint("frozen",{"weights":"synthetic-only"})
        batch = registry.assignments(manifest["manifest_id"],"frozen",controller_id="synthetic-controller",controller_version="v1",starts_at=0.,expires_at=100.)
        self.assertEqual(batch,registry.assignments(manifest["manifest_id"],"frozen",controller_id="synthetic-controller",controller_version="v1",starts_at=0.,expires_at=100.))
        adapter = SyntheticAdapter(); adapter.checkpoint_digest = checkpoint["digest"]
        summary,_ = self.execute(batch["assignments"][0],adapter=adapter,attempt="evaluation")
        self.assertEqual(summary["episode_purpose"],"evaluation"); self.assertFalse(self.store.records("episodes"))
        self.assertEqual(export_dataset(self.repo),[])
        self.assertEqual(len(export_dataset(self.repo,include_evaluation=True,policy_id="explicit-research-export")),1)
        # Changing only the seed/index cannot leak identical physical parameters.
        d = self.point(); d = deepcopy(d); case = cases[0]
        region = next(r for r in d["family_region_allocations"]["learn"] if r["family_id"]==case["family_id"])
        region["parameter_restrictions"] = {k:[v,v] for k,v in {**case["instance"]["theta"],**case["instance"]["phi"]}.items() if not isinstance(v,str)}
        region["categorical_filters"] = {"surface":[case["instance"]["phi"]["surface"]]}
        result = self.sample(seal(d)); self.assertTrue(any("held-out evaluation specification" in x["reasons"] for x in result["diagnostics"]))
        # Evaluation digest mutation interrupts rather than fabricating policy failure.
        adapter = SyntheticAdapter(); adapter.checkpoint_digest = checkpoint["digest"]
        bridge = AssignmentEnvironments(self.scheduler,adapter,clock=lambda:1.)
        bridge.start("eval",batch["assignments"][1]["assignment_id"],"eval-mutates",worker_id="w",ttl=20.)
        adapter.checkpoint_digest = "changed"
        with self.assertRaises(ValueError): bridge.step("eval")
        self.assertEqual(len(self.repo.records("episode_summary")),1)

    def test_detailed_feedback_and_advisor_only_completed_training(self):
        b = self.sample(); before = self.scheduler.diagnostics(b["request_id"])
        self.assertTrue(all(r["executed"]==0 for r in before["rows"]))
        self.execute(b["assignments"][0])
        report = self.scheduler.diagnostics(b["request_id"])
        self.assertEqual(sum(r["completed"] for r in report["rows"]),1)
        self.assertEqual(sum(r["scheduled"] for r in report["rows"]),1)
        self.assertTrue(any(r["executed_distribution"] for r in report["rows"]))
        self.assertTrue(all(r["sampling_latency_seconds"]>=0 for r in report["rows"]))
        self.scheduler.feedback(b["request_id"])
        advised = Advisor().advise("synthetic-checkpoint-v1",self.store.records("tasks"),self.store.records("episodes"))
        self.assertEqual(len(advised["evidence_ids"]),1)
        self.assertTrue(self.store.records("feedback"))

    def test_persistence_reopen_reproducibility_and_two_connection_lease_race(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/"sampler.sqlite3")
            store = Store(path); repo,lib,sampler,scheduler,d = setup(store)
            b = sampler.sample(d,now=0.); a = b["assignments"][0]; store.close()
            store = Store(path); repo = Repository(store); lib = TaskLibrary(repo)
            # Fresh callbacks and reopened storage must replay immutable assignments.
            _,_,s,_,_ = setup(store)
            self.assertEqual(b,s.sample(d,now=1.)); store.close()
            barrier = threading.Barrier(2); results = []; errors = []
            def lease(index):
                st = Store(path)
                try:
                    rp = Repository(st); lb = TaskLibrary(rp); sc = AssignmentScheduler(rp,lb)
                    barrier.wait()
                    sc.lease(a["assignment_id"],"worker"+str(index),"race"+str(index),now=2.,ttl=20.,compatibility_key=a["execution_compatibility_key"])
                    results.append("leased")
                except ValueError: results.append("rejected")
                except Exception as exc: errors.append(str(exc))
                finally: st.close()
            threads = [threading.Thread(target=lease,args=(i,)) for i in range(2)]
            for t in threads:t.start()
            for t in threads:t.join(10.)
            self.assertFalse(errors); self.assertCountEqual(results,["leased","rejected"])
            st = Store(path); rp = Repository(st); sc = AssignmentScheduler(rp,TaskLibrary(rp))
            sc.expire(now=30.)
            self.assertEqual(rp.db.execute("SELECT state FROM assignment_state WHERE identity=?",(a["assignment_id"],)).fetchone()[0],"pending")
            st.close()
        other = Store(":memory:")
        try:
            _,_,sampler,_,d = setup(other)
            self.assertEqual(self.sample()["assignments"],sampler.sample(d,now=0.)["assignments"])
        finally: other.close()

    def test_recorded_smoke_two_approved_families_parallel_interruption(self):
        output = smoke(self.store)
        self.assertGreaterEqual(len({s["family_id"] for s in output["summaries"]}),2)
        self.assertEqual(output["feedback"]["executed_episodes"],len(output["summaries"]))
        self.assertEqual(output["feedback"]["interrupted_attempts"],1)
        self.assertTrue(output["trajectories"]); self.assertTrue(output["initial_states"])
        self.assertTrue(all("SYNTHETIC" in a["physical_evidence"]["evidence_label"] for a in output["batch"]["assignments"]))


    def publish_patch(self, change):
        task = fixture_task(0); task["revision"] = 2
        c,artifact = contract_for(task); change(c)
        context = self.library.binding("synthetic-reach","1.0.0")["context"]
        self.library.register("synthetic-reach","1.0.1",task,
            dependencies=dict.fromkeys(("task_dsl","predicate_library","capability_ontology","object_ontology"),"synthetic-v1"),
            provenance={"source":"human","proposal_id":"synthetic-patch","generator_version":"synthetic-v1","parents":[]})
        for state in ("STRUCTURALLY_ACCEPTED","VALIDATING","VALID"):
            self.library.transition("synthetic-reach","1.0.1",state,event_id="patch-"+state,reason="synthetic test")
        record = self.library.publish_version("synthetic-reach","1.0.1",c,artifact,context=context)
        self.library.transition("synthetic-reach","1.0.1","ACTIVE",event_id="patch-active",reason="synthetic test")
        d = deepcopy(self.directive); d["window"]["window_id"] = "patch-window"
        r = deepcopy(d["family_region_allocations"]["learn"][0])
        r.update(family_id=c["family_id"],family_version=2,region_id="patch-region",weight=1.)
        d["family_region_allocations"]["learn"] = [r]; d["total_episode_budget"] = 4
        return record,seal(d)

    def test_registered_geometry_rejections_and_constructor_parameter_integrity(self):
        self.sampler.registry.register("geometry","reject-geometry",lambda i:False,dependencies=("target_distance",))
        _,d = self.publish_patch(lambda c:c.update(geometry_checks=[{"id":"reject-geometry","dependencies":["target_distance"]}]))
        b = self.sample(d)
        self.assertEqual(b["shortfall"],4)
        self.assertEqual(b["diagnostics"][0]["reasons"],{"geometry: reject-geometry":32})
        self.assertFalse(self.store.records("episodes"))

    def test_outside_envelope_validation_policy_and_reference_failure(self):
        calls = []
        def validator(task,instance):
            calls.append(instance); result = evidence(task,instance); result["feasibility_status"] = "unknown"; return result
        self.sampler.registry.register("validator","expensive-test-v1",validator)
        self.sampler.registry.register("reference","limited-reference-v1",lambda i:{"status":"failed","controller":"synthetic-limited"})
        def change(c):
            c["validation_policy"] = {"mode":"outside_envelope","validator_id":"expensive-test-v1"}
            c["validation_evidence"]["envelope"]["target_distance"] = [.04,.05]
            c["reference_check_id"] = "limited-reference-v1"
        record,d = self.publish_patch(change)
        task = record["task"]
        self.library.add_validation("synthetic-reach","1.0.1",context=self.library.binding("synthetic-reach","1.0.1")["context"],
            regions=[{**task["theta"],**task["phi"]}],outcome="valid",report_id="synthetic-additional-region",evidence_reference="synthetic-only",checks=evidence(task)["checks"])
        d["family_region_allocations"]["learn"][0]["parameter_restrictions"]["target_distance"] = [.1,.15]
        b = self.sample(seal(d)); self.assertEqual(len(calls),4)
        self.assertTrue(all(a["validation_result"]["reference_controller_evidence"]["status"]=="failed" for a in b["assignments"]))
        self.assertTrue(all(a["validation_result"]["feasibility_status"]=="unknown" for a in b["assignments"]))
        d["window"]["window_id"] = "inside-envelope"
        d["family_region_allocations"]["learn"][0]["region_version"] = 2
        d["family_region_allocations"]["learn"][0]["parameter_restrictions"]["target_distance"] = [.04,.05]
        b = self.sample(seal(d)); self.assertEqual(len(calls),4)
        self.assertTrue(all(a["physical_evidence"]["validation_scope"]=="trusted_published_envelope" for a in b["assignments"]))

    def test_invalid_constructor_and_initial_state_rejected_before_assignment(self):
        from task_advisor.loop import numeric_instance
        def bad_constructor(task,parameters,seed):
            result = numeric_instance(task,parameters,seed); result["initial_state_specification"] = {}; return result
        self.sampler.registry.register("constructor","bad-state-v1",bad_constructor)
        _,d = self.publish_patch(lambda c:c.update(instance_constructor_id="bad-state-v1"))
        batch = self.sample(d); self.assertEqual(batch["shortfall"],4)
        self.assertIn("invalid instance state/goal specification",batch["diagnostics"][0]["reasons"])

    def test_categorical_governance_conflict_blocks_only_named_subset(self):
        record = self.library.get_version("synthetic-reach","1.0.0")
        region = deepcopy({**record["task_spec"]["theta"],**record["task_spec"]["phi"]})
        region["surface"] = {"type":"categorical","values":["mat"]}
        self.library.add_validation("synthetic-reach","1.0.0",context=self.library.binding("synthetic-reach","1.0.0")["context"],
            regions=[region],outcome="invalid",report_id="synthetic-cat-invalid",evidence_reference="synthetic-only")
        coverage = self.library.supported_regions("synthetic-reach","1.0.0",self.library.binding("synthetic-reach","1.0.0")["context"])
        self.assertTrue(coverage["gaps"])
        self.assertTrue(all(r["surface"]["values"]==["tray"] for r in coverage["supported"]))
        b = self.sample()
        reach = [a for a in b["assignments"] if a["family_id"]==record["task_content_hash"]]
        self.assertTrue(reach); self.assertTrue(all(a["environment_parameters"]["surface"]=="tray" for a in reach))
        self.assertTrue(b["shortfall"])

    def test_demo_nonfinite_optional_payload_rejected_but_summary_durable(self):
        class BadAction(SyntheticAdapter):
            def controller_action(self,*args): return {"joint_target":float("nan")}
        d = self.changed_directive(episode_purpose="demonstration",policy_checkpoint_id=None)
        a = self.sample(d)["assignments"][0]
        summary,_ = self.execute(a,adapter=BadAction())
        self.assertEqual(summary["recording_status"],"rejected")
        self.assertEqual(len(self.repo.records("episode_summary")),1)
        trajectory = self.repo.get("trajectory",summary["trajectory_reference"])
        self.assertEqual(trajectory["samples"][0]["actions"]["joint_target"],{"invalid_nonfinite":"nan"})
        self.assertEqual(export_dataset(self.repo),[])

    def test_adapter_step_and_malformed_frame_failures_are_not_policy_failures(self):
        class Broken(SyntheticAdapter):
            def step(self,env,action): raise RuntimeError("synthetic-worker-crash")
        class Malformed(SyntheticAdapter):
            def step(self,env,action):
                result = super().step(env,action); result["frame"]["episode_id"] = "post-reset-wrong-id"; return result
        b = self.sample()
        for index,adapter in enumerate((Broken(),Malformed())):
            bridge = AssignmentEnvironments(self.scheduler,adapter,clock=lambda:1.)
            bridge.start("env",b["assignments"][index]["assignment_id"],"broken-"+str(index),worker_id="w",ttl=10.)
            with self.assertRaises((ValueError,RuntimeError)): bridge.step("env")
            self.assertFalse(bridge.sessions)
        self.assertEqual(len(self.repo.records("execution_failure")),2)
        self.assertFalse(self.store.records("episodes")); self.assertFalse(self.repo.records("episode_summary"))

    def test_expired_worker_never_steps_physics_and_finalize_ack_retry(self):
        a = self.sample()["assignments"][0]; adapter = SyntheticAdapter(); clock = [1.]
        bridge = AssignmentEnvironments(self.scheduler,adapter,clock=lambda:clock[0])
        bridge.start("env",a["assignment_id"],"expired-worker",worker_id="w",ttl=1.)
        clock[0] = 3.
        with self.assertRaises(ValueError): bridge.step("env")
        self.assertFalse(any(e[1]=="pre_reset_frame" for e in adapter.events))
        class LostAck(SyntheticAdapter):
            def finalized(self,env):
                if not hasattr(self,"lost"):
                    self.lost = True; raise RuntimeError("lost-finalize-ack")
                return super().finalized(env)
        adapter = LostAck(); bridge = AssignmentEnvironments(self.scheduler,adapter,clock=lambda:3.)
        bridge.start("env",a["assignment_id"],"retry-after-expiry",worker_id="w",ttl=10.)
        bridge.step("env")
        with self.assertRaises(RuntimeError): bridge.step("env")
        self.assertEqual(len(self.repo.records("episode_summary")),1)
        result = bridge.step("env"); self.assertEqual(result["control_step_count"],2)
        self.assertEqual(sum(e[1]=="pre_reset_frame" for e in adapter.events),2)

    def test_exact_idempotent_completion_and_conflicting_retry_rejected(self):
        a = self.sample()["assignments"][0]; adapter = SyntheticAdapter()
        bridge = AssignmentEnvironments(self.scheduler,adapter,clock=lambda:1.)
        bridge.start("env",a["assignment_id"],"complete-idempotent",worker_id="w",ttl=20.)
        recorder = bridge.sessions["env"]["recorder"]; captured = []; original = recorder.record
        def capture(annotation,episode):
            captured.append(deepcopy(episode)); return original(annotation,episode)
        recorder.record = capture
        bridge.step("env"); bridge.step("env")
        original({},captured[0]); self.assertEqual(len(self.store.records("episodes")),1)
        bad = deepcopy(captured[0]); bad["reward"] = 999.
        with self.assertRaises(ValueError): original({},bad)
        self.assertEqual(len(self.repo.records("completion")),1)

    def test_parallel_sampling_reuses_frozen_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/"shared.sqlite3")
            st = Store(path); setup(st); st.close()
            barrier = threading.Barrier(2); results = []; errors = []
            def sample():
                store = Store(path)
                try:
                    _,_,sampler,_,d = setup(store); barrier.wait(); results.append(sampler.sample(d,now=0.))
                except Exception as exc: errors.append(str(exc))
                finally: store.close()
            threads = [threading.Thread(target=sample) for _ in range(2)]
            for t in threads:t.start()
            for t in threads:t.join(10.)
            self.assertFalse(errors); self.assertEqual(len(results),2); self.assertEqual(results[0],results[1])
            store = Store(path); repo = Repository(store)
            self.assertEqual(len(repo.records("assignment")),8); self.assertEqual(len(repo.records("sampling")),1)
            store.close()

    def test_reopen_interrupted_attempt_and_retry_then_concurrent_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/"recovery.sqlite3")
            store = Store(path); repo,lib,sampler,sc,d = setup(store); a = sampler.sample(d,now=0.)["assignments"][0]
            adapter = SyntheticAdapter(); bridge = AssignmentEnvironments(sc,adapter,clock=lambda:1.)
            bridge.start("env",a["assignment_id"],"interrupted-before-reopen",worker_id="w",ttl=20.); bridge.step("env")
            bridge.interrupt("env",reason="synthetic-restart"); store.close()
            store = Store(path); repo,lib,sampler,sc,d = setup(store)
            self.assertEqual(repo.get("incomplete_episode","interrupted-before-reopen")["execution_status"],"incomplete")
            adapter = SyntheticAdapter(); bridge = AssignmentEnvironments(sc,adapter,clock=lambda:2.)
            bridge.start("env",a["assignment_id"],"reopened-attempt",worker_id="w",ttl=20.)
            recorder = bridge.sessions["env"]["recorder"]; original = recorder.record; inputs = []
            def capture(annotation,episode):
                inputs.append((deepcopy(annotation),deepcopy(episode))); raise RuntimeError("defer first completion to concurrent writers")
            recorder.record = capture; bridge.step("env")
            with self.assertRaises(RuntimeError): bridge.step("env")
            episode = inputs[0][1]; episode["assignment_execution"] = deepcopy(recorder.execution); episode["trajectory"] = recorder.trajectory
            store.close()
            barrier = threading.Barrier(2); results = []; errors = []
            def complete():
                st = Store(path)
                try:
                    rp = Repository(st); scheduler = AssignmentScheduler(rp,TaskLibrary(rp)); barrier.wait()
                    scheduler.complete(a["assignment_id"],"reopened-attempt",episode,now=3.); results.append("ok")
                except Exception as exc: errors.append(str(exc))
                finally: st.close()
            threads = [threading.Thread(target=complete) for _ in range(2)]
            for t in threads:t.start()
            for t in threads:t.join(10.)
            self.assertFalse(errors); self.assertEqual(results,["ok","ok"])
            st = Store(path); rp = Repository(st)
            self.assertEqual(len(st.records("episodes")),1); self.assertEqual(len(rp.records("completion")),1); st.close()

    def test_malformed_unknown_contract_directive_and_quality_fields(self):
        with self.assertRaises(ValueError): self.sample(self.changed_directive(unknown_expression="__import__('os')"))
        with self.assertRaises(ValueError): self.sample(self.changed_directive(recording_profile={"trajectory":True,"unknown":True}))
        d = deepcopy(self.directive); d["family_region_allocations"]["learn"][0]["categorical_filters"] = {"mass":[.04]}
        with self.assertRaises(ValueError): self.sample(seal(d))
        d = deepcopy(self.directive); d["exclusions"] = [{"unrecognized":True}]
        with self.assertRaises(ValueError): self.sample(seal(d))
        d = deepcopy(self.directive); d["minimum_coverage_requirements"] = [{"category":"learn","region_id":"missing","minimum":1}]
        with self.assertRaises(ValueError): self.sample(seal(d))

    def test_fixed_manifest_requires_constraint_registry_and_independent_seed(self):
        registry = BenchmarkRegistry(self.repo,self.library)
        task = fixture_task(0); instance = TaskGenerator(123).sample(task)
        instance["theta"]["corridor_width"] = .025; instance["theta"]["object_size"] = .04
        case = {"family_id":fingerprint(task),"family_version":1,"instance":instance,"physical_evidence":evidence(task,instance),"probe_seed":1000}
        with self.assertRaises(ValueError): registry.freeze("bad",1,[case],seed=1000)
        with self.assertRaises(ValueError): registry.freeze("bad",1,[case],seed=1000,registry=self.sampler.registry)
        self.assertFalse(self.repo.records("benchmark"))

    def test_rollups_fallback_accounting_and_wait_metrics(self):
        b = self.sample(); self.execute(b["assignments"][0])
        report = self.scheduler.diagnostics(b["request_id"])
        total = report["rollups"]["directive"][0]
        self.assertEqual(total["requested"],8); self.assertEqual(total["completed"],1); self.assertEqual(total["remaining_shortfall"],0)
        self.assertEqual(total["worker_wait_seconds"],[1.])
        self.assertEqual(len(report["rollups"]["family"]),2)
        self.assertEqual(sum(r["completed"] for r in report["rollups"]["family"]),1)

    def test_immutable_region_versions_and_all_three_categories(self):
        self.sample()
        d = deepcopy(self.directive); d["window"]["window_id"] = "different-region-window"
        d["family_region_allocations"]["learn"][0]["parameter_restrictions"] = {"corridor_width":[.075,.08]}
        with self.assertRaises(ValueError): self.sample(seal(d))
        d["family_region_allocations"]["learn"][0]["region_version"] = 2
        self.assertEqual(self.sample(seal(d))["shortfall"],0)
        d = deepcopy(self.directive); d["window"]["window_id"] = "three-categories"; d["total_episode_budget"] = 12
        d["category_allocations"] = {"learn":.5,"explore":.25,"retain":.25}
        for category in ("explore","retain"):
            d["family_region_allocations"][category] = deepcopy(d["family_region_allocations"]["learn"])
        b = self.sample(seal(d))
        from collections import Counter
        self.assertEqual(Counter(a["category"] for a in b["assignments"]),{"learn":6,"explore":3,"retain":3})
        self.assertEqual(b["shortfall"],0)

    def test_registered_fixed_distribution_generation_and_simulator_version_checks(self):
        registry = BenchmarkRegistry(self.repo,self.library)
        refs = [(r["contract"]["family_id"],1) for r in self.library.list_eligible_families()]
        cases = registry.generate_cases(refs,seed=901,per_family=2,validator=evidence,registry=self.sampler.registry)
        self.assertEqual(len(cases),4)
        self.assertTrue(all(c["instance"]["theta"]["corridor_width"]>=c["instance"]["theta"]["object_size"]+.005 for c in cases))
        self.assertEqual(cases,registry.generate_cases(refs,seed=901,per_family=2,validator=evidence,registry=self.sampler.registry))
        registry.freeze("synthetic-fixed-distribution",1,cases,seed=901,registry=self.sampler.registry)
        adapter = SyntheticAdapter(); adapter.simulator_version = "unapproved-simulator-v99"
        a = self.sample()["assignments"][0]
        with self.assertRaises(ValueError): self.execute(a,adapter=adapter)
        self.assertFalse(self.store.records("episodes"))

    def test_unresolved_advisor_allocations_are_explicit_shortfalls(self):
        from task_advisor.curriculum import make_directive
        from task_advisor.research import uniform_directive
        advisor = uniform_directive("policy",self.library.list_eligible_families())
        advisor["learn_targets"] = [{"capabilities":["unsupported-insertion"],"parameters":{},"weight":1.}]
        advisor = seal(advisor)
        d = make_directive(advisor,self.library,total=5,seed=1,controller_id="synthetic-controller",controller_version="v1",window_id="unsupported",starts_at=0.,expires_at=10.)
        b = self.sample(d)
        self.assertEqual(b["shortfall"],5); self.assertEqual(b["unallocated_region_budgets"]["learn"],5)
        self.assertEqual(b["unresolved_advisor_targets"][0]["target"]["capabilities"],["unsupported-insertion"])
        self.assertEqual(self.scheduler.diagnostics(b["request_id"])["rollups"]["directive"][0]["remaining_shortfall"],5)


if __name__ == "__main__": unittest.main()
