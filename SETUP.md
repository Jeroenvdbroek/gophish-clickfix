# Azure Setup Guide
## ClickFix Simulatie — Azure & Sentinel Configuratie

This guide walks you through setting up the Azure infrastructure needed for the ClickFix simulation pipeline.

---

## Prerequisites

- Azure subscription
- Microsoft Sentinel workspace (Log Analytics)
- Azure App Service (to host simulation pages)
- GoPhish server (Azure VM or on-premise)
- Azure CLI or access to Azure Portal

---

## Step 1 — Azure App Service

Host `index.html`, `add.html` and the awareness landing page on Azure App Service.

1. Create an **App Service** in Azure Portal
2. Upload the HTML files to the root of your App Service
3. Note your hostname — e.g. `your-app.azurewebsites.net`
4. Update the following placeholders in the HTML files:
   - `YOUR_SIMULATION_DOMAIN` → your App Service hostname
   - `YOUR_AWARENESS_DOMAIN` → your awareness page hostname

### Enable AppServiceHTTPLogs

This is required for tracking in Sentinel.

1. Azure Portal → Your App Service → **Diagnostic settings**
2. Add diagnostic setting → check **AppServiceHTTPLogs**
3. Send to: **Log Analytics Workspace** (your Sentinel workspace)
4. Save

---

## Step 2 — Data Collection Endpoint (DCE)

The DCE receives data from the Python script.

1. Azure Portal → **Monitor** → **Data Collection Endpoints** → **Create**
2. Name: `dce-gophish` (or your preferred name)
3. Region: same as your Log Analytics workspace
4. After creation, copy the **Logs Ingestion URL** — this is your `DCE_ENDPOINT`

---

## Step 3 — Custom Table in Log Analytics

Create the `GoPhish_CL` table that will store campaign data.

1. Azure Portal → **Log Analytics Workspace** → **Tables** → **Create** → **New custom log (DCR based)**
2. Upload the sample JSON below as schema:

```json
[{
    "TimeGenerated": "2026-01-01T00:00:00Z",
    "CampaignName": "Test Campaign",
    "CampaignId": "1",
    "RID": "abc123",
    "FirstName": "Jan",
    "LastName": "Jansen",
    "Email": "j.jansen@yourorg.nl",
    "OpenedEmail": true,
    "ClickedLink": true,
    "ExecutedClickFix": false,
    "ExecutedFirstSeen": "",
    "ExecutedLastSeen": "",
    "ExecutedFromIPs": "[]",
    "ExecutedUserAgents": "[]"
}]
```

3. Table name: `GoPhish` (Azure adds `_CL` automatically → `GoPhish_CL`)
4. Select your DCE
5. After creation, note the **DCR Immutable ID** — this is your `DCR_IMMUTABLE_ID`

---

## Step 4 — Entra ID App Registration

The Python script needs an identity to authenticate to Azure.

1. Azure Portal → **Entra ID** → **App Registrations** → **New Registration**
2. Name: `GoPhish-Sentinel-Ingest`
3. Leave everything default → **Register**
4. Copy:
   - **Tenant ID** (from overview)
   - **Client ID** (from overview)
5. Go to **Certificates & Secrets** → **New client secret**
   - Copy the **Value** immediately — it is only shown once
   - This is your `CLIENT_SECRET`

---

## Step 5 — Assign Roles to App Registration

### Role 1 — Write data to Sentinel

1. Azure Portal → **Monitor** → **Data Collection Rules** → your DCR
2. **Access Control (IAM)** → **Add role assignment**
3. Role: **Monitoring Metrics Publisher**
4. Assign to: `GoPhish-Sentinel-Ingest`

### Role 2 — Query Sentinel logs

1. Azure Portal → **Log Analytics Workspace** → your workspace
2. **Access Control (IAM)** → **Add role assignment**
3. Role: **Log Analytics Reader**
4. Assign to: `GoPhish-Sentinel-Ingest`

