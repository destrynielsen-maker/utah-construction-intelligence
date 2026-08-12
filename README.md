# Utah Construction Intelligence

A browser-accessible construction lead feed built from public Utah building-permit sources.

**MVP sources:** Provo, Orem, and Summit County.

**Primary lead categories:**

- New single-family construction
- Multifamily / apartments / condominiums / duplexes / townhomes
- Ground-up or structural commercial construction

The project collects permits, normalizes records, removes duplicates, classifies new construction, scores opportunities, publishes RSS feeds, and generates a static dashboard that can be hosted on GitHub Pages.

## What gets generated

- `public/index.html` — browser dashboard
- `public/feeds/new-construction.xml`
- `public/feeds/multifamily.xml`
- `public/feeds/single-family.xml`
- `public/feeds/commercial.xml`
- `public/feeds/top-opportunities.xml`
- `public/data/permits.json` — qualifying permit records for the dashboard
- `public/data/builders.json` — 90-day contractor/builder rollups
- `public/data/sources.json` — collector health and counts
- `data/permits.json` — persistent permit history used for deduplication

## Architecture

```text
Official Utah permit sources
          |
          v
   Source collectors
 (ArcGIS / public PDFs)
          |
          v
  Normalization + keys
          |
          v
New-build classification
          |
          v
Opportunity scoring
          |
          v
Historical JSON store
       /      \
      v        v
 Dashboard    RSS
```

The stable record key is:

```text
STATE:JURISDICTION:PERMIT_NUMBER
```

That prevents the same permit from becoming a new RSS item every time a source is checked.

## Lead scoring v0.1

Base scores:

| Category | Score |
|---|---:|
| Multifamily | 40 |
| Commercial | 30 |
| Single family | 15 |

Additional points are added for reported valuation, dwelling-unit count, and an identified contractor. Medium-confidence commercial records receive a small confidence adjustment.

The scoring rules are intentionally transparent and live in `src/utah_permits/classify.py`.

## Run locally

Requires Python 3.12+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# Windows PowerShell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python -m utah_permits.main

# macOS/Linux
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m utah_permits.main
```

Then serve the `public` directory locally:

```bash
python -m http.server 8000 --directory public
```

Open `http://localhost:8000`.

## Browser-only deployment with GitHub

1. Create a GitHub repository named `utah-construction-intelligence`.
2. Upload the contents of this project to the repository.
3. In **Settings → Pages**, choose **GitHub Actions** as the Pages source.
4. Open **Actions → Collect Utah permits and publish → Run workflow** for the first collection.
5. After the workflow deploys, the dashboard will be available from the repository's GitHub Pages URL.
6. The workflow is also scheduled to re-run every six hours.

A public repository is the simplest GitHub Pages deployment for this public-data MVP. If you later need private code/data or authentication, move the dashboard/data layer to a hosted database/application while keeping the collectors.

## Source behavior

- **Provo:** uses the city's public ArcGIS REST feature layer. It does not scrape the visible map.
- **Orem:** discovers and parses the official current-year permit-statistics PDF using text coordinates; no OCR.
- **Summit County:** parses the official issued-building-permits PDF using text coordinates; no OCR.

See `docs/SOURCE_NOTES.md` for field details and classification caveats.

## Important limitations of v0.1

- Government report freshness varies by jurisdiction.
- Orem's public report does not expose a unit count, so townhome unit counts may initially be unknown.
- Summit County's issued-permit report does not include builder/GC or valuation.
- Provo has the richest structured fields of the three sources.
- Project aggregation (matching multiple building permits to one development) is the next major feature after the base collectors are proven live.
- Builder-name normalization is currently exact-text based. For example, punctuation variants can appear as separate builders until entity normalization is added.
