"""Layered validation with explicitly contextual synthetic evidence."""
from copy import deepcopy
import math

from taskgen.core import fingerprint, validate
from taskgen.parameters import check_values, domain
from simulation import LocalSimulationAdapter
from task_compiler import TaskCompiler


class TaskValidator:
    version = "local-validator-1.0"
    simulator_version = LocalSimulationAdapter.simulator_version

    def __init__(self, compiler=None):
        self.compiler = compiler or TaskCompiler()

    def geometry(self, instance):
        theta, phi = instance["theta"], instance["phi"]
        return (.08 + .005 + theta["target_distance"] + theta["object_size"]/2 <= .35 and
                theta["object_size"] <= .055 and 0 < phi["mass"] <= 2. and 0 < phi["friction"] <= 2.)

    def validate(self, task, instance, *, reference=True, max_reference_steps=None):
        structure = validate(task)
        checks = {"logical": structure.structurally_valid, "affordances": structure.structurally_valid,
                  "kinematics": False, "collision": False, "physics": False, "reset_stability": False}
        reasons = list(structure.errors)
        reference_result = {"status": "not_run", "success": None}
        if structure.structurally_valid:
            try:
                if instance.get("family_id") != fingerprint(task) or instance.get("revision") != task["revision"]:
                    raise ValueError("exact TaskSpec instance identity mismatch")
                for group in ("theta", "phi"):
                    check_values({name: domain(spec) for name, spec in task[group].items()}, instance[group])
                checks["kinematics"] = self.geometry(instance)
                checks["collision"] = self.geometry(instance)
                if not checks["kinematics"]:
                    reasons.append("instance outside synthetic workspace/grasp/physics domain")
                else:
                    compiled = self.compiler.compile(task)
                    adapter = LocalSimulationAdapter()
                    parameters = {**instance["theta"], **instance["phi"]}
                    assignment = {"assignment_id": fingerprint(instance), "sampling_seed": instance["seed"],
                        "task_parameters": instance["theta"], "environment_parameters": instance["phi"],
                        "compiled_artifact_hash": fingerprint(compiled), "policy_checkpoint_id": None}
                    adapter.configure("reference", compiled, "validation", {k: parameters[k] for k in ("object_size", "mass", "friction")})
                    adapter.install("reference", assignment, "validation-episode")
                    adapter.apply_reset("reference", {k: parameters[k] for k in ("target_distance", "tolerance")})
                    realized = adapter.reset("reference", task["initial_state"], task["success"])
                    checks["reset_stability"] = (realized["realized_parameters"] == parameters and
                        adapter.environments["reference"]["speed"] == 0.)
                    checks["physics"] = all(math.isfinite(v) for key in ("eef", "object", "target")
                                            for v in adapter.environments["reference"][key])
                    if reference:
                        steps = task["horizon"] if max_reference_steps is None else max_reference_steps
                        if type(steps) is not int or steps < 1:
                            raise ValueError("positive reference execution budget required")
                        success = False
                        for _ in range(min(steps, task["horizon"])):
                            action = adapter.controller_action("reference", adapter.observations("reference"),
                                                               {"id": "local-reference", "policy_checkpoint_id": None})
                            output = adapter.step("reference", action)
                            frame = output["frame"]
                            checks["physics"] &= all(math.isfinite(frame[k]) for k in
                                ("eef_object_distance", "object_target_distance", "height_above_reset", "object_speed"))
                            checks["collision"] &= not frame["collision"]
                            if frame["terminated"] or frame["truncated"]:
                                success = frame["terminated"] and not frame["collision"]
                                break
                        reference_result = {"status": "passed" if success else "failed", "success": success,
                                            "executed_steps": adapter.environments["reference"]["step"],
                                            "controller_version": "local-reference-1.0"}
            except (ValueError, KeyError, TypeError) as exc:
                reasons.append(str(exc))
        physical = {name: checks[name] for name in ("kinematics", "collision", "physics", "reset_stability")}
        valid = all(checks.values()) and not reasons
        status = "validated" if valid and reference_result["success"] else "unknown" if valid else "rejected_contextually"
        report = {"schema_version": "validation-report-1.0", "family_id": fingerprint(task),
            "instance_id": fingerprint(instance), "validator_version": self.version, "simulator_version": self.simulator_version,
            "checks": physical, "layers": checks, "reference_controller_evidence": reference_result,
            "feasibility_status": status, "validation_scope": "synthetic_model_only", "reasons": reasons,
            "evidence_label": "synthetic Cartesian approximation only; no SO-101 IK, dynamics or learnability claim"}
        report["report_id"] = fingerprint(report)
        return report

    def evidence(self, task, instance):
        report = self.validate(task, instance)
        if report["feasibility_status"] != "validated":
            raise ValueError("instance not approved for local synthetic execution: " + str(report["reasons"]))
        return report

    def envelope(self, task):
        """Check full bounds analytically for this simple surrogate, then probe
        opposing corners through the reference controller. This certifies only
        the declared synthetic model; it is not physical envelope certification.
        """
        from taskgen.core import TaskGenerator
        if set(task["theta"]) != {"target_distance", "tolerance", "object_size"} or set(task["phi"]) != {"mass", "friction"}:
            raise ValueError("validator lacks an envelope proof for extra parameters")
        reports = []
        for corner in (0, 1):
            instance = TaskGenerator(0).sample(task, corner)
            for group in ("theta", "phi"):
                instance[group] = {name: domain(bounds)["bounds"][corner] for name, bounds in task[group].items()}
            reports.append(self.evidence(task, instance))
        result = {"family_id": fingerprint(task), "validator_version": self.version,
            "simulator_version": self.simulator_version, "checks": deepcopy(reports[0]["checks"]),
            "envelope": deepcopy({**task["theta"], **task["phi"]}),
            "evidence_label": "analytic synthetic workspace/contact domain with two reference corner probes",
            "reference_report_ids": [report["report_id"] for report in reports]}
        result["report_id"] = fingerprint(result)
        return result
