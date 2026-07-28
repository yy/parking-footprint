# Data sources and redistribution

The MIT license in `LICENSE` applies to the `parking-footprint` software and its
original documentation. It does not purport to relicense third-party source
data.

The GeoJSON extracts under `examples/brooks-ymca/data/` contain geometry and
feature IDs from the City of Charlottesville's `OpenData_1` ArcGIS service:

| File | City dataset | Layer |
| --- | --- | --- |
| `parking.geojson` | Vehicle Parking Area | [34](https://gisweb.charlottesville.org/arcgis/rest/services/OpenData_1/MapServer/34) |
| `driveway.geojson` | Vehicle Driveway Area | [33](https://gisweb.charlottesville.org/arcgis/rest/services/OpenData_1/MapServer/33) |
| `building.geojson` | Existing Structure Area | [59](https://gisweb.charlottesville.org/arcgis/rest/services/OpenData_1/MapServer/59) |

The snapshots were refreshed from those public endpoints on 2026-07-28.
Attribute fields not required by the audit were removed.

Charlottesville's adopted [Open Data
Policy](https://widget.charlottesville.org/gis/opendata/OpenDataPolicy.pdf)
states that portal data is made freely available with minimal restrictions and
is licensed under a standard Creative Commons public copyright license that
enables free distribution. The policy and layer metadata do not identify a
specific Creative Commons variant. These extracts are redistributed on the
basis of that policy, with conservative attribution to:

> City of Charlottesville GIS and Open Data Services

Users who redistribute or repurpose the extracts should retain this notice and
consult the current City policy and layer metadata for any updated terms. The
City datasets are provided without any claim that they are legal surveys or
current representations of site conditions.
