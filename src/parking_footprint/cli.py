from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from .audit import (
    baseline_payload,
    run_audit,
    verify_against_baseline,
)


def _nonnegative_finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be a finite, nonnegative number")
    return number


def _print_summary(result: dict[str, Any]) -> None:
    print(result["audit"]["name"])
    print(f"analysis CRS: {result['audit']['analysis_crs']}")
    for role, values in result["roles"].items():
        print(
            f"{role}: {values['area_sq_ft']:,.2f} sq ft ({values['area_acres']:.4f} ac)"
        )
    for comparison_id, comparison in result["comparisons"].items():
        ratio = comparison["ratio"]
        rendered = "undefined" if ratio is None else f"{ratio:.3f}"
        print(f"{comparison_id}: {rendered}")


def _write_baseline(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            baseline_payload(result),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parking-footprint",
        description="Run reproducible land-allocation audits around buildings.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run an audit")
    run_parser.add_argument("config", type=Path)
    run_parser.add_argument("--offline", action="store_true")
    run_parser.add_argument("--output", type=Path)
    run_parser.add_argument("--write-baseline", type=Path)

    verify_parser = subparsers.add_parser(
        "verify",
        help="rerun an audit and compare it with a locked baseline",
    )
    verify_parser.add_argument("config", type=Path)
    verify_parser.add_argument("baseline", type=Path)
    verify_parser.add_argument("--offline", action="store_true")
    verify_parser.add_argument("--output", type=Path)
    verify_parser.add_argument(
        "--area-tolerance-pct",
        type=_nonnegative_finite_float,
        default=0.1,
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "run":
        result = run_audit(
            args.config,
            offline=args.offline,
            output_dir=args.output,
        )
        _print_summary(result)
        if args.write_baseline:
            _write_baseline(result, args.write_baseline)
        return

    result = run_audit(
        args.config,
        offline=args.offline,
        output_dir=args.output,
    )
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    issues = verify_against_baseline(
        result,
        baseline,
        area_tolerance_pct=args.area_tolerance_pct,
    )
    _print_summary(result)
    if issues:
        print("verification failed:")
        for issue in issues:
            print(f"- {issue}")
        raise SystemExit(1)
    print("verification passed")


if __name__ == "__main__":
    main()
