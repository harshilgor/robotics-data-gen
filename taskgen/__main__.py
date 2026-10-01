"""Run with python -m taskgen --output generated-tasks.json."""
import argparse
import json
from pathlib import Path
from .core import TaskGenerator, bootstrap_families, compose, mutate, novelty, fingerprint

def main():
    parser = argparse.ArgumentParser(description="Generate symbolic task families and reproducible instances")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--instances-per-family", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("generated-tasks.json"))
    args = parser.parse_args()
    if args.instances_per_family < 1:
        parser.error("--instances-per-family must be positive")
    generator = TaskGenerator(args.seed)
    families = bootstrap_families()
    families += [compose(families[1], ["lift", "transport", "release"], "composed_pick_place"),
                 mutate(families[-1], "tolerance", 0.5)]
    records = []
    for candidate in families:
        score = novelty(candidate, generator.archive)
        if generator.register(candidate):
            records.append({"family_id": fingerprint(candidate), "specification": candidate, "novelty": score,
                            "instances": [generator.sample(candidate, i) for i in range(args.instances_per_family)]})
    args.output.write_text(json.dumps({"generator_version": "0.1.0", "seed": args.seed, "families": records}, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} families and {len(records)*args.instances_per_family} instances to {args.output}")
    print("Structural validation only; simulator approval is pending.")

if __name__ == "__main__":
    main()
