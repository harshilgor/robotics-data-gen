"""Per-environment adapter bridge; the adapter alone steps physics.

Isaac integration must implement this protocol for its pinned version, verify
artifact binaries/configuration and expose terminal state before auto-reset.
Callbacks here never reseed global RNGs. Each environment owns its assignment,
controller, counters, measured tracker and recorder independently.
"""
from copy import deepcopy
from typing import Protocol
from taskgen.core import fingerprint
from .curriculum import identity
from .instrumentation import EpisodeTracker, compile_instrumentation
from .loop import AssignmentRecorder


class ExecutionAdapter(Protocol):
    simulator_version: str
    environment_version: str
    software_versions: dict
    def configure(self, environment_id: str, artifact: dict, compatibility_key: str, build_parameters: dict) -> None: ...
    def install(self, environment_id: str, assignment: dict, episode_id: str) -> None: ...
    def apply_reset(self, environment_id: str, parameters: dict) -> None: ...
    def reset(self, environment_id: str, initial_state: dict, goal: dict) -> dict:
        """Return actual initial_state and realized_parameters after supported reset."""
        ...
    def apply_step(self, environment_id: str, parameters: dict) -> None: ...
    def capture_initial(self, environment_id: str) -> dict:
        """Realized state/parameters after reset and supported step initialization."""
        ...
    def observations(self, environment_id: str) -> dict: ...
    def controller_action(self, environment_id: str, observations: dict, controller: dict) -> dict: ...
    def step(self, environment_id: str, action: dict) -> dict:
        """Return frame (post-action/pre-reset), optional privileged_state separately."""
        ...
    def policy_digest(self, environment_id: str) -> str: ...
    def finalized(self, environment_id: str) -> None:
        """Allow automatic reset only after durable completion."""
        ...
    def abandon(self, environment_id: str) -> None: ...


