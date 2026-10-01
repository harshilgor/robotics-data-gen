"""Persistent exact-version library and reproducible curriculum assignments.

Physical validation and compiled artifacts are supplied by trusted integrations.
No counts in this module become capability evidence without completed episodes.
"""
from copy import deepcopy
import json
import math
import random
import sqlite3
from contextlib import nullcontext
from taskgen.parameters import domain, validate_domain, intersect_domain

from taskgen.core import fingerprint, validate
from .core import canonical, number, task_annotation, validate_episode
from .instrumentation import compile_instrumentation


def text_id(value):
    if not isinstance(value, str) or not value:
        raise ValueError("nonempty identity required")


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be integer >= {minimum}")


def quotas(weights, total):
    """Largest remainder, lexical key tie break, with explicit unused capacity."""
    integer(total, "budget")
    for weight in weights.values(): number(weight, "weight", 0, 1)
    if sum(weights.values()) > 1 + 1e-9: raise ValueError("weights exceed budget")
    weights = {**weights, "unallocated": max(0., 1 - sum(weights.values()))}
    result = {key: math.floor(value * total) for key, value in weights.items()}
    for key in sorted(weights, key=lambda k: (-(weights[k]*total-result[k]), k))[:total-sum(result.values())]:
        result[key] += 1
    return result


