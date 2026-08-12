from __future__ import annotations

import json
from pathlib import Path

from .pipeline import run


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    summary = run(root)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
