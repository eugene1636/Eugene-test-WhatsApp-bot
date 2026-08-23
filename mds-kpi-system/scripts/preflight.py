"""Check every source system against real credentials, before Monday does.

This is the live dry run. It makes small read-only calls, reports what each
system actually answered, and where a setting is ambiguous it probes the options
and prints the .env line to use.

    python scripts/preflight.py                  # everything configured
    python scripts/preflight.py --only stripe gohighlevel
    python scripts/preflight.py --week 2026-08-17

Anything not configured is reported as skipped, never as passing.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402
from src.connectors import gohighlevel as ghl  # noqa: E402
from src.connectors import stripe_conn  # noqa: E402
from src.weeks import Week, last_full_week, parse_week  # noqa: E402

OK, FAIL, SKIP = "ok", "FAIL", "skip"

# Version header values GoHighLevel has used. Current docs say v3; tokens issued
# against the older date-versioned API answer to one of the dates.
GHL_VERSIONS = ("v3", "2021-04-15", "2021-07-28")


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fixes: list[str] = field(default_factory=list)


def check_supabase(week: Week) -> Check:
    if not config.get("SUPABASE_DB_URL"):
        return Check("supabase", SKIP, "SUPABASE_DB_URL not set")
    try:
        from src.warehouse import Warehouse

        warehouse = Warehouse()
    except Exception as exc:
        return Check("supabase", FAIL, f"{type(exc).__name__}: {exc}")
    try:
        known = warehouse.known_metric_ids()
    except Exception as exc:
        return Check(
            "supabase",
            FAIL,
            f"connected, but the schema is not there ({exc})",
            ["python scripts/bootstrap_warehouse.py"],
        )
    finally:
        warehouse.close()
    if len(known) < 13:
        return Check(
            "supabase",
            FAIL,
            f"only {len(known)} of 13 metrics seeded",
            ["python scripts/bootstrap_warehouse.py"],
        )
    return Check("supabase", OK, f"schema applied, {len(known)} metrics registered")


def check_stripe(week: Week) -> Check:
    if not config.get("STRIPE_API_KEY"):
        return Check("stripe", SKIP, "STRIPE_API_KEY not set")
    try:
        source = stripe_conn.StripeSource()
        payload = stripe_conn.fetch_new_member_payments(
            week.start, week.end, client=source
        )
    except Exception as exc:
        return Check("stripe", FAIL, f"{type(exc).__name__}: {exc}")

    members = payload["new_members"]
    intervals = Counter(m["plan_interval"] for m in members)
    dollars = sum(m["amount_dollars"] for m in members)
    detail = (
        f"{len(members)} first-time payments in week of {week.start}, "
        f"${dollars:,.0f}, plans: {dict(intervals) or 'none'}"
    )
    fixes = []
    if members and intervals.get("one_time") == len(members):
        fixes.append(
            "every plan_interval came back one_time. Check the invoice line "
            "shape in src/connectors/stripe_conn.py:_plan_interval against your "
            "Stripe API version."
        )
    if not members:
        fixes.append(
            "zero new members. Confirm with --week for a week you know had joins "
            "before trusting this."
        )
    return Check("stripe", OK, detail, fixes)


def check_gohighlevel(week: Week) -> Check:
    if not (config.get("GHL_API_KEY") and config.get("GHL_LOCATION_ID")):
        return Check("gohighlevel", SKIP, "GHL_API_KEY or GHL_LOCATION_ID not set")

    key = config.require("GHL_API_KEY")
    location = config.require("GHL_LOCATION_ID")
    fixes: list[str] = []

    version, calendars, error = _probe_ghl_version(key, location)
    if version is None:
        return Check("gohighlevel", FAIL, f"no Version header worked. Last: {error}")
    if version != (config.get("GHL_API_VERSION") or ghl.DEFAULT_API_VERSION):
        fixes.append(f"GHL_API_VERSION={version}")

    needle = (config.get("GHL_DISCOVERY_CALENDAR_MATCH") or "discovery").lower()
    configured = config.get_list("GHL_DISCOVERY_CALENDAR_IDS")
    matched = [c for c in calendars if needle in (c.get("name") or "").lower()]
    if not configured and not matched:
        names = ", ".join(sorted((c.get("name") or "?") for c in calendars)) or "none"
        return Check(
            "gohighlevel",
            FAIL,
            f"Version {version} works, but no calendar name contains {needle!r}. "
            f"Calendars: {names}",
            ["set GHL_DISCOVERY_CALENDAR_IDS to the discovery calendar ids"],
        )

    search = _probe_ghl_contact_search(key, location, version)
    if search is None:
        fixes.append(
            "neither POST /contacts/search nor GET /contacts/ answered. Lead "
            "source attribution will report unknown for every member."
        )
    elif search != (config.get("GHL_CONTACT_SEARCH") or "post"):
        fixes.append(f"GHL_CONTACT_SEARCH={search}")

    try:
        source = ghl.GoHighLevelSource(api_key=key, location_id=location, api_version=version)
        calls = ghl.fetch_discovery_calls(week.start, week.end, client=source)["calls"]
    except Exception as exc:
        return Check("gohighlevel", FAIL, f"pulling events failed: {type(exc).__name__}: {exc}", fixes)

    statuses = Counter(c["status"] for c in calls)
    detail = (
        f"Version {version}, {len(matched) or len(configured)} discovery calendar(s), "
        f"{len(calls)} calls in week of {week.start}: {dict(statuses) or 'none'}"
    )
    if calls and not any(c["email"] for c in calls):
        fixes.append(
            "no event carried an email, so calls cannot be matched to payments. "
            "The conversion and with/without discovery sub-metrics will be empty."
        )
    return Check("gohighlevel", OK, detail, fixes)


def _probe_ghl_version(key: str, location: str) -> tuple[str | None, list[dict], str]:
    last = ""
    for version in GHL_VERSIONS:
        try:
            response = requests.get(
                f"{ghl.API_BASE}/calendars/",
                params={"locationId": location},
                headers={
                    "Authorization": f"Bearer {key}",
                    "Version": version,
                    "Accept": "application/json",
                },
                timeout=30,
            )
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}"
            continue
        if response.status_code < 400:
            return version, (response.json().get("calendars") or []), ""
        last = f"Version {version} -> HTTP {response.status_code}: {response.text[:120]}"
    return None, [], last


def _probe_ghl_contact_search(key: str, location: str, version: str) -> str | None:
    headers = {
        "Authorization": f"Bearer {key}",
        "Version": version,
        "Accept": "application/json",
    }
    try:
        post = requests.post(
            f"{ghl.API_BASE}/contacts/search",
            json={"locationId": location, "page": 1, "pageLimit": 1},
            headers=headers,
            timeout=30,
        )
        if post.status_code < 400:
            return "post"
    except requests.RequestException:
        pass
    try:
        get = requests.get(
            f"{ghl.API_BASE}/contacts/",
            params={"locationId": location, "limit": 1},
            headers=headers,
            timeout=30,
        )
        if get.status_code < 400:
            return "get"
    except requests.RequestException:
        pass
    return None


def check_anthropic(week: Week) -> Check:
    if not config.get("ANTHROPIC_API_KEY"):
        return Check("anthropic", SKIP, "ANTHROPIC_API_KEY not set")
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.require("ANTHROPIC_API_KEY"))
        model = client.models.retrieve(config.RECAP_MODEL)
    except Exception as exc:
        return Check(
            "anthropic",
            FAIL,
            f"{type(exc).__name__}: {exc}",
            [f"check RECAP_MODEL={config.RECAP_MODEL} is available to this key"],
        )
    return Check("anthropic", OK, f"recap model {model.id} reachable")


def check_slack(week: Week) -> Check:
    if not config.get("SLACK_BOT_TOKEN"):
        return Check("slack", SKIP, "SLACK_BOT_TOKEN not set")
    try:
        body = requests.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {config.require('SLACK_BOT_TOKEN')}"},
            timeout=30,
        ).json()
    except requests.RequestException as exc:
        return Check("slack", FAIL, f"{type(exc).__name__}: {exc}")
    if not body.get("ok"):
        return Check("slack", FAIL, f"auth.test said {body.get('error')}")

    configured = [
        f"{name.removeprefix('SLACK_RECAP_CHANNEL_').lower()}"
        for name in (
            "SLACK_RECAP_CHANNEL_EXEC",
            "SLACK_RECAP_CHANNEL_GROWTH",
        )
        if config.get(name)
    ]
    fixes = []
    if "exec" not in configured:
        fixes.append("SLACK_RECAP_CHANNEL_EXEC=<channel id> so the exec recap has somewhere to land")
    if "growth" not in configured:
        fixes.append("SLACK_RECAP_CHANNEL_GROWTH=<channel id>")
    return Check("slack", OK, f"authed as {body.get('user')}, channels: {configured or 'none'}", fixes)


CHECKS = {
    "supabase": check_supabase,
    "stripe": check_stripe,
    "gohighlevel": check_gohighlevel,
    "anthropic": check_anthropic,
    "slack": check_slack,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", help="any date in the week to probe (default: last full week)")
    parser.add_argument("--only", nargs="+", choices=sorted(CHECKS), help="a subset of systems")
    args = parser.parse_args(argv)

    week = parse_week(args.week) if args.week else last_full_week()
    names = args.only or list(CHECKS)

    print(f"Preflight against week of {week}\n")
    results = []
    for name in names:
        result = CHECKS[name](week)
        results.append(result)
        print(f"  [{result.status:>4}] {result.name}: {result.detail}")
        for fix in result.fixes:
            print(f"         -> {fix}")

    failed = [r for r in results if r.status == FAIL]
    skipped = [r for r in results if r.status == SKIP]
    print()
    print(
        f"{len(results) - len(failed) - len(skipped)} ok, "
        f"{len(failed)} failed, {len(skipped)} not configured"
    )
    if failed:
        print("\nMonday will report these as unavailable until they are fixed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
