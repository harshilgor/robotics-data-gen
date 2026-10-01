"""Versioned sampler contracts and batch helpers for the existing loop engine.

No physics, arbitrary expression evaluation, capability inference or global RNG.
Trusted registries contain application-owned callbacks, not task-provided code.
"""
from copy import deepcopy
from collections import Counter, defaultdict
import math
import random
import time
from taskgen.core import fingerprint
from taskgen.parameters import (domain, validate_domain, schema_contract, check_values,
                                restrict, draw, contains, intersect_domain)
from .core import canonical, number

ALGORITHM = "constraint-stratified-v2"
CATEGORIES = ("learn", "explore", "retain")


def identity(value):
    if not isinstance(value, str) or not value: raise ValueError("nonempty identity required")


def natural(value, name, minimum=0):
    if type(value) is not int or value < minimum: raise ValueError(name + " must be integer")


class Registry:
    """Immutable IDs pin callback behavior. Changing implementation needs a new ID.

    callback dependencies are explicitly declared and checked against contracts.
    Geometry callbacks return boolean; expensive validators return exact-instance
    physical evidence. Reference evidence is informational, never impossibility.
    """
    def __init__(self): self.functions = {}

    def register(self, kind, name, callback, *, dependencies=()):
        if kind not in ("constraint", "geometry", "constructor", "validator", "reference"): raise ValueError("unknown callback kind")
        identity(name)
        if not callable(callback): raise ValueError("callback required")
        if (kind, name) in self.functions: raise ValueError("registered identity immutable")
        self.functions[kind, name] = (callback, tuple(dependencies))
        return self

    def resolve(self, kind, name, schema):
        if (kind, name) not in self.functions: raise ValueError("unregistered " + kind + ": " + str(name))
        function, deps = self.functions[kind, name]
        if not set(deps) <= set(schema): raise ValueError("callback dependencies absent from schema")
        return function

    def check(self, contract):
        schema = contract["parameter_schema"]
        self.resolve("constructor", contract["instance_constructor_id"], schema)
        for kind in ("constraint", "geometry"):
            for spec in contract.get("constraints" if kind == "constraint" else "geometry_checks", []):
                _, deps = self.functions.get((kind, spec["id"]), (None, ()))
                self.resolve(kind, spec["id"], schema)
                if set(deps) != set(spec["dependencies"]): raise ValueError("constraint dependency declaration mismatch")
        self.resolve("validator", contract["validation_policy"]["validator_id"], schema)
        if contract.get("reference_check_id"): self.resolve("reference", contract["reference_check_id"], schema)


def validate_contract(task, contract):
    schema_contract(contract["parameter_schema"])
    schema = contract["parameter_schema"]
    for group in ("theta", "phi"):
        for key, spec in task[group].items():
            if schema[key]["sampling_role"] != group or domain(spec)["type"] != schema[key]["type"]:
                raise ValueError("parameter role/type mismatches task")
            expected = domain(spec)
            field = "values" if expected["type"] == "categorical" else "bounds"
            if schema[key].get(field) != expected[field]: raise ValueError("parameter domain mismatches task")
    tags = contract.get("capability_tags")
    if tags != sorted({n["skill"] for n in task["task_graph"]}): raise ValueError("capability tags mismatch")
    for collection in ("constraints", "geometry_checks"):
        if not isinstance(contract.get(collection), list): raise ValueError("explicit check list required")
        seen = set()
        for spec in contract[collection]:
            identity(spec.get("id"))
            if spec["id"] in seen: raise ValueError("duplicate constraint")
            seen.add(spec["id"])
            deps = spec.get("dependencies")
            if not isinstance(deps, list) or not set(deps) <= set(schema): raise ValueError("unknown constraint dependencies")
    for name,spec in schema.items():
        for dep in spec["dependencies"]:
            if not any({name,dep} <= set(check["dependencies"]) for check in contract["constraints"]):
                raise ValueError("joint parameter dependency requires registered constraint")
    policy = contract.get("validation_policy", {})
    if policy.get("mode") not in ("always", "outside_envelope"): raise ValueError("validation policy required")
    identity(policy.get("validator_id"))
    for key in ("robot_configuration", "actuator_configuration", "sensor_configuration"):
        if key not in contract: raise ValueError("structural configuration required")
    interfaces = contract.get("trajectory_schema", {})
    for kind in ("observations", "actions"):
        fields = interfaces.get(kind)
        if not isinstance(fields, dict) or not fields: raise ValueError("trajectory interface fields required")
        for name, spec in fields.items():
            validate_domain(spec)
            identity(spec.get("units"))
            if "coordinate_frame" not in spec: raise ValueError("trajectory frame required")
    identity(interfaces.get("schema_id"))
    quality = contract.get("demonstration_quality", {})
    if type(quality.get("max_collisions")) is not int or quality["max_collisions"] < 0: raise ValueError("demo physical quality bound required")
    number(quality.get("max_step_seconds"), "demo timing", .000001)


