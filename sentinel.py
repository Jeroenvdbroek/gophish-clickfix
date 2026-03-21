#!/usr/bin/env python3
"""
GoPhish → Sentinel Ingestion Script
Runs hourly via cron on the GoPhish server.
Pulls campaign results from GoPhish API, matches RIDs from Azure App Service logs,
and pushes combined data to Sentinel GoPhish_CL table.
"""

import json
import logging
import requests
from datetime import datetime, timezone, timedelta
from azure.identity import ClientSecretCredential
from azure.monitor.query import LogsQueryClient, LogsQueryStatus

# ── Logging ──
logging.basicConfig(
    filename='/var/log/gophish_sentinel.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
log = logging.getLogger(__name__)

# ══════════════════════════════════════════
# CONFIG — fill in your values
# ══════════════════════════════════════════
GOPHISH_URL      = "http://localhost:3333"   # GoPhish API (local)
GOPHISH_API_KEY  = "YOUR_GOPHISH_API_KEY"

TENANT_ID        = "YOUR_TENANT_ID"
CLIENT_ID        = "YOUR_CLIENT_ID"
CLIENT_SECRET    = "YOUR_CLIENT_SECRET"

DCE_ENDPOINT     = "https://YOUR_DCE_ENDPOINT.ingest.monitor.azure.com"
DCR_IMMUTABLE_ID = "YOUR_DCR_IMMUTABLE_ID"
STREAM_NAME      = "Custom-GoPhish_CL"

WORKSPACE_ID     = "YOUR_LOG_ANALYTICS_WORKSPACE_ID"

# How far back to look for executed ClickFix events in Sentinel
LOOKBACK_HOURS   = 2  # slightly more than cron interval to avoid gaps
# ══════════════════════════════════════════


def get_gophish_campaigns():
    """Get all campaigns from GoPhish API."""
    try:
        resp = requests.get(
            f"{GOPHISH_URL}/api/campaigns/",
            headers={"Authorization": GOPHISH_API_KEY},
            verify=False
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"Failed to fetch GoPhish campaigns: {e}")
        return []


def get_gophish_results(campaign_id):
    """Get results for a specific campaign."""
    try:
        resp = requests.get(
            f"{GOPHISH_URL}/api/campaigns/{campaign_id}/results",
            headers={"Authorization": GOPHISH_API_KEY},
            verify=False
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"Failed to fetch results for campaign {campaign_id}: {e}")
        return {}


def get_executed_rids_from_sentinel(credential):
    """Query Sentinel for RIDs that visited the awareness landing page."""
    try:
        client = LogsQueryClient(credential)
        query = """
AppServiceHTTPLogs
| where (CsHost == "YOUR_AWARENESS_DOMAIN" 
         and CsUriStem contains "/source/content.webp")
    or (CsHost == "access.yourorgportaal.nl" 
        and CsUriStem contains "/captcha.html")
| extend rid = extract("rid=([^&\\" ]+)", 1, Referer)
| where isnotempty(rid) and rid <> "unknown"
| summarize
    FirstSeen = min(TimeGenerated),
    LastSeen  = max(TimeGenerated),
    IPs       = make_set(CIp),
    UserAgents = make_set(UserAgent)
    by rid
        """
        response = client.query_workspace(
            workspace_id=WORKSPACE_ID,
            query=query,
            timespan=timedelta(hours=LOOKBACK_HOURS)
        )
        executed_rids = {}
        if response.status == LogsQueryStatus.SUCCESS:
            for row in response.tables[0].rows:
                rid        = row[0]
                first_seen = row[1]
                last_seen  = row[2]
                ips        = row[3]
                useragents = row[4]
                executed_rids[rid] = {
                    "FirstSeen":  str(first_seen),
                    "LastSeen":   str(last_seen),
                    "IPs":        ips,
                    "UserAgents": useragents
                }
        log.info(f"Found {len(executed_rids)} executed ClickFix RIDs in Sentinel")
        return executed_rids
    except Exception as e:
        log.error(f"Failed to query Sentinel for RIDs: {e}")
        return {}


def push_to_sentinel(credential, records):
    """Push records to GoPhish_CL table via DCR ingestion API."""
    try:
        token = credential.get_token("https://monitor.azure.com/.default").token
        url = (
            f"{DCE_ENDPOINT}/dataCollectionRules/{DCR_IMMUTABLE_ID}"
            f"/streams/{STREAM_NAME}?api-version=2023-01-01"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json"
        }
        resp = requests.post(url, data=json.dumps(records), headers=headers)
        if resp.status_code == 204:
            log.info(f"Successfully pushed {len(records)} records to Sentinel")
        else:
            log.error(f"Failed to push to Sentinel: HTTP {resp.status_code} — {resp.text}")
        return resp.status_code
    except Exception as e:
        log.error(f"Exception pushing to Sentinel: {e}")
        return None


def main():
    log.info("=== GoPhish → Sentinel sync started ===")

    # Authenticate to Azure
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)

    # Get RIDs that executed ClickFix from Sentinel
    executed_rids = get_executed_rids_from_sentinel(credential)

    # Get all GoPhish campaigns
    campaigns = get_gophish_campaigns()
    if not campaigns:
        log.warning("No campaigns found in GoPhish")
        return

    records = []

    for campaign in campaigns:
        campaign_id   = campaign.get("id")
        campaign_name = campaign.get("name", "Unknown")
        log.info(f"Processing campaign: {campaign_name} (ID: {campaign_id})")

        results = get_gophish_results(campaign_id)
        if not results:
            continue

        for recipient in results.get("results", []):
            rid        = recipient.get("id", "")
            email      = recipient.get("email", "")
            first_name = recipient.get("first_name", "")
            last_name  = recipient.get("last_name", "")

            # Check what GoPhish events this recipient has
            timeline       = recipient.get("timeline", [])
            event_messages = [e.get("message", "") for e in timeline]
            clicked_link   = any("Clicked Link" in m for m in event_messages)
            opened_email   = any("Email Opened" in m for m in event_messages)

            # Check if they executed ClickFix (visited awareness page)
            executed = rid in executed_rids
            exec_data = executed_rids.get(rid, {})

            record = {
                "TimeGenerated":    datetime.now(timezone.utc).isoformat(),
                "CampaignName":     campaign_name,
                "CampaignId":       str(campaign_id),
                "RID":              rid,
                "Email":            email,
                "FirstName":        first_name,
                "LastName":         last_name,
                "OpenedEmail":      opened_email,
                "ClickedLink":      clicked_link,
                "ExecutedClickFix": executed,
                "ExecutedFirstSeen": exec_data.get("FirstSeen", ""),
                "ExecutedLastSeen":  exec_data.get("LastSeen", ""),
                "ExecutedFromIPs":   json.dumps(exec_data.get("IPs", [])),
                "ExecutedUserAgents": json.dumps(exec_data.get("UserAgents", []))
            }
            records.append(record)

    if records:
        log.info(f"Pushing {len(records)} total records to Sentinel")
        push_to_sentinel(credential, records)
    else:
        log.info("No records to push")

    log.info("=== GoPhish → Sentinel sync complete ===")


if __name__ == "__main__":
    main()
