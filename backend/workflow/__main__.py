"""Command-line entry point for the declarative workflow engine.

    python -m workflow validate macroshock.yaml
    python -m workflow run      macroshock.yaml --output results/

`validate` is separated from `run` on purpose: a scheduler (or the Go CLI, or a REANA job) can
check a spec is well-formed without paying for the computation.
"""
from __future__ import annotations

import argparse
import json
import sys

from .runner import run_workflow
from .spec import load_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="workflow", description="Run a MacroShock workflow spec.")
    sub = parser.add_subparsers(dest="command", required=True)

    v = sub.add_parser("validate", help="Validate a spec without running it.")
    v.add_argument("spec", help="Path to a macroshock.yaml specification.")

    r = sub.add_parser("run", help="Validate and execute a spec.")
    r.add_argument("spec", help="Path to a macroshock.yaml specification.")
    r.add_argument("--output", "-o", default=None,
                   help="Directory for result artifacts (default: outputs.directory in the spec).")

    args = parser.parse_args(argv)

    try:
        spec = load_spec(args.spec)
    except Exception as exc:                      # invalid YAML or failed validation
        print(f"spec is invalid: {exc}", file=sys.stderr)
        return 2

    if args.command == "validate":
        print(f"{args.spec}: valid "
              f"({len(spec.workflow.steps)} step(s), {len(spec.inputs.portfolio)} holding(s))")
        return 0

    try:
        summary = run_workflow(spec, output_dir=args.output)
    except Exception as exc:                      # a step failed — surface it, don't half-succeed
        print(f"workflow failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, indent=2, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