def make_directive(advisor_directive, library, *, total, seed, controller_id,
                   controller_version, window_id, starts_at, expires_at,
                   purpose="training", recording_profile=None):
    """Resolve Advisor recommendations once; freeze exact versions for this window.

    Missing capabilities remain explicit unresolved allocations/shortfalls. Existing
    budget and target weights are preserved; this adapter introduces no strategy.
    """
    original = deepcopy(advisor_directive); claimed = original.pop("directive_id", None)
    if fingerprint(original) != claimed: raise ValueError("Advisor directive digest mismatch")
    targets, unresolved = {}, []
    for category in CATEGORIES:
        targets[category] = []
        for i, target in enumerate(advisor_directive[category+"_targets"]):
            candidates = library.list_eligible_families(target.get("capabilities", []))
            if target.get("family_id"):
                candidates = [r for r in candidates if r["contract"]["family_id"] == target["family_id"] and r["contract"]["family_version"] == target["family_version"]]
            if not candidates:
                unresolved.append({"category":category,"target":deepcopy(target),"reason":"no eligible exact family version"})
            # A capability-only target is resolved deterministically across exact
            # eligible versions; its declared weight is divided, never re-ranked.
            for record in candidates:
                c = record["contract"]
                targets[category].append({"region_id": target.get("region_id") or fingerprint([claimed, category, i, c["family_id"]]),
                    "region_version": 1, "family_id": c["family_id"], "family_version": c["family_version"],
                    "parameter_restrictions": deepcopy(target.get("parameters", {})), "categorical_filters": {},
                    "weight": target["weight"]/len(candidates)})
    directive = {"schema_version": "2.0", "directive_version": 1,
        "advisor_directive_id": claimed, "policy_checkpoint_id": advisor_directive["policy_version"],
        "embodiment_id": "so101", "episode_purpose": purpose, "total_episode_budget": total,
        "category_allocations": deepcopy(advisor_directive["budget"]), "family_region_allocations": targets,
        "exclusions": deepcopy(advisor_directive.get("exclusions", [])), "minimum_coverage_requirements": [],
        "allowed_fallbacks": [], "recording_profile": recording_profile or {"trajectory": False},
        "seed": seed, "window": {"window_id": window_id, "starts_at": starts_at, "expires_at": expires_at},
        "controller_id": controller_id, "controller_version": controller_version,
        "diversity": {"mode": "allow_repetition", "dimensions": [], "balanced_categorical": True},
        "max_candidate_attempts": 8, "unresolved_advisor_targets":unresolved}
    directive["directive_id"] = fingerprint(directive)
    return directive


