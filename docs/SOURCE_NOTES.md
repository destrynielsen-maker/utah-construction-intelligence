# Source Notes

The MVP intentionally uses public, official government sources and does not automate logins, solve CAPTCHAs, or bypass access controls.

## Provo

**Primary source:** Provo City public ArcGIS `DevServ/CurrentProjects/FeatureServer/1` (Building Permits).

Source directory:
`https://gispublicweb.provo.gov/ArcGIS/rest/services/DevServ/CurrentProjects/FeatureServer/1`

The public layer exposes structured fields including:

- Date Issued
- Permit Number
- Name
- Type
- Building Use
- Street Address
- Number of Units
- Total Valuation
- Contractor Name
- Status

Building-use codes are useful for first-pass classification:

- `SFR` — Single Family Residential
- `MFR`, `COT`, `TFR` — Multi Family Residential
- `COM`, `IND`, `INS`, `MED` — Commercial-style categories

The collector uses the ArcGIS REST query endpoint and paginates rather than scraping the visual map.

## Orem

**Landing page:** `https://orem.gov/buildingsafety/`

Orem publishes a cumulative current-year permit-statistics PDF and monthly permit reports. The cumulative report is preferred because the collector can rediscover the current URL from the Building Safety page instead of hard-coding a month.

Observed columns in the 2026 report:

- Date
- Permit #
- Permit Type
- Builder
- Site Address
- Valuation

The PDF is text-based. The parser uses PDF word coordinates and the stable column bands rather than OCR.

High-confidence MVP new-build types include:

- `Single Family Dwelling`
- `Town Homes`
- `New Commercial Bldg`
- `New Commercial Building`

## Summit County

**Issued permits:** `https://www.summitcountyutah.gov/558/Issued-Building-Permits`

Observed columns:

- Permit Issued
- Permit Number
- Project Type
- Area
- APN
- Address

The report explicitly identifies useful categories including:

- `Residential: Single Family Detached (New Construction) (IRC)`
- `Residential: New Single Family Detached (IRC)`
- `Residential: New Single Family Attached (Duplex) (IRC)`
- `Residential: Multi-Family (Apartments or Condominiums) (IBC)`

Commercial records are less explicit about whether a permit is ground-up. The MVP therefore promotes only structural commercial signals such as shell buildings and parking garages, and marks those as **MEDIUM** new-construction confidence.

## Polling behavior

The default GitHub Actions schedule runs every six hours. That cadence is intentionally conservative. Orem and Summit County documents may update less frequently; polling does not imply the underlying government data is real-time.

If a source fails, the pipeline records a source error, keeps historical permits, and continues with other sources.
