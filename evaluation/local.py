"""Frozen measured local probes using the existing BenchmarkRegistry runner."""
from copy import deepcopy
from taskgen.core import fingerprint
from simulation import LocalSimulationAdapter


class LocalProbeRuntime:
    def __init__(self, factory, checkpoints):
        self.factory, self.checkpoints = factory, checkpoints
        self.adapter = None
        self.checkpoint = None

    def load_frozen_policy(self, checkpoint):
        self.checkpoint = deepcopy(checkpoint)
        weights = self.checkpoints.load(checkpoint["policy_version"])
        if weights["checkpoint_digest"] != checkpoint["digest"]:
            raise ValueError("checkpoint changed during probe initialization")
        self.adapter = LocalSimulationAdapter(policies={checkpoint["policy_version"]: weights})

    def policy_digest(self):
        # Verify weight payloads, rather than returning an arbitrary cached label.
        self.checkpoints.load(self.checkpoint["policy_version"])
        return self.checkpoint["digest"]

    def begin_probe(self, family, instance, *, seed):
        if "probe" in self.adapter.environments:
            self.adapter.abandon("probe")
        compiled = self.factory.library.get_compiled_artifact(family["contract"]["compiled_artifact_reference"])
        values = {**instance["theta"], **instance["phi"]}
        assignment = {"assignment_id": fingerprint([instance, seed]), "sampling_seed": instance["seed"],
                      "task_parameters": instance["theta"], "environment_parameters": instance["phi"],
                      "compiled_artifact_hash": fingerprint(compiled), "policy_checkpoint_id": self.checkpoint["policy_version"]}
        self.adapter.configure("probe", compiled, "frozen-probe", {k: values[k] for k in ("object_size", "mass", "friction")})
        self.adapter.install("probe", assignment, "pending-probe-identity")
        self.adapter.apply_reset("probe", {k: values[k] for k in ("target_distance", "tolerance")})
        self.adapter.reset("probe", family["task"]["initial_state"], family["task"]["success"])

    def step(self, episode_id):
        self.adapter.environments["probe"]["episode_id"] = episode_id
        observations = self.adapter.observations("probe")
        action = self.adapter.controller_action("probe", observations,
            {"id": "local-reference", "policy_checkpoint_id": self.checkpoint["policy_version"]})
        return self.adapter.step("probe", action)["frame"]
