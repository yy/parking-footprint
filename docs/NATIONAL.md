# Applying the audit across the United States

The package accepts any polygonal GeoJSON source. This makes the calculation
portable, but it does not make every source equally complete.

## 1. Download candidate buildings

Download a small area around the site, replacing the bounding box:

```sh
uvx --from overturemaps overturemaps download \
  --bbox=-78.485,38.044,-78.472,38.053 \
  -f geojson \
  --type=building \
  -o candidate-buildings.geojson
```

Open the result in QGIS or another map, compare it with current aerial imagery,
and retain the building that belongs to the audit. Do not use “nearest building”
as an unattended ownership rule.

## 2. Lock the reviewed features

Save the selected features as a GeoJSON FeatureCollection. A layer can lock
Overture's string ID:

```toml
[[layers]]
id = "building"
role = "building"
source_kind = "geojson"
snapshot = "data/building.geojson"
object_ids = ["reviewed-overture-id"]
id_field = "id"
source_crs = "EPSG:4326"
expected_feature_count = 1
quality = "national-estimate"
note = "Reviewed against imagery on YYYY-MM-DD."
```

Choose a suitable projected CRS for `analysis_crs`. A local State Plane or UTM
CRS is preferable to measuring longitude and latitude directly.

## 3. Add parking and vehicle access

Use sources in this order:

1. Municipal parking, driveway, road-area, or impervious-surface polygons.
2. Reviewed polygons traced from dated aerial imagery.
3. National parking data or buffered road centerlines with explicit
   assumptions.

Overture transportation segments are centerlines. Some carry width rules; many
do not. If width is missing, record the assumed width by road class, calculate
low and high scenarios, and mark the layer `national-estimate`.

Do not silently include a public road. Add it as a separate layer so the audit
can report both the site-only result and a road-inclusive sensitivity.

## 4. Verify

Commit the configuration, selected GeoJSON, and baseline:

```sh
uv run parking-footprint run path/to/audit.toml \
  --offline \
  --output results/site \
  --write-baseline path/to/baseline.json

uv run parking-footprint verify path/to/audit.toml \
  path/to/baseline.json \
  --offline \
  --output results/site-verify
```

The frozen run verifies the calculation. Re-download the upstream data
periodically and review any changed geometry before replacing the baseline.
