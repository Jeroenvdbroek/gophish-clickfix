# 🎣 GoPhish ClickFix Simulation

> A fully self-built ClickFix / FakeCaptcha phishing simulation using GoPhish, Azure App Service and Microsoft Sentinel — because no ready-made tool exists for this attack technique.

**Live blog:** [jeroenvdbroek.github.io/gophish-clickfix](https://jeroenvdbroek.github.io/gophish-clickfix/)

---

## What is ClickFix?

ClickFix (also known as FakeCaptcha) is a social engineering attack where a fake verification page tricks the user into executing a command via `Win+R` or macOS Spotlight. No exploit, no malware download — the user does it themselves.

This technique bypasses browser security completely and is actively used in real-world attacks against organisations worldwide.

---

## Why I built this

GoPhish is great for classic phishing simulations but has no built-in support for ClickFix attacks. It can't:

- Copy a payload to the clipboard via JavaScript
- Handle a multi-page simulation flow
- Track whether a user actually executed Win+R

No commercial tools (KnowBe4, Proofpoint etc.) have ClickFix templates either. So I built it from scratch and am sharing everything openly.

---

## How it works

```
GoPhish email → index.html → add.html → clipboard hijack → Win+R → awareness page
     ↓               ↓            ↓                                      ↓
  RID tracking   Azure logs   Azure logs                          Sentinel confirmed
```

1. GoPhish sends phishing email with unique RID per recipient
2. User clicks link → lands on fake Microsoft MFA setup page
3. User clicks "Enable Passkey Method" → awareness URL silently copied to clipboard
4. Modal instructs Win+R → Ctrl+V → Enter
5. Awareness page opens — explains what just happened
6. Visit to `/source/content.webp` confirms Win+R was executed in Sentinel

---

## Stack

| Component | Purpose |
|---|---|
| **GoPhish** | Email delivery + RID tracking |
| **Azure App Service** | Hosts simulation pages |
| **Azure AppServiceHTTPLogs** | Tracks page visits per RID |
| **Python script** | Syncs GoPhish data to Sentinel hourly |
| **Microsoft Sentinel** | Live dashboard + KQL analysis |

---

## Repository structure

```
gophish-clickfix/
├── index.html              ← Blog / documentation (GitHub Pages)
├── README.md               ← This file
├── SETUP.md                ← Step-by-step Azure setup guide
├── gh_sentinel.py          ← Python sync script (GoPhish → Sentinel)
├── gh_queries.kql          ← All KQL queries including GoPhishEnriched function
└── simulation/
    ├── Captcha/
    │   ├── gh_index.html   ← First landing page (Microsoft MFA style)
    │   ├── gh_add.html     ← ClickFix trigger page
    │   └── ...             ← Assets (logo, background, FontAwesome)
    └── Landing/
        └── gh_landing.html ← Awareness landing page (NL/EN bilingual)
```

---

## Quick start

### 1. Deploy simulation pages
Upload `simulation/Captcha/` and `simulation/Landing/` to Azure App Service.

### 2. Configure GoPhish
Set your landing page URL to:
```
https://YOUR_SIMULATION_DOMAIN/?rid={{.RId}}
```

### 3. Set up Sentinel
Follow the step-by-step guide in [SETUP.md](SETUP.md).

### 4. Run the Python script
```bash
pip3 install azure-identity azure-monitor-query requests --break-system-packages
python3 gh_sentinel.py
```

### 5. Import the KQL function
Save `GoPhishEnriched` from `gh_queries.kql` as a Sentinel function.

---

## Tracking events

| Event | Source | How |
|---|---|---|
| Email opened | GoPhish | Automatic tracking pixel |
| Link clicked | AppServiceHTTPLogs | `rid=` in CsUriQuery on `/` |
| ClickFix page reached | AppServiceHTTPLogs | `rid=` in CsUriQuery on `/add.html` |
| **Win+R executed** | AppServiceHTTPLogs | `rid=` in Referer on `/source/content.webp` |

---

## Bot/scanner protection

All KQL queries use a `ValidRIDs` filter — only GoPhish recipients count. A regex `^[A-Za-z0-9]{5,10}$` blocks XSS payloads and scanner traffic from polluting your results.

---

## Safety

This simulation is completely safe. The clipboard payload is only the URL to the awareness page. No real commands or scripts are ever copied to the clipboard.

---

## Requirements

- GoPhish server (Azure VM or on-premise)
- Azure App Service (for simulation pages)
- Microsoft Sentinel workspace
- Azure App Registration (for Python script authentication)
- Python 3.8+

---

## Author

**Jeroen van der Broek** — [github.com/Jeroenvdbroek](https://github.com/Jeroenvdbroek)

Built this because no tool existed for it. Feel free to use, adapt and share.

---

## Disclaimer

This tool is intended for **authorised security awareness training only**. Only use it against systems and users you have explicit permission to test. The author is not responsible for misuse.

---

## License

MIT — free to use, modify and distribute. Attribution appreciated.