def validate_directive(directive, *, now):
    number(now, "clock", 0)
    d = deepcopy(directive); claimed = d.pop("directive_id", None)
    if claimed != fingerprint(d): raise ValueError("directive content hash mismatch")
    if d.get("schema_version") != "2.0": raise ValueError("unsupported directive version")
    allowed = {"schema_version","directive_version","advisor_directive_id","policy_checkpoint_id","embodiment_id","episode_purpose","total_episode_budget","category_allocations","family_region_allocations","exclusions","minimum_coverage_requirements","allowed_fallbacks","recording_profile","seed","window","controller_id","controller_version","diversity","max_candidate_attempts","unresolved_advisor_targets"}
    if set(d)-allowed: raise ValueError("unknown directive fields")
    natural(d.get("directive_version"), "directive version", 1)
    for key in ("embodiment_id", "controller_id", "controller_version"): identity(d.get(key))
    if d.get("episode_purpose") not in ("training", "demonstration"): raise ValueError("evaluation requires frozen manifest")
    if d["episode_purpose"] == "training": identity(d.get("policy_checkpoint_id"))
    natural(d.get("total_episode_budget"), "budget"); natural(d.get("seed"), "seed")
    natural(d.get("max_candidate_attempts"), "attempt bound", 1)
    w = d.get("window", {})
    if set(w) != {"window_id","starts_at","expires_at"}: raise ValueError("window fields missing or unknown")
    identity(w.get("window_id")); number(w.get("starts_at"), "start", 0); number(w.get("expires_at"), "expiry", w["starts_at"]+.000001)
    if not w["starts_at"] <= now < w["expires_at"]: raise ValueError("directive outside frozen window")
    weights = d.get("category_allocations", {})
    if set(weights) != set(CATEGORIES): raise ValueError("invalid categories")
    from .loop import quotas
    category_quotas = quotas(weights, d["total_episode_budget"])
    allocations = d.get("family_region_allocations", {})
    if set(allocations) != set(CATEGORIES): raise ValueError("invalid region allocations")
    regions = {}
    for category in CATEGORIES:
        if not isinstance(allocations[category], list): raise ValueError("allocation list required")
        for region in allocations[category]:
            if set(region) != {"region_id","region_version","family_id","family_version","parameter_restrictions","categorical_filters","weight"}: raise ValueError("region fields missing or unknown")
            for key in ("region_id", "family_id"): identity(region.get(key))
            if region["region_id"] == "unallocated": raise ValueError("reserved quota identity")
            for key in ("region_version", "family_version"): natural(region.get(key), key, 1)
            number(region.get("weight"), "region weight", 0, 1)
            for key in ("parameter_restrictions", "categorical_filters"):
                if not isinstance(region.get(key), dict): raise ValueError("explicit region restrictions required")
            if set(region["parameter_restrictions"]) & set(region["categorical_filters"]): raise ValueError("ambiguous region restriction")
            ref = (category, region["region_id"])
            if ref in regions: raise ValueError("duplicate allocation region")
            regions[ref] = region
        quotas({r["region_id"]: r["weight"] for r in allocations[category]}, category_quotas[category])
    exclusions = d.get("exclusions")
    if not isinstance(exclusions, list): raise ValueError("exclusion list required")
    for exclusion in exclusions:
        if not isinstance(exclusion, dict) or not set(exclusion) & {"region_id", "family_id", "capabilities"}: raise ValueError("uninterpretable exclusion")
        for region in regions.values():
            if exclusion.get("region_id") == region["region_id"] or exclusion.get("family_id") == region["family_id"]:
                raise ValueError("target contradicts exclusion")
    floors = d.get("minimum_coverage_requirements")
    if not isinstance(floors, list): raise ValueError("coverage list required")
    seen = set()
    for floor in floors:
        ref = (floor.get("category"), floor.get("region_id"))
        if ref not in regions or ref in seen: raise ValueError("unknown/duplicate coverage region")
        seen.add(ref); natural(floor.get("minimum"), "coverage minimum")
    for category in CATEGORIES:
        if sum(f["minimum"] for f in floors if f["category"] == category) > category_quotas[category]: raise ValueError("minimum coverage exceeds category budget")
    if not isinstance(d.get("allowed_fallbacks"), list): raise ValueError("fallback list required")
    seen = set()
    for fallback in d["allowed_fallbacks"]:
        ref = (fallback.get("category"), fallback.get("from_region_id"))
        if ref not in regions or ref in seen: raise ValueError("unknown/duplicate fallback source")
        seen.add(ref)
        target = fallback.get("to_region", {})
        # Validate fallback through same region contract without recursively
        # allocating a new directive or changing the source quota.
        probe = deepcopy(d); probe["family_region_allocations"] = {c: [] for c in CATEGORIES}
        probe["family_region_allocations"][ref[0]] = [dict(target, weight=1.)]
        probe["minimum_coverage_requirements"] = []; probe["allowed_fallbacks"] = []
        probe["directive_id"] = fingerprint(probe)
        validate_directive(probe, now=now)
    diversity = d.get("diversity", {})
    if diversity.get("mode") not in ("unique_parameters", "allow_repetition") or not isinstance(diversity.get("dimensions"), list) or type(diversity.get("balanced_categorical")) is not bool:
        raise ValueError("invalid diversity contract")
    if len(set(diversity["dimensions"])) != len(diversity["dimensions"]): raise ValueError("duplicate diversity dimensions")
    recording = d.get("recording_profile", {})
    if set(recording) != {"trajectory"}: raise ValueError("unknown recording profile fields")
    if type(recording.get("trajectory")) is not bool: raise ValueError("explicit recording profile required")
    if d["episode_purpose"] == "demonstration" and not recording["trajectory"]: raise ValueError("demonstrations require quality-verifiable trajectory")
    return category_quotas


