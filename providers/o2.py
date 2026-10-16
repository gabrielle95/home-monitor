from __future__ import annotations

from typing import Any

from providers.base import Outage, Provider


class O2Provider(Provider):
    """
    Placeholder for O2 Czech Republic internet-outage monitoring.

    O2 does not publish a public, address-filterable planned-outage feed.
    Their outage lookup requires a phone number tied to a Moje O2 account,
    and planned-maintenance notifications are delivered out-of-band (SMS/email).

    If/when O2 exposes a public feed, implement fetch() here. The rest of the
    pipeline will pick up results automatically.
    """

    name = "o2"
    utility = "internet"

    def fetch(self, address_cfg: dict[str, Any]) -> list[Outage]:
        return []
