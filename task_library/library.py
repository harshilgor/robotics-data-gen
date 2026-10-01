"""Canonical knowledge registry, separate from execution contracts and episodes."""
from copy import deepcopy
from taskgen.parameters import domain, contains, intersect_domain, check_values, validate_domain
import re
from taskgen.core import fingerprint, validate
from task_advisor.core import canonical, number
from task_advisor.loop import TaskLibrary as ExecutionLibrary, text_id
from .governance import Governance, transaction

DEPENDENCIES = {"task_dsl", "predicate_library", "capability_ontology", "object_ontology"}
CONTEXT = {"robot", "gripper", "controller", "compiler_version", "validator_version", "simulator_version"}
TRANSITIONS = {
    "PROPOSED": {"STRUCTURALLY_ACCEPTED", "ARCHIVED"},
    "STRUCTURALLY_ACCEPTED": {"VALIDATING", "ARCHIVED"},
    "VALIDATING": {"VALID", "REJECTED_CONTEXTUALLY", "ARCHIVED"},
    "REJECTED_CONTEXTUALLY": {"VALIDATING", "ARCHIVED"},
    "VALID": {"ACTIVE", "ARCHIVED"}, "ACTIVE": {"DEPRECATED", "ARCHIVED"},
    "DEPRECATED": {"ARCHIVED"}, "ARCHIVED": set(),
}


