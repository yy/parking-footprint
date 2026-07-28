# Brooks Family YMCA example

This audit locks three Charlottesville municipal datasets:

- four vehicle-parking polygons
- one vehicle-driveway polygon
- one building-footprint polygon

The car-access total includes parking aisles represented inside those selected
polygons. It does not include the public road or right-of-way. Add the municipal
road-area feature as a separate `car_access` layer for a road-inclusive
sensitivity analysis.

The bicycle figure is an illustrative scenario, not a current observation. It
assumes 27 inverted-U hoops, two nominal bicycles per hoop, and 12 square feet
per bicycle. The linked panorama is undated context rather than archived
evidence. The scenario measures nominal bicycle storage, not the access aisle
around each rack.

The frozen baseline reports:

| Role | Square feet | Acres |
| --- | ---: | ---: |
| Car access | 92,802.31 | 2.1304 |
| Building | 50,165.49 | 1.1516 |
| Illustrative bicycle storage | 648.00 | 0.0149 |

Car-access area is 1.85 times the building footprint. Under the illustrative
bicycle-storage scenario, it is 143.21 times the nominal bicycle footprint.
