"""Reliability, purpose-aware records and diagnostics for AssignmentScheduler."""
from copy import deepcopy
import math
from collections import defaultdict, Counter
from taskgen.core import fingerprint
from taskgen.parameters import check_values
from task_library.governance import transaction
from .core import canonical, number, validate_episode
from .curriculum import identity, natural, physical_identity, structural_key


def check_lease(scheduler, assignment, *, now):
    if not assignment["window"]["starts_at"] <= now < assignment["window"]["expires_at"]: raise ValueError("assignment directive expired")
    record = scheduler.library.get_family(assignment["family_id"], assignment["family_version"])
    contract = record["contract"]
    if fingerprint(scheduler.library.get_compiled_artifact(contract["compiled_artifact_reference"])) != assignment["compiled_artifact_hash"]: raise ValueError("artifact mismatch")
    if assignment["controller_id"]+"@"+assignment["controller_version"] not in contract["supported_controller_references"]: raise ValueError("controller incompatible")
    # Approval for the bound context cannot approve a different controller.
    binding = scheduler.library.assert_sample_allowed(record, assignment["instance"])
    if binding["context"]["controller"] != assignment["controller_id"]+"@"+assignment["controller_version"]: raise ValueError("context controller mismatch")
    if assignment["execution_compatibility_key"] != structural_key(contract, {**assignment["task_parameters"],**assignment["environment_parameters"]}): raise ValueError("structural compatibility mismatch")


def trajectory_quality(trajectory, assignment, contract, episode):
    """Return reasons, retaining summaries even when a dataset trajectory is rejected.

    Policy-visible observations are strictly the approved scalar schema; privileged
    state lives in a different stream and never enters the observations field.
    """
    reasons = []
    try:
        if not isinstance(trajectory, dict): raise ValueError("trajectory missing")
        expected = contract["trajectory_schema"]
        if trajectory.get("schema") != expected or trajectory.get("observation_schema_id") != assignment["observation_schema_id"] or trajectory.get("action_schema_id") != assignment["action_schema_id"]:
            raise ValueError("trajectory interface/schema/units/frame mismatch")
        if trajectory.get("time_units") != "s" or trajectory.get("terminal_boundary") != "pre_reset": raise ValueError("trajectory timing/terminal boundary missing")
        samples = trajectory.get("samples")
        if not isinstance(samples,list) or len(samples) != episode["episode_length"]: raise ValueError("trajectory step count mismatch")
        previous = None
        for i, sample in enumerate(samples):
            if sample.get("step") != i+1: raise ValueError("trajectory steps not contiguous")
            observation_time = sample.get("observation_time")
            action_time = sample.get("action_time")
            next_time = sample.get("next_observation_time")
            for value in (observation_time,action_time,next_time): number(value,"trajectory time",0)
            if not observation_time <= action_time < next_time: raise ValueError("observation/action timing invalid")
            if previous is not None and observation_time != previous: raise ValueError("trajectory boundary discontinuity")
            if next_time-action_time > contract["demonstration_quality"]["max_step_seconds"]: raise ValueError("control timing limit")
            check_values(expected["observations"],sample.get("observations"))
            check_values(expected["observations"],sample.get("next_observations"))
            check_values(expected["actions"],sample.get("actions"))
            if type(sample.get("terminal")) is not bool or sample["terminal"] != (i == len(samples)-1): raise ValueError("trajectory terminal flag mismatch")
            if next_time != episode["instrumentation"]["frames"][i]["sim_time"]: raise ValueError("trajectory/measured frame time mismatch")
            previous = next_time
        privileged = trajectory.get("privileged_state", [])
        if not isinstance(privileged, list) or privileged and len(privileged) != len(samples): raise ValueError("privileged state stream length mismatch")
        canonical(trajectory)
    except (ValueError, TypeError, KeyError) as exc: reasons.append(str(exc))
    if assignment["episode_purpose"] == "demonstration":
        if not episode["success"]: reasons.append("demonstration unsuccessful")
        if episode.get("collisions",0) > contract["demonstration_quality"]["max_collisions"]: reasons.append("demonstration physical constraint/collision limit")
    return reasons


