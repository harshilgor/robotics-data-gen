"""A small trainable synthetic motion baseline behind a replaceable backend.

The policy learns motion magnitude from demonstrated state/action pairs. Task
phase and gripper sequencing remain a trusted controller prior. This is a local
integration baseline, not PPO or evidence of general robotic skill learning.
"""
from copy import deepcopy
import math
from typing import Protocol

from task_advisor.core import canonical, number
from taskgen.core import fingerprint
from task_library.governance import transaction


class TrainingBackend(Protocol):
    version: str
    def train(self, catalog, dataset_id: str) -> dict: ...


class CheckpointStore:
    def __init__(self, repository):
        self.repo = repository
        if getattr(repository, "payload_store", None) is None:
            raise ValueError("checkpoint weights require external payload storage")

    def save(self, policy_version, weights, *, backend, dataset_id=None):
        number(weights.get("gain"), "gain", 0, .012)
        reference = self.repo.payload_store.put(weights)
        artifact = {"schema_version": "local-checkpoint-1.0", "backend": backend,
                    "weights": reference, "weights_digest": fingerprint(weights),
                    "dataset_id": dataset_id, "notice": "synthetic motion calibration baseline"}
        checkpoint = {"policy_version": policy_version, "artifact": artifact, "digest": fingerprint(artifact)}
        with transaction(self.repo.db):
            self.repo.put("checkpoint", policy_version, checkpoint)
        return checkpoint

    def load(self, policy_version):
        checkpoint = self.repo.get("checkpoint", policy_version)
        if checkpoint["digest"] != fingerprint(checkpoint["artifact"]):
            raise ValueError("checkpoint descriptor checksum mismatch")
        weights = self.repo.payload_store.get(checkpoint["artifact"]["weights"])
        if fingerprint(weights) != checkpoint["artifact"]["weights_digest"]:
            raise ValueError("checkpoint weight checksum mismatch")
        number(weights.get("gain"), "gain", 0, .012)
        return {**weights, "checkpoint_digest": checkpoint["digest"]}


class MotionCloningBackend:
    version = "synthetic-motion-cloning-1.0"

    def train(self, catalog, dataset_id):
        manifest = catalog.repo.get("dataset_manifest", dataset_id)
        if any(entry["purpose"] == "evaluation" for entry in manifest["episodes"]):
            raise ValueError("baseline trainer excludes evaluation data even under export exceptions")
        magnitudes = []
        for record in catalog.records(dataset_id):
            if record["metadata"]["purpose"] != "demonstration" or not record["metadata"]["success"]:
                continue
            for sample in record["trajectory"]["samples"]:
                actions = sample["actions"]
                if not {"delta_x", "delta_y", "delta_z", "close_gripper"} <= set(actions):
                    raise ValueError("unsupported action interface for motion cloning")
                magnitude = math.sqrt(sum(actions["delta_" + axis]**2 for axis in "xyz"))
                if magnitude > 1e-8:
                    magnitudes.append(magnitude)
        if not magnitudes:
            raise ValueError("training requires accepted successful motion demonstrations")
        # Most movements use the demonstrated cap; final approach samples are
        # smaller. The median robustly estimates that cap without tuning against
        # the held-out suite or reading privileged state.
        values = sorted(magnitudes)
        gain = min(.012, values[len(values)//2])
        weights = {"gain": gain, "motion_samples": len(values), "dataset_id": dataset_id,
                   "controller_prior": "trusted-stage-and-gripper-sequencing-1.0"}
        result = {"backend": self.version, "weights": weights,
                  "training_metrics": {"sample_count": len(values),
                      "mean_absolute_magnitude_error": sum(abs(v-gain) for v in values)/len(values)},
                  "dataset_id": dataset_id, "limitations": ["synthetic motion only", "discrete task plan is supplied"]}
        with transaction(catalog.repo.db):
            catalog.repo.put("training_run", fingerprint(result), result)
        return result
