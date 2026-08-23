"""Delivery: Slack (bot token, per-department channels) and WhatsApp via the
existing n8n webhook. Exec recap goes to Eugene and Ian.

Channel routing is env config, one var per department, so adding a department
channel never needs a code change:

    SLACK_RECAP_CHANNEL_EXEC=C123
    SLACK_RECAP_CHANNEL_GROWTH=C456
    SLACK_RECAP_CHANNEL_RETENTION=...

Anything with no channel configured is skipped and reported, never silently
dropped.
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import config
from ..connectors.http import post_json
from ..errors import SourceError
from .generator import Recap

SLACK_URL = "https://slack.com/api/chat.postMessage"


@dataclass
class Delivery:
    audience: str
    channel: str
    status: str          # sent | skipped | failed | dry_run
    detail: str = ""


def channel_for(audience: str) -> str | None:
    return config.get(f"SLACK_RECAP_CHANNEL_{audience.upper()}")


def deliver(
    recaps: list[Recap],
    *,
    dry_run: bool = True,
    slack: bool = True,
    whatsapp: bool = False,
) -> list[Delivery]:
    deliveries: list[Delivery] = []
    for recap in recaps:
        if slack:
            deliveries.append(_deliver_slack(recap, dry_run=dry_run))
        if whatsapp:
            deliveries.append(_deliver_whatsapp(recap, dry_run=dry_run))
    return deliveries


def _deliver_slack(recap: Recap, *, dry_run: bool) -> Delivery:
    channel = channel_for(recap.audience)
    if not channel:
        return Delivery(
            recap.audience,
            "slack",
            "skipped",
            f"no SLACK_RECAP_CHANNEL_{recap.audience.upper()} configured",
        )
    if dry_run:
        return Delivery(recap.audience, f"slack:{channel}", "dry_run")
    try:
        body = post_json(
            "slack",
            SLACK_URL,
            {"channel": channel, "text": recap.as_text()},
            {
                "Authorization": f"Bearer {config.require('SLACK_BOT_TOKEN')}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
    except SourceError as exc:
        return Delivery(recap.audience, f"slack:{channel}", "failed", exc.message)
    if not body.get("ok", False):
        return Delivery(
            recap.audience,
            f"slack:{channel}",
            "failed",
            f"slack said {body.get('error', 'not ok')}",
        )
    return Delivery(recap.audience, f"slack:{channel}", "sent", body.get("ts", ""))


def _deliver_whatsapp(recap: Recap, *, dry_run: bool) -> Delivery:
    url = config.get("N8N_WHATSAPP_WEBHOOK_URL")
    if not url:
        return Delivery(recap.audience, "whatsapp", "skipped", "no N8N_WHATSAPP_WEBHOOK_URL")
    if dry_run:
        return Delivery(recap.audience, "whatsapp", "dry_run")
    try:
        post_json(
            "n8n",
            url,
            {
                "audience": recap.audience,
                "title": recap.title,
                "body": recap.body,
                "week_start": recap.facts.get("week_start"),
            },
            {"Content-Type": "application/json"},
        )
    except SourceError as exc:
        return Delivery(recap.audience, "whatsapp", "failed", exc.message)
    return Delivery(recap.audience, "whatsapp", "sent")