def rejected_payload(value):
    """Loss-aware JSON representation for rejected optional recorder payloads."""
    if type(value) is float and not math.isfinite(value): return {"invalid_nonfinite":repr(value)}
    if type(value) in (str,bool,int,float) or value is None: return value
    if isinstance(value,list): return [rejected_payload(v) for v in value]
    if isinstance(value,dict): return {str(k):rejected_payload(v) for k,v in value.items()}
    return {"invalid_payload_type":type(value).__name__}


def complete(scheduler, assignment, attempt, episode, *, now):
    """One valid completion per immutable assignment; retries never inflate evidence.

    Worker/recording failures are not policy failures. A terminal policy timeout or
    failed goal is a completed execution with its own termination reason.
    """
    identity(attempt)
    record = scheduler.library.get_family(assignment["family_id"], assignment["family_version"])
    c, annotation = record["contract"], record["annotation"]
    aid = assignment["assignment_id"]
    purpose = assignment["episode_purpose"]
    expected_source = "training" if purpose == "training" else "development"
    if (episode.get("source") != expected_source or episode.get("family_id") != assignment["family_id"] or
        episode.get("family_version") != assignment["family_version"] or episode.get("task_instance_id") != fingerprint(assignment["instance"]) or
        episode.get("policy_version") != (assignment.get("policy_checkpoint_id") or assignment["controller_version"])):
        raise ValueError("episode assignment/controller/purpose mismatch")
    measured_episode = deepcopy(episode); measured_episode.pop("trajectory",None)
    validate_episode(measured_episode, {(annotation["family_id"],annotation["family_version"]):annotation})
    execution = episode.get("assignment_execution", {})
    if execution.get("assignment_id") != aid or execution.get("attempt_id") != attempt: raise ValueError("attempt provenance mismatch")
    parameters = {**assignment["task_parameters"],**assignment["environment_parameters"]}
    if execution.get("realized_parameters") != parameters or episode["task_parameters"] != assignment["task_parameters"]: raise ValueError("realized parameters mismatch")
    for key,expected in (("compiler_version",c["compiler_version"]),("controller_id",assignment["controller_id"]),("controller_version",assignment["controller_version"])):
        if execution.get(key) != expected: raise ValueError("execution version mismatch: "+key)
    for key in ("simulator_version","environment_version"): identity(execution.get(key))
    if execution["simulator_version"] != c["validation_evidence"]["simulator_version"]: raise ValueError("unapproved simulator version")
    versions = execution.get("software_versions")
    if not isinstance(versions,dict) or not versions: raise ValueError("software versions missing")
    if set(versions) & {"simulator","environment","compiler"}: raise ValueError("reserved software version keys")
    for value in versions.values(): identity(value)
    if not isinstance(execution.get("initial_state"),dict) or not execution["initial_state"]: raise ValueError("realized initial state missing")
    # Replay measured predicates instead of accepting caller success/stage claims.
    from .instrumentation import compile_instrumentation, EpisodeTracker
    tracker = EpisodeTracker(compile_instrumentation(record["task"],assignment["instance"],assignment["physical_evidence"]),
                             episode_id=episode["episode_id"],policy_version=episode["policy_version"],source=expected_source)
    for frame in episode.get("instrumentation",{}).get("frames",[]): tracker.observe(frame)
    if tracker.ready is None: raise ValueError("pre-reset terminal measurements required")
    for key,value in tracker.ready.items():
        if episode.get(key) != value: raise ValueError("episode differs from measured instrumentation: "+key)
    if purpose == "evaluation":
        checkpoint = scheduler.repo.get("checkpoint",assignment["policy_checkpoint_id"])
        if execution.get("frozen_policy_digest") != checkpoint["digest"]: raise ValueError("frozen policy evidence mismatch")
        manifest = scheduler.repo.get("benchmark",assignment["evaluation_manifest_id"])
        case = manifest["cases"][assignment["evaluation_case_index"]]
        if case["instance"] != assignment["instance"]: raise ValueError("evaluation manifest mismatch")
    trajectory = episode.get("trajectory")
    reasons = trajectory_quality(trajectory,assignment,c,episode) if assignment["recording_profile"]["trajectory"] else []
    accepted = trajectory is not None and assignment["recording_profile"]["trajectory"] and not reasons
    trajectory_reference = fingerprint([aid,attempt,rejected_payload(trajectory)]) if trajectory is not None and assignment["recording_profile"]["trajectory"] else None
    state_reference = fingerprint([aid,attempt,execution["initial_state"]])
    summary = {"episode_id":episode["episode_id"],"assignment_id":aid,"execution_attempt_id":attempt,
        "episode_purpose":purpose,"directive_id":assignment["directive_id"],"directive_version":assignment["directive_version"],
        "family_id":assignment["family_id"],"family_version":assignment["family_version"],"region_id":assignment["region_id"],
        "controller_id":assignment["controller_id"],"controller_or_policy_version":episode["policy_version"],
        "controller_version":assignment["controller_version"],"policy_checkpoint_id":assignment.get("policy_checkpoint_id"),
        "simulator_and_environment_versions":{"simulator":execution["simulator_version"],"environment":execution["environment_version"],"compiler":execution["compiler_version"],**versions},
        "realized_parameters":deepcopy(parameters),"initial_state_reference":state_reference,
        "success":episode["success"],"termination_reason":"success" if episode["success"] else "timeout" if episode["timed_out"] else "policy_failure",
        "elapsed_simulation_time":episode["instrumentation"]["frames"][-1]["sim_time"],"control_step_count":episode["episode_length"],
        "reward_summary":{"sum":episode["reward"]},"stage_outcomes":deepcopy(episode["subgoal_results"]),
        "execution_status":"completed","recording_status":"accepted" if accepted else "rejected" if reasons else "not_requested",
        "trajectory_reference":trajectory_reference,"quality_rejection_reasons":reasons,
        "dataset_eligible":accepted and purpose != "evaluation","retry_evidence_policy":assignment["retry_evidence_policy"]}
    result = {"assignment_id":aid,"attempt_id":attempt,"episode":deepcopy(episode),"summary":summary}
    # Do not persist optional frame trajectories redundantly in lightweight summaries
    # or completion records when recording is disabled.
    stored_episode = result["episode"]
    stored_episode.pop("trajectory",None)
    stored_episode["instrumentation"] = deepcopy(stored_episode["instrumentation"])
    stored_episode["instrumentation"].pop("frames",None)
    result["completion_input_hash"] = fingerprint(rejected_payload(episode))
    with transaction(scheduler.repo.db):
        old = scheduler.repo.db.execute("SELECT payload FROM loop_records WHERE kind='completion' AND identity=?",(aid,)).fetchone()
        if old:
            if old[0] != canonical(result): raise ValueError("conflicting completion")
            return deepcopy(summary)
        row = scheduler.repo.db.execute("SELECT state,attempt,deadline FROM assignment_state WHERE identity=?",(aid,)).fetchone()
        if not row or row[0] != "running" or row[1] != attempt or row[2] <= now: raise ValueError("stale execution attempt")
        if purpose == "training":
            scheduler.repo.store.ingest([annotation],[stored_episode],transactional=False)
        scheduler.repo.put("initial_state",state_reference,execution["initial_state"])
        if trajectory_reference: scheduler.repo.put("trajectory",trajectory_reference,rejected_payload(trajectory))
        scheduler.repo.put("episode_summary",aid,summary)
        scheduler.repo.put("completion",aid,result)
        scheduler.repo.db.execute("UPDATE assignment_state SET state='completed' WHERE identity=?",(aid,))
        scheduler.repo.db.execute("UPDATE execution_attempts SET status='completed' WHERE identity=?",(attempt,))
    return deepcopy(summary)


