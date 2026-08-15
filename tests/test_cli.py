import json
import sys
from pathlib import Path

import pytest

from parking_footprint.cli import build_parser, main

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "examples" / "brooks-ymca" / "audit.toml"
BASELINE = ROOT / "examples" / "brooks-ymca" / "baseline.json"


def run_cli(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr(sys, "argv", ["parking-footprint", *argv])
    main()


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

    run_cli(
        monkeypatch,
        "run",
        str(CONFIG),
        "--offline",
        "--output",
        str(output),
        "--write-baseline",
        str(baseline),
    )

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
    run_cli(
        monkeypatch,
        "verify",
        str(CONFIG),
        str(BASELINE),
        "--offline",
        "--output",
        str(tmp_path / "verify"),
        "--area-tolerance-pct",
        "0.1",
    )

    assert "verification passed" in capsys.readouterr().out


def test_verify_cli_exits_one_and_lists_issues(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    baseline["roles"]["car_access"]["area_sq_ft"] += 50_000
    stale = tmp_path / "stale-baseline.json"
    stale.write_text(json.dumps(baseline), encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        run_cli(monkeypatch, "verify", str(CONFIG), str(stale), "--offline")

    stdout = capsys.readouterr().out
    assert exit_info.value.code == 1
    assert "verification failed:" in stdout
    assert "car_access: area_sq_ft changed" in stdout


def test_cli_reports_a_missing_configuration_without_a_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run_cli(monkeypatch, "run", str(tmp_path / "absent.toml"), "--offline")

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.err.startswith("error: ")
    assert "absent.toml" in captured.err
    assert "Traceback" not in captured.err


def test_cli_reports_a_configuration_error_without_a_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    config = tmp_path / "audit.toml"
    config.write_text(
        """
[audit]
id = "broken"
name = "Broken"
analysis_crs = "EPSG:2284"

[[layers]]
id = "cars"
role = "car_access"
source_kind = "manual"
manual_area_sq_ft = 100
quality = "gold-plated"
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exit_info:
        run_cli(monkeypatch, "run", str(config), "--offline")

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "unknown quality 'gold-plated'" in captured.err


def test_cli_reports_a_missing_baseline_without_a_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    output = tmp_path / "result"
    with pytest.raises(SystemExit) as exit_info:
        run_cli(
            monkeypatch,
            "verify",
            str(CONFIG),
            str(tmp_path / "absent.json"),
            "--offline",
            "--output",
            str(output),
        )

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "absent.json" in captured.err
    # The baseline is read before the audit runs, so nothing was published.
    assert not output.exists()


def test_cli_reports_a_non_object_baseline_without_a_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("[]\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        run_cli(monkeypatch, "verify", str(CONFIG), str(baseline), "--offline")

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert captured.err.startswith("error: ")
    assert "JSON object" in captured.err
    assert "Traceback" not in captured.err


def test_cli_reports_an_unmanaged_output_directory_without_a_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    output = tmp_path / "result"
    output.mkdir()
    (output / "notes.txt").write_text("keep me\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        run_cli(monkeypatch, "run", str(CONFIG), "--offline", "--output", str(output))

    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "unmanaged entries" in captured.err
    assert (output / "notes.txt").read_text(encoding="utf-8") == "keep me\n"


def test_run_cli_without_output_still_prints_a_summary(monkeypatch, capsys) -> None:
    run_cli(monkeypatch, "run", str(CONFIG), "--offline")

    stdout = capsys.readouterr().out
    assert "car_to_building: 1.850" in stdout
    assert "analysis CRS: EPSG:2284" in stdout