---

## Step 6 — Configure the Python Script

Edit `sentinel.py` and fill in your values:

```python
GOPHISH_URL      = "https://localhost:3333"        # GoPhish API URL
GOPHISH_API_KEY  = "YOUR_GOPHISH_API_KEY"          # From GoPhish Settings page
TENANT_ID        = "YOUR_TENANT_ID"                # Entra ID Tenant ID
CLIENT_ID        = "YOUR_CLIENT_ID"                # App Registration Client ID
CLIENT_SECRET    = "YOUR_CLIENT_SECRET"            # App Registration Client Secret
DCE_ENDPOINT     = "https://YOUR_DCE_ENDPOINT..."  # Data Collection Endpoint URL
DCR_IMMUTABLE_ID = "YOUR_DCR_IMMUTABLE_ID"         # Data Collection Rule ID
STREAM_NAME      = "Custom-GoPhish_CL"             # Keep as-is
WORKSPACE_ID     = "YOUR_WORKSPACE_ID"             # Log Analytics Workspace ID
LOOKBACK_HOURS   = 2                               # Increase to 720 for first run
```

### Install dependencies

```bash
pip3 install azure-identity azure-monitor-query requests --break-system-packages
```

### Test the script

```bash
python3 sentinel.py
```

Check the log:

```bash
tail -f ~/gophish_sentinel.log
```

Expected output:
```
[INFO] === GoPhish → Sentinel sync started ===
[INFO] Found X executed ClickFix RIDs in Sentinel
[INFO] Processing campaign: Your Campaign (ID: 1)
[INFO] Successfully pushed X records to Sentinel
[INFO] === GoPhish → Sentinel sync complete ===
```

### Set up hourly cron job

```bash
crontab -e
# Add:
0 * * * * python3 /home/youruser/sentinel.py
```

---

## Step 7 — Sentinel Function

Save the `GoPhishEnriched` KQL function in Sentinel:

1. Azure Portal → **Microsoft Sentinel** → **Logs**
2. Paste the query from `queries.kql` (section 1 — GoPhishEnriched)
3. Replace `YOUR_SIMULATION_DOMAIN` and `YOUR_AWARENESS_DOMAIN` with your actual hostnames
4. Click **Save** → **Save as function**
5. Function name: `GoPhishEnriched`
6. Save

Test it:

```kusto
GoPhishEnriched
| sort by ClickedAt desc
```

---

## Step 8 — Import Sentinel Workbook

1. Azure Portal → **Microsoft Sentinel** → **Workbooks**
2. Click **Add Workbook**
3. Click the **edit** (pencil) button
4. Click **`</>`** (Advanced Editor)
5. Delete all existing content
6. Paste the contents of `workbook.json`
7. Click **Apply** → **Save**

---

## Step 9 — GoPhish Campaign Setup

In GoPhish, set your landing page URL using the `{{.RId}}` template variable:

```
https://YOUR_SIMULATION_DOMAIN/?rid={{.RId}}
```

GoPhish automatically replaces `{{.RId}}` with each recipient's unique tracking ID.

---

## First Run Tips

1. Set `LOOKBACK_HOURS = 720` for the first sync to capture all historical data
2. After first sync, set it back to `2` for hourly runs
3. Verify data in Sentinel: `GoPhish_CL | take 10`
4. If table is empty, wait 5-10 minutes — custom tables have ingestion delay

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `InsufficientAccessError` | Missing role | Add Log Analytics Reader role |
| `400 Bad Request` GoPhish | Wrong URL scheme | Use `https://` not `http://` |
| `PermissionError` log file | No write access to `/var/log` | Change log path to `~/gophish_sentinel.log` |
| `externally-managed-environment` pip | Debian managed Python | Add `--break-system-packages` flag |
| Empty results in workbook | AppServiceHTTPLogs not enabled | Enable in App Service Diagnostic settings |
