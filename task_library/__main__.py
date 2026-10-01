"""Local library operations; no simulator provisioning or fabricated approval."""
import argparse
import json
from pathlib import Path
from task_advisor.storage import Store
from task_advisor.loop import Repository
from .library import TaskLibrary


def main():
    parser = argparse.ArgumentParser(description="Task Library registry and recovery")
    parser.add_argument("--db", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register")
    register.add_argument("--input", required=True, help="JSON with family_id, version, task, dependencies, provenance")
    search = commands.add_parser("search")
    search.add_argument("--capability", action="append", default=[])
    search.add_argument("--status")
    export = commands.add_parser("export"); export.add_argument("--output", required=True)
    restore = commands.add_parser("restore"); restore.add_argument("--input", required=True)
    args = parser.parse_args()
    store = Store(args.db)
    try:
        library = TaskLibrary(Repository(store))
        if args.command == "register":
            result = library.register(**json.loads(Path(args.input).read_text(encoding="utf-8-sig")))
        elif args.command == "search": result = library.search(capabilities=args.capability, status=args.status)
        elif args.command == "export":
            result = library.snapshot()
            Path(args.output).write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
        else: result = library.restore(json.loads(Path(args.input).read_text(encoding="utf-8-sig")))
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, KeyError, TypeError) as exc: parser.error(str(exc))
    finally: store.close()


if __name__ == "__main__": main()