class Repository:
    """Uses the Advisor Store connection so episode and assignment commits are atomic."""
    def __init__(self, store):
        self.store = store
        self.db = store.db
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS loop_records (
                kind TEXT, identity TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind,identity));
            CREATE TABLE IF NOT EXISTS assignment_state (
                identity TEXT PRIMARY KEY, state TEXT NOT NULL, attempt TEXT, worker TEXT, deadline REAL);
            CREATE TABLE IF NOT EXISTS execution_attempts (
                identity TEXT PRIMARY KEY, assignment TEXT NOT NULL, status TEXT NOT NULL);
        """)

    def put(self, kind, identity, payload):
        text_id(identity)
        data = canonical(payload)
        row = self.db.execute("SELECT payload FROM loop_records WHERE kind=? AND identity=?", (kind, identity)).fetchone()
        if row:
            if row[0] != data: raise ValueError("immutable record conflict")
        else:
            self.db.execute("INSERT INTO loop_records VALUES (?,?,?)", (kind, identity, data))

    def get(self, kind, identity):
        row = self.db.execute("SELECT payload FROM loop_records WHERE kind=? AND identity=?", (kind, identity)).fetchone()
        if not row: raise ValueError(f"unknown {kind}: {identity}")
        return json.loads(row[0])

    def records(self, kind):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT payload FROM loop_records WHERE kind=? ORDER BY identity", (kind,))]


class TaskLibrary:
    def __init__(self, repository): self.repo = repository

    def publish(self, task, contract, artifact, *, transactional=True):
        if not validate(task).structurally_valid: raise ValueError("invalid family")
        expected = {"family_id": fingerprint(task), "family_version": task["revision"],
            "observation_schema_id": task["interfaces"]["observation"],
            "action_schema_id": task["interfaces"]["action"]}
        if any(contract.get(k) != v for k, v in expected.items()): raise ValueError("contract mismatches family")
        for key in ("compiled_artifact_reference", "execution_compatibility_key", "compiler_version",
                    "success_predicate_version", "reward_version", "instance_constructor_id"):
            text_id(contract.get(key))
        if contract.get("status") != "active": raise ValueError("publish active execution contracts only")
        if contract.get("compiled_artifact_hash") != fingerprint(artifact): raise ValueError("artifact digest mismatch")
        if contract.get("supported_embodiments") != [task["embodiment"]]: raise ValueError("unsupported embodiment")
        controllers = contract.get("supported_controller_references")
        if not isinstance(controllers, list) or not controllers: raise ValueError("controllers required")
        for controller in controllers: text_id(controller)
        schema = contract.get("parameter_schema", {})
        if set(schema) != set(task["theta"]) | set(task["phi"]): raise ValueError("parameter schema mismatch")
        if contract.get("schema_version") == "2.0":
            from .curriculum import validate_contract
            validate_contract(task, contract)
        else:
            for key, spec in schema.items():
                group = "theta" if key in task["theta"] else "phi"
                if spec.get("bounds") != task[group][key] or spec.get("sampling_role") != group:
                    raise ValueError("parameter range/role mismatch")
                if spec.get("application_stage") not in ("build", "reset", "step") or spec.get("type") != "float":
                    raise ValueError("V1 parameters require float and explicit application stage")
                text_id(spec.get("units"))
        # Evidence describes the declared envelope, never implicit whole-family approval.
        evidence = contract.get("validation_evidence", {})
        for key in ("report_id", "validator_version", "simulator_version"): text_id(evidence.get(key))
        if evidence.get("family_id") != expected["family_id"]: raise ValueError("validation family mismatch")
        envelope = evidence.get("envelope", {})
        if set(envelope) != set(schema): raise ValueError("explicit validated envelope required")
        for key, bounds in envelope.items():
            validate_domain(bounds)
            if intersect_domain(bounds, schema[key]) != bounds: raise ValueError("invalid envelope")
        checks = evidence.get("checks", {})
        if set(checks) != {"kinematics", "collision", "physics", "reset_stability"} or any(v is not True for v in checks.values()):
            raise ValueError("physical envelope checks required")
        record = {"task": deepcopy(task), "contract": deepcopy(contract), "annotation": task_annotation(task)}
        from task_library.governance import transaction
        with transaction(self.repo.db) if transactional else nullcontext():
            self.repo.put("artifact", contract["compiled_artifact_reference"], artifact)
            self.repo.put("family", canonical([expected["family_id"], expected["family_version"]]), record)
        return record

    def get_family(self, family_id, family_version):
        return self.repo.get("family", canonical([family_id, family_version]))

    def get_sampling_contract(self, family_id, family_version):
        return self.get_family(family_id, family_version)["contract"]

    def get_compiled_artifact(self, reference): return self.repo.get("artifact", reference)

    def list_eligible_families(self, capabilities=()):
        return [r for r in self.repo.records("family") if set(capabilities) <= set(r["annotation"]["capabilities"])]


class CurriculumSampler:
    """Advisor allocations are honored; unsupported requests yield shortfalls."""
    def __init__(self, repository, library, constructors=None, validators=None, *, registry=None):
        self.repo, self.library = repository, library
        self.constructors, self.validators = constructors or {}, validators or {}
        self.registry = registry

    def sample(self, directive, *, total=None, seed=None, controller_id=None, purpose="training", max_attempts=4, experiment=None, now=None):
        if directive.get("schema_version") == "2.0":
            from .curriculum import sample_batch
            if any(v is not None for v in (total, seed, controller_id)) or experiment is not None:
                raise ValueError("v2 execution settings are frozen inside directive")
            return sample_batch(self, directive, now=now)
        integer(total, "total")
        integer(seed, "seed")
        integer(max_attempts, "attempt limit", 1)
        if purpose not in ("training", "demonstration"): raise ValueError("evaluation requires frozen manifest")
        text_id(controller_id)
        original = deepcopy(directive)
        claimed_id = original.pop("directive_id", None)
        if claimed_id != fingerprint(original): raise ValueError("directive content hash mismatch")
        if set(directive["budget"]) != {"learn", "explore", "retain"}: raise ValueError("invalid categories")
        text_id(directive.get("policy_version"))
        request = {"directive": directive, "total": total, "seed": seed, "controller_id": controller_id,
                   "purpose": purpose, "max_attempts": max_attempts, "algorithm": "stratified-v1", "experiment": experiment}
        request["library_snapshot"] = [fingerprint(r) for r in self.repo.records("family")]
        if hasattr(self.library, "snapshot"):
            request["library_approval_snapshot"] = self.library.snapshot()["digest"]
        request_id = fingerprint(request)
        old = self.repo.db.execute("SELECT payload FROM loop_records WHERE kind='sampling' AND identity=?", (request_id,)).fetchone()
        if old: return json.loads(old[0])
        category_quotas = quotas(directive["budget"], total)
        assignments, diagnostics = [], []
        excluded = {x["region_id"] for x in directive.get("exclusions", []) if "region_id" in x}
        for category in ("learn", "explore", "retain"):
            targets = directive[f"{category}_targets"]
            weights = {str(i): t["weight"] for i, t in enumerate(targets)}
            target_quotas = quotas(weights, category_quotas[category])
            for i, target in enumerate(targets):
                count = target_quotas[str(i)]
                candidates = self.library.list_eligible_families(target.get("capabilities", []))
                if "family_id" in target:
                    candidates = [r for r in candidates if r["contract"]["family_id"] == target["family_id"]
                        and r["contract"]["family_version"] == target["family_version"]]
                if target.get("region_id") in excluded: raise ValueError("target contradicts exclusion")
                generated = rejected = 0
                accepted = []
                reasons = {}
                for slot in range(count):
                    for attempt in range(max_attempts):
                        if not candidates: break
                        record = candidates[slot % len(candidates)]
                        task, contract = record["task"], record["contract"]
                        try:
                            if controller_id not in contract["supported_controller_references"]:
                                raise ValueError("controller unsupported")
                            bounds = deepcopy(contract["validation_evidence"]["envelope"])
                            for key, restriction in target.get("parameters", {}).items():
                                if key not in bounds: raise ValueError("unknown restricted parameter")
                                lo, hi = restriction.get("lower"), restriction.get("upper")
                                if lo is not None: bounds[key][0] = max(bounds[key][0], lo)
                                if hi is not None: bounds[key][1] = min(bounds[key][1], math.nextafter(hi, -math.inf))
                                if bounds[key][0] > bounds[key][1]: raise ValueError("empty region intersection")
                            sampling_seed = int(fingerprint([request_id, category, i, slot, attempt])[:16], 16)
                            rng = random.Random(sampling_seed)
                            # Stratify all numeric dimensions, permuting strata independently.
                            parameters = {}
                            for key, (lo, hi) in sorted(bounds.items()):
                                permutation = list(range(count))
                                random.Random(fingerprint([request_id, category, i, key, attempt])).shuffle(permutation)
                                parameters[key] = lo + (hi-lo) * (permutation[slot] + rng.random()) / max(1, count)
                            constructor = self.constructors[contract["instance_constructor_id"]]
                            generated += 1
                            instance = constructor(deepcopy(task), deepcopy(parameters), sampling_seed)
                            if instance.get("theta") != {k: parameters[k] for k in task["theta"]} or instance.get("phi") != {k: parameters[k] for k in task["phi"]}:
                                raise ValueError("constructor changed sampled parameters")
                            evidence = self.validators[contract["instance_constructor_id"]](deepcopy(task), deepcopy(instance))
                            compile_instrumentation(task, instance, evidence)
                            if hasattr(self.library, "assert_sample_allowed"):
                                self.library.assert_sample_allowed(record, instance)
                            if any(fingerprint(instance) == fingerprint(c["instance"]) for m in self.repo.records("benchmark") for c in m["cases"]):
                                raise ValueError("reserved development instance")
                            build = {k: parameters[k] for k, s in contract["parameter_schema"].items() if s["application_stage"] == "build"}
                            assignment = {"schema_version": "1.0", "sampling_request_id": request_id,
                                "directive_id": directive["directive_id"], "category": category, "episode_purpose": purpose,
                                "family_id": contract["family_id"], "family_version": contract["family_version"],
                                "region_id": target.get("region_id"), "compiled_artifact_hash": contract["compiled_artifact_hash"],
                                "execution_compatibility_key": fingerprint([contract["execution_compatibility_key"], build]),
                                "controller_id": controller_id, "policy_checkpoint_id": directive["policy_version"],
                                "sampling_seed": sampling_seed, "instance": instance, "physical_evidence": evidence,
                                "experiment": experiment,
                                "recording_profile": "measured_frames_v1"}
                            assignment["assignment_id"] = fingerprint(assignment)
                            accepted.append(assignment)
                            break
                        except (ValueError, KeyError) as exc:
                            rejected += 1
                            reasons[str(exc)] = reasons.get(str(exc), 0) + 1
                assignments.extend(accepted)
                diagnostics.append({"category": category, "target_index": i, "requested": count,
                    "generated": generated, "rejected": rejected, "accepted": len(accepted),
                    "shortfall": count-len(accepted), "reasons": reasons})
        result = {"request_id": request_id, "request": request, "assignments": assignments,
            "diagnostics": diagnostics, "shortfall": total-len(assignments), "fallbacks": []}
        with self.repo.db:
            self.repo.put("sampling", request_id, result)
            for assignment in assignments:
                self.repo.put("assignment", assignment["assignment_id"], assignment)
                self.repo.db.execute("INSERT OR IGNORE INTO assignment_state VALUES (?,'pending',NULL,NULL,NULL)", (assignment["assignment_id"],))
        return result


class AssignmentScheduler:
    def __init__(self, repository, library): self.repo, self.library = repository, library

    def lease(self, identity, worker, attempt, *, now, ttl, compatibility_key):
        text_id(worker); text_id(attempt)
        number(now, "clock", 0); number(ttl, "ttl", .001)
        assignment = self.repo.get("assignment", identity)
        if hasattr(self.library, "assert_sample_allowed"):
            execution = self.library.get_family(assignment["family_id"], assignment["family_version"])
            self.library.assert_sample_allowed(execution, assignment["instance"])
        if compatibility_key != assignment["execution_compatibility_key"]: raise ValueError("worker incompatible")
        with self.repo.db:
            self.repo.db.execute("BEGIN IMMEDIATE")
            if assignment.get("schema_version") == "2.0":
                from .execution import check_lease
                check_lease(self, assignment, now=now)
            elif hasattr(self.library, "assert_sample_allowed"):
                self.library.assert_sample_allowed(self.library.get_family(assignment["family_id"], assignment["family_version"]), assignment["instance"])
            row = self.repo.db.execute("SELECT state,attempt,deadline FROM assignment_state WHERE identity=?", (identity,)).fetchone()
            if not row or row[0] in ("completed", "cancelled", "failed", "expired"): raise ValueError("assignment unavailable")
            if row[0] in ("leased", "running"):
                if row[2] > now: raise ValueError("live lease exists")
                self.repo.db.execute("UPDATE execution_attempts SET status='expired' WHERE identity=?", (row[1],))
                self.repo.put("attempt_expiry", row[1], {"assignment_id": identity, "at": now, "reason": "lease_expired"})
            self.repo.db.execute("INSERT INTO execution_attempts VALUES (?,?,'leased')", (attempt, identity))
            self.repo.put("attempt_metadata", attempt, {"assignment_id": identity, "worker": worker, "leased_at": now})
            self.repo.db.execute("UPDATE assignment_state SET state='leased',attempt=?,worker=?,deadline=? WHERE identity=?", (attempt, worker, now+ttl, identity))
        return assignment

    def renew(self, identity, attempt, *, now, ttl):
        number(ttl, "ttl", .001); number(now, "clock", 0)
        assignment = self.repo.get("assignment", identity)
        if assignment.get("window", {}).get("expires_at", float("inf")) <= now: raise ValueError("directive expired")
        with self.repo.db:
            cursor = self.repo.db.execute("UPDATE assignment_state SET deadline=? WHERE identity=? AND attempt=? AND state IN ('leased','running') AND deadline>?", (now+ttl, identity, attempt, now))
            if cursor.rowcount != 1: raise ValueError("stale lease")

    def start(self, identity, attempt, *, now):
        number(now, "clock", 0)
        assignment = self.repo.get("assignment", identity)
        if assignment.get("window", {}).get("expires_at", float("inf")) <= now: raise ValueError("directive expired")
        with self.repo.db:
            cursor = self.repo.db.execute("UPDATE assignment_state SET state='running' WHERE identity=? AND attempt=? AND state='leased' AND deadline>?", (identity, attempt, now))
            if cursor.rowcount != 1: raise ValueError("stale or invalid attempt")
            self.repo.db.execute("UPDATE execution_attempts SET status='running' WHERE identity=?", (attempt,))
            self.repo.put("attempt_start", attempt, {"assignment_id": identity, "started_at": now})

    def complete(self, identity, attempt, episode, *, now):
        number(now, "clock", 0)
        assignment = self.repo.get("assignment", identity)
        if assignment.get("schema_version") == "2.0":
            from .execution import complete
            return complete(self, assignment, attempt, episode, now=now)
        if assignment["episode_purpose"] != "training": raise ValueError("demonstrations require separate recorder")
        record = self.library.get_family(assignment["family_id"], assignment["family_version"])
        annotation = record["annotation"]
        if episode.get("source") != "training" or episode.get("policy_version") != assignment["policy_checkpoint_id"] or episode.get("task_instance_id") != fingerprint(assignment["instance"]):
            raise ValueError("episode does not match assignment/controller")
        if episode.get("task_parameters") != assignment["instance"]["theta"]:
            raise ValueError("realized parameters differ from assignment")
        execution = episode.get("assignment_execution", {})
        if execution.get("assignment_id") != identity or execution.get("attempt_id") != attempt:
            raise ValueError("execution provenance missing")
        if execution.get("realized_parameters") != {**assignment["instance"]["theta"], **assignment["instance"]["phi"]}:
            raise ValueError("applied parameters differ from assignment")
        if execution.get("compiler_version") != record["contract"]["compiler_version"] or execution.get("controller_id") != assignment["controller_id"]:
            raise ValueError("compiler/controller provenance mismatch")
        for key in ("simulator_version", "environment_version"): text_id(execution.get(key))
        if not isinstance(execution.get("initial_state"), dict) or not execution["initial_state"]:
            raise ValueError("realized reset state required")
        validate_episode(episode, {(annotation["family_id"], annotation["family_version"]): annotation})
        result = {"assignment_id": identity, "attempt_id": attempt, "episode": episode}
        from task_library.governance import transaction
        with transaction(self.repo.db):
            old = self.repo.db.execute("SELECT payload FROM loop_records WHERE kind='completion' AND identity=?", (identity,)).fetchone()
            if old:
                if old[0] != canonical(result): raise ValueError("conflicting completion")
                return
            row = self.repo.db.execute("SELECT state,attempt,deadline FROM assignment_state WHERE identity=?", (identity,)).fetchone()
            if not row or row[0] != "running" or row[1] != attempt or row[2] <= now: raise ValueError("stale execution attempt")
            self.repo.store.ingest([annotation], [episode], transactional=False)
            self.repo.put("completion", identity, result)
            self.repo.db.execute("UPDATE assignment_state SET state='completed' WHERE identity=?", (identity,))
            self.repo.db.execute("UPDATE execution_attempts SET status='completed' WHERE identity=?", (attempt,))

    def interrupt(self, identity, attempt, *, now, reason):
        text_id(reason)
        number(now, "clock", 0)
        from task_library.governance import transaction
        with transaction(self.repo.db):
            row = self.repo.db.execute("SELECT state,attempt,deadline FROM assignment_state WHERE identity=?", (identity,)).fetchone()
            if not row or row[1] != attempt or row[0] not in ("leased", "running") or row[2] <= now:
                raise ValueError("stale execution attempt")
            self.repo.put("interruption", attempt, {"assignment_id": identity, "reason": reason, "execution_status": "incomplete", "at": now})
            self.repo.db.execute("UPDATE execution_attempts SET status='interrupted' WHERE identity=?", (attempt,))
            self.repo.db.execute("UPDATE assignment_state SET state='pending',attempt=NULL,worker=NULL,deadline=NULL WHERE identity=?", (identity,))

    def cancel(self, identity):
        with self.repo.db:
            cursor = self.repo.db.execute("UPDATE assignment_state SET state='cancelled' WHERE identity=? AND state='pending'", (identity,))
            if cursor.rowcount != 1: raise ValueError("only pending assignments can be cancelled")
            self.repo.put("cancellation", identity, {"assignment_id": identity, "explicit": True})

    def fail(self, identity, attempt, *, now, reason, retry=False):
        from .execution import fail
        return fail(self, identity, attempt, now=now, reason=reason, retry=retry)

    def expire(self, *, now):
        from .execution import expire
        return expire(self, now=now)

    def diagnostics(self, request_id):
        from .execution import diagnostics
        return diagnostics(self, request_id)

    def feedback(self, request_id):
        batch = self.repo.get("sampling", request_id)
        if batch["request"]["directive"].get("schema_version") == "2.0":
            from .execution import feedback
            return feedback(self, request_id)
        ids = {a["assignment_id"] for a in batch["assignments"]}
        states = [row for row in self.repo.db.execute("SELECT identity,state FROM assignment_state") if row[0] in ids]
        completed = sum(row[1] == "completed" for row in states)
        attempts = [row for row in self.repo.db.execute("SELECT assignment,status FROM execution_attempts") if row[0] in ids]
        counts = {"directive_id": batch["request"]["directive"]["directive_id"],
            "requested": batch["request"]["total"], "generated": sum(d["generated"] for d in batch["diagnostics"]),
            "validated": len(ids), "scheduled": len({row[0] for row in attempts}),
            "executed_episodes": completed, "interrupted_attempts": sum(row[1] in ("expired", "interrupted") for row in attempts)}
        counts["feedback_id"] = fingerprint([request_id, counts])
        self.repo.store.ingest(feedback=[counts])
        return counts


def numeric_instance(task, parameters, seed):
    """Trusted constructor for existing float-only generator DSL."""
    from taskgen.core import TaskGenerator
    instance = TaskGenerator(seed).sample(task)
    instance["seed"] = seed
    instance["theta"] = {k: parameters[k] for k in task["theta"]}
    instance["phi"] = {k: parameters[k] for k in task["phi"]}
    return instance


class AssignmentRecorder:
    """Bind observed reset state and software provenance to a leased attempt.

    Pass this recorder to EpisodeTracker.finish or InstrumentedEnvironments.
    The worker supplies realized state after reset, before taking actions.
    """
    def __init__(self, scheduler, assignment_id, attempt_id, *, realized_parameters,
                 initial_state, simulator_version, environment_version, clock,
                 controller_version=None, software_versions=None, trajectory=None):
        self.scheduler, self.identity, self.attempt = scheduler, assignment_id, attempt_id
        assignment = scheduler.repo.get("assignment", assignment_id)
        contract = scheduler.library.get_sampling_contract(assignment["family_id"], assignment["family_version"])
        self.execution = {"assignment_id": assignment_id, "attempt_id": attempt_id,
            "realized_parameters": deepcopy(realized_parameters), "initial_state": deepcopy(initial_state),
            "simulator_version": simulator_version, "environment_version": environment_version,
            "compiler_version": contract["compiler_version"], "controller_id": assignment["controller_id"]}
        if assignment.get("schema_version") == "2.0":
            text_id(controller_version)
            if not isinstance(software_versions, dict) or not software_versions:
                raise ValueError("software versions required")
            for value in software_versions.values(): text_id(value)
            self.execution["controller_version"] = controller_version
            self.execution["software_versions"] = deepcopy(software_versions)
        self.trajectory = trajectory
        self.clock = clock

    def record(self, annotation, episode):
        episode = deepcopy(episode)
        episode["assignment_execution"] = deepcopy(self.execution)
        if self.trajectory is not None: episode["trajectory"] = deepcopy(self.trajectory)
        self.scheduler.complete(self.identity, self.attempt, episode, now=self.clock())
