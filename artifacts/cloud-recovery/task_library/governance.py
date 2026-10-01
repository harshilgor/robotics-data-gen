"""Governed publication, region knowledge and portable recovery APIs."""
from contextlib import contextmanager
from copy import deepcopy
from taskgen.parameters import restrict, contains
import json
import uuid
from taskgen.core import fingerprint
from task_advisor.core import canonical, number
from task_advisor.loop import TaskLibrary as ExecutionLibrary, text_id
from .regions import intersect, remove


@contextmanager
def transaction(db):
    """Acquire writer lock before read-modify-write; nested calls use savepoints."""
    if db.in_transaction:
        name = "library_" + uuid.uuid4().hex
        db.execute("SAVEPOINT " + name)
        try:
            yield
            db.execute("RELEASE " + name)
        except BaseException:
            db.execute("ROLLBACK TO " + name); db.execute("RELEASE " + name)
            raise
    else:
        db.execute("BEGIN IMMEDIATE")
        try: yield
        except BaseException: db.rollback(); raise
        else: db.commit()


class Governance:
    def initialize_governance(self):
        self.repo.db.executescript("""
            CREATE TABLE IF NOT EXISTS library_schema (version INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS library_bindings (
                family TEXT, version TEXT, execution_id TEXT, revision INTEGER,
                context TEXT, payload TEXT NOT NULL, PRIMARY KEY(family,version));
            CREATE INDEX IF NOT EXISTS library_binding_context ON library_bindings(context);
            CREATE TABLE IF NOT EXISTS library_identity_decisions (
                identity TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)
        versions = [r[0] for r in self.repo.db.execute("SELECT version FROM library_schema")]
        if any(v > 1 for v in versions): raise ValueError("library schema is newer than runtime")
        with self.repo.db: self.repo.db.execute("INSERT OR IGNORE INTO library_schema VALUES (1)")

    def reconcile(self, task):
        from .library import structural_signature
        matches = self.search(structural_hash=fingerprint(structural_signature(task)))
        return {"decision": "existing_family" if matches else "new_structure",
            "matches": [{"family_id": r["family_id"], "version": r["version"]} for r in matches]}

    def identity_override(self, task, *, family_id, reason, decision_id):
        text_id(family_id); text_id(reason); text_id(decision_id)
        data = {"family_id": family_id, "structure": self.reconcile(task),
            "task_hash": fingerprint(task), "reason": reason}
        with transaction(self.repo.db):
            old = self.repo.db.execute("SELECT payload FROM library_identity_decisions WHERE identity=?", (decision_id,)).fetchone()
            if old and old[0] != canonical(data): raise ValueError("immutable identity decision conflict")
            self.repo.db.execute("INSERT OR IGNORE INTO library_identity_decisions VALUES (?,?)", (decision_id, canonical(data)))
        return decision_id

    def binding(self, family_id, version):
        row = self.repo.db.execute("SELECT payload FROM library_bindings WHERE family=? AND version=?", (family_id, version)).fetchone()
        return json.loads(row[0]) if row else None

    def publish_version(self, family_id, version, contract, artifact, *, context):
        self._context(context)
        with transaction(self.repo.db):
            record = self.get_version(family_id, version)
            if record["status"] not in {"VALID", "ACTIVE"}: raise ValueError("publication requires VALID canonical version")
            if contract["compiler_version"] != context["compiler_version"] or context["controller"] not in contract["supported_controller_references"]:
                raise ValueError("contract context mismatch")
            evidence = contract["validation_evidence"]
            if evidence["validator_version"] != context["validator_version"] or evidence["simulator_version"] != context["simulator_version"]:
                raise ValueError("validation context mismatch")
            if context["robot"] != record["task_spec"]["embodiment"]: raise ValueError("robot mismatch")
            # A changed artifact uses a new task execution revision and canonical
            # patch version; immutable existing execution keys are never overwritten.
            execution = ExecutionLibrary.publish(self, record["task_spec"], contract, artifact, transactional=False)
            self.add_validation(family_id, version, context=context, regions=[evidence["envelope"]],
                outcome="valid", report_id="publication-"+fingerprint([family_id, version, contract]),
                evidence_reference=evidence["report_id"], checks=evidence["checks"])
            mapping = {"family_id": family_id, "version": version,
                "execution_id": contract["family_id"], "execution_revision": contract["family_version"],
                "contract_hash": fingerprint(contract), "context": context,
                "artifact_reference": contract["compiled_artifact_reference"], "artifact_hash": contract["compiled_artifact_hash"]}
            old = self.binding(family_id, version)
            if old and old != mapping: raise ValueError("immutable publication binding conflict")
            self.repo.db.execute("INSERT OR IGNORE INTO library_bindings VALUES (?,?,?,?,?,?)",
                (family_id, version, mapping["execution_id"], mapping["execution_revision"], canonical(context), canonical(mapping)))
        return execution

    def publish(self, task, contract, artifact):
        raise ValueError("governed library requires register(), then publish_version(); use migrate_legacy() for old contracts")

    def migrate_legacy(self, execution_id, revision, *, family_id, version, dependencies, provenance, context):
        execution = ExecutionLibrary.get_family(self, execution_id, revision)
        with transaction(self.repo.db):
            self.register(family_id, version, execution["task"], dependencies=dependencies, provenance=provenance)
            for state in ("STRUCTURALLY_ACCEPTED", "VALIDATING", "VALID"):
                self.transition(family_id, version, state, event_id="migration-"+fingerprint([family_id, version, state]), reason="explicit legacy import")
            self.publish_version(family_id, version, execution["contract"], self.get_compiled_artifact(execution["contract"]["compiled_artifact_reference"]), context=context)
        return self.get_version(family_id, version)

    def supported_regions(self, family_id, version, context, restrictions=None):
        self._context(context)
        record = self.get_version(family_id, version)
        domain = deepcopy({**record["task_spec"]["theta"], **record["task_spec"]["phi"]})
        for key, restriction in (restrictions or {}).items():
            if key not in domain: raise ValueError("unknown parameter restriction")
            try: domain[key] = restrict(domain[key], restriction)
            except ValueError as exc:
                if str(exc) == "empty region intersection":
                    return {"supported": [], "gaps": [], "outside_domain": True}
                raise
        evidence = [e for e in self.history(family_id, version) if e["kind"] == "validation" and e["context"] == context]
        valid = [i for e in evidence if e["outcome"] == "valid" for r in e["regions"] if (i := intersect(domain, r)) is not None]
        blocked = [r for e in evidence if e["outcome"] in {"invalid", "unknown"} for r in e["regions"]]
        supported = remove(valid, blocked)
        return {"supported": supported, "gaps": remove([domain], supported), "outside_domain": False,
            "reports": [e["report_id"] for e in evidence]}

    def compatibility(self, family_id, version, context):
        regions = self.supported_regions(family_id, version, context)
        return {"status": "compatible" if regions["supported"] and not regions["gaps"] else
                "partial" if regions["supported"] else "unknown_or_rejected", **regions}

    def assert_sample_allowed(self, execution, instance):
        bindings = [json.loads(r[0]) for r in self.repo.db.execute(
            "SELECT payload FROM library_bindings WHERE execution_id=? AND revision=?",
            (execution["contract"]["family_id"], execution["contract"]["family_version"]))]
        values = {**instance["theta"], **instance["phi"]}
        for binding in bindings:
            if self.get_version(binding["family_id"], binding["version"])["status"] != "ACTIVE": continue
            regions = self.supported_regions(binding["family_id"], binding["version"], binding["context"])["supported"]
            if any(all(contains(v, values[k]) for k, v in r.items()) for r in regions): return binding
        raise ValueError("instance lacks active, context-valid library approval")

    def snapshot(self):
        with transaction(self.repo.db):
            return self._snapshot()

    def _snapshot(self):
        tables = {
            "library_versions": [list(r) for r in self.repo.db.execute("SELECT * FROM library_versions ORDER BY family,version")],
            "library_tags": [list(r) for r in self.repo.db.execute("SELECT * FROM library_tags ORDER BY family,version,kind,value")],
            "library_events": [list(r) for r in self.repo.db.execute("SELECT * FROM library_events ORDER BY sequence")],
            "library_bindings": [list(r) for r in self.repo.db.execute("SELECT * FROM library_bindings ORDER BY family,version")],
            "library_identity_decisions": [list(r) for r in self.repo.db.execute("SELECT * FROM library_identity_decisions ORDER BY identity")],
            "loop_records": [list(r) for r in self.repo.db.execute("SELECT * FROM loop_records WHERE kind IN ('family','artifact') ORDER BY kind,identity")],
        }
        data = {"schema_version": 1, "tables": tables}
        return {**data, "digest": fingerprint(data)}

    def restore(self, snapshot):
        expected = self.snapshot()["tables"]
        data = deepcopy(snapshot); digest = data.pop("digest", None)
        if data.get("schema_version") != 1 or fingerprint(data) != digest or set(data.get("tables", {})) != set(expected):
            raise ValueError("invalid snapshot schema/checksum")
        if any(expected.values()): raise ValueError("restore requires empty library")
        with transaction(self.repo.db):
            for table, rows in data["tables"].items():
                columns = len(self.repo.db.execute("PRAGMA table_info("+table+")").fetchall())
                for row in rows:
                    if not isinstance(row, list) or len(row) != columns: raise ValueError("invalid snapshot row")
                    self.repo.db.execute("INSERT INTO "+table+" VALUES ("+",".join("?" for _ in row)+")", row)
            for record in self.search():
                from taskgen.core import validate
                from .library import structural_signature, semver, DEPENDENCIES
                semver(record["version"])
                if not validate(record["task_spec"]).structurally_valid or fingerprint(record["task_spec"]) != record["task_content_hash"]:
                    raise ValueError("corrupt restored TaskSpec")
                if record["structural_signature"] != structural_signature(record["task_spec"]) or record["structural_hash"] != fingerprint(record["structural_signature"]):
                    raise ValueError("corrupt structural identity")
                if set(record["dependencies"]) != DEPENDENCIES: raise ValueError("missing restored dependencies")
                for parent in record["provenance"]["parents"]: self.get_version(parent["family_id"], parent["version"])
                for event in self.history(record["family_id"], record["version"]):
                    if event["kind"] == "validation":
                        self._context(event["context"])
                        if event["outcome"] not in ("valid", "invalid", "unknown"): raise ValueError("invalid restored validation")
            for row in self.repo.db.execute("SELECT payload FROM library_bindings"):
                binding = json.loads(row[0]); record = self.get_version(binding["family_id"], binding["version"])
                execution = self.get_family(binding["execution_id"], binding["execution_revision"])
                if record["task_spec"] != execution["task"] or fingerprint(execution["contract"]) != binding["contract_hash"]:
                    raise ValueError("corrupt restored binding")
                artifact = self.get_compiled_artifact(binding["artifact_reference"])
                if fingerprint(artifact) != binding["artifact_hash"]: raise ValueError("corrupt artifact")
        return self.snapshot()
