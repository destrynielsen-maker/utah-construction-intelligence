from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import requests

from ..models import Permit


DEFAULT_HEADERS = {
    "User-Agent": "UtahConstructionIntelligence/0.1 (+public-permit-research; respectful polling)",
}


@dataclass
class CollectionResult:
    source: str
    permits: list[Permit]
    source_url: str
    note: str = ""


class Collector(Protocol):
    name: str

    def collect(self, session: requests.Session | None = None) -> CollectionResult:
        ...


def new_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    return session