def fail(scheduler, aid, attempt, *, now, reason, retry=False):
    identity(reason); number(now,"clock",0)
    if type(retry) is not bool: raise ValueError("retry flag required")
    with transaction(scheduler.repo.db):
        row = scheduler.repo.db.execute("SELECT state,attempt,deadline FROM assignment_state WHERE identity=?",(aid,)).fetchone()
        if not row or row[0] not in ("leased","running") or row[1] != attempt or row[2] <= now: raise ValueError("stale attempt")
        scheduler.repo.put("execution_failure",attempt,{"assignment_id":aid,"execution_status":"failed","reason":reason,"retry":retry,"at":now})
        scheduler.repo.db.execute("UPDATE execution_attempts SET status='failed' WHERE identity=?",(attempt,))
        scheduler.repo.db.execute("UPDATE assignment_state SET state=?,attempt=NULL,worker=NULL,deadline=NULL WHERE identity=?",("pending" if retry else "failed",aid))


def expire(scheduler, *, now):
    number(now,"clock",0)
    expired = []
    with transaction(scheduler.repo.db):
        for aid,state,attempt,deadline in scheduler.repo.db.execute("SELECT identity,state,attempt,deadline FROM assignment_state").fetchall():
            assignment = scheduler.repo.get("assignment",aid)
            dead_directive = assignment.get("window",{}).get("expires_at",math_infinity()) <= now
            dead_lease = state in ("leased","running") and deadline <= now
            if state not in ("pending","leased","running") or not (dead_directive or dead_lease): continue
            if attempt:
                scheduler.repo.db.execute("UPDATE execution_attempts SET status='expired' WHERE identity=?",(attempt,))
                scheduler.repo.put("attempt_expiry",attempt,{"assignment_id":aid,"at":now,"reason":"directive_expired" if dead_directive else "lease_expired"})
            scheduler.repo.db.execute("UPDATE assignment_state SET state=?,attempt=NULL,worker=NULL,deadline=NULL WHERE identity=?",("expired" if dead_directive else "pending",aid))
            expired.append(aid)
    return expired


