import json
import sys
from pathlib import Path

import pytest

from parking_footprint.cli import build_parser, main

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "brooks-ymca" / "audit.toml"
BASELINE = ROOT / "examples" / "brooks-ymca" / "baseline.json"


def test_cli_rejects_non_finite_area_tolerance() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "verify",
                "audit.toml",
                "baseline.json",
                "--area-tolerance-pct",
                "nan",
            ]
        )


def test_run_cli_writes_shareable_output_and_baseline(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    output = tmp_path / "result"
    baseline = tmp_path / "baseline.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parking-footprint",
            "run",
            str(CONFIG),
            "--offline",
            "--output",
            str(output),
            "--write-baseline",
            str(baseline),
        ],
    )

    main()

    stdout = capsys.readouterr().out
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    assert "Brooks Family YMCA parking footprint" in stdout
    assert payload["config_sha256"] == provenance["config_sha256"]
    assert provenance["config_path"] == "audit.toml"


def test_verify_cli_reports_success(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parking-footprint",
            "verify",
            str(CONFIG),
            str(BASELINE),
            "--offline",
            "--output",
            str(tmp_path / "verify"),
            "--area-tolerance-pct",
            "0.1",
        ],
    )

    main()

    assert "verification passed" in capsys.readouterr().out
