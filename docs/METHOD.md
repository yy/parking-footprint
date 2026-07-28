# Method and evidence grades

## Audit unit

An audit measures a named building and the surfaces selected as serving it. The
legal parcel, leasehold, and functional service area may differ. State which
boundary the audit uses and do not convert measured area to a site percentage
without a defensible denominator.

## Selection lock

Automated proximity is useful for finding candidates, but it is not a defensible
ownership rule. A nearby parking lot may serve another building; a remote lot
may serve the audited building. Review candidates against current aerial imagery
and save the accepted source feature IDs.

The lock contains:

- source layer URL
- object IDs or a documented query
- expected feature count
- source and analysis CRS
- source snapshot and canonical hash
- note explaining why the features were included

The configuration and source hashes are also stored in the baseline. `verify`
compares them exactly before applying the configured numeric tolerance to areas
and ratios.

## Area calculation

GeoJSON coordinates are transformed from their declared source CRS into the
configured projected CRS. The package repairs invalid polygonal geometry,
unions features within a layer, and then unions geometric layers sharing a role.
Area is converted through the CRS unit metadata rather than assuming meters or
feet.

Manual areas are added after geometric union because they have no polygon that
can be checked for overlap.

## Evidence grades

`authoritative-local`
: Surface polygons published by a city, county, or other responsible agency.

`derived-local`
: A measurement traced or classified from a dated local aerial image.

`observed-estimate`
: A field or street-level count converted to area using a stated rule.

`illustrative-assumption`
: A transparent scenario that is not supported by a dated observation. Do not
  report it as a current empirical measurement.

`national-estimate`
: A national building, parking, or transportation source combined with stated
  assumptions such as road width.

Comparisons should retain these labels. A precise number from a
`national-estimate` source is not equivalent to an authoritative local polygon.

## Bicycle parking

The Brooks YMCA example illustrates how an assumed inverted-U hoop count can be
converted to nominal bicycle storage area:

```text
hoops × 2 bicycles per hoop × 12 square feet per bicycle
```

The 12-square-foot value represents a typical 6-by-2-foot bicycle. The example's
hoop count is an illustrative assumption because its linked panorama has no
archived capture date. It excludes access aisles, cargo-bike clearance, and
unusable hardware. Report those limitations beside the result.

## Roads

Parking polygons often include internal aisles. A driveway layer may include an
entrance loop without including the public access road or right-of-way. Keep
these categories separate in the configuration so readers can reproduce both a
conservative result and a broader road-inclusive sensitivity analysis.

Overture transportation features are centerlines. Use a feature's width rules
when they are populated; otherwise, a national road-surface estimate needs a
width model by road class. In either case, state the uncertainty and validate
the method against cities with authoritative road-area polygons.