def math_infinity(): return float("inf")


def diagnostics(scheduler, rid):
    batch = scheduler.repo.get("sampling",rid)
    assignments = batch["assignments"]
    attempt_rows = scheduler.repo.db.execute("SELECT identity,assignment,status FROM execution_attempts ORDER BY identity").fetchall()
    summaries = {r["assignment_id"]:r for r in scheduler.repo.records("episode_summary")}
    states = dict(scheduler.repo.db.execute("SELECT identity,state FROM assignment_state"))
    timing = scheduler.repo.get("sampling_timing",rid)
    starts = {r["assignment_id"] for r in scheduler.repo.records("attempt_start")}
    rows = []
    for d in batch["diagnostics"]:
        chosen = [a for a in assignments if a["category"] == d["category"] and a["family_id"] == d["family_id"] and a["family_version"] == d["family_version"] and a["region_id"] == d["region_id"] and a.get("fallback_from_region_id") == d.get("fallback_from_region_id")]
        ids = {a["assignment_id"] for a in chosen}
        attempts = [r for r in attempt_rows if r[1] in ids]
        completed = [summaries[i] for i in ids if i in summaries]
        waits = [scheduler.repo.get("attempt_metadata",r[0])["leased_at"]-timing["created_at"] for r in attempts]
        def distribution(values):
            result = {}
            for name in sorted({k for point in values for k in point}):
                data = [p[name] for p in values if name in p]
                result[name] = {"values":data,"counts":dict(Counter(canonical(v) for v in data))}
                if all(type(v) in (int,float) for v in data): result[name].update(minimum=min(data),maximum=max(data),mean=sum(data)/len(data))
            return result
        rows.append({**d,"scheduled":len({r[1] for r in attempts}),"executed":len(ids & starts),"completed":len(completed),
            "started_attempts":sum(bool(scheduler.repo.db.execute("SELECT 1 FROM loop_records WHERE kind='attempt_start' AND identity=?", (r[0],)).fetchone()) for r in attempts),
            "interrupted_attempts":sum(r[2]=="interrupted" for r in attempts),"expired_attempts":sum(r[2]=="expired" for r in attempts),
            "failed_attempts":sum(r[2]=="failed" for r in attempts),"cancelled":sum(states[i]=="cancelled" for i in ids),
            "fallback_assignments":len(chosen) if d.get("fallback_from_region_id") else 0,
            "worker_wait_seconds":waits,"sampling_latency_seconds":timing["latency_seconds"],
            "accepted_distribution":distribution([{**a["task_parameters"],**a["environment_parameters"]} for a in chosen]),
            "executed_distribution":distribution([s["realized_parameters"] for s in completed])})
    rollups = {}
    for level,keys in (("directive",()),("category",("category",)),("family",("family_id","family_version"))):
        grouped = defaultdict(list)
        for row in rows: grouped[canonical([row[k] for k in keys])].append(row)
        aggregates = []
        for key,group in sorted(grouped.items()):
            entry = {k:group[0][k] for k in keys}
            entry["requested"] = sum(r["requested"] for r in group if not r.get("fallback_from_region_id"))
            entry["fallback_requested"] = sum(r["requested"] for r in group if r.get("fallback_from_region_id"))
            for metric in ("generated","rejected","accepted","scheduled","executed","completed","interrupted_attempts","expired_attempts","failed_attempts","cancelled","fallback_assignments"):
                entry[metric] = sum(r[metric] for r in group)
            entry["rejection_reasons"] = dict(sum((Counter(r["reasons"]) for r in group),Counter()))
            entry["worker_wait_seconds"] = [v for r in group for v in r["worker_wait_seconds"]]
            entry["sampling_latency_seconds"] = timing["latency_seconds"]
            entry["region_distributions"] = [{"region_id":r["region_id"],"accepted":r["accepted_distribution"],"executed":r["executed_distribution"]} for r in group]
            entry["primary_shortfall"] = sum(r["shortfall"] for r in group if not r.get("fallback_from_region_id"))
            entry["remaining_shortfall"] = max(0,entry["primary_shortfall"]-entry["fallback_assignments"])
            aggregates.append(entry)
        rollups[level] = aggregates
    if rollups["directive"]:
        rollups["directive"][0]["requested"] = batch["request"]["total"]
        rollups["directive"][0]["remaining_shortfall"] = batch["shortfall"]
    return {"rollups":rollups,"request_id":rid,"directive_id":batch["request"]["directive"]["directive_id"],"rows":rows,
            "budget_shortfall":batch["shortfall"],"fallbacks":batch["fallbacks"],"coverage_shortfalls":batch.get("coverage_shortfalls",[])}


