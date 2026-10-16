from __future__ import annotations

import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from providers.base import Outage


def _fmt_dt(dt) -> str:
    return dt.strftime("%a %d %b %Y, %H:%M")


def render_html(new_outages: list[Outage], reminders: list[Outage]) -> str:
    def section(title: str, outages: list[Outage]) -> str:
        if not outages:
            return ""
        rows = "".join(
            f"""
            <tr>
              <td style="padding:8px;border-bottom:1px solid #eee;">
                <div style="font-weight:600;">{o.utility.title()} — {o.address_label}</div>
                <div style="color:#555;">{_fmt_dt(o.start)} → {_fmt_dt(o.end)}</div>
                <div style="color:#333;margin-top:4px;">{o.description or ''}</div>
                {'<div><a href="' + o.url + '">Details</a></div>' if o.url else ''}
              </td>
            </tr>
            """
            for o in outages
        )
        return f"""
        <h2 style="font-size:16px;margin:16px 0 8px;">{title}</h2>
        <table style="border-collapse:collapse;width:100%;font-family:system-ui,sans-serif;font-size:14px;">
          {rows}
        </table>
        """

    body = section("Newly detected outages", new_outages) + section(
        "Reminder — outage coming up", reminders
    )
    return f"""<html><body>{body or '<p>No outages.</p>'}</body></html>"""


def render_text(new_outages: list[Outage], reminders: list[Outage]) -> str:
    def section(title: str, outages: list[Outage]) -> str:
        if not outages:
            return ""
        lines = [f"== {title} =="]
        for o in outages:
            lines.append(
                f"- [{o.utility}] {o.address_label}\n"
                f"  {_fmt_dt(o.start)} → {_fmt_dt(o.end)}\n"
                f"  {o.description or ''}\n"
                f"  {o.url or ''}"
            )
        return "\n".join(lines) + "\n"

    return (section("Newly detected outages", new_outages)
            + section("Reminder — outage coming up", reminders)) or "No outages.\n"


def _parse_recipients(to: str | list[str]) -> list[str]:
    if isinstance(to, list):
        items = to
    else:
        # Accept comma- or semicolon-separated lists in a single string
        # (handy for a single GitHub Actions secret).
        items = re.split(r"[,;]", to)
    return [addr.strip() for addr in items if addr and addr.strip()]


def send_email(
    *,
    subject: str,
    html: str,
    text: str,
    to: str | list[str],
) -> None:
    user = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]

    recipients = _parse_recipients(to)
    if not recipients:
        raise ValueError("No recipients configured")

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="home-monitor.local")
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, password)
        s.send_message(msg, to_addrs=recipients)
