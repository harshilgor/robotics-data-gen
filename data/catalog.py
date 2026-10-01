"""Integrity curation owns data correctness, never curriculum strategy."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json

from taskgen.core import fingerprint
from taskgen.parameters import check_values
from task_advisor.core import canonical, number
from task_library.governance import transaction


def integrity_report(trajectory, summary, assignment, contract, payload_store=None):
    reasons = []
    try:
        canonical(trajectory)
        if trajectory["schema"] != contract["trajectory_schema"]:
            raise ValueError("trajectory schema/units/frames differ from compiled contract")
        if (trajectory["observation_schema_id"] != assignment["observation_schema_id"] or
                trajectory["action_schema_id"] != assignment["action_schema_id"]):
            raise ValueError("observation/action interface mismatch")
        if trajectory["time_units"] != "s" or trajectory["terminal_boundary"] != "pre_reset":
            raise ValueError("unsupported time units or terminal boundary")
        samples = trajectory["samples"]
        if not samples or len(samples) != summary["control_step_count"]:
            raise ValueError("missing or corrupt trajectory frames")
        previous = 0.
        for i, sample in enumerate(samples):
            if type(sample.get("step")) is not int or sample["step"] != i + 1:
                raise ValueError("noncontiguous trajectory frames")
            start, action, end = (sample[k] for k in ("observation_time", "action_time", "next_observation_time"))
            for value in (start, action, end):
                number(value, "timestamp", 0)
            if start != previous or not start <= action < end:
                raise ValueError("nonmonotonic or discontinuous timestamps")
            check_values(contract["trajectory_schema"]["observations"], sample["observations"])
            check_values(contract["trajectory_schema"]["observations"], sample["next_observations"])
            check_values(contract["trajectory_schema"]["actions"], sample["actions"])
            if type(sample.get("terminal")) is not bool or sample["terminal"] != (i == len(samples)-1):
                raise ValueError("incorrect terminal frame boundary")
            previous = end
        if previous != summary["elapsed_simulation_time"]:
            raise ValueError("trajectory duration differs from episode metadata")
        requested = assignment.get("recording_profile", {}).get("modalities", [])
        sensors = trajectory.get("modalities", [])
        if requested or sensors:
            from .modalities import validate_frame
            if len(sensors) != len(samples) or payload_store is None:
                raise ValueError("missing modality frames or payload store")
            for sample, frames in zip(samples, sensors):
                if set(frames) != set(requested): raise ValueError("modality coverage mismatch")
                for name, frame in frames.items():
                    metadata = deepcopy(frame)
                    reference = metadata.pop("payload_reference")
                    if reference["media_type"] != metadata["media_type"]: raise ValueError("modality encoding reference mismatch")
                    validate_frame(name, metadata, payload_store.get_bytes(reference), sample["next_observation_time"])
        privileged = trajectory.get("privileged_state", [])
        if privileged and len(privileged) != len(samples):
            raise ValueError("privileged stream length mismatch")
        if summary["execution_status"] != "completed":
            raise ValueError("incomplete episode")
        for key in ("episode_id", "assignment_id", "execution_attempt_id", "family_id", "family_version",
                    "controller_or_policy_version", "simulator_and_environment_versions", "initial_state_reference"):
            if not summary.get(key):
                raise ValueError("missing episode provenance: " + key)
        if summary["family_id"] != assignment["family_id"] or summary["family_version"] != assignment["family_version"]:
            raise ValueError("family version provenance mismatch")
    except (ValueError, KeyError, TypeError) as exc:
        reasons.append(str(exc))
    # Timestamp IDs and privileged state are not policy training samples.
    policy_stream = [{key: sample.get(key) for key in ("observations", "actions", "next_observations", "terminal")}
                     for sample in trajectory.get("samples", [])] if isinstance(trajectory, dict) else []
    return {"valid": not reasons, "reasons": reasons,
            "policy_stream_digest": fingerprint(policy_stream) if not reasons else None}


class DatasetCatalog:
    version = "dataset-catalog-1.0"

    def __init__(self, repository, library):
        self.repo, self.library = repository, library

    def create(self, name, version, assignment_ids, *, created_at,
               purposes=("training", "demonstration"), include_failures=True,
               deduplicate=True, evaluation_policy=None):
        if not isinstance(name, str) or not name or type(version) is not int or version < 1:
            raise ValueError("dataset requires name and positive version")
        stamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("dataset timestamp requires timezone")
        if type(include_failures) is not bool or type(deduplicate) is not bool:
            raise ValueError("explicit boolean curation policy required")
        if not purposes or not set(purposes) <= {"training", "demonstration", "evaluation"}:
            raise ValueError("unknown dataset purpose")
        if "evaluation" in purposes and (not isinstance(evaluation_policy, dict) or
                set(evaluation_policy) != {"policy_id", "reason"} or not all(evaluation_policy.values())):
            raise ValueError("evaluation data requires an explicit versioned dataset policy")
        ids = list(assignment_ids)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate assignment IDs")
        selection = {"purposes": sorted(purposes), "include_failures": include_failures,
                     "deduplicate": deduplicate, "evaluation_policy": evaluation_policy}
        episodes, excluded, seen = [], [], set()
        with transaction(self.repo.db):
            for aid in sorted(ids):
                summary = self.repo.get("episode_summary", aid)
                assignment = self.repo.get("assignment", aid)
                reason = None
                if summary["episode_purpose"] not in purposes:
                    reason = "purpose_excluded"
                elif not include_failures and not summary["success"]:
                    reason = "unsuccessful_episode_excluded"
                elif summary["recording_status"] != "accepted" or not summary["trajectory_reference"]:
                    reason = "recording_not_accepted"
                if reason:
                    excluded.append({"assignment_id": aid, "reasons": [reason]})
                    continue
                contract = self.library.get_sampling_contract(assignment["family_id"], assignment["family_version"])
                try:
                    trajectory = self.repo.get("trajectory", summary["trajectory_reference"])
                    report = integrity_report(trajectory, summary, assignment, contract, getattr(self.repo, "payload_store", None))
                    self.repo.get("initial_state", summary["initial_state_reference"])
                except ValueError as exc:
                    report = {"valid": False, "reasons": [str(exc)], "policy_stream_digest": None}
                if not report["valid"]:
                    excluded.append({"assignment_id": aid, "reasons": report["reasons"]})
                    continue
                if deduplicate and report["policy_stream_digest"] in seen:
                    excluded.append({"assignment_id": aid, "reasons": ["duplicate_policy_stream"]})
                    continue
                seen.add(report["policy_stream_digest"])
                # Historical datasets remain reproducible after a family is
                # deprecated or its envelope changes. Curation resolves the
                # original immutable binding, never grants a new execution lease.
                bindings = [json.loads(row[0]) for row in self.repo.db.execute(
                    "SELECT payload FROM library_bindings WHERE execution_id=? AND revision=? ORDER BY family,version",
                    (assignment["family_id"], assignment["family_version"]))]
                matches = [b for b in bindings if b["contract_hash"] == fingerprint(contract) and
                           b["artifact_hash"] == assignment["compiled_artifact_hash"]]
                if not matches:
                    raise ValueError("historical assignment has no exact governed publication binding")
                binding = matches[0]
                episodes.append({"episode_id": summary["episode_id"], "assignment_id": aid,
                    "execution_attempt_id": summary["execution_attempt_id"], "purpose": summary["episode_purpose"],
                    "success": summary["success"], "trajectory_reference": summary["trajectory_reference"],
                    "trajectory_digest": fingerprint(trajectory), "policy_stream_digest": report["policy_stream_digest"],
                    "family_id": binding["family_id"], "family_version": binding["version"],
                    "semantic_dependencies": self.library.get_version(binding["family_id"], binding["version"])["dependencies"],
                    "compiled_artifact_hash": assignment["compiled_artifact_hash"],
                    "task_instance": deepcopy(assignment["instance"]), "controller_id": assignment["controller_id"],
                    "policy_version": summary["controller_or_policy_version"],
                    "software_versions": summary["simulator_and_environment_versions"],
                    "robot_configuration": contract["robot_configuration"],
                    "observation_schema_id": assignment["observation_schema_id"],
                    "recording_profile": deepcopy(assignment["recording_profile"]),
                    "compiler_version": contract["compiler_version"],
                    "action_schema_id": assignment["action_schema_id"],
                    "initial_state_reference": summary["initial_state_reference"]})
            manifest = {"schema_version": self.version, "name": name, "version": version,
                "created_at": created_at, "selection": selection, "requested_assignment_ids": sorted(ids),
                "episodes": episodes, "excluded": excluded,
                "distribution": {"family": dict(Counter(e["family_id"] for e in episodes)),
                    "purpose": dict(Counter(e["purpose"] for e in episodes)),
                    "success": dict(Counter(str(e["success"]).lower() for e in episodes))},
                "episode_count": len(episodes)}
            manifest["dataset_id"] = fingerprint(manifest)
            self.repo.put("dataset_version", canonical([name, version]), manifest)
            self.repo.put("dataset_manifest", manifest["dataset_id"], manifest)
            if evaluation_policy is not None:
                self.repo.put("dataset_policy", evaluation_policy["policy_id"], evaluation_policy)
        return manifest

    def records(self, dataset_id):
        manifest = self.repo.get("dataset_manifest", dataset_id)
        for entry in manifest["episodes"]:
            trajectory = self.repo.get("trajectory", entry["trajectory_reference"])
            if fingerprint(trajectory) != entry["trajectory_digest"]:
                raise ValueError("dataset payload changed since manifest creation")
            for frames in trajectory.get("modalities", []):
                for frame in frames.values():
                    self.repo.payload_store.get_bytes(frame["payload_reference"])
            # Privileged state is never included in training exports.
            trajectory = deepcopy(trajectory)
            trajectory.pop("privileged_state", None)
            yield {"metadata": deepcopy(entry), "trajectory": trajectory}

    def export_jsonl(self, dataset_id, path):
        with open(path, "x", encoding="utf-8", newline="\n") as handle:
            for record in self.records(dataset_id):
                handle.write(canonical(record) + "\n")
        return {"dataset_id": dataset_id, "path": str(path)}
