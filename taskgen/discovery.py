"""Library-first bounded discovery; proposals remain validated data."""
from copy import deepcopy
from typing import Protocol
from .bootstrap import broad_bootstrap
from .core import fingerprint, validate, novelty, mutate, compose
from .parameters import restrict
from semantics.capabilities import capabilities_for
from task_library.governance import transaction


class ProposalProvider(Protocol):
    """Deployment-owned LLM provider boundary; never executable response code."""
    def propose(self, request: dict, vocabulary: dict) -> list[dict]: ...


class TaskDiscovery:
    def __init__(self, factory, *, proposals=None):
        self.factory, self.proposals = factory, proposals

    def resolve(self, directive, *, max_candidates=16):
        if type(max_candidates) is not int or max_candidates < 1:
            raise ValueError("positive bounded discovery budget required")
        source = deepcopy(directive)
        claimed = source.pop("directive_id", None)
        if claimed != fingerprint(source):
            raise ValueError("Advisor directive checksum mismatch")
        lookup = self.factory.library.resolve_directive(directive)
        accepted, rejected, remaining, used = [], [], [], 0
        archive = [r["task_spec"] for r in self.factory.library.search()]
        templates = broad_bootstrap()
        for gap in lookup["generation_requests"]:
            target = gap["target"]
            candidates = []
            for parent in archive:
                if set(target.get("capabilities", [])) <= set(capabilities_for(parent)):
                    for parameter in target.get("parameters", {}):
                        if parameter in parent["theta"] or parameter in parent["phi"]:
                            for factor in (.8, 1.2):
                                try: candidates.append((mutate(parent, parameter, factor), "mutation"))
                                except ValueError: pass
                # Composition is bounded to trusted skill suffixes and one-role
                # chains. General role graphs stay under their own grammar.
                if {node["object"] for node in parent["task_graph"]} != {"object"}:
                    continue
                for suffix in (("grasp",), ("lift", "transport"), ("release",)):
                    try:
                        child = compose(parent, suffix, parent["family"] + "_" + suffix[-1])
                        if set(target.get("capabilities", [])) <= set(capabilities_for(child)):
                            candidates.append((child, "composition"))
                    except (ValueError, KeyError): pass
            candidates.extend((deepcopy(t), "bootstrap") for t in templates
                          if set(target.get("capabilities", [])) <= set(capabilities_for(t)))
            if self.proposals is not None and used < max_candidates:
                vocabulary = {"semantics": self.factory.compiler.semantics.snapshot(),
                              "resources": self.factory.compiler.resources.snapshot(),
                              "schema_versions": ["1.1", "1.2"]}
                generated = self.proposals.propose(deepcopy(target), vocabulary)
                if not isinstance(generated, list):
                    raise ValueError("proposal provider must return a list of TaskSpecs")
                candidates.extend((t, "llm") for t in generated[:max_candidates-used])
            fulfilled = False
            for candidate, origin in candidates:
                if used >= max_candidates:
                    break
                used += 1
                try:
                    if not isinstance(candidate, dict) or not validate(candidate).structurally_valid:
                        raise ValueError("proposal violates trusted declarative grammar")
                    if not set(target.get("capabilities", [])) <= set(capabilities_for(candidate)):
                        raise ValueError("proposal does not exercise requested capabilities")
                    for name, restriction in target.get("parameters", {}).items():
                        group = "theta" if name in candidate["theta"] else "phi" if name in candidate["phi"] else None
                        if group is None:
                            raise ValueError("candidate lacks requested parameter")
                        candidate[group][name] = restrict(candidate[group][name], restriction)
                    candidate.setdefault("provenance", {"engine": origin, "parents": []})
                    candidate["provenance"]["directive_id"] = claimed
                    scores = novelty(candidate, archive)
                    record = self.factory.publish(candidate, source=origin)
                    archive.append(deepcopy(candidate))
                    accepted.append({"family_id": record["contract"]["family_id"], "family_version": record["contract"]["family_version"],
                                     "target": deepcopy(target), "novelty": scores})
                    fulfilled = True
                    break
                except (ValueError, KeyError, TypeError) as exc:
                    rejected.append({"target": deepcopy(target), "reason": str(exc), "candidate_index": used})
            if not fulfilled:
                remaining.append(deepcopy(gap))
        result = {"directive_id": claimed, "initial_coverage": lookup, "accepted": accepted, "rejected": rejected,
                  "unfulfilled": remaining, "candidates_used": used, "budget": max_candidates,
                  "final_coverage": self.factory.library.resolve_directive(directive)}
        with transaction(self.factory.repo.db):
            self.factory.repo.put("discovery_run", fingerprint(result), result)
        return result
