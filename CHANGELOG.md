# Changelog

This project records audit artifacts that are meant to be re-verified later, so
changes to the artifact schema are listed first in every release.

## Unreleased

### Artifact schema

- `schema_version` is now `3` in both `audit.json` and `provenance.json`. A
  baseline written under schema 2 reports a schema change and must be rewritten
  after its configuration and areas are reviewed.
- Layer provenance gained `captured_at`: the fetch timestamp for an online run,
  and the layer's declared `captured_at` for a snapshot or manual layer. The
  date a source was downloaded is now part of the machine-readable record
  instead of prose in a note.
- Layer provenance no longer carries the singular `request_url`. Feature batches
  are POSTed, so that URL never held the query; `request_urls`,
  `feature_request_parameters`, and `selection_request_url` describe the
  requests that were actually made.

### Configuration

- New optional layer field `captured_at`, accepting a TOML date, a TOML
  timestamp, or an ISO 8601 string.
- `quality` is validated against the five evidence grades in `docs/METHOD.md`
  plus `unrated`. A misspelled grade previously became a sixth grade and made
  the label incomparable across audits.
- Repeated `object_ids` are rejected instead of producing a confusing lock
  mismatch at fetch time.
- `expected_feature_count` must agree with the number of locked `object_ids`,
  and must be nonnegative.
- Unparsable TOML is reported as a configuration error rather than a
  `TOMLDecodeError` traceback.

### Fixed

- Integer feature IDs sort numerically rather than lexicographically, so
  `provenance.locked_object_ids` and `layers[].feature_ids` no longer report
  `["10", "100", "2", "9"]`. Ordering was internally consistent before, so no
  measured value changes; only the order these IDs are listed in.
- `__version__` is read from the installed distribution instead of being
  duplicated in `__init__.py`, where it could drift from `pyproject.toml` and
  misreport which code produced a provenance record.
- Publishing an output directory now cleans up its backup directory in a
  `finally` block, so a failure while removing the superseded result no longer
  leaves a hidden `.previous` directory beside the output.
- The analysis CRS is rejected if its axes carry different units, which would
  have made "square unit" ambiguous.

### Command line

- Configuration, source, geometry, and output errors print as
  `error: <message>` on stderr with exit status 2. Verification failure keeps
  exit status 1. Tracebacks are now reserved for bugs.
- `verify` reads its baseline before running the audit, so a missing or
  malformed baseline no longer wastes the run or publishes an unverified
  `--output` directory. A baseline that is not a JSON object is reported as an
  error instead of a traceback.

### Packaging

- Added a `py.typed` marker so the package's annotations are visible to type
  checkers in downstream projects.

### Removed

- An unreachable feature-count check in the ArcGIS adapter. The element-by-element
  object-ID comparison above it already guarantees the counts match.
