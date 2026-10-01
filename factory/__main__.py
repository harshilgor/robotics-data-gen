"""Run a complete explicitly synthetic factory cycle in a local directory."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .local import LocalFactory
from task_advisor.evaluation import BenchmarkRegistry
from training import CheckpointStore, MotionCloningBackend
from evaluation import LocalProbeRuntime


def run_cycle(factory, *, seed=42, episodes=12, broad=False, modalities=None):
    families = factory.seed(broad=broad)
    checkpoints = CheckpointStore(factory.repo)
    checkpoints.save("initial-policy", {"gain": .0001}, backend="initial-local-motion")
    registry = BenchmarkRegistry(factory.repo, factory.library)
    cases = registry.generate_cases([(f["contract"]["family_id"], f["contract"]["family_version"]) for f in families],
        seed=seed+10000, per_family=2, validator=factory.validator.evidence, registry=factory.registry)
    suite = registry.freeze("local-fixed-development", 1, cases, seed=seed+10000, registry=factory.registry)
    before = registry.run(suite["manifest_id"], "initial-policy", LocalProbeRuntime(factory, checkpoints))
    batch = factory.sample(total=episodes, seed=seed, policy_version="reference-demonstrations",
                           window="demonstration-window", purpose="demonstration",
                           recording_profile={"trajectory": True, "modalities": modalities or []})
    demonstration = factory.execute(batch, environments=3, interrupt_first=True)
    created_at = datetime.now(timezone.utc).isoformat()
    dataset = factory.catalog.create("local-imitation", 1, [a["assignment_id"] for a in batch["assignments"]],
                                    created_at=created_at, purposes=("demonstration",), deduplicate=False)
    trained = MotionCloningBackend().train(factory.catalog, dataset["dataset_id"])
    checkpoints.save("trained-policy", trained["weights"], backend=trained["backend"], dataset_id=dataset["dataset_id"])
    after = registry.run(suite["manifest_id"], "trained-policy", LocalProbeRuntime(factory, checkpoints))
    training_batch = factory.sample(total=episodes, seed=seed+1, policy_version="trained-policy", window="training-window")
    training = factory.execute(training_batch, environments=3, policies={"trained-policy": checkpoints.load("trained-policy")})
    advisor = factory.advise("trained-policy", "initial-policy")
    factory.store.save_snapshot(advisor)
    from taskgen.discovery import TaskDiscovery
    discovery = TaskDiscovery(factory).resolve(advisor["directive"])
    next_batch = factory.sample(total=episodes, seed=seed+2, policy_version="trained-policy", window="adaptive-window",
                                advisor_directive=advisor["directive"])
    return {"notice": "SYNTHETIC CARTESIAN INTEGRATION ONLY; no SO-101 physics or general learning claim",
        "families": len(families), "fixed_manifest_id": suite["manifest_id"],
        "before_evaluation": before, "after_evaluation": after,
        "observed_fixed_suite_change": after["success_rate"] - before["success_rate"],
        "demonstration_feedback": demonstration["feedback"], "dataset": dataset,
        "training_metrics": trained["training_metrics"], "training_feedback": training["feedback"],
        "advisor_snapshot_id": advisor["snapshot_id"], "discovery": discovery, "next_requested": episodes,
        "next_assignments": len(next_batch["assignments"]), "next_shortfall": next_batch["shortfall"],
        "unresolved_advisor_targets": next_batch.get("unresolved_advisor_targets", [])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="New local factory output directory")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--episodes", type=int, default=12)
    parser.add_argument("--broad", action="store_true", help="Use the expanded hand-authored task coverage")
    parser.add_argument("--modalities", nargs="*", choices=["rgb", "depth"], default=[], help="Persist synthetic diagnostic camera streams")
    parser.add_argument('--iterations', type=int, default=0, help='Run/resume this many complete adaptive iterations')
    parser.add_argument('--job', default='local-adaptive')
    parser.add_argument('--postgres-dsn-env', help='Optional environment variable containing an already configured PostgreSQL DSN')
    args = parser.parse_args()
    root = Path(args.root)
    if not args.iterations and (root / "cycle-report.json").exists():
        parser.error("cycle output already exists; choose a new root")
    import os
    dsn = None
    if args.postgres_dsn_env:
        dsn = os.environ.get(args.postgres_dsn_env)
        if not dsn: parser.error('configured PostgreSQL DSN environment variable is unavailable')
    factory = LocalFactory(root,postgres_dsn=dsn)
    try:
        if args.iterations:
            from .adaptive import AdaptiveLoop
            result = AdaptiveLoop(factory,job=args.job,seed=args.seed,episodes=args.episodes).run(args.iterations)
            output = root/'adaptive-report.json'
            output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            print(json.dumps({'report':str(output.resolve()),'iterations':len(result['iterations']),
                'fixed_manifest_id':result['manifest_id'],'executed':[i['feedback']['executed_episodes'] for i in result['iterations']]}))
            return
        result = run_cycle(factory, seed=args.seed, episodes=args.episodes, broad=args.broad, modalities=args.modalities)
        output = root / "cycle-report.json"
        output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(output.resolve()), "before": result["before_evaluation"]["success_rate"],
                          "after": result["after_evaluation"]["success_rate"], "dataset_episodes": result["dataset"]["episode_count"]}))
    finally:
        factory.close()


if __name__ == "__main__":
    main()