def semver(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("version must be major.minor.patch")
    return tuple(map(int, value.split(".")))


def structural_signature(task):
    """Ignore parameter bounds/name/revision; normalize sequential node IDs."""
    positions = {n["id"]: i for i, n in enumerate(task["task_graph"])}
    return {"goal": deepcopy(task["success"]), "skills": [
        {"skill": n["skill"], "object": n["object"], "target": n["target"],
         "dependencies": sorted(positions[d] for d in n["depends_on"])} for n in task["task_graph"]],
        "roles": {k: {"affordances": sorted(v.get("affordances", v.get("requires", [])))} for k, v in sorted(task["objects"].items())},
        "constraints": {"scene": task["scene"], "initial_state": task["initial_state"]}}


class TaskLibrary(Governance, ExecutionLibrary):
    def __init__(self, repository):
        super().__init__(repository)
        self.repo.db.executescript("""
            CREATE TABLE IF NOT EXISTS library_versions (
                family TEXT, version TEXT, signature TEXT, payload TEXT NOT NULL,
                PRIMARY KEY(family,version));
            CREATE INDEX IF NOT EXISTS library_signature ON library_versions(signature);
            CREATE TABLE IF NOT EXISTS library_tags (
                family TEXT, version TEXT, kind TEXT, value TEXT,
                PRIMARY KEY(family,version,kind,value));
            CREATE INDEX IF NOT EXISTS library_tag_search ON library_tags(kind,value);
            CREATE TABLE IF NOT EXISTS library_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, family TEXT, version TEXT,
                event_id TEXT UNIQUE, payload TEXT NOT NULL);
        """)
        self.initialize_governance()

    def register(self, family_id, version, task, *, dependencies, provenance, metadata=None, identity_decision=None):
        with transaction(self.repo.db):
            return self._register(family_id, version, task, dependencies=dependencies, provenance=provenance,
                                  metadata=metadata, identity_decision=identity_decision)

    def _register(self, family_id, version, task, *, dependencies, provenance, metadata=None, identity_decision=None):
        text_id(family_id); current = semver(version)
        if not validate(task).structurally_valid: raise ValueError("unsupported or invalid TaskSpec")
        if set(dependencies) != DEPENDENCIES: raise ValueError("pinned semantic dependencies required")
        for v in dependencies.values(): text_id(v)
        if provenance.get("source") not in {"human", "bootstrap", "mutation", "composition", "llm"}:
            raise ValueError("unknown provenance source")
        for key in ("proposal_id", "generator_version"): text_id(provenance.get(key))
        parents = provenance.get("parents")
        if not isinstance(parents, list): raise ValueError("explicit parents required")
        for parent in parents: self.get_version(parent["family_id"], parent["version"])
        signature = structural_signature(task)
        duplicates = [r for r in self.search(structural_hash=fingerprint(signature)) if r["family_id"] != family_id]
        if duplicates:
            import json
            decision = self.repo.db.execute("SELECT payload FROM library_identity_decisions WHERE identity=?", (identity_decision,)).fetchone()
            if not decision or json.loads(decision[0]).get("family_id") != family_id or json.loads(decision[0]).get("task_hash") != fingerprint(task):
                raise ValueError("existing structural family found; reuse its ID or record explicit identity override")
        record = {"family_id": family_id, "version": version, "task_spec": deepcopy(task),
            "task_content_hash": fingerprint(task), "structural_signature": signature,
            "structural_hash": fingerprint(signature), "dependencies": dependencies,
            "provenance": provenance, "metadata": metadata or {}}
        payload = canonical(record)
        old = self.repo.db.execute("SELECT payload FROM library_versions WHERE family=? AND version=?", (family_id, version)).fetchone()
        if old:
            if old[0] != payload: raise ValueError("immutable family version conflict")
            return self.get_version(family_id, version)
        versions = self.search(family_id=family_id)
        if versions:
            latest = max(versions, key=lambda r: semver(r["version"]))
            previous = semver(latest["version"])
            if current <= previous: raise ValueError("new versions must increase")
            prior = latest["task_spec"]
            semantics_changed = (signature != latest["structural_signature"] or
                task["reward"] != prior["reward"] or task["interfaces"] != prior["interfaces"] or
                task["horizon"] != prior["horizon"] or task["objects"] != prior["objects"] or
                task["embodiment"] != prior["embodiment"] or dependencies != latest["dependencies"])
            bounds_changed = any(task[k] != prior[k] for k in ("theta", "phi"))
            if semantics_changed and current[0] == previous[0]: raise ValueError("semantic change requires major version")
            if bounds_changed and current[:2] == previous[:2]: raise ValueError("task-space change requires minor version")
            if bounds_changed and current[0] == previous[0]:
                for group in ("theta", "phi"):
                    if set(task[group]) != set(prior[group]): raise ValueError("parameter schema change requires major version")
                    for key, old_domain in prior[group].items():
                        new_domain = task[group][key]
                        if domain(old_domain)["type"] != domain(new_domain)["type"]:
                            raise ValueError("parameter type change requires major version")
                        if intersect_domain(old_domain, new_domain) != old_domain:
                            raise ValueError("incompatible range narrowing requires major version")
        with transaction(self.repo.db):
            self.repo.db.execute("INSERT INTO library_versions VALUES (?,?,?,?)", (family_id, version, record["structural_hash"], payload))
            from semantics.capabilities import capabilities_for
            tags = [("capability", capability) for capability in capabilities_for(task)]
            tags += [("parameter", k) for group in ("theta", "phi") for k in task[group]]
            tags += [("role", k) for k in task["objects"]] + [("goal", task["success"]["predicate"])]
            for kind, value in set(tags):
                self.repo.db.execute("INSERT INTO library_tags VALUES (?,?,?,?)", (family_id, version, kind, value))
            self._event(family_id, version, "registered", {"state": "PROPOSED"}, "register-"+fingerprint(record))
        return self.get_version(family_id, version)

    def _event(self, family, version, kind, data, event_id):
        text_id(event_id)
        payload = canonical({"kind": kind, **data})
        old = self.repo.db.execute("SELECT family,version,payload FROM library_events WHERE event_id=?", (event_id,)).fetchone()
        if old:
            if old != (family, version, payload): raise ValueError("event identity conflict")
            return
        self.repo.db.execute("INSERT INTO library_events(family,version,event_id,payload) VALUES (?,?,?,?)", (family, version, event_id, payload))

    def history(self, family_id, version):
        import json
        return [json.loads(r[0]) for r in self.repo.db.execute(
            "SELECT payload FROM library_events WHERE family=? AND version=? ORDER BY sequence", (family_id, version))]

    def get_version(self, family_id, version):
        import json
        row = self.repo.db.execute("SELECT payload FROM library_versions WHERE family=? AND version=?", (family_id, version)).fetchone()
        if not row: raise ValueError("unknown exact family version")
        record = json.loads(row[0])
        record["status"] = next(e["state"] for e in reversed(self.history(family_id, version)) if "state" in e)
        return record

    def transition(self, family_id, version, state, *, event_id, reason, context=None):
        with transaction(self.repo.db):
            return self._transition(family_id, version, state, event_id=event_id, reason=reason, context=context)

    def _transition(self, family_id, version, state, *, event_id, reason, context=None):
        text_id(reason)
        record = self.get_version(family_id, version)
        old = self.repo.db.execute("SELECT 1 FROM library_events WHERE event_id=?", (event_id,)).fetchone()
        if not old and state not in TRANSITIONS[record["status"]]: raise ValueError("invalid lifecycle transition")
        if state == "REJECTED_CONTEXTUALLY": self._context(context)
        if state == "ACTIVE":
            if not self.binding(family_id, version):
                raise ValueError("active requires approved execution contract")
        with transaction(self.repo.db):
            self._event(family_id, version, "transition", {"state": state, "reason": reason, "context": context}, event_id)
        return self.get_version(family_id, version)

    def _context(self, context):
        if not isinstance(context, dict) or set(context) != CONTEXT: raise ValueError("complete execution context required")
        for v in context.values(): text_id(v)

    def add_validation(self, family_id, version, *, context, regions, outcome, report_id, evidence_reference, checks=None):
        record = self.get_version(family_id, version)
        self._context(context); text_id(report_id); text_id(evidence_reference)
        if outcome not in {"valid", "invalid", "unknown"} or not regions: raise ValueError("explicit validation regions required")
        parameters = {**record["task_spec"]["theta"], **record["task_spec"]["phi"]}
        for region in regions:
            if set(region) != set(parameters): raise ValueError("complete parameter envelope required")
            for name, bounds in region.items():
                validate_domain(bounds)
                if intersect_domain(bounds, parameters[name]) != bounds: raise ValueError("envelope outside family")
        if outcome == "valid":
            required = {"kinematics", "collision", "physics", "reset_stability"}
            if not isinstance(checks, dict) or set(checks) != required or any(v is not True for v in checks.values()):
                raise ValueError("physical envelope evidence required")
        data = {"context": context, "regions": regions, "outcome": outcome,
                "report_id": report_id, "evidence_reference": evidence_reference, "checks": checks}
        with transaction(self.repo.db): self._event(family_id, version, "validation", data, report_id)

    def feasibility(self, family_id, version, parameters, context):
        self._context(context)
        record = self.get_version(family_id, version)
        bounds = {**record["task_spec"]["theta"], **record["task_spec"]["phi"]}
        if set(parameters) != set(bounds): raise ValueError("full parameter point required")
        check_values(bounds, parameters)
        matches = [e for e in self.history(family_id, version) if e["kind"] == "validation" and e["context"] == context
            and any(all(contains(v, parameters[k]) for k, v in region.items()) for region in e["regions"])]
        outcomes = {e["outcome"] for e in matches}
        return {"status": "conflict" if {"valid", "invalid"} <= outcomes else "invalid" if "invalid" in outcomes else "valid" if "valid" in outcomes else "unknown",
                "reports": [e["report_id"] for e in matches]}

    def search(self, *, family_id=None, capabilities=(), parameters=(), roles=(), goal=None, status=None, structural_hash=None, context=None):
        query, args = "SELECT family,version FROM library_versions WHERE 1=1", []
        if family_id is not None: query += " AND family=?"; args.append(family_id)
        if structural_hash is not None: query += " AND signature=?"; args.append(structural_hash)
        for kind, values in (("capability", capabilities), ("parameter", parameters), ("role", roles), ("goal", [goal] if goal else [])):
            for value in values:
                query += " AND EXISTS (SELECT 1 FROM library_tags t WHERE t.family=library_versions.family AND t.version=library_versions.version AND t.kind=? AND t.value=?)"
                args.extend([kind, value])
        records = [self.get_version(*r) for r in self.repo.db.execute(query+" ORDER BY family,version", args)]
        records = [r for r in records if status is None or r["status"] == status]
        if context is not None:
            self._context(context)
            records = [r for r in records if self.compatibility(r["family_id"], r["version"], context)["supported"]]
        return records

    def nearest(self, task, limit=5):
        target = structural_signature(task)
        skills = {n["skill"] for n in target["skills"]}
        records = self.search()
        def score(r):
            other = {n["skill"] for n in r["structural_signature"]["skills"]}
            return 0. if target == r["structural_signature"] else 1-len(skills & other)/max(1, len(skills | other)) + .1
        return [{"family_id": r["family_id"], "version": r["version"], "distance": score(r)}
                for r in sorted(records, key=lambda r: (score(r), r["family_id"], r["version"]))[:limit]]

    def lineage(self, family_id, version):
        result, seen = [], set()
        def visit(family, ver):
            if (family, ver) in seen: return
            seen.add((family, ver)); record = self.get_version(family, ver)
            result.append({"family_id": family, "version": ver, "provenance": record["provenance"]})
            for p in record["provenance"]["parents"]: visit(p["family_id"], p["version"])
        visit(family_id, version)
        return result

    def resolve_directive(self, directive, *, context=None):
        resolved, gaps = [], []
        for category in ("learn", "explore", "retain"):
            for target in directive[category+"_targets"]:
                matches = self.search(capabilities=target.get("capabilities", []), status="ACTIVE")
                if target.get("family_id"):
                    matches = [r for r in matches if r["task_content_hash"] == target["family_id"] and r["task_spec"]["revision"] == target["family_version"]]
                supported = []
                for record in matches:
                    binding = self.binding(record["family_id"], record["version"])
                    if not binding: continue
                    chosen = context or binding["context"]
                    if chosen != binding["context"]: continue
                    coverage = self.supported_regions(record["family_id"], record["version"], chosen, target.get("parameters"))
                    if coverage["supported"]:
                        supported.append({"family_id": record["family_id"], "version": record["version"], **coverage})
                entry = {"category": category, "target": target, "families": supported}
                if supported: resolved.append(entry)
                if not supported or all(r["gaps"] for r in supported):
                    gaps.append({**entry, "reason": "partial_coverage" if supported else "missing_contextual_coverage"})
        return {"resolved": resolved, "generation_requests": gaps}

    def list_eligible_families(self, capabilities=()):
        # Existing exact-content execution API remains compatible. Governed
        # contracts are unavailable for new work after deprecation/archive.
        records = super().list_eligible_families(capabilities)
        result = []
        for execution in records:
            governed = [r for r in self.search() if r["task_content_hash"] == execution["contract"]["family_id"]]
            if any(r["status"] == "ACTIVE" and self.binding(r["family_id"], r["version"]) and
                   self.compatibility(r["family_id"], r["version"], self.binding(r["family_id"], r["version"])["context"])["supported"] for r in governed):
                result.append(execution)
        return result