def feedback(scheduler, rid):
    batch = scheduler.repo.get("sampling",rid); report = diagnostics(scheduler,rid)
    rows = report["rows"]
    result = {"directive_id":batch["request"]["directive"]["directive_id"],"requested":batch["request"]["total"],
        "generated":sum(r["generated"] for r in rows),"validated":len(batch["assignments"]),
        "scheduled":sum(r["scheduled"] for r in rows),"executed_episodes":sum(r["completed"] for r in rows),
        "interrupted_attempts":sum(r["interrupted_attempts"]+r["expired_attempts"] for r in rows),"diagnostics":report}
    result["feedback_id"] = fingerprint(result)
    directive = batch["request"]["directive"]
    with transaction(scheduler.repo.db):
        scheduler.repo.put("sampler_feedback",result["feedback_id"],result)
        if directive["episode_purpose"] == "training":
            # Original Advisor identity remains traceable; counts from demo/eval
            # never enter Advisor evidence or inflate training coverage.
            advisor_id = directive.get("advisor_directive_id")
            linked = {**result,"directive_id":advisor_id or result["directive_id"]}
            linked["feedback_id"] = fingerprint(linked)
            if not any(s["directive"]["directive_id"] == linked["directive_id"] for s in scheduler.repo.store.records("snapshots")):
                scheduler.repo.store._put("snapshots", "sampler-"+fingerprint(directive), {"snapshot_id":"sampler-"+fingerprint(directive),"directive":directive})
                linked["directive_id"] = directive["directive_id"]
                linked["feedback_id"] = fingerprint(linked)
            scheduler.repo.store.ingest(feedback=[linked],transactional=False)
    return result


def export_dataset(repository, *, include_evaluation=False, policy_id=None):
    """Explicit evaluation opt-in is recorded, never the default training dataset."""
    if include_evaluation: identity(policy_id)
    records = []
    for summary in repository.records("episode_summary"):
        if summary["recording_status"] != "accepted": continue
        if summary["episode_purpose"] == "evaluation" and not include_evaluation: continue
        trajectory = deepcopy(repository.get("trajectory",summary["trajectory_reference"]))
        trajectory.pop("privileged_state",None)
        records.append({"summary":summary,"trajectory":trajectory})
    policy = {"include_evaluation":include_evaluation,"policy_id":policy_id,"assignment_ids":[r["summary"]["assignment_id"] for r in records]}
    with transaction(repository.db): repository.put("dataset_export",fingerprint(policy),policy)
    return records
