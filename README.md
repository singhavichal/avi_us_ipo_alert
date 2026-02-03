# avi_us_ipo_alert

Fetches **U.S. IPOs for “today” only** (same-day IPOs; **not** upcoming), identifies tickers with **offer amount > USD 200M** (Offer Amount = **IPO price × shares**), and sends an **email alert**.

Data source: **Finnhub IPO Calendar API**  
Email delivery: **Gmail SMTP (STARTTLS)**

---

## What the script does

1. Determines **today’s date in America/New_York** (US market date).
2. Calls Finnhub IPO calendar API for `from=today` and `to=today`.
3. Filters IPOs to **same-day only** (exact date match).
4. Computes **Offer Amount**:
   - Uses provided total fields if available (`totalSharesValue` / `proceeds` / `totalValue`)
   - Otherwise computes `price × numberOfShares` (or equivalent fields)
5. Filters for **Offer Amount > $200,000,000**
6. Sends an HTML email with results (or “no IPOs above threshold”), and includes a **brief error summary** in email if API/network issues occur.
7. (Optional) Runs continuously and executes daily at **09:00 Asia/Dubai**.

---

## Project structure

- `ipo_monitor.py` — main script (supports one-time run or daily scheduler)

---

## Prerequisites

- Python **3.10+** (recommended 3.11+)
- A **Finnhub API token**
- A Gmail account with:
  - **2-Step Verification enabled**
  - A **Gmail App Password** created for SMTP
- Internet access to `https://finnhub.io` and `https://smtp.gmail.com`

---

## Installation

```bash
python -m pip install --upgrade pip
python -m pip install requests certifi urllib3
```

> Notes:
> - `requests` is used for API calls.
> - `certifi` provides CA certificates for HTTPS verification.
> - `urllib3` supports retry behavior via `requests`.

---

## Required settings (before running)

Configure the following environment variables:

### 1) Finnhub token
- `FINNHUB_TOKEN` = your Finnhub API token

### 2) Gmail SMTP settings
- `SENDER_EMAIL` = Gmail address sending the alert
- `SENDER_PASSWORD` = **Gmail App Password** (NOT your normal Gmail password)
- `RECEIVER_EMAIL` = recipient email address

Optional (defaults are fine):
- `SMTP_SERVER` = `smtp.gmail.com`
- `SMTP_PORT` = `587`

### 3) SSL / corporate network (optional)
If you are on a corporate VPN with SSL inspection and you see certificate errors, set one of these to your corporate CA bundle PEM file:

- `REQUESTS_CA_BUNDLE` = `C:\path\to\combined.pem`
- `SSL_CERT_FILE` = `C:\path\to\combined.pem`

Last resort only (insecure; not recommended):
- `ALLOW_INSECURE_SSL` = `1`

---

## Example: set environment variables

### Windows PowerShell (current session)
```powershell
$env:FINNHUB_TOKEN="YOUR_FINNHUB_TOKEN"
$env:SENDER_EMAIL="from_email@gmail.com"
$env:SENDER_PASSWORD="YOUR_GMAIL_APP_PASSWORD"
$env:RECEIVER_EMAIL="to_email@gmail.com"
```

### macOS/Linux
```bash
export FINNHUB_TOKEN="YOUR_FINNHUB_TOKEN"
export SENDER_EMAIL="from_email@gmail.com"
export SENDER_PASSWORD="YOUR_GMAIL_APP_PASSWORD"
export RECEIVER_EMAIL="to_email@gmail.com"
```

---

## Running

### Option A: One-time run (recommended for cron/Task Scheduler)
Edit `ipo_monitor.py` so the `__main__` section calls:

- `ipo_monitor_job()`

Run:
```bash
python ipo_monitor.py
```

### Option B: Run continuously (built-in scheduler: 09:00 Dubai time)
Edit `ipo_monitor.py` so the `__main__` section calls:

- `run_daily_9am_dubai_forever()`

Run:
```bash
python ipo_monitor.py
```

This keeps the process running and triggers once per day at **09:00 Asia/Dubai**.

---

## How “today” is defined

The script uses **America/New_York** timezone to compute `today` (US market date).  
This prevents off-by-one-day issues when running from Dubai or other timezones.

---

## Offer amount logic

Offer Amount = **IPO price × shares**

The script tries, in order:
1. Use provided totals if Finnhub includes them:
   - `totalSharesValue`, `proceeds`, or `totalValue`
2. Otherwise compute:
   - `price × numberOfShares` (or similar share/price fields)

Only IPOs with Offer Amount **> $200,000,000** are included in the alert.

---

## Troubleshooting

### Email error: `535 5.7.8 Username and Password not accepted`
- Ensure you are using a **Gmail App Password** (requires 2FA).
- Ensure `SENDER_EMAIL` matches the account that generated the App Password.

### No IPOs returned
- There may truly be no IPOs for the day.
- Test with a historical date by temporarily overriding the date range in the script, or query Finnhub for a wider range and pick a day with multiple IPOs.

### SSL errors (corporate VPN)
- Set `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` to your corporate root CA bundle PEM.
- Avoid setting `ALLOW_INSECURE_SSL=1` except for short-lived testing.

---

## Security note

Do **not** commit credentials (Finnhub token, Gmail App Password) into GitHub.  
Use environment variables or a local `.env` solution (not included here by default).

---
