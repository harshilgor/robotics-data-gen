from copy import deepcopy
from pathlib import Path
import time

from data import LocalObjectStore, DatasetCatalog
from taskgen.core import bootstrap_families, fingerprint
from taskgen.bootstrap import broad_bootstrap
from task_advisor.storage import Store
from task_advisor.loop import Repository, CurriculumSampler, AssignmentScheduler, numeric_instance
from task_advisor.curriculum import Registry, make_directive
from task_advisor.core import Advisor
from task_advisor.research import uniform_directive
from task_advisor.worker import AssignmentEnvironments
from task_library import TaskLibrary
from task_compiler import TaskCompiler
from task_validator import TaskValidator
from simulation import LocalSimulationAdapter


class LocalFactory:
    """Local resources all share the existing governed Library and metadata DB."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = Store(str(self.root / "metadata.sqlite3"))
        self.repo = Repository(self.store, payload_store=LocalObjectStore(self.root / "objects"))
        self.library = TaskLibrary(self.repo)
        self.compiler = TaskCompiler()
        self.validator = TaskValidator(self.compiler)
        self.registry = Registry().register("constructor", "local-instance-1.0", numeric_instance)
        self.registry.register("geometry", "local-geometry-1.0", self.validator.geometry,
                               dependencies=("target_distance", "tolerance", "object_size", "mass", "friction"))
        self.registry.register("validator", "local-validator-1.0", self.validator.evidence)
        self.sampler = CurriculumSampler(self.repo, self.library, registry=self.registry)
        self.scheduler = AssignmentScheduler(self.repo, self.library)
        self.catalog = DatasetCatalog(self.repo, self.library)

    def close(self):
        self.store.close()

    def seed(self, *, broad=False):
        families = []
        for task in broad_bootstrap() if broad else bootstrap_families():
            if not broad:
                task["schema_version"] = "1.1"
            task["interfaces"] = {"observation": "local_cartesian_state_v1", "action": "local_cartesian_delta_v1"}
            families.append(self.publish(task, source="bootstrap"))
        return families

    def publish(self, task, *, source="human"):
        task = deepcopy(task)
        from task_library.governance import transaction
        with transaction(self.repo.db):
            canonical_id = "local-" + task["family"]
            if self.library.search() and any(r["task_content_hash"] == fingerprint(task) for r in self.library.search()):
                return self.library.get_family(fingerprint(task), task["revision"])
            identity = self.library.reconcile(task)
            if identity["matches"]:
                canonical_id = identity["matches"][0]["family_id"]
            versions = self.library.search(family_id=canonical_id)
            version = str(max(int(r["version"].split(".")[0]) for r in versions)+1) + ".0.0" if versions else "1.0.0"
            artifact = self.compiler.compile(task)
            envelope = self.validator.envelope(task)
            contract = self.compiler.contract(task, artifact, envelope)
            dependencies = {"task_dsl": task["schema_version"],
                "predicate_library": self.compiler.semantics.snapshot()["digest"],
                "capability_ontology": self.compiler.semantics.snapshot()["digest"],
                "object_ontology": self.compiler.resources.snapshot()["digest"]}
            parents = []
            for parent_hash in task.get("provenance", {}).get("parents", []):
                matches = [record for record in self.library.search() if record["task_content_hash"] == parent_hash]
                if len(matches) != 1:
                    raise ValueError("generated lineage must resolve an exact published parent")
                parents.append({"family_id": matches[0]["family_id"], "version": matches[0]["version"]})
            self.library.register(canonical_id, version, task, dependencies=dependencies,
                provenance={"source": source, "proposal_id": fingerprint(task), "generator_version": "local-bootstrap-1.0",
                            "parents": parents}, metadata={"notice": artifact["notice"]})
            for state in ("STRUCTURALLY_ACCEPTED", "VALIDATING", "VALID"):
                self.library.transition(canonical_id, version, state, event_id=canonical_id+"-"+version+"-"+state,
                                        reason="local synthetic model validation")
            context = {"robot": "so101", "gripper": "synthetic-cartesian-gripper", "controller": "local-reference@1.0",
                "compiler_version": self.compiler.version, "validator_version": self.validator.version,
                "simulator_version": self.validator.simulator_version}
            record = self.library.publish_version(canonical_id, version, contract, artifact, context=context)
            self.library.transition(canonical_id, version, "ACTIVE", event_id=canonical_id+"-"+version+"-ACTIVE", reason="synthetic execution only")
        return record

    def sample(self, *, total, seed, policy_version, window, purpose="training", advisor_directive=None, recording_profile=None):
        if advisor_directive is None:
            advisor_directive = uniform_directive(policy_version, self.library.list_eligible_families())
        snapshot = {"snapshot_id": fingerprint(advisor_directive), "directive": advisor_directive}
        self.store.save_snapshot(snapshot)
        directive = make_directive(advisor_directive, self.library, total=total, seed=seed,
            controller_id="local-reference", controller_version="1.0", window_id=window,
            starts_at=0., expires_at=1e12, purpose=purpose, recording_profile=recording_profile or {"trajectory": True})
        return self.sampler.sample(directive, now=time.monotonic())

    def execute(self, batch, *, environments=3, policies=None, interrupt_first=False):
        if type(environments) is not int or environments < 1:
            raise ValueError("positive environment count required")
        adapter = LocalSimulationAdapter(policies=policies)
        bridge = AssignmentEnvironments(self.scheduler, adapter, clock=time.monotonic)
        pending = list(batch["assignments"])
        summaries = []
        interrupted = False
        attempts = 0
        while pending or bridge.sessions:
            for i in range(environments):
                env = "env" + str(i)
                if env not in bridge.sessions and pending:
                    assignment = pending.pop(0)
                    state = self.repo.db.execute("SELECT state FROM assignment_state WHERE identity=?", (assignment["assignment_id"],)).fetchone()[0]
                    if state == "completed":
                        summaries.append(self.repo.get("episode_summary", assignment["assignment_id"]))
                        continue
                    attempts += 1
                    bridge.start(env, assignment["assignment_id"], fingerprint([batch["request_id"], env, attempts, time.monotonic_ns()]),
                                 worker_id="local-worker", ttl=60.)
            for env in list(bridge.sessions):
                if interrupt_first and not interrupted:
                    assignment = bridge.sessions[env]["assignment"]
                    bridge.step(env)
                    bridge.interrupt(env, reason="injected local worker interruption")
                    pending.insert(0, assignment)
                    interrupted = True
                    continue
                bridge.renew(env, ttl=60.)
                summary = bridge.step(env)
                if summary:
                    summaries.append(summary)
        return {"summaries": summaries, "events": adapter.events,
                "feedback": self.scheduler.feedback(batch["request_id"]),
                "diagnostics": self.scheduler.diagnostics(batch["request_id"])}

    def advise(self, policy_version, previous_policy_version=None):
        return Advisor().advise(policy_version, self.store.records("tasks"), self.store.records("episodes"),
                                previous_policy_version=previous_policy_version)
