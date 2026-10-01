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

    def freeze(self, name, version, cases, *, seed):
        text_id(name); integer(version, "benchmark version", 1); integer(seed, "seed")
        if not cases: raise ValueError("benchmark cases required")
        seen = set()
        for case in cases:
            record = self.library.get_family(case["family_id"], case["family_version"])
            compile_instrumentation(record["task"], case["instance"], case["physical_evidence"])
            identity = fingerprint(case["instance"])
            if identity in seen: raise ValueError("duplicate benchmark instance")
            seen.add(identity)
            integer(case["probe_seed"], "probe seed")
        trained = {ep["task_instance_id"] for ep in self.repo.store.records("episodes") if ep["source"] == "training"}
        assigned = {fingerprint(a["instance"]) for a in self.repo.records("assignment")}
        if seen & (trained | assigned): raise ValueError("benchmark instances overlap training/assignments")
        manifest = {"schema_version": "1.0", "source": "development", "name": name,
                    "version": version, "seed": seed, "cases": deepcopy(cases)}
        manifest["manifest_id"] = fingerprint(manifest)
        with self.repo.db:
            self.repo.put("benchmark_version", canonical([name, version]), manifest)
            self.repo.put("benchmark", manifest["manifest_id"], manifest)
        return manifest

    def generate_cases(self, families, *, seed, per_family, validator):
        """Separate deterministic development sampling stream, fixed at freeze time."""
        integer(seed, "seed"); integer(per_family, "per family", 1)
        generator = TaskGenerator(int(fingerprint(["development-v1", seed])[:16], 16))
        cases = []
        for family_id, version in families:
            task = self.library.get_family(family_id, version)["task"]
            for index in range(per_family):
                instance = generator.sample(task, index)
                evidence = validator(deepcopy(task), deepcopy(instance))
                cases.append({"family_id": family_id, "family_version": version, "instance": instance,
                    "physical_evidence": evidence, "probe_seed": int(fingerprint(["probe", seed, family_id, version, index])[:16], 16)})
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
    for episode in episodes:
        if episode.get("source") == "development": registry.verify_episode(episode)
        elif episode.get("task_instance_id") in reserved: raise ValueError("development instance cannot enter training")