class AssignmentEnvironments:
    def __init__(self, scheduler, adapter, *, clock):
        self.scheduler, self.adapter, self.clock = scheduler, adapter, clock
        self.sessions, self.episode_counters = {}, {}

    def start(self, environment_id, assignment_id, attempt_id, *, worker_id, ttl):
        identity(environment_id)
        if environment_id in self.sessions: raise ValueError("environment still owns an episode")
        a = self.scheduler.repo.get("assignment",assignment_id)
        if a.get("schema_version") != "2.0": raise ValueError("bridge requires full assignment contract")
        record = self.scheduler.library.get_family(a["family_id"],a["family_version"])
        c = record["contract"]
        now = self.clock()
        self.scheduler.lease(assignment_id,worker_id,attempt_id,now=now,ttl=ttl,compatibility_key=a["execution_compatibility_key"])
        self.episode_counters[environment_id] = self.episode_counters.get(environment_id,0)+1
        episode_id = fingerprint([assignment_id,attempt_id,environment_id,self.episode_counters[environment_id]])
        parameters = {**a["task_parameters"],**a["environment_parameters"]}
        staged = {stage:{k:v for k,v in parameters.items() if c["parameter_schema"][k]["application_stage"] == stage} for stage in ("build","reset","step")}
        try:
            if self.adapter.simulator_version != c["validation_evidence"]["simulator_version"]: raise ValueError("adapter simulator version outside approved context")
            self.adapter.configure(environment_id,self.scheduler.library.get_compiled_artifact(a["compiled_artifact_reference"]),a["execution_compatibility_key"],deepcopy(staged["build"]))
            self.adapter.install(environment_id,deepcopy(a),episode_id)
            self.adapter.apply_reset(environment_id,deepcopy(staged["reset"]))
            realized = self.adapter.reset(environment_id,deepcopy(a["initial_state_specification"]),deepcopy(a["goal_specification"]))
            # Step-stage variation is initialized through its runtime API after reset,
            # never falsely claimed to be a reset-supported physics randomization.
            self.adapter.apply_step(environment_id,deepcopy(staged["step"]))
            realized = self.adapter.capture_initial(environment_id)
            if realized.get("realized_parameters") != parameters: raise ValueError("adapter realized parameters mismatch")
            if not isinstance(realized.get("initial_state"),dict) or not realized["initial_state"]: raise ValueError("adapter initial state missing")
            tracker = EpisodeTracker(compile_instrumentation(record["task"],a["instance"],a["physical_evidence"]),
                episode_id=episode_id,policy_version=a.get("policy_checkpoint_id") or a["controller_version"],
                source="training" if a["episode_purpose"] == "training" else "development")
            recorder = AssignmentRecorder(self.scheduler,assignment_id,attempt_id,
                realized_parameters=realized["realized_parameters"],initial_state=realized["initial_state"],
                simulator_version=self.adapter.simulator_version,environment_version=self.adapter.environment_version,
                controller_version=a["controller_version"],software_versions=self.adapter.software_versions,clock=self.clock)
            if a["episode_purpose"] == "evaluation":
                checkpoint = self.scheduler.repo.get("checkpoint",a["policy_checkpoint_id"])
                if self.adapter.policy_digest(environment_id) != checkpoint["digest"]: raise ValueError("frozen policy mismatch")
                recorder.execution["frozen_policy_digest"] = checkpoint["digest"]
            self.scheduler.start(assignment_id,attempt_id,now=self.clock())
        except Exception as exc:
            self.scheduler.fail(assignment_id,attempt_id,now=self.clock(),reason="adapter_initialization: "+str(exc),retry=True)
            self.adapter.abandon(environment_id)
            raise
        self.sessions[environment_id] = {"assignment":a,"contract":c,"tracker":tracker,"recorder":recorder,"last_time":0.,
            "trajectory":{"schema":deepcopy(c["trajectory_schema"]),"observation_schema_id":a["observation_schema_id"],
                "action_schema_id":a["action_schema_id"],"time_units":"s","terminal_boundary":"pre_reset","samples":[],"privileged_state":[]}}
        return episode_id

    def renew(self, environment_id, *, ttl):
        s = self.sessions[environment_id]
        self.scheduler.renew(s["assignment"]["assignment_id"],s["recorder"].attempt,now=self.clock(),ttl=ttl)

    def step(self, environment_id):
        s = self.sessions[environment_id]; a = s["assignment"]; tracker = s["tracker"]
        if tracker.ready is None:
            row = self.scheduler.repo.db.execute("SELECT state,attempt,deadline FROM assignment_state WHERE identity=?",(a["assignment_id"],)).fetchone()
            if not row or row[0] != "running" or row[1] != s["recorder"].attempt or row[2] <= self.clock():
                self.scheduler.expire(now=self.clock())
                self.adapter.abandon(environment_id); del self.sessions[environment_id]
                raise ValueError("worker lost execution lease")
            if a["episode_purpose"] == "evaluation" and self.adapter.policy_digest(environment_id) != s["recorder"].execution["frozen_policy_digest"]:
                self.interrupt(environment_id,reason="frozen_policy_changed"); raise ValueError("evaluation policy changed")
            try:
                observations = deepcopy(self.adapter.observations(environment_id))
                controller = {"id":a["controller_id"],"version":a["controller_version"],"policy_checkpoint_id":a.get("policy_checkpoint_id"),"purpose":a["episode_purpose"]}
                action = self.adapter.controller_action(environment_id,deepcopy(observations),controller)
                output = self.adapter.step(environment_id,deepcopy(action))
                sensor_frames = {}
                requested = a["recording_profile"].get("modalities", [])
                if requested:
                    from data.modalities import validate_frame
                    if set(output.get("modalities", {})) != set(requested):
                        raise ValueError("adapter omitted requested recording modalities")
                    store = getattr(self.scheduler.repo, "payload_store", None)
                    if store is None: raise ValueError("modalities require an external payload store")
                    for name in requested:
                        measured = deepcopy(output["modalities"][name])
                        payload = measured.pop("payload")
                        validate_frame(name, measured, payload, output["frame"]["sim_time"])
                        measured["payload_reference"] = store.put_bytes(payload, media_type=measured["media_type"])
                        sensor_frames[name] = measured
            except Exception as exc:
                self.scheduler.fail(a["assignment_id"],s["recorder"].attempt,now=self.clock(),reason="adapter_step: "+str(exc),retry=True)
                self.adapter.abandon(environment_id); del self.sessions[environment_id]
                raise
            frame = output.get("frame")
            if a["episode_purpose"] == "evaluation" and self.adapter.policy_digest(environment_id) != s["recorder"].execution["frozen_policy_digest"]:
                self.interrupt(environment_id,reason="frozen_policy_changed"); raise ValueError("evaluation policy changed")
            try:
                tracker.observe(frame)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                self.scheduler.fail(a["assignment_id"],s["recorder"].attempt,now=self.clock(),reason="malformed_terminal_measurements: "+str(exc),retry=True)
                self.adapter.abandon(environment_id); del self.sessions[environment_id]
                raise
            if a["recording_profile"]["trajectory"]:
                s["trajectory"]["samples"].append({"step":frame["step"],"observation_time":s["last_time"],
                    "action_time":output.get("action_time",s["last_time"]),"next_observation_time":frame["sim_time"],
                    "observations":observations,"actions":deepcopy(action),"next_observations":deepcopy(output.get("next_observations")),
                    "reward": frame["reward"],
                    "terminal":tracker.ready is not None})
                s["trajectory"]["privileged_state"].append({"adapter": deepcopy(output.get("privileged_state",{})),
                    "measurements": deepcopy(frame)})
                if a["recording_profile"].get("modalities"):
                    s["trajectory"].setdefault("modalities", []).append(sensor_frames)
            s["last_time"] = frame["sim_time"]
        if tracker.ready is None: return None
        if a["recording_profile"]["trajectory"]: s["recorder"].trajectory = deepcopy(s["trajectory"])
        # Failed recorder calls retain terminal tracker and trajectory. Retry does
        # not step the environment or collect the post-reset observation again.
        if not tracker.closed: tracker.finish(s["recorder"])
        summary = self.scheduler.repo.get("episode_summary",a["assignment_id"])
        self.adapter.finalized(environment_id)
        del self.sessions[environment_id]
        return summary

    def interrupt(self, environment_id, *, reason):
        s = self.sessions[environment_id]
        from task_library.governance import transaction
        with transaction(self.scheduler.repo.db):
            self.scheduler.repo.put("incomplete_episode",s["recorder"].attempt,{"assignment_id":s["assignment"]["assignment_id"],
                "execution_attempt_id":s["recorder"].attempt,"episode_id":s["tracker"].episode_id,"execution_status":"incomplete",
                "control_step_count":len(s["tracker"].frames),"realized_parameters":s["recorder"].execution["realized_parameters"],"reason":reason})
            self.scheduler.interrupt(s["assignment"]["assignment_id"],s["recorder"].attempt,now=self.clock(),reason=reason)
        self.adapter.abandon(environment_id)
        del self.sessions[environment_id]