def region_quotas(regions, floors, total):
    """Reserve explicit floors, then Hamilton-allocate remaining budget, lexical ties."""
    from .loop import quotas
    reserved = {r["region_id"]: next((f["minimum"] for f in floors if f["region_id"] == r["region_id"]), 0) for r in regions}
    extra = quotas({r["region_id"]: r["weight"] for r in regions}, total-sum(reserved.values()))
    return {k: v+extra[k] for k, v in reserved.items()}


def domains_for(contract, region):
    bounds = {k: deepcopy(domain(v)) for k, v in contract["parameter_schema"].items()}
    restrictions = {**region["parameter_restrictions"], **{k: {"values": v} for k, v in region["categorical_filters"].items()}}
    for key, restriction in restrictions.items():
        if key not in bounds: raise ValueError("unknown restricted parameter")
        bounds[key] = restrict(bounds[key], restriction)
    return bounds


def structural_key(contract, parameters):
    return fingerprint({"base": contract["execution_compatibility_key"],
        "robot": contract.get("robot_configuration"), "actuators": contract.get("actuator_configuration"),
        "sensors": contract.get("sensor_configuration"), "observation": contract["observation_schema_id"],
        "action": contract["action_schema_id"],
        "build": {k: v for k, v in parameters.items() if contract["parameter_schema"][k]["application_stage"] == "build"}})


def physical_identity(assignment):
    return fingerprint([assignment["family_id"], assignment["family_version"],
                        assignment["task_parameters"], assignment["environment_parameters"],
                        assignment["initial_state_specification"], assignment["goal_specification"]])


def build_assignment(record, region, instance, parameters, evidence, *, request_id, directive,
                     category, sampling_seed, ordinal, fallback_from=None):
    c = record["contract"]
    result = {"schema_version": "2.0", "sampling_request_id": request_id,
        "directive_id": directive["directive_id"], "directive_version": directive["directive_version"],
        "category": category, "episode_purpose": directive["episode_purpose"],
        "family_id": c["family_id"], "family_version": c["family_version"],
        "region_id": region["region_id"], "region_version": region["region_version"],
        "origin_region": deepcopy(region), "fallback_from_region_id": fallback_from,
        "compiled_artifact_reference": c["compiled_artifact_reference"], "compiled_artifact_hash": c["compiled_artifact_hash"],
        "execution_compatibility_key": structural_key(c, parameters),
        "embodiment_id": directive["embodiment_id"], "controller_id": directive["controller_id"],
        "controller_version": directive["controller_version"], "policy_checkpoint_id": directive.get("policy_checkpoint_id"),
        "task_parameters": deepcopy(instance["theta"]), "environment_parameters": deepcopy(instance["phi"]),
        "initial_state_specification": deepcopy(instance.get("initial_state_specification", record["task"]["initial_state"])),
        "goal_specification": deepcopy(instance.get("goal_specification", record["task"]["success"])),
        "observation_schema_id": c["observation_schema_id"], "action_schema_id": c["action_schema_id"],
        "recording_profile": deepcopy(directive["recording_profile"]), "sampling_seed": sampling_seed,
        "instance": deepcopy(instance), "physical_evidence": deepcopy(evidence),
        "validation_result": {"instantiation_validity": "valid", "geometric_or_kinematic_checks": "passed",
            "reference_controller_evidence": evidence.get("reference_controller_evidence", {"status": "not_run"}),
            "feasibility_status": evidence.get("feasibility_status", "supported_envelope"),
            "report_id": evidence["report_id"]},
        "window": deepcopy(directive["window"]), "ordinal": ordinal,
        "retry_evidence_policy": "first_valid_completion_per_assignment"}
    if evidence.get("feasibility_status") not in (None, "supported_envelope", "validated", "unknown"):
        raise ValueError("invalid feasibility status")
    result["assignment_id"] = fingerprint(result)
    return result


