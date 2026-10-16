from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from notify.email import render_html, render_text, send_email
from providers.base import Outage
from providers.egd import EgdProvider
from providers.o2 import O2Provider

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
STATE_PATH = ROOT / "state" / "seen.json"

log = logging.getLogger("home-monitor")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    cfg = _expand_env(raw)

    # Addresses pull their fields from env vars. If a required one is missing,
    # fail loudly rather than silently querying EG.D with empty strings.
    required_addr_fields = ("label", "egd_address_id", "egd_address_label")
    for i, addr in enumerate(cfg.get("addresses", []) or []):
        missing = [f for f in required_addr_fields if not addr.get(f)]
        if missing:
            raise RuntimeError(
                f"addresses[{i}]: missing values for {missing}. "
                "Set the corresponding env vars (or edit config.yaml)."
            )
    return cfg


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"outages": {}, "reminded": {}}
    with STATE_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


def build_providers() -> list:
    return [EgdProvider(), O2Provider()]


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load_config()
    state = load_state()

    tz = ZoneInfo(cfg.get("timezone", "Europe/Prague"))
    today = datetime.now(tz=tz).date()
    reminder_days = int(cfg.get("reminder_days_before", 1))

    providers = build_providers()

    all_outages: list[Outage] = []
    for provider in providers:
        for addr in cfg["addresses"]:
            try:
                found = provider.fetch(addr)
            except Exception:
                log.exception("Provider %s failed for %s", provider.name, addr.get("label"))
                continue
            log.info("Provider %s returned %d outage(s) for %s",
                     provider.name, len(found), addr.get("label"))
            all_outages.extend(found)

    seen: dict[str, Any] = state.get("outages", {})
    reminded: dict[str, Any] = state.get("reminded", {})

    new_outages: list[Outage] = []
    reminders: list[Outage] = []

    for o in all_outages:
        if o.key not in seen:
            new_outages.append(o)
            seen[o.key] = o.to_json()

        # Reminder: when outage start is exactly `reminder_days` days away.
        start_date = o.start.astimezone(tz).date()
        delta = (start_date - today).days
        if 0 <= delta <= reminder_days:
            already = reminded.get(o.key)
            if already != today.isoformat():
                # Only send a reminder for an outage we already knew about
                # (don't double-notify when discovery+reminder coincide).
                if o.key not in {n.key for n in new_outages}:
                    reminders.append(o)
                    reminded[o.key] = today.isoformat()

    # Prune state entries for outages whose end is well in the past (>30 days).
    cutoff = (datetime.now(tz=tz)).timestamp() - 30 * 86400
    for key in list(seen.keys()):
        try:
            end_ts = datetime.fromisoformat(seen[key]["end"]).timestamp()
            if end_ts < cutoff:
                seen.pop(key, None)
                reminded.pop(key, None)
        except Exception:
            pass

    state["outages"] = seen
    state["reminded"] = reminded

    if new_outages or reminders:
        subject_prefix = cfg["notify"].get("subject_prefix", "[home-monitor]")
        count = len(new_outages) + len(reminders)
        subject = f"{subject_prefix} {count} outage notice(s)"
        html = render_html(new_outages, reminders)
        text = render_text(new_outages, reminders)
        to = cfg["notify"]["to"]
        if not to:
            log.error("No notify.to recipient configured — skipping email")
        else:
            send_email(subject=subject, html=html, text=text, to=to)
            log.info("Sent email: %d new, %d reminder(s)", len(new_outages), len(reminders))
    else:
        log.info("No new outages or reminders.")

    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(run())
