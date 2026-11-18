"""Run paired GPT-5 mini cases against the project's shared bounded mock tools."""
import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT.parent / "white_greybox_testing"
sys.path.insert(0, str(SHARED / "runner"))
from mock_tools import DEFINITIONS, configure_case, initial_state, read
from retrieval_context import prepared_input
from run_test import INSTRUCTIONS


def main(argv=None):
    suites = read(ROOT / "tests/suites.json")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=[*suites, "all"], default="agentdojo")
    parser.add_argument("--case", default="1", help="Case number, inclusive range (1-10), or all")
    parser.add_argument("--condition", choices=["both", "clean", "attacked"], default="both")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prompt-key", action="store_true", help="Prompt for a key even when OPENAI_API_KEY is set")
    args = parser.parse_args(argv)
    numbers = None
    if args.case != "all":
        bounds = args.case.split("-")
        if len(bounds) > 2 or not all(x.isdecimal() for x in bounds):
            parser.error("Expected a case number, inclusive range, or all")
        first, last = int(bounds[0]), int(bounds[-1])
        if not 1 <= first <= last <= 100:
            parser.error("Case numbers must be between 1 and 100 in ascending order")
        numbers = range(first, last + 1)
    conditions = ["clean", "attacked"] if args.condition == "both" else [args.condition]
    batch = ROOT / "results" / uuid.uuid4().hex
    env = os.environ.copy()
    if args.prompt_key:
        env.pop("OPENAI_API_KEY", None)
    rows = []
    for dataset, subdir in suites.items():
        if args.dataset not in ("all", dataset):
            continue
        for folder in sorted((SHARED / "tests" / subdir).iterdir()):
            if not (folder / "clean.json").is_file():
                continue
            if numbers is not None and int(folder.name.split("_")[0]) not in numbers:
                continue
            for condition in conditions:
                configure_case(folder, condition)
                case = prepared_input(folder, condition)
                definitions = DEFINITIONS.copy()
                if dataset == "connor":
                    spec = read(folder / "environment_spec.json")
                    definitions = spec["definitions" if condition == "clean" else "attacked_definitions"]
                payload = dict(case=case, definitions=definitions, state=initial_state(), instructions=INSTRUCTIONS)
                if not args.dry_run and not env.get("OPENAI_API_KEY"):
                    env["OPENAI_API_KEY"] = getpass.getpass("OpenAI API key (hidden): ").strip()
                    if not env["OPENAI_API_KEY"]:
                        parser.error("An API key is required")
                proc = subprocess.run(["node", str(ROOT / "runner/session.mjs"),
                                       "offline" if args.dry_run else "live"], input=json.dumps(payload),
                                      capture_output=True, encoding="utf-8", env=env, check=True)
                result = json.loads(proc.stdout)
                rows.append(dict(dataset=dataset, case=folder.name, condition=condition, status=result["status"]))
                if not args.dry_run:
                    dest = batch / dataset / folder.name / condition
                    dest.mkdir(parents=True)
                    (dest / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                    (batch / "summary.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
                    print(dest, result["status"], flush=True)
                    if result["status"] == "error":
                        if result.get("error") == "OpenAI HTTP 401":
                            print("OpenAI rejected the API credentials (401). Run again with --prompt-key to enter a fresh key.", file=sys.stderr)
                        return 1
    if not rows:
        parser.error("No matching cases")
    print(f"{len(rows)} conditions {'validated offline' if args.dry_run else 'run'}")
    return int(any(row["status"] not in ("validated", "completed") for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
