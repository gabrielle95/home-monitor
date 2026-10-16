"""Dump raw HTML fragment EG.D returns, so we can inspect the parser's input.

Reads EGD_ADDRESS_ID / EGD_ADDRESS_LABEL from the environment.
"""
from __future__ import annotations

import os

import requests

from providers.egd import (
    AJAX_URL,
    FORM_URL,
    _extract_results_html,
    _fetch_tokens,
    _post_outage_search,
)


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise SystemExit(
            f"Missing env var {name}. Set EGD_ADDRESS_ID and EGD_ADDRESS_LABEL."
        )
    return val


def main() -> int:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/129.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "cs,en;q=0.8",
    })

    address_id = _require("EGD_ADDRESS_ID")
    address_label = _require("EGD_ADDRESS_LABEL")
    full_id = f"{address_label} ({address_id})"

    tokens = _fetch_tokens(session)
    ajax = _post_outage_search(session, tokens, full_id)
    html = _extract_results_html(ajax)
    print(html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
