"""Immutable development manifests and frozen-policy measured probes.

There is intentionally no sealed-test evaluator in this package.
"""
from copy import deepcopy
from dataclasses import dataclass
from typing import Protocol

from taskgen.core import fingerprint, TaskGenerator
from .core import canonical, validate_episode
from .instrumentation import compile_instrumentation, EpisodeTracker
from .loop import text_id, integer


class ProbeRuntime(Protocol):
    def load_frozen_policy(self, checkpoint: dict) -> None: ...
    def policy_digest(self) -> str: ...
    def begin_probe(self, family: dict, instance: dict, *, seed: int) -> None:
        """Apply instance, capture/reset state, execute frozen controller on step()."""
        ...
    def step(self, episode_id: str) -> dict:
        """Return a measured post-action, pre-reset frame to EpisodeTracker."""
        ...


class BenchmarkRegistry:
    def __init__(self, repository, library): self.repo, self.library = repository, library

    def register_checkpoint(self, policy_version, artifact):
        text_id(policy_version)
        checkpoint = {"policy_version": policy_version, "artifact": deepcopy(artifact),
                      "digest": fingerprint(artifact)}
        with self.repo.db: self.repo.put("checkpoint", policy_version, checkpoint)
        return checkpoint

    def freeze(self, name, version, cases, *, seed, registry=None):
        from task_library.governance import transaction
        with transaction(self.repo.db):
            return self._freeze(name,version,cases,seed=seed,registry=registry)

    def _freeze(self, name, version, cases, *, seed, registry=None):
        text_id(name); integer(version, "benchmark version", 1); integer(seed, "seed")
        if not cases: raise ValueError("benchmark cases required")
        seen = set()
        for case in cases:
            record = self.library.get_family(case["family_id"], case["family_version"])
            compile_instrumentation(record["task"], case["instance"], case["physical_evidence"])
            contract = record["contract"]
            if contract.get("schema_version") == "2.0":
                if registry is None: raise ValueError("typed evaluation manifest requires registered constraints")
                registry.check(contract)
                values = {**case["instance"]["theta"],**case["instance"]["phi"]}
                for check in contract["constraints"]:
                    if registry.resolve("constraint",check["id"],contract["parameter_schema"])(deepcopy(values)) is not True: raise ValueError("evaluation constraint rejected")
                for check in contract["geometry_checks"]:
                    if registry.resolve("geometry",check["id"],contract["parameter_schema"])(deepcopy(case["instance"])) is not True: raise ValueError("evaluation geometry rejected")
            if hasattr(self.library, "assert_sample_allowed"): self.library.assert_sample_allowed(record,case["instance"])
            identity = fingerprint(case["instance"])
            if identity in seen: raise ValueError("duplicate benchmark instance")
            seen.add(identity)
            integer(case["probe_seed"], "probe seed")
        from .curriculum import held_out_parameters
        physical = {fingerprint([c["family_id"],c["family_version"],c["instance"]["theta"],c["instance"]["phi"]]) for c in cases}
        trained_parameters = {fingerprint([ep["family_id"],ep["family_version"],ep["task_parameters"],ep.get("instrumentation",{}).get("randomization")]) for ep in self.repo.store.records("episodes") if ep["source"] == "training"}
        if physical & trained_parameters: raise ValueError("benchmark physical specifications overlap training evidence")
        assigned_parameters = {fingerprint([a["family_id"],a["family_version"],a["instance"]["theta"],a["instance"]["phi"]]) for a in self.repo.records("assignment") if a["episode_purpose"] != "evaluation"}
        if physical & assigned_parameters: raise ValueError("benchmark physical specifications overlap training")
        trained = {ep["task_instance_id"] for ep in self.repo.store.records("episodes") if ep["source"] == "training"}
        assigned = {fingerprint(a["instance"]) for a in self.repo.records("assignment")}
        if seen & (trained | assigned): raise ValueError("benchmark instances overlap training/assignments")
        manifest = {"schema_version": "1.0", "source": "development", "name": name,
                    "version": version, "seed": seed, "cases": deepcopy(cases)}
        manifest["manifest_id"] = fingerprint(manifest)
        from task_library.governance import transaction
        with transaction(self.repo.db):
            self.repo.put("benchmark_version", canonical([name, version]), manifest)
            self.repo.put("benchmark", manifest["manifest_id"], manifest)
        return manifest

    def assignments(self, manifest_id, policy_version, *, controller_id, controller_version,
                    starts_at, expires_at, recording_profile=None):
        """Fixed manifest assignments, independent of all adaptive allocation budgets.

        Checkpoint descriptors are immutable. Workers verify their frozen digest at
        initialization and before/after every action. Results remain purpose-tagged
        summaries outside the training Evidence Engine.
        """
        from .curriculum import build_assignment, identity
        from task_library.governance import transaction
        from collections import defaultdict
        from .core import number
        identity(controller_id); identity(controller_version)
        number(starts_at,"start",0); number(expires_at,"expiry",starts_at+.000001)
        import time
        started = time.perf_counter()
        manifest = self.repo.get("benchmark",manifest_id)
        self.repo.get("checkpoint",policy_version)
        directive = {"schema_version":"evaluation-2.0","directive_version":manifest["version"],
            "policy_checkpoint_id":policy_version,"episode_purpose":"evaluation","embodiment_id":"so101",
            "controller_id":controller_id,"controller_version":controller_version,
            "recording_profile":recording_profile or {"trajectory":True},
            "window":{"window_id":"evaluation-"+manifest_id+"-"+policy_version,"starts_at":starts_at,"expires_at":expires_at},
            "manifest_id":manifest_id}
        if type(directive["recording_profile"].get("trajectory")) is not bool: raise ValueError("recording profile required")
        directive["directive_id"] = fingerprint(directive)
        request = {"directive":directive,"total":len(manifest["cases"]),"seed":manifest["seed"],"algorithm":"fixed-manifest-v2"}
        rid = fingerprint(request)
        with transaction(self.repo.db):
            old = self.repo.db.execute("SELECT payload FROM loop_records WHERE kind='sampling' AND identity=?",(rid,)).fetchone()
            if old:
                import json
                return json.loads(old[0])
            assignments, diagnostics, groups = [], [], defaultdict(list)
            for index,case in enumerate(manifest["cases"]):
                record = self.library.get_family(case["family_id"],case["family_version"])
                c = record["contract"]
                if c.get("schema_version") != "2.0": raise ValueError("full typed contract required")
                if controller_id+"@"+controller_version not in c["supported_controller_references"]: raise ValueError("controller unsupported")
                self.library.assert_sample_allowed(record,case["instance"])
                region = {"region_id":manifest_id+"-"+str(index),"region_version":manifest["version"],
                    "family_id":case["family_id"],"family_version":case["family_version"],
                    "parameter_restrictions":{},"categorical_filters":{}}
                a = build_assignment(record,region,case["instance"],{**case["instance"]["theta"],**case["instance"]["phi"]},case["physical_evidence"],
                    request_id=rid,directive=directive,category="evaluation",sampling_seed=case["probe_seed"],ordinal=index)
                a.update(evaluation_manifest_id=manifest_id,evaluation_case_index=index)
                a.pop("assignment_id"); a["assignment_id"] = fingerprint(a)
                self.repo.put("assignment",a["assignment_id"],a)
                self.repo.db.execute("INSERT INTO assignment_state VALUES (?,'pending',NULL,NULL,NULL)",(a["assignment_id"],))
                assignments.append(a); groups[a["execution_compatibility_key"]].append(a["assignment_id"])
                diagnostics.append({"directive_id":directive["directive_id"],"category":"evaluation","family_id":a["family_id"],"family_version":a["family_version"],
                    "region_id":a["region_id"],"requested":1,"generated":1,"rejected":0,"accepted":1,"shortfall":0,"reasons":{}})
            batch = {"request_id":rid,"request":request,"assignments":assignments,"diagnostics":diagnostics,"shortfall":0,"fallbacks":[],"groups":dict(groups)}
            self.repo.put("sampling",rid,batch)
            self.repo.put("sampling_timing",rid,{"created_at":starts_at,"latency_seconds":time.perf_counter()-started})
            return batch

    def generate_cases(self, families, *, seed, per_family, validator, registry=None, max_attempts=16):
        """Separate deterministic development sampling stream, fixed at freeze time."""
        integer(seed, "seed"); integer(per_family, "per family", 1)
        integer(max_attempts,"attempt limit",1)
        generator = TaskGenerator(int(fingerprint(["development-v1", seed])[:16], 16))
        cases = []
        for family_id, version in families:
            task = self.library.get_family(family_id, version)["task"]
            contract = self.library.get_sampling_contract(family_id,version)
            typed = contract.get("schema_version") == "2.0"
            if typed:
                if registry is None: raise ValueError("typed evaluation sampling requires registered constraints")
                registry.check(contract)
            for index in range(per_family):
                for attempt in range(max_attempts):
                    instance = generator.sample(task,index*max_attempts+attempt if typed else index)
                    if typed:
                        values = {**instance["theta"],**instance["phi"]}
                        if any(registry.resolve("constraint",c["id"],contract["parameter_schema"])(deepcopy(values)) is not True for c in contract["constraints"]): continue
                        instance = registry.resolve("constructor",contract["instance_constructor_id"],contract["parameter_schema"])(deepcopy(task),deepcopy(values),instance["seed"])
                        if instance.get("theta") != {k:values[k] for k in task["theta"]} or instance.get("phi") != {k:values[k] for k in task["phi"]}: raise ValueError("evaluation constructor changed parameters")
                        if any(registry.resolve("geometry",c["id"],contract["parameter_schema"])(deepcopy(instance)) is not True for c in contract["geometry_checks"]): continue
                    evidence = validator(deepcopy(task),deepcopy(instance))
                    compile_instrumentation(task,instance,evidence)
                    if hasattr(self.library,"assert_sample_allowed"): self.library.assert_sample_allowed(self.library.get_family(family_id,version),instance)
                    cases.append({"family_id":family_id,"family_version":version,"instance":instance,
                        "physical_evidence":evidence,"probe_seed":int(fingerprint(["probe",seed,family_id,version,index])[:16],16)})
                    break
                else: raise ValueError("fixed evaluation distribution has constraint shortfall")
        return cases

    def verify_episode(self, episode):
        if episode.get("source") != "development": raise ValueError("development records only")
        provenance = episode.get("development_probe", {})
        manifest = self.repo.get("benchmark", provenance.get("manifest_id"))
        checkpoint = self.repo.get("checkpoint", episode["policy_version"])
        if provenance.get("policy_digest") != checkpoint["digest"]: raise ValueError("checkpoint mismatch")
        integer(provenance.get("case_index"), "case index")
        index = provenance["case_index"]
        if index >= len(manifest["cases"]): raise ValueError("unknown benchmark case")
        case = manifest["cases"][index]
        if (episode["task_instance_id"] != fingerprint(case["instance"]) or
            episode["family_id"] != case["family_id"] or episode["family_version"] != case["family_version"] or
            episode["task_parameters"] != case["instance"]["theta"] or provenance.get("probe_seed") != case["probe_seed"]):
            raise ValueError("episode differs from frozen benchmark")
        expected_id = fingerprint([manifest["manifest_id"], checkpoint["digest"], checkpoint["policy_version"], index])
        if episode["episode_id"] != expected_id: raise ValueError("noncanonical probe identity")

    def run(self, manifest_id, policy_version, runtime):
        """Run every fixed case exactly once, staging all records before atomic ingest."""
        manifest = self.repo.get("benchmark", manifest_id)
        checkpoint = self.repo.get("checkpoint", policy_version)
        run_id = fingerprint([manifest_id, policy_version, checkpoint["digest"]])
        old = [r for r in self.repo.records("evaluation_run") if r["run_id"] == run_id]
        if old: return old[0]
        runtime.load_frozen_policy(deepcopy(checkpoint))
        episodes, annotations = [], []
        for index, case in enumerate(manifest["cases"]):
            if runtime.policy_digest() != checkpoint["digest"]: raise ValueError("policy changed during evaluation")
            family = self.library.get_family(case["family_id"], case["family_version"])
            compiled = compile_instrumentation(family["task"], case["instance"], case["physical_evidence"])
            episode_id = fingerprint([manifest_id, checkpoint["digest"], policy_version, index])
            tracker = EpisodeTracker(compiled, episode_id=episode_id, policy_version=policy_version, source="development")
            runtime.begin_probe(deepcopy(family), deepcopy(case["instance"]), seed=case["probe_seed"])
            for _ in range(family["task"]["horizon"]):
                episode = tracker.observe(runtime.step(episode_id))
                if episode is not None: break
            if runtime.policy_digest() != checkpoint["digest"]: raise ValueError("policy changed during evaluation")
            episode["development_probe"] = {"manifest_id": manifest_id, "case_index": index,
                "probe_seed": case["probe_seed"], "policy_digest": checkpoint["digest"]}
            self.verify_episode(episode)
            episodes.append(episode); annotations.append(tracker.annotation)
        run = {"run_id": run_id, "manifest_id": manifest_id, "policy_version": policy_version,
            "policy_digest": checkpoint["digest"], "episode_ids": [e["episode_id"] for e in episodes],
            "sample_count": len(episodes), "success_rate": sum(e["success"] for e in episodes)/len(episodes)}
        with self.repo.db:
            self.repo.store.ingest(annotations, episodes, transactional=False)
            self.repo.put("evaluation_run", run_id, run)
        return run


def enforce_development_membership(store, episodes):
    """Called by Store whenever a controlled-loop repository exists."""
    present = store.db.execute("SELECT 1 FROM sqlite_master WHERE name='loop_records'").fetchone()
    if not present: return
    # Construct no new tables/transactions while inside episode ingestion.
    from .loop import Repository, TaskLibrary
    repo = object.__new__(Repository)
    repo.store, repo.db = store, store.db
    registry = BenchmarkRegistry(repo, TaskLibrary(repo))
    reserved = {fingerprint(c["instance"]) for m in repo.records("benchmark") for c in m["cases"]}
    from .curriculum import held_out_parameters
    reserved_parameters = held_out_parameters(repo)
    for episode in episodes:
        actual = fingerprint([episode.get("family_id"),episode.get("family_version"),episode.get("task_parameters"),episode.get("instrumentation",{}).get("randomization")])
        if episode.get("source") == "training" and actual in reserved_parameters: raise ValueError("held-out physical parameters cannot enter training")
        if episode.get("source") == "development": registry.verify_episode(episode)
        elif episode.get("task_instance_id") in reserved: raise ValueError("development instance cannot enter training")
