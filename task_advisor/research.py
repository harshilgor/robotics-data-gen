"""Budget-matched, seed-paired observational experiment bookkeeping."""
from taskgen.core import fingerprint
from .loop import integer, text_id


class ResearchLedger:
    def __init__(self, repository): self.repo = repository

    def plan(self, experiment_id, manifest_id, seeds, *, control_steps, arms=("adaptive", "uniform")):
        text_id(experiment_id); integer(control_steps, "control steps", 1)
        self.repo.get("benchmark", manifest_id)
        if len(seeds) < 2 or len(set(seeds)) != len(seeds): raise ValueError("at least two distinct seeds required")
        for seed in seeds: integer(seed, "seed")
        if len(arms) < 2 or len(set(arms)) != len(arms): raise ValueError("distinct comparison arms required")
        for arm in arms: text_id(arm)
        plan = {"experiment_id": experiment_id, "manifest_id": manifest_id, "seeds": list(seeds),
            "arms": list(arms), "control_steps_per_trial": control_steps, "budget_unit": "executed_control_steps",
            "library_snapshot": [fingerprint(r) for r in self.repo.records("family")]}
        with self.repo.db: self.repo.put("experiment", experiment_id, plan)
        return plan

    def record_block(self, experiment_id, arm, seed, *, before_run, after_run, assignment_ids):
        existing = [b for b in self.repo.records("training_block") if
                    b["experiment_id"] == experiment_id and b["arm"] == arm and b["seed"] == seed]
        if existing:
            old = existing[0]
            if old["before_run"] != before_run or old["after_run"] != after_run or old["assignment_ids"] != assignment_ids:
                raise ValueError("immutable training block conflict")
            return old
        plan = self.repo.get("experiment", experiment_id)
        if arm not in plan["arms"] or seed not in plan["seeds"]: raise ValueError("unplanned arm/seed")
        before = self.repo.get("evaluation_run", before_run)
        after = self.repo.get("evaluation_run", after_run)
        if before["manifest_id"] != plan["manifest_id"] or after["manifest_id"] != plan["manifest_id"]:
            raise ValueError("development distributions must match")
        if before["policy_version"] == after["policy_version"]: raise ValueError("distinct before/after checkpoints required")
        if not assignment_ids or len(set(assignment_ids)) != len(assignment_ids): raise ValueError("unique completed assignments required")
        completions = [self.repo.get("completion", a) for a in assignment_ids]
        assignments = [self.repo.get("assignment", a) for a in assignment_ids]
        if any(a.get("experiment") != {"experiment_id": experiment_id, "arm": arm, "seed": seed} for a in assignments):
            raise ValueError("assignment experiment/arm/seed provenance mismatch")
        for assignment in assignments:
            request = self.repo.get("sampling", assignment["sampling_request_id"])["request"]
            if request["library_snapshot"] != plan["library_snapshot"] or request["seed"] != seed:
                raise ValueError("training library/seed changed from experiment plan")
        if arm == "uniform":
            from .loop import TaskLibrary
            families = TaskLibrary(self.repo).list_eligible_families()
            for assignment in assignments:
                request = self.repo.get("sampling", assignment["sampling_request_id"])["request"]
                expected = uniform_directive(assignment["policy_checkpoint_id"], families)
                if request["directive"] != expected: raise ValueError("uniform baseline must use uniform-family allocations")
        if any(a["episode_purpose"] != "training" for a in assignments): raise ValueError("training blocks require training assignments")
        steps = sum(c["episode"]["episode_length"] for c in completions)
        if steps != plan["control_steps_per_trial"]: raise ValueError("executed control-step budget mismatch")
        previous = self.repo.records("training_block")
        if any(set(b["assignment_ids"]) & set(assignment_ids) for b in previous): raise ValueError("executions already counted in another block")
        # Reuse the frozen initial checkpoint within each seed across comparison arms.
        for block in previous:
            if block["experiment_id"] == experiment_id and block["seed"] == seed:
                old_before = self.repo.get("evaluation_run", block["before_run"])
                if old_before["policy_digest"] != before["policy_digest"]: raise ValueError("comparison arms need same initial checkpoint")
        episode_lookup = {e["episode_id"]: e for e in self.repo.store.records("episodes")}
        deltas = {}
        manifest = self.repo.get("benchmark", plan["manifest_id"])
        for case in manifest["cases"]:
            family = case["family_id"]
            pre = [episode_lookup[e] for e in before["episode_ids"] if episode_lookup[e]["family_id"] == family]
            post = [episode_lookup[e] for e in after["episode_ids"] if episode_lookup[e]["family_id"] == family]
            deltas[family] = sum(e["success"] for e in post)/len(post) - sum(e["success"] for e in pre)/len(pre)
        focus = {}
        for a, c in zip(assignments, completions):
            focus[a["family_id"]] = focus.get(a["family_id"], 0) + c["episode"]["episode_length"]/steps
        block = {"experiment_id": experiment_id, "arm": arm, "seed": seed,
            "before_run": before_run, "after_run": after_run, "assignment_ids": assignment_ids,
            "executed_control_steps": steps, "training_focus": focus, "development_delta": deltas,
            "interpretation": "Observed association, not causal transfer"}
        block_id = fingerprint([experiment_id, arm, seed])
        with self.repo.db: self.repo.put("training_block", block_id, block)
        return block

    def compare(self, experiment_id):
        plan = self.repo.get("experiment", experiment_id)
        blocks = [b for b in self.repo.records("training_block") if b["experiment_id"] == experiment_id]
        if {(b["arm"], b["seed"]) for b in blocks} != {(a, s) for a in plan["arms"] for s in plan["seeds"]}:
            raise ValueError("all budget-matched seed/arm trials required")
        baseline = plan["arms"][-1]
        comparisons = []
        for arm in plan["arms"][:-1]:
            for family in sorted({f for b in blocks for f in b["development_delta"]}):
                pairs = []
                for seed in plan["seeds"]:
                    measured = next(b for b in blocks if b["arm"] == arm and b["seed"] == seed)
                    reference = next(b for b in blocks if b["arm"] == baseline and b["seed"] == seed)
                    pairs.append(measured["development_delta"][family] - reference["development_delta"][family])
                mean = sum(pairs)/len(pairs)
                sd = (sum((p-mean)**2 for p in pairs)/(len(pairs)-1))**.5
                comparisons.append({"arm": arm, "baseline": baseline, "family_id": family,
                    "paired_deltas": pairs, "mean_difference": mean, "sample_std": sd, "seed_count": len(pairs)})
        return {"experiment_id": experiment_id, "comparisons": comparisons,
            "limitations": ["No causal transfer claim", "No learned transfer predictor", "Control-step budgets do not equal wall-clock or GPU budgets"]}

    def run_experiment(self, experiment_id, registry, runtime_factory, trainer, initial_checkpoints):
        """Execute planned trials through a supplied real trainer and frozen runtime.

        trainer.train_trial must honor step_budget, use experiment-tagged sampler
        assignments, complete them through the scheduler and return checkpoint
        artifact/version plus assignment_ids. Validation rejects budget overruns.
        """
        plan = self.repo.get("experiment", experiment_id)
        for seed in plan["seeds"]:
            initial = initial_checkpoints[seed]
            for arm in plan["arms"]:
                if any(b["experiment_id"] == experiment_id and b["arm"] == arm and b["seed"] == seed
                       for b in self.repo.records("training_block")):
                    continue
                before = registry.run(plan["manifest_id"], initial, runtime_factory())
                result = trainer.train_trial(arm=arm, seed=seed, initial_checkpoint=initial,
                    step_budget=plan["control_steps_per_trial"], experiment_id=experiment_id)
                registry.register_checkpoint(result["policy_version"], result["artifact"])
                after = registry.run(plan["manifest_id"], result["policy_version"], runtime_factory())
                self.record_block(experiment_id, arm, seed, before_run=before["run_id"],
                    after_run=after["run_id"], assignment_ids=result["assignment_ids"])
        return self.compare(experiment_id)


def uniform_directive(policy_version, families):
    """Explicit uniform-family baseline, independent of adaptive Advisor scoring."""
    if not families: raise ValueError("eligible families required")
    families = sorted(families, key=lambda r: (r["contract"]["family_id"], r["contract"]["family_version"]))
    directive = {"schema_version": "1.0", "policy_version": policy_version, "previous_policy_version": None,
        "budget": {"learn": 1., "explore": 0., "retain": 0.}, "unallocated_budget": 0.,
        "learn_targets": [{"family_id": r["contract"]["family_id"], "family_version": r["contract"]["family_version"],
                           "capabilities": [], "parameters": {}, "weight": 1/len(families)} for r in families],
        "explore_targets": [], "retain_targets": [], "exclusions": []}
    directive["directive_id"] = fingerprint(directive)
    return directive
