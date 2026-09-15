from __future__ import annotations

import csv
import io
import requests

URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSZGOL7drAPewGqBm9rRrxUs-CtmzaCR27pmPJoakGPhdJxZ1gVrUGVsbyyrpO-aFNprorxWaz953y9/pub?output=csv"

r = requests.get(URL, timeout=45, headers={"User-Agent":"Mozilla/5.0 UtahConstructionIntelligence/0.3"})
print("status", r.status_code)
print("content-type", r.headers.get("content-type"))
r.raise_for_status()
rows = list(csv.reader(io.StringIO(r.text)))
print("row_count", len(rows))
print("headers", rows[0] if rows else [])
for row in rows[1:8]:
    print("row", row)
