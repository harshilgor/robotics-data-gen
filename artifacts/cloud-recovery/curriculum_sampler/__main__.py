"""Runnable synthetic smoke and production sampler/feedback CLI (no provisioning)."""
import argparse
import importlib
import json
from pathlib import Path
from task_advisor.storage import Store
from task_advisor.loop import Repository, CurriculumSampler, AssignmentScheduler
from task_library import TaskLibrary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db",required=True)
    parser.add_argument("--output",required=True)
    sub = parser.add_subparsers(dest="command",required=True)
    sub.add_parser("smoke",help="synthetic fixtures only, use a fresh database")
    sample = sub.add_parser("sample")
    sample.add_argument("--directive",required=True)
    sample.add_argument("--registry-factory",required=True,help="trusted installed module:function returning Registry")
    sample.add_argument("--now",type=float,required=True)
    report = sub.add_parser("feedback"); report.add_argument("--request-id",required=True)
    args = parser.parse_args()
    store = Store(args.db)
    try:
        if args.command == "smoke":
            from .synthetic import smoke
            result = smoke(store)
        else:
            repo = Repository(store); library = TaskLibrary(repo)
            if args.command == "sample":
                module,name = args.registry_factory.split(":")
                registry = getattr(importlib.import_module(module),name)()
                directive = json.loads(Path(args.directive).read_text())
                result = CurriculumSampler(repo,library,registry=registry).sample(directive,now=args.now)
            else: result = AssignmentScheduler(repo,library).feedback(args.request_id)
        Path(args.output).write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
        print(json.dumps({"output":args.output,"assignments":len(result.get("batch",result).get("assignments",[])),"summaries":len(result.get("summaries",[]))}))
    finally: store.close()


if __name__ == "__main__": main()
