from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from .audit import (
    baseline_payload,
    run_audit,
    verify_against_baseline,
)
from .candidates import find_candidates
from .errors import AuditError, ParkingFootprintError

# Reported as "error: ..." with exit status 2. Anything else is a bug and keeps
# its traceback.
EXPECTED_ERRORS = (ParkingFootprintError, OSError, json.JSONDecodeError)


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

    candidates_parser = subparsers.add_parser(
        "candidates",
        help="list ArcGIS features near a point for review before locking",
    )
    candidates_parser.add_argument("config", type=Path)
    candidates_parser.add_argument("--lat", type=float, required=True)
    candidates_parser.add_argument("--lon", type=float, required=True)
    candidates_parser.add_argument(
        "--radius-ft",
        type=_nonnegative_finite_float,
        default=300.0,
    )
    candidates_parser.add_argument("--output", type=Path)
    return parser


def _candidates(args: argparse.Namespace) -> None:
    candidates = find_candidates(
        args.config,
        longitude=args.lon,
        latitude=args.lat,
        radius_ft=args.radius_ft,
        output_dir=args.output,
    )
    layer_ids = list(dict.fromkeys(candidate.layer_id for candidate in candidates))
    for layer_id in layer_ids:
        layer = [c for c in candidates if c.layer_id == layer_id]
        print(f"{layer_id}: {len(layer)} within {args.radius_ft:g} ft")
        for candidate in layer:
            mark = "  locked" if candidate.locked else ""
            print(
                f"  {candidate.feature_id:>10}  "
                f"{candidate.area_sq_ft:>12,.2f} sq ft{mark}"
            )
    if not candidates:
        print(f"no ArcGIS features within {args.radius_ft:g} ft")


def _run(args: argparse.Namespace) -> None:
    result = run_audit(
        args.config,
        offline=args.offline,
        output_dir=args.output,
    )
    _print_summary(result)
    if args.write_baseline:
        _write_baseline(result, args.write_baseline)


def _load_baseline(path: Path) -> dict[str, Any]:
    baseline = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(baseline, dict):
        raise AuditError(f"baseline {path} must contain a JSON object")
    return baseline


def _verify(args: argparse.Namespace) -> None:
    # Read the baseline before the audit runs so a bad baseline cannot waste
    # the run or publish an unverified --output directory.
    baseline = _load_baseline(args.baseline)
    result = run_audit(
        args.config,
        offline=args.offline,
        output_dir=args.output,
    )
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


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.command == "run":
            _run(args)
        elif args.command == "candidates":
            _candidates(args)
        else:
            _verify(args)
    except EXPECTED_ERRORS as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":  # pragma: no cover
    main()
