"""Run cases 1 through 10 from each suite as one paired batch."""
import argparse

from run_tests import main


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    options = ["--dataset", "all", "--case", "1-10", "--prompt-key"]
    if args.dry_run:
        options.append("--dry-run")
    raise SystemExit(main(options))
