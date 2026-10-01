"""Run: python -m task_advisor --input evidence.json --policy checkpoint_002."""
import argparse
import json
from pathlib import Path
from .core import Advisor, Config
from .storage import Store


def main():
    parser = argparse.ArgumentParser(description="Build evidence-based task-space directives")
    parser.add_argument("--input", required=True, help="JSON containing tasks and episodes; optional feedback")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--previous-policy")
    parser.add_argument("--db", default="task-advisor.sqlite3")
    parser.add_argument("--output", default="advisor-state.json")
    parser.add_argument("--config", help="JSON Config overrides")
    args = parser.parse_args()
    try:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        config = Config(**json.loads(Path(args.config).read_text(encoding="utf-8-sig"))) if args.config else Config()
        store = Store(args.db)
        try:
            store.ingest(payload.get("tasks", []), payload.get("episodes", []), payload.get("feedback", []))
            snapshot = Advisor(config).advise(args.policy, store.records("tasks"), store.records("episodes"),
                args.previous_policy, store.records("feedback"))
            store.save_snapshot(snapshot)
            Path(args.output).write_text(json.dumps(snapshot, indent=2, allow_nan=False)+"\n", encoding="utf-8")
        finally:
            store.close()
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(f"Saved {args.output}; directive {snapshot['directive']['directive_id']}")


if __name__ == "__main__":
    main()
