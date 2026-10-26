# parking-footprint

`parking-footprint` measures how much land around a building is devoted to
parking and vehicle access, compared with the building itself and other
transportation uses. It produces an area table and a provenance record that
another person can rerun.

The package does not decide which polygons “belong” to a building. An audit
begins with a reviewed selection of feature IDs. The configuration locks that
selection so later runs can detect changes in the source data or calculation.

## Brooks YMCA example

Clone the repository, install the locked environment, and reproduce the saved
source snapshot:

```sh
uv sync --locked
uv run parking-footprint run \
  examples/brooks-ymca/audit.toml \
  --offline \
  --output results/brooks-ymca
```

Check the result against the reviewed baseline:

```sh
uv run parking-footprint verify \
  examples/brooks-ymca/audit.toml \
  examples/brooks-ymca/baseline.json \
  --offline \
  --output results/brooks-ymca-verify
```

Drop `--offline` to fetch the locked object IDs from Charlottesville’s current
ArcGIS service. The verification command fails if a feature disappears, its ID
changes, or its measured area moves outside the configured tolerance.

## Verification workflow

1. Define the audit boundary and inclusion rule in plain language.
2. Inspect candidate features on an aerial image or GIS map. `candidates`
   lists every feature in the config's ArcGIS layers within a radius of a
   point, with its area and whether it is already locked, and writes one
   GeoJSON file per layer for review in QGIS or geojson.io:

   ```sh
   uv run parking-footprint candidates audit.toml \
     --lat 38.0487 --lon -78.4787 --radius-ft 300 --output candidates
   ```

   The search radius is a discovery aid, not an inclusion rule.
3. Save the accepted feature IDs in `audit.toml`.
4. Run the audit. The package records the query URL, IDs, data hash, CRS, areas,
   software version, and source snapshots.
5. Write a baseline. It locks the configuration and source hashes as well as the
   reviewed areas and ratios.
6. Review the map separately. Numeric reproducibility cannot detect a polygon
   that was consistently classified under the wrong role.

Each output directory contains:

- `audit.json`: measured layer and role areas, plus requested ratios
- `provenance.json`: source queries, locked IDs, hashes, capture dates, CRS,
  and software
- `sources/*.geojson`: the exact geometries used in that run

Both artifacts carry a `schema_version`. The baseline locks it, so a format
change surfaces as a verification failure rather than a silent comparison
against a differently shaped record. See [CHANGELOG.md](CHANGELOG.md).

Provenance uses configuration-relative path references so sharing an output
directory does not disclose the machine's local filesystem layout.

Rerunning into the same output directory replaces these artifacts as one
complete result. The command refuses to replace a directory containing other
top-level files.

The package unions polygons assigned to the same role before measuring them.
This prevents overlapping parking and driveway polygons from being counted
twice. It also reports overlap within each source layer.

## Apply it to another building

Copy `examples/brooks-ymca/audit.toml` and change:

- the projected `analysis_crs`
- municipal layer URLs
- reviewed feature IDs
- expected feature counts
- `captured_at`, the date you downloaded each snapshot
- manual observations, if any

A layer's `quality` must be one of the evidence grades in
[docs/METHOD.md](docs/METHOD.md); an unrecognized grade is a configuration
error rather than a new label.

ArcGIS layers and local GeoJSON snapshots work now. A manual layer can represent
an observed quantity such as bicycle storage when no public polygon exists.
Feature locks accept both municipal integer IDs and national-source string IDs.

The committed municipal extracts retain only feature IDs and geometry. See
[DATA_LICENSE.md](DATA_LICENSE.md) for source attribution and redistribution
terms. The software itself is MIT licensed.

## City and national coverage

Municipal parking, driveway, impervious-surface, and building polygons provide
the strongest measurements. Many US cities publish these through ArcGIS REST
services, so the same adapter can query them.

National sources require a different evidence grade. Overture building exports
can be audited now through the package's GeoJSON adapter. Its transportation
geometry is a centerline; width attributes may be absent, and parking coverage
varies. Road and parking areas therefore remain estimates unless local surface
polygons replace them. See [docs/NATIONAL.md](docs/NATIONAL.md) for the exact
download-and-lock workflow and [docs/METHOD.md](docs/METHOD.md) for the
measurement rules.

## Development

```sh
uv run pytest --cov
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv build
uv run parking-footprint verify \
  examples/brooks-ymca/audit.toml \
  examples/brooks-ymca/baseline.json \
  --offline
```

The same checks run in continuous integration on Python 3.12 and 3.13.
