from __future__ import annotations

import csv
import io
from collections import Counter
import requests

URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSZGOL7drAPewGqBm9rRrxUs-CtmzaCR27pmPJoakGPhdJxZ1gVrUGVsbyyrpO-aFNprorxWaz953y9/pub?output=csv"

r = requests.get(URL, timeout=45, headers={"User-Agent":"Mozilla/5.0 UtahConstructionIntelligence/0.3"})
print("status", r.status_code)
print("content-type", r.headers.get("content-type"))
r.raise_for_status()
rows = list(csv.reader(io.StringIO(r.text)))
print("row_count", len(rows))
print("headers", rows[0] if rows else [])
body = [row for row in rows[1:] if any(cell.strip() for cell in row)]
descriptions = Counter((row[2].strip() if len(row) > 2 else "") for row in body)
statuses = Counter((row[3].strip() if len(row) > 3 else "") for row in body)
print("descriptions")
for value, count in descriptions.most_common():
    print(count, repr(value))
print("statuses")
for value, count in statuses.most_common():
    print(count, repr(value))
print("new_build_candidates")
for row in body:
    description = row[2].strip().lower() if len(row) > 2 else ""
    if any(token in description for token in ("new", "town", "apartment", "multifamily", "multi-family", "duplex", "condo", "hotel")):
        print("candidate", row)
