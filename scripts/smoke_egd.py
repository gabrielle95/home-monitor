"""Quick smoke test: fetch EG.D outages for the configured address, print results.

Reads EGD_ADDRESS_ID / EGD_ADDRESS_LABEL / ADDRESS_LABEL from the environment.
"""
from __future__ import annotations

import os
import sys

from providers.egd import EgdProvider


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise SystemExit(
            f"Missing env var {name}. Set EGD_ADDRESS_ID, EGD_ADDRESS_LABEL, "
            "and ADDRESS_LABEL before running (see README)."
        )
    return val


def main() -> int:
    provider = EgdProvider()
    addr = {
        "label": _require("ADDRESS_LABEL"),
        "egd_address_id": _require("EGD_ADDRESS_ID"),
        "egd_address_label": _require("EGD_ADDRESS_LABEL"),
    }
    outages = provider.fetch(addr)
    print(f"Found {len(outages)} outage(s)")
    for o in outages:
        print(f"  - [{o.external_id}] {o.start.isoformat()} → {o.end.isoformat()}")
        print(f"    {o.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
