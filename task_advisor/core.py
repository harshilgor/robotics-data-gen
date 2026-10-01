"""Validated contracts and deterministic Advisor pipeline (standard library only)."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from hashlib import sha256
import json
import math


def shared_ontology():
    from semantics.registry import default_registry
    return {name: definition.get("parent") for name, definition in
            default_registry().snapshot()["definitions"]["capability"].items()}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def number(value, name, low=None, high=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric")
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f"{name} outside range")


def task_annotation(task):
    """Explicit adapter for the existing sequential taskgen DSL, not inference from outcomes."""
    from taskgen.core import validate, fingerprint
    if not validate(task).structurally_valid:
        raise ValueError("invalid generator TaskSpec")
    from semantics.capabilities import capabilities_for, STAGE_CAPABILITY
    annotation = {"family_id": fingerprint(task), "family": task["family"], "family_version": task["revision"],
            "capabilities": capabilities_for(task),
            "subgoals": [{"id": n["id"], "capability": STAGE_CAPABILITY.get(n["skill"], n["skill"]) if task["schema_version"] == "1.2" else n["skill"], "depends_on": n["depends_on"]}
                         for n in task["task_graph"]]}
    if task["schema_version"] in ("1.1", "1.2"): annotation["parameter_schema"] = task["theta"]
    return annotation


@dataclass
class Config:
    minimum_samples: int = 20
    progress_samples: int = 20
    window: int = 100
    combination_samples: int = 20
    mastered: float = .9
    progress_threshold: float = .05
    regression_threshold: float = .1
    stalled: float = .25
    maximum_std: float = .1
    budget: dict = field(default_factory=lambda: {"learn": .65, "explore": .25, "retain": .10})
    bins: dict = field(default_factory=lambda: {"tolerance": [.005, .01, .02, .04],
        "placement_tolerance": [.005, .01, .02, .04], "target_distance": [.1, .25, .4],
        "transport_distance": [.1, .25, .4], "obstacle_count": [1, 3, 6], "sequence_length": [2, 4, 6]})
    ontology: dict = field(default_factory=shared_ontology)

    def validate(self):
        for name in ("minimum_samples", "progress_samples", "window", "combination_samples"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"invalid {name}")
        if self.window < self.progress_samples:
            raise ValueError("window must cover progress_samples")
        for name in ("mastered", "progress_threshold", "regression_threshold", "stalled", "maximum_std"):
            number(getattr(self, name), name, 0, 1)
        if set(self.budget) != {"learn", "explore", "retain"}:
            raise ValueError("invalid budget channels")
        for value in self.budget.values():
            number(value, "budget", 0, 1)
        if not math.isclose(sum(self.budget.values()), 1):
            raise ValueError("budget must sum to one")
        for cuts in self.bins.values():
            for cut in cuts:
                number(cut, "bin edge")
            if cuts != sorted(set(cuts)):
                raise ValueError("bin edges must be strictly increasing")


def validate_annotation(task):
    for key in ("family_id", "family"):
        if not isinstance(task.get(key), str) or not task[key]:
            raise ValueError(f"invalid {key}")
    if type(task.get("family_version")) is not int or task["family_version"] < 1:
        raise ValueError("invalid family_version")
    caps = task.get("capabilities")
    if not isinstance(caps, list) or not caps or any(not isinstance(c, str) or not c for c in caps) or len(caps) != len(set(caps)):
        raise ValueError("invalid capability tags")
    seen = set()
    for stage in task.get("subgoals", []):
        if not isinstance(stage.get("id"), str) or not stage["id"] or stage["id"] in seen:
            raise ValueError("invalid subgoal identity")
        if stage.get("capability") not in caps or not isinstance(stage.get("depends_on"), list) or not set(stage["depends_on"]) <= seen:
            raise ValueError("invalid subgoal capability or dependency order")
        seen.add(stage["id"])
    if not seen:
        raise ValueError("instrumented subgoals required")


def validate_episode(ep, tasks):
    canonical(ep)
    for key in ("episode_id", "policy_version", "task_instance_id", "family_id", "timestamp"):
        if not isinstance(ep.get(key), str) or not ep[key]:
            raise ValueError(f"missing {key}")
    stamp = datetime.fromisoformat(ep["timestamp"].replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    if ep.get("source") not in ("training", "development"):
        raise ValueError("only training or development evidence allowed; sealed/test evaluation rejected")
    task = tasks.get((ep["family_id"], ep.get("family_version")))
    if task is None:
        raise ValueError("unregistered exact family version")
    if type(ep.get("success")) is not bool:
        raise ValueError("success must be boolean")
    number(ep.get("reward"), "reward")
    number(ep.get("completion_fraction"), "completion_fraction", 0, 1)
    if type(ep.get("episode_length")) is not int or ep["episode_length"] < 1:
        raise ValueError("invalid episode_length")
    if not isinstance(ep.get("task_parameters"), dict):
        raise ValueError("task_parameters required")
    if "parameter_schema" in task:
        from taskgen.parameters import check_values
        check_values(task["parameter_schema"], ep["task_parameters"])
    else:
        for name, value in ep["task_parameters"].items(): number(value, name)
    results = ep.get("subgoal_results")
    expected = {stage["id"] for stage in task["subgoals"]}
    if not isinstance(results, dict) or set(results) != expected:
        raise ValueError("all subgoals require true/false/null instrumentation")
    for stage in task["subgoals"]:
        outcome = results[stage["id"]]
        if outcome is not None and type(outcome) is not bool:
            raise ValueError("subgoal result must be bool or null")
        reached = all(results[d] is True for d in stage["depends_on"])
        if not reached and outcome is not None:
            raise ValueError("unreached subgoal must be null, not failure")
    if ep["success"] and any(v is not True for v in results.values()):
        raise ValueError("successful episode requires completed subgoals")
    for name in ("collisions", "grasp_losses"):
        if type(ep.get(name, 0)) is not int or ep.get(name, 0) < 0:
            raise ValueError(f"invalid {name}")
    if ep.get("final_goal_error") is not None:
        number(ep["final_goal_error"], "final_goal_error", 0)
    if type(ep.get("timed_out", False)) is not bool:
        raise ValueError("timed_out must be boolean")
    for name in ("failure_type", "failure_stage"):
        if ep.get(name) is not None and (not isinstance(ep[name], str) or not ep[name]):
            raise ValueError(f"invalid {name}")
    return task


def failure(ep, task):
    if ep["success"]:
        return None
    stage = next((s["id"] for s in task["subgoals"] if ep["subgoal_results"][s["id"]] is False), None)
    if ep.get("grasp_losses", 0):
        kind = "grasp_stability"
    elif ep.get("collisions", 0):
        kind = "collision"
    elif ep.get("timed_out"):
        kind = "timeout"
    else:
        kind = ep.get("failure_type") or "predicate_not_achieved"
    return {"type": kind, "stage": ep.get("failure_stage") or stage, "attribution": "event_or_predicate"}


def region(task, parameters, bins):
    bounds = {}
    for name, cuts in sorted(bins.items()):
        if name not in parameters:
            continue
        v = parameters[name]
        if type(v) not in (int, float):
            bounds[name] = {"values": [v]}
            continue
        lower = None
        upper = None
        for cut in cuts:
            if v < cut:
                upper = cut
                break
            lower = cut
        bounds[name] = {"lower": lower, "upper": upper, "lower_inclusive": True, "upper_inclusive": False}
    descriptor = {"family_id": task["family_id"], "family_version": task["family_version"], "parameters": bounds}
    return sha256(canonical(descriptor).encode()).hexdigest()[:24], descriptor


def estimate(outcomes):
    n = len(outcomes)
    s = sum(outcomes)
    alpha, beta = 1 + s, 1 + n - s
    mean = alpha / (alpha + beta)
    std = math.sqrt(alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1)))
    return {"sample_count": n, "successes": s, "success_estimate": mean,
            "posterior_alpha": alpha, "posterior_beta": beta, "posterior_std": std,
            "confidence": 1 - 2 * std}


def comparable_development(current, previous):
    """Progress requires the same frozen manifest and exact case membership."""
    def membership(rows):
        return {(row[0].get("development_probe", {}).get("manifest_id"), row[0]["task_instance_id"]) for row in rows}
    a, b = membership(current), membership(previous)
    return bool(a) and a == b and all(manifest is not None for manifest, _ in a)


class Advisor:
    def __init__(self, config=None):
        self.config = config or Config()
        self.config.validate()

    def advise(self, policy_version, tasks, episodes, previous_policy_version=None, feedback=None):
        if not isinstance(policy_version, str) or not policy_version or previous_policy_version == policy_version:
            raise ValueError("distinct current/previous policy versions required")
        registry = {}
        for task in tasks:
            validate_annotation(task)
            key = (task["family_id"], task["family_version"])
            if key in registry:
                raise ValueError("duplicate task version")
            registry[key] = task
        rows = []
        seen = set()
        for ep in episodes:
            task = validate_episode(ep, registry)
            if ep["episode_id"] in seen:
                raise ValueError("duplicate episode_id")
            seen.add(ep["episode_id"])
            if ep["policy_version"] not in (policy_version, previous_policy_version):
                continue
            rid, descriptor = region(task, ep["task_parameters"], self.config.bins)
            rows.append((ep, task, rid, descriptor))
        rows.sort(key=lambda row: (datetime.fromisoformat(row[0]["timestamp"].replace("Z", "+00:00")), row[0]["episode_id"]))
        groups = defaultdict(list)
        for row in rows:
            ep, task, rid, descriptor = row
            groups[(rid, ep["source"], ep["policy_version"])].append(row)
        states = []
        for rid in sorted({r[2] for r in rows}):
            current = groups[(rid, "training", policy_version)][-self.config.window:]
            previous = groups[(rid, "training", previous_policy_version)][-self.config.window:]
            # Development does not mix into training counts or curriculum success.
            dev = groups[(rid, "development", policy_version)][-self.config.window:]
            old_dev = groups[(rid, "development", previous_policy_version)][-self.config.window:]
            prototype = next(r for r in rows if r[2] == rid)
            metrics = estimate([r[0]["success"] for r in current])
            lp = None
            if min(len(current), len(previous)) >= self.config.progress_samples:
                lp = metrics["success_estimate"] - estimate([r[0]["success"] for r in previous])["success_estimate"]
            dev_delta = None
            if min(len(dev), len(old_dev)) >= self.config.progress_samples and comparable_development(dev, old_dev):
                dev_delta = estimate([r[0]["success"] for r in dev])["success_estimate"] - estimate([r[0]["success"] for r in old_dev])["success_estimate"]
            regression = max(0, -(dev_delta if dev_delta is not None else lp or 0))
            if metrics["sample_count"] < self.config.minimum_samples or metrics["posterior_std"] > self.config.maximum_std:
                state = "UNKNOWN"
            elif regression >= self.config.regression_threshold:
                state = "REGRESSING"
            elif metrics["success_estimate"] >= self.config.mastered:
                state = "MASTERED"
            elif lp is not None and lp >= self.config.progress_threshold:
                state = "FRONTIER"
            elif lp is not None and metrics["success_estimate"] <= self.config.stalled and abs(lp) < self.config.progress_threshold:
                state = "STALLED"
            else:
                state = "UNKNOWN"
            failures = Counter(failure(r[0], r[1])["type"] for r in current if not r[0]["success"])
            errors = [r[0]["final_goal_error"] for r in current if r[0].get("final_goal_error") is not None]
            states.append({"region_id": rid, **prototype[3], "family": prototype[1]["family"],
                "capabilities": prototype[1]["capabilities"], **metrics, "state": state, "learning_progress": lp,
                "previous_sample_count": len(previous), "regression_score": regression,
                "development_score": estimate([r[0]["success"] for r in dev]) if dev else None,
                "development_delta": dev_delta, "failure_distribution": dict(failures),
                "mean_completion": sum(r[0]["completion_fraction"] for r in current)/len(current) if current else None,
                "mean_goal_error": sum(errors)/len(errors) if errors else None,
                "collision_rate": sum(r[0].get("collisions", 0)>0 for r in current)/len(current) if current else None})
        capability_rows = defaultdict(list)
        combinations = defaultdict(list)
        for ep, task, rid, descriptor in rows:
            if ep["source"] != "training" or ep["policy_version"] != policy_version:
                continue
            for stage in task["subgoals"]:
                outcome = ep["subgoal_results"][stage["id"]]
                if outcome is not None:
                    capability_rows[stage["capability"]].append(outcome)
            combo = tuple(s["capability"] for s in task["subgoals"])
            if len(combo) > 1:
                combinations[combo].append(ep["success"])
        caps = [{"capability_id": cap, "parent": self.config.ontology.get(cap, "custom"),
                 **estimate(capability_rows[cap][-self.config.window:]), "measurement": "observed_subgoal_attempts"}
                for cap in sorted(set(self.config.ontology) | set(capability_rows))]
        for capability in caps:
            cap = capability["capability_id"]
            matched_deltas = []
            dev_deltas = []
            stage_failures = Counter()
            regional_evidence = []
            for rid in sorted({r[2] for r in rows}):
                def stage_outcomes(source, version):
                    return [ep["subgoal_results"][s["id"]]
                        for ep, task, _, _ in groups[(rid, source, version)][-self.config.window:]
                        for s in task["subgoals"] if s["capability"] == cap
                        and ep["subgoal_results"][s["id"]] is not None]
                current_stage = stage_outcomes("training", policy_version)
                old_stage = stage_outcomes("training", previous_policy_version)
                if current_stage:
                    regional_evidence.append({"region_id": rid, **estimate(current_stage)})
                if min(len(current_stage), len(old_stage)) >= self.config.progress_samples:
                    matched_deltas.append(estimate(current_stage)["success_estimate"] - estimate(old_stage)["success_estimate"])
                current_dev = stage_outcomes("development", policy_version)
                old_dev_stage = stage_outcomes("development", previous_policy_version)
                if min(len(current_dev), len(old_dev_stage)) >= self.config.progress_samples and comparable_development(
                        groups[(rid, "development", policy_version)][-self.config.window:],
                        groups[(rid, "development", previous_policy_version)][-self.config.window:]):
                    dev_deltas.append(estimate(current_dev)["success_estimate"] - estimate(old_dev_stage)["success_estimate"])
                for ep, task, _, _ in groups[(rid, "training", policy_version)][-self.config.window:]:
                    if any(s["capability"] == cap and ep["subgoal_results"][s["id"]] is False for s in task["subgoals"]):
                        stage_failures[(failure(ep, task) or {"type": "predicate_not_achieved"})["type"]] += 1
            # Equal weighting over matched regions avoids changing task mix driving capability progress.
            lp = sum(matched_deltas)/len(matched_deltas) if matched_deltas else None
            dev_lp = sum(dev_deltas)/len(dev_deltas) if dev_deltas else None
            capability.update({"learning_progress": lp, "matched_region_count": len(matched_deltas),
                "development_delta": dev_lp, "regression_score": max(0, -(dev_lp if dev_lp is not None else lp or 0)),
                "failure_distribution": dict(stage_failures), "regional_evidence": regional_evidence})
        combos = [{"sequence": list(seq), **estimate(outcomes[-self.config.window:])} for seq, outcomes in sorted(combinations.items())
                  if len(outcomes) >= self.config.combination_samples]
        targets = {"learn": [], "explore": [], "retain": []}
        exclusions = []
        for state in states:
            category = {"FRONTIER": "learn", "UNKNOWN": "explore", "REGRESSING": "retain"}.get(state["state"])
            if category is None:
                exclusions.append({"region_id": state["region_id"], "reason": state["state"].lower(),
                    "constraint": "deprioritize", "suggestion": "easier_related_region" if state["state"] == "STALLED" else "maintenance_floor_owned_by_sampler"})
                continue
            score = max(0, state["learning_progress"] or 0) + 2*state["posterior_std"] + (1-state["success_estimate"]) + 2*state["regression_score"]
            targets[category].append({"region_id": state["region_id"], "family_id": state["family_id"],
                "family_version": state["family_version"], "capabilities": state["capabilities"],
                "parameters": state["parameters"], "score": score, "reason": state["state"].lower(),
                "sample_count": state["sample_count"], "learning_progress": state["learning_progress"]})
        observed = {cap for cap, outcomes in capability_rows.items() if outcomes}
        for cap in sorted(set(self.config.ontology) - observed):
            targets["explore"].append({"capabilities": [cap], "score": 1.0, "reason": "coverage_gap", "sample_count": 0,
                "requires_library_or_generator_support": True})
        for entries in targets.values():
            entries.sort(key=lambda t: (-t["score"], canonical(t)))
            total = sum(t["score"] for t in entries)
            for t in entries:
                t["weight"] = t["score"]/total if total else 1/len(entries)
        # Empty categories remain unallocated, never silently redirected.
        budget = {key: self.config.budget[key] if targets[key] else 0 for key in targets}
        directive = {"schema_version": "1.0", "policy_version": policy_version,
            "previous_policy_version": previous_policy_version, "budget": budget,
            "unallocated_budget": 1-sum(budget.values()), "learn_targets": targets["learn"],
            "explore_targets": targets["explore"], "retain_targets": targets["retain"], "exclusions": exclusions}
        directive["directive_id"] = sha256(canonical(directive).encode()).hexdigest()
        snapshot = {"schema_version": "1.0", "policy_version": policy_version, "config": asdict(self.config),
            "capabilities": caps, "combinations": combos, "regions": states, "directive": directive,
            "generator_feedback": feedback or [], "evidence_ids": [r[0]["episode_id"] for r in rows],
            "limitations": ["Concrete simulator runtime supplied externally", "Development evaluation only; sealed evaluation rejected",
                "Progress comparable only within configured bins; within-bin distribution shifts can confound it",
                "Capability estimates are conditional on observed stages, not causal skill isolation",
                "Confidence is a heuristic uncertainty score, not a calibrated probability",
                "Use controlled-loop Store for enforced frozen development membership; raw advise inputs remain caller-controlled"]}
        snapshot["snapshot_id"] = sha256(canonical(snapshot).encode()).hexdigest()
        return snapshot
