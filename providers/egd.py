"""
EG.D (eg.d / E.ON Distribuce) planned electricity outage provider.

Flow:
  1. GET  https://www.egd.cz/formular-bezproudi
       → scrape form_build_id, form_id, raw antibot key from drupalSettings JSON
  2. Transform antibot key (reverse string, swap adjacent char pairs)
  3. POST https://www.egd.cz/formular-bezproudi?ajax_form=1
       with the autocomplete address id (full "<label> (<24-hex>)" string)
       → Drupal AJAX JSON command array; the outage HTML is in
         the `insert` command targeting #container-results-blackout
  4. Parse HTML: one .accordion__topic block per outage.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

from providers.base import Outage, Provider

FORM_URL = "https://www.egd.cz/formular-bezproudi"
AJAX_URL = "https://www.egd.cz/formular-bezproudi?ajax_form=1"
DETAIL_URL = FORM_URL  # EG.D doesn't publish per-outage links
TZ = ZoneInfo("Europe/Prague")

CZ_MONTHS = {
    "leden": 1, "ledna": 1,
    "únor": 2, "února": 2,
    "březen": 3, "března": 3,
    "duben": 4, "dubna": 4,
    "květen": 5, "května": 5,
    "červen": 6, "června": 6,
    "červenec": 7, "července": 7,
    "srpen": 8, "srpna": 8,
    "září": 9,
    "říjen": 10, "října": 10,
    "listopad": 11, "listopadu": 11,
    "prosinec": 12, "prosince": 12,
}


@dataclass
class _FormTokens:
    form_build_id: str
    form_id: str
    antibot_key: str


def _transform_antibot(raw: str) -> str:
    """Reverse whole string, then swap each adjacent character pair.

    Matches the JS footer.js transform:
      reversed = raw.reverse()
      for i in 0..len step 2: pair = reversed[i:i+2]; out += pair.reverse()
    """
    reversed_s = raw[::-1]
    pairs = [reversed_s[i:i + 2] for i in range(0, len(reversed_s), 2)]
    return "".join(p[::-1] for p in pairs)


def _parse_cz_datetime(date_part: str, time_part: str, *, now: datetime) -> datetime:
    """Parse e.g. date_part='16. říjen (pá)', time_part='12:00' into aware datetime.

    EG.D doesn't include the year, so we infer: pick the nearest future year
    (same calendar year if the date is still ahead, else next year).
    """
    m = re.match(r"\s*(\d{1,2})\.\s*([a-zěščřžýáíéúůďťňÉŠČŘŽÝÁÍÚŮ]+)", date_part, re.IGNORECASE)
    if not m:
        raise ValueError(f"Unparseable EG.D date: {date_part!r}")
    day = int(m.group(1))
    month_name = m.group(2).lower()
    month = CZ_MONTHS.get(month_name)
    if not month:
        raise ValueError(f"Unknown Czech month: {month_name!r} in {date_part!r}")

    hh, mm = (int(x) for x in time_part.split(":"))

    year = now.year
    candidate = datetime(year, month, day, hh, mm, tzinfo=TZ)
    # If the computed moment is more than a day in the past, roll to next year.
    if (now - candidate).days > 1:
        candidate = datetime(year + 1, month, day, hh, mm, tzinfo=TZ)
    return candidate


def _fetch_tokens(session: requests.Session) -> _FormTokens:
    r = session.get(FORM_URL, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    form = soup.find("form", attrs={"data-drupal-selector": re.compile("power-outage")}) \
        or soup.find("form", id=re.compile("power-outage"))
    if form is None:
        raise RuntimeError("Could not find EG.D power-outage form on the page")

    def hidden(name: str) -> str:
        el = form.find("input", attrs={"name": name})
        if not el or not el.get("value"):
            raise RuntimeError(f"Missing hidden field {name!r} on EG.D form")
        return el["value"]

    form_build_id = hidden("form_build_id")
    form_id = hidden("form_id")

    # drupalSettings carries the raw antibot key for this form instance.
    raw_key = None
    for script in soup.find_all("script", attrs={"type": "application/json"}):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        antibot = data.get("antibot") if isinstance(data, dict) else None
        forms = antibot.get("forms") if isinstance(antibot, dict) else None
        if not isinstance(forms, dict):
            continue
        for form_cfg in forms.values():
            if isinstance(form_cfg, dict) and form_cfg.get("key"):
                raw_key = form_cfg["key"]
                break
        if raw_key:
            break

    if not raw_key:
        raise RuntimeError("Could not locate antibot key in EG.D drupalSettings")

    return _FormTokens(
        form_build_id=form_build_id,
        form_id=form_id,
        antibot_key=_transform_antibot(raw_key),
    )


def _post_outage_search(
    session: requests.Session, tokens: _FormTokens, address_id_full: str
) -> list[dict[str, Any]]:
    data = {
        "address_ean[input]": address_id_full,
        "address_ean[id]": address_id_full,
        "form_build_id": tokens.form_build_id,
        "form_id": tokens.form_id,
        "antibot_key": tokens.antibot_key,
        "_triggering_element_name": "poweroutage_address_ean_button",
        "_triggering_element_value": "Vyhledat",
        "_drupal_ajax": "1",
        "ajax_page_state[theme]": "egd",
        "ajax_page_state[libraries]": "",
    }
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": FORM_URL,
    }
    r = session.post(AJAX_URL, data=data, headers=headers, timeout=20)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected EG.D AJAX response shape: {type(payload)}")
    return payload


def _extract_results_html(ajax: list[dict[str, Any]]) -> str:
    for cmd in ajax:
        if (
            cmd.get("command") == "insert"
            and cmd.get("selector") == "#container-results-blackout"
            and isinstance(cmd.get("data"), str)
        ):
            return cmd["data"]
    return ""


def _parse_outages(
    html: str,
    *,
    address_label: str,
    now: datetime,
) -> list[Outage]:
    """
    EG.D emits one `.accordion__topic` per outage followed by many
    `.blackout-accordion__content-adress` siblings (not children) that list the
    affected streets. We walk the DOM in document order, grouping address rows
    under the preceding topic.
    """
    soup = BeautifulSoup(html, "html.parser")
    outages: list[Outage] = []

    # Collect every topic + address-row node in document order from the whole fragment.
    nodes = soup.select(".accordion__topic, .blackout-accordion__content-adress")

    groups: list[tuple[Tag, list[Tag]]] = []
    for node in nodes:
        classes = node.get("class") or []
        if "accordion__topic" in classes:
            groups.append((node, []))
        elif groups:
            groups[-1][1].append(node)

    for topic, address_rows in groups:
        # Date + time + outage id live inside the topic's own content block.
        content = topic.select_one(".blackout-accordion__content")
        if not content:
            continue
        content_text = " ".join(content.get_text(" ", strip=True).split())

        id_match = re.search(r"Číslo odstávky[:\s]*([0-9]+)", content_text)
        if not id_match:
            header = topic.get_text(" ", strip=True)
            id_match = re.search(r"Odstávka\s+([0-9]+)", header)
        if not id_match:
            continue
        external_id = id_match.group(1)

        dt_match = re.search(
            r"(\d{1,2}\.\s*[A-Za-zěščřžýáíéúůďťňÉŠČŘŽÝÁÍÚŮ]+)"
            r"[^,]*,\s*od\s*(\d{1,2}:\d{2})\s*do\s*(\d{1,2}:\d{2})",
            content_text,
        )
        if not dt_match:
            continue
        date_part, start_t, end_t = dt_match.group(1), dt_match.group(2), dt_match.group(3)
        start = _parse_cz_datetime(date_part, start_t, now=now)
        end = _parse_cz_datetime(date_part, end_t, now=now)
        if end < start:  # overnight
            end = end.replace(day=end.day + 1)

        # The "Týká se domů ..." row is the one whose icon div has class "lightning".
        affected = ""
        for row in address_rows:
            if row.select_one(".blackout-accordion__icon.lightning"):
                affected = row.get_text(" ", strip=True)
                break

        description = f"Číslo odstávky: {external_id}."
        if affected:
            description += f" {affected}"

        outages.append(
            Outage(
                provider="egd",
                utility="electricity",
                external_id=external_id,
                address_label=address_label,
                start=start,
                end=end,
                description=description,
                url=DETAIL_URL,
            )
        )
    return outages


class EgdProvider(Provider):
    name = "egd"
    utility = "electricity"

    def __init__(self, session: requests.Session | None = None, now_fn=None):
        self._session = session or requests.Session()
        self._session.headers.update({
            # The EG.D edge rejects "bot-shaped" requests. Use browser-like
            # headers (UA + Accept + Accept-Language) to pass through.
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "cs,en;q=0.8",
        })
        self._now_fn = now_fn or (lambda: datetime.now(tz=TZ))

    def fetch(self, address_cfg: dict[str, Any]) -> list[Outage]:
        address_id = address_cfg["egd_address_id"]
        address_label = address_cfg["egd_address_label"]
        # EG.D expects the full "<label> (<24-hex>)" string, not just the hex id.
        full_id = f"{address_label} ({address_id})"

        tokens = _fetch_tokens(self._session)
        ajax = _post_outage_search(self._session, tokens, full_id)
        html = _extract_results_html(ajax)
        if not html.strip():
            return []
        return _parse_outages(
            html,
            address_label=address_cfg.get("label", address_label),
            now=self._now_fn(),
        )
