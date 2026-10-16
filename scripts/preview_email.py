"""Render the email payload against live EG.D data; write HTML + text to /tmp.

Reads EGD_ADDRESS_ID / EGD_ADDRESS_LABEL / ADDRESS_LABEL from the environment.
"""
from __future__ import annotations

import os
from pathlib import Path

from notify.email import render_html, render_text
from providers.egd import EgdProvider


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise SystemExit(
            f"Missing env var {name}. Set EGD_ADDRESS_ID, EGD_ADDRESS_LABEL, "
            "and ADDRESS_LABEL before running."
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
    # For preview purposes: treat them all as newly-discovered, and also
    # render a copy of the first one as a reminder, so both sections appear.
    new = outages
    reminders = outages[:1]

    html = render_html(new, reminders)
    text = render_text(new, reminders)

    Path("/tmp/home-monitor-preview.html").write_text(html, encoding="utf-8")
    Path("/tmp/home-monitor-preview.txt").write_text(text, encoding="utf-8")

    print(f"Subject: [home-monitor] {len(new) + len(reminders)} outage notice(s)")
    print()
    print("=== plaintext body ===")
    print(text)
    print("=== html body (sources) ===")
    print(html)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