def sample_batch(sampler, directive, *, now):
    """Called by existing CurriculumSampler.sample; all mutations share its repository."""
    from task_library.governance import transaction
    from .instrumentation import compile_instrumentation
    if not hasattr(sampler.library, "assert_sample_allowed"): raise ValueError("v2 requires governed Library")
    cq = validate_directive(directive, now=now)
    registry = sampler.registry
    if registry is None: raise ValueError("v2 requires registered callbacks")
    started = time.perf_counter()
    # Serialize sampling/publication so snapshot and approval cannot race. Bounded
    # batch validation runs under this local database lock, not an external service.
    with transaction(sampler.repo.db):
        window_key = canonical([directive["episode_purpose"], directive["embodiment_id"], directive["window"]["window_id"]])
        sampler.repo.put("directive_window", window_key, directive)
        sampler.repo.put("directive", canonical([directive["directive_id"], directive["directive_version"]]), directive)
        directive_key = canonical([directive["directive_id"],directive["directive_version"]])
        pinned = sampler.repo.db.execute("SELECT payload FROM loop_records WHERE kind='directive_batch' AND identity=?", (directive_key,)).fetchone()
        if pinned:
            import json
            return sampler.repo.get("sampling",json.loads(pinned[0])["request_id"])
        selected = {}
        all_regions = [r for c in CATEGORIES for r in directive["family_region_allocations"][c]] + [f["to_region"] for f in directive["allowed_fallbacks"]]
        eligible = {(r["contract"]["family_id"], r["contract"]["family_version"]): r for r in sampler.library.list_eligible_families()}
        for region in all_regions:
            definition = {k:deepcopy(v) for k,v in region.items() if k != "weight"}
            sampler.repo.put("task_region", canonical([region["region_id"],region["region_version"]]), definition)
            ref = (region["family_id"], region["family_version"])
            record = sampler.library.get_family(*ref)
            contract = record["contract"]
            if contract.get("schema_version") != "2.0": raise ValueError("v2 sampling requires typed contract")
            registry.check(contract)
            restrictions = {**region["parameter_restrictions"], **{k:{"values":v} for k,v in region["categorical_filters"].items()}}
            for key,value in restrictions.items():
                if key not in contract["parameter_schema"]: raise ValueError("unknown restricted parameter")
                spec = contract["parameter_schema"][key]
                if key in region["categorical_filters"] and spec["type"] != "categorical": raise ValueError("categorical filter applied to numeric parameter")
                try: restrict(spec,value)
                except ValueError as exc:
                    if str(exc) != "empty region intersection": raise
            if directive["embodiment_id"] not in contract["supported_embodiments"]: raise ValueError("embodiment unsupported")
            controller = directive["controller_id"]+"@"+directive["controller_version"]
            if controller not in contract["supported_controller_references"]: raise ValueError("controller unsupported")
            if any(set(e.get("capabilities", [])) & set(contract["capability_tags"]) for e in directive["exclusions"]): raise ValueError("target contradicts capability exclusion")
            if not set(directive["diversity"]["dimensions"]) <= set(contract["parameter_schema"]): raise ValueError("unknown diversity dimension")
            artifact = sampler.library.get_compiled_artifact(contract["compiled_artifact_reference"])
            if fingerprint(artifact) != contract["compiled_artifact_hash"]: raise ValueError("artifact hash mismatch")
            selected[ref] = record if ref in eligible else None
        request = {"directive": deepcopy(directive), "total": directive["total_episode_budget"], "seed": directive["seed"],
                   "algorithm": ALGORITHM, "library_snapshot": sampler.library.snapshot()["digest"]}
        rid = fingerprint(request)
        existing = sampler.repo.db.execute("SELECT payload FROM loop_records WHERE kind='sampling' AND identity=?", (rid,)).fetchone()
        if existing:
            import json
            return json.loads(existing[0])
        accepted, diagnostics, fallbacks, seen = [], [], [], set()
        reserved = {physical_identity(a) for a in sampler.repo.records("assignment") if a.get("schema_version") == "2.0" and a["episode_purpose"] == "evaluation"}
        def generate(category, region, count, fallback_from=None):
            record = selected[region["family_id"], region["family_version"]]
            diag = {"directive_id": directive["directive_id"], "category": category, "family_id": region["family_id"],
                    "family_version": region["family_version"], "region_id": region["region_id"], "region_version": region["region_version"],
                    "requested": count, "generated": 0, "rejected": 0, "accepted": 0, "reasons": {}, "fallback_from_region_id": fallback_from}
            diagnostics.append(diag)
            if record is None:
                diag["reasons"]["family not actively approved"] = count; diag["shortfall"] = count; return 0
            c = record["contract"]; schema = c["parameter_schema"]
            try: bounds = domains_for(c, region)
            except ValueError as exc:
                diag["reasons"][str(exc)] = count; diag["shortfall"] = count; return 0
            for slot in range(count):
                for attempt in range(directive["max_candidate_attempts"]):
                    diag["generated"] += 1
                    ss = int(fingerprint([rid, category, region["region_id"], fallback_from, slot, attempt])[:16], 16)
                    rng = random.Random(ss)
                    values = {}
                    for key, value in sorted(bounds.items()):
                        spec = domain(value)
                        permutation = list(range(count))
                        random.Random(fingerprint([rid, category, region["region_id"], key])).shuffle(permutation)
                        if spec["type"] == "categorical" and directive["diversity"]["balanced_categorical"]:
                            choices = list(spec["values"])
                            random.Random(fingerprint([rid, region["region_id"], key])).shuffle(choices)
                            values[key] = choices[permutation[slot] % len(choices)]
                        else: values[key] = draw(value, rng, (permutation[slot]+rng.random())/max(1,count))
                    try:
                        check_values(schema, values)
                        for check in c["constraints"]:
                            if registry.resolve("constraint", check["id"], schema)(deepcopy(values)) is not True: raise ValueError("constraint: "+check["id"])
                        constructor = registry.resolve("constructor", c["instance_constructor_id"], schema)
                        instance = constructor(deepcopy(record["task"]), deepcopy(values), ss)
                        if instance.get("theta") != {k:v for k,v in values.items() if schema[k]["sampling_role"] == "theta"} or instance.get("phi") != {k:v for k,v in values.items() if schema[k]["sampling_role"] == "phi"}:
                            raise ValueError("constructor changed parameters")
                        for field in ("initial_state_specification", "goal_specification"):
                            if field in instance and (not isinstance(instance[field],dict) or not instance[field]): raise ValueError("invalid instance state/goal specification")
                        for check in c["geometry_checks"]:
                            if registry.resolve("geometry", check["id"], schema)(deepcopy(instance)) is not True: raise ValueError("geometry: "+check["id"])
                        # Governing context is checked for this exact instance, never
                        # silently intersected with a narrower approved/easier region.
                        binding = sampler.library.assert_sample_allowed(record, instance)
                        if binding["context"]["controller"] != directive["controller_id"]+"@"+directive["controller_version"]: raise ValueError("context controller mismatch")
                        envelope = c["validation_evidence"]["envelope"]
                        inside = all(contains(v, values[k]) for k,v in envelope.items())
                        policy = c["validation_policy"]
                        if policy["mode"] == "always" or not inside:
                            evidence = registry.resolve("validator", policy["validator_id"], schema)(deepcopy(record["task"]), deepcopy(instance))
                        else:
                            evidence = deepcopy(c["validation_evidence"]); evidence.pop("envelope", None)
                            evidence["instance_id"] = fingerprint(instance)
                            evidence["validation_scope"] = "trusted_published_envelope"
                        if c.get("reference_check_id"):
                            reference = registry.resolve("reference", c["reference_check_id"], schema)(deepcopy(instance))
                            if reference.get("status") not in ("passed", "failed", "not_run"): raise ValueError("invalid reference evidence")
                            evidence["reference_controller_evidence"] = reference
                        if evidence.get("validator_version") != binding["context"]["validator_version"] or evidence.get("simulator_version") != binding["context"]["simulator_version"]: raise ValueError("validation context version mismatch")
                        compile_instrumentation(record["task"], instance, evidence)
                        a = build_assignment(record, region, instance, values, evidence, request_id=rid, directive=directive,
                            category=category, sampling_seed=ss, ordinal=len(accepted), fallback_from=fallback_from)
                        physical = physical_identity(a)
                        if physical in reserved or fingerprint([a["family_id"],a["family_version"],a["task_parameters"],a["environment_parameters"]]) in held_out_parameters(sampler.repo): raise ValueError("held-out evaluation specification")
                        dims = directive["diversity"]["dimensions"] or sorted(values)
                        duplicate = fingerprint([c["family_id"], c["family_version"], {k: values[k] for k in dims}])
                        if directive["diversity"]["mode"] == "unique_parameters" and duplicate in seen: raise ValueError("requested diversity duplicate")
                        seen.add(duplicate); accepted.append(a); diag["accepted"] += 1; break
                    except (ValueError, KeyError, TypeError) as exc:
                        diag["rejected"] += 1
                        reason = str(exc); diag["reasons"][reason] = diag["reasons"].get(reason,0)+1
            diag["shortfall"] = count-diag["accepted"]
            return diag["accepted"]
        unallocated_regions = {}
        for category in CATEGORIES:
            regions = directive["family_region_allocations"][category]
            floors = [f for f in directive["minimum_coverage_requirements"] if f["category"] == category]
            rq = region_quotas(regions, floors, cq[category])
            unallocated_regions[category] = cq[category]-sum(rq.values())
            if unallocated_regions[category]:
                diagnostics.append({"directive_id":directive["directive_id"],"category":category,"family_id":None,"family_version":None,
                    "region_id":None,"region_version":None,"requested":unallocated_regions[category],"generated":0,"rejected":0,"accepted":0,
                    "shortfall":unallocated_regions[category],"reasons":{"unresolved_or_unallocated_region_budget":unallocated_regions[category]},"fallback_from_region_id":None})
            for region in sorted(regions, key=lambda r:r["region_id"]):
                count = rq[region["region_id"]]
                done = generate(category, region, count)
                fallback = next((f for f in directive["allowed_fallbacks"] if f["category"] == category and f["from_region_id"] == region["region_id"]), None)
                if done < count and fallback:
                    added = generate(category, fallback["to_region"], count-done, region["region_id"])
                    fallbacks.append({"category":category,"from_region_id":region["region_id"],"to_region_id":fallback["to_region"]["region_id"],"requested":count-done,"accepted":added})
        groups = defaultdict(list)
        for a in accepted: groups[a["execution_compatibility_key"]].append(a["assignment_id"])
        result = {"request_id": rid, "request": request, "assignments": accepted, "diagnostics": diagnostics,
            "shortfall": directive["total_episode_budget"]-len(accepted), "fallbacks": fallbacks,
            "groups": dict(groups), "category_quotas": cq, "unallocated_region_budgets":unallocated_regions,
            "unresolved_advisor_targets":deepcopy(directive.get("unresolved_advisor_targets",[])),
            "coverage_shortfalls": [{**f,"shortfall":max(0,f["minimum"]-sum(a["category"]==f["category"] and a["region_id"]==f["region_id"] and not a["fallback_from_region_id"] for a in accepted))} for f in directive["minimum_coverage_requirements"]]}
        sampler.repo.put("sampling", rid, result)
        sampler.repo.put("directive_batch", directive_key, {"request_id":rid,"library_snapshot":request["library_snapshot"]})
        sampler.repo.put("sampling_timing", rid, {"latency_seconds":time.perf_counter()-started,"created_at":now})
        for a in accepted:
            sampler.repo.put("assignment", a["assignment_id"], a)
            sampler.repo.db.execute("INSERT INTO assignment_state VALUES (?,'pending',NULL,NULL,NULL)",(a["assignment_id"],))
        return result


def held_out_parameters(repository):
    """Physical task parameters identify held-out instances independently of seed."""
    return {fingerprint([c["family_id"],c["family_version"],c["instance"]["theta"],c["instance"]["phi"]])
            for m in repository.records("benchmark") for c in m["cases"]}
