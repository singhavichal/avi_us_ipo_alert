import os
import time
import ssl
import smtplib
import requests
import certifi
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# =========================
# CONFIG
# =========================

FINNHUB_TOKEN = os.environ.get("FINNHUB_TOKEN", "finnhub_token")

SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "from_email@gmail.com")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD", "gmail_app_pswd")  # Gmail App Password
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "to_email@gmail.com")

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))

OFFER_AMOUNT_THRESHOLD = 200_000_000  # $200M

DUBAI_TZ = ZoneInfo("Asia/Dubai")
NY_TZ = ZoneInfo("America/New_York")

# Daily run time in Dubai
RUN_HOUR_DUBAI = 9
RUN_MINUTE_DUBAI = 0

# Last resort only (insecure): set env ALLOW_INSECURE_SSL=1
ALLOW_INSECURE_SSL = os.environ.get("ALLOW_INSECURE_SSL", "0") == "1"


# =========================
# Helpers
# =========================

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


def now_dubai() -> datetime:
    return datetime.now(tz=DUBAI_TZ)


def ny_market_date_str() -> str:
    """Treat 'today' as New York date for US market."""
    return datetime.now(tz=NY_TZ).strftime("%Y-%m-%d")


def short_text(s: str, n: int = 260) -> str:
    s = (s or "").replace("\n", " ").replace("\r", " ")
    return s[:n] + ("..." if len(s) > n else "")


def safe_float(x) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s:
        return None
    s = s.replace("$", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def requests_verify_value():
    if ALLOW_INSECURE_SSL:
        return False

    ca_bundle = os.environ.get("REQUESTS_CA_BUNDLE")
    if ca_bundle and os.path.exists(ca_bundle):
        return ca_bundle

    ssl_cert_file = os.environ.get("SSL_CERT_FILE")
    if ssl_cert_file and os.path.exists(ssl_cert_file):
        return ssl_cert_file

    return certifi.where()


def build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


@dataclass
class FetchResult:
    source: str
    items: List[Dict[str, Any]]
    error_summary: Optional[str] = None


# =========================
# Finnhub fetcher
# =========================

def fetch_ipos_finnhub(session: requests.Session, from_date: str, to_date: str) -> FetchResult:
    verify = requests_verify_value()

    url = "https://finnhub.io/api/v1/calendar/ipo"
    params = {"from": from_date, "to": to_date, "token": FINNHUB_TOKEN}

    try:
        r = session.get(url, params=params, headers=COMMON_HEADERS, timeout=30, verify=verify)

        if r.status_code >= 400:
            return FetchResult("FINNHUB", [], f"FINNHUB HTTP {r.status_code}. Body={short_text(r.text)}")

        try:
            data = r.json()
        except Exception:
            return FetchResult("FINNHUB", [], f"FINNHUB non-JSON response. Body={short_text(r.text)}")

        if not isinstance(data, dict):
            return FetchResult("FINNHUB", [], f"FINNHUB unexpected JSON type: {type(data)}")

        calendar = data.get("ipoCalendar")
        if calendar is None:
            return FetchResult("FINNHUB", [], f"FINNHUB missing 'ipoCalendar'. Keys={list(data.keys())}")

        if not isinstance(calendar, list):
            return FetchResult("FINNHUB", [], f"FINNHUB ipoCalendar not a list: {type(calendar)}")

        items = [x for x in calendar if isinstance(x, dict)]
        return FetchResult("FINNHUB", items, None)

    except requests.exceptions.SSLError as e:
        return FetchResult("FINNHUB", [], f"FINNHUB SSL error: {e.__class__.__name__}: {short_text(str(e))}")
    except Exception as e:
        return FetchResult("FINNHUB", [], f"FINNHUB error: {e.__class__.__name__}: {short_text(str(e))}")


# =========================
# Business logic
# =========================

def compute_offer_amount(item: Dict[str, Any]) -> Tuple[Optional[float], str]:
    total = safe_float(item.get("totalSharesValue") or item.get("proceeds") or item.get("totalValue"))
    if total is not None:
        return total, "provided_total"

    price = safe_float(item.get("price") or item.get("offerPrice") or item.get("finalPrice"))
    shares = safe_float(item.get("numberOfShares") or item.get("shares") or item.get("sharesOffered"))

    if price is None or shares is None:
        return None, "missing_price_or_shares"

    return price * shares, "price_x_shares"


def filter_today_large_ipos(items: List[Dict[str, Any]], today_ny: str) -> List[Dict[str, Any]]:
    matches: List[Dict[str, Any]] = []
    for it in items:
        ipo_date = str(it.get("date") or it.get("ipoDate") or "")[:10]

        # Condition 1: today only (strict)
        if ipo_date != today_ny:
            continue

        offer_amount, method = compute_offer_amount(it)
        if offer_amount is None:
            continue

        # Condition 2: > $200M
        if offer_amount > OFFER_AMOUNT_THRESHOLD:
            ticker = it.get("symbol") or it.get("ticker") or "N/A"
            company = it.get("name") or it.get("companyName") or it.get("company") or "N/A"
            price = safe_float(it.get("price") or it.get("offerPrice") or it.get("finalPrice"))

            matches.append({
                "Ticker": str(ticker).upper(),
                "Company": company,
                "Offer Amount (USD)": f"${offer_amount:,.0f}",
                "Price": f"${price:.2f}" if price is not None else "N/A",
                "Calc Method": method,
            })
    return matches


# =========================
# Email
# =========================

def send_email(subject: str, html_body: str):
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())


def render_email(today_ny: str, matches: List[Dict[str, Any]], errors: List[str], total_items: int) -> Tuple[str, str]:
    run_ts = now_dubai().strftime("%Y-%m-%d %H:%M:%S %Z")

    error_block = ""
    if errors:
        error_block = "<h3>Errors (brief)</h3><ul>" + "".join(f"<li><code>{e}</code></li>" for e in errors) + "</ul>"

    if matches:
        subject = f"US IPOs Today > $200M — {today_ny}"
        rows = ""
        for m in matches:
            rows += (
                "<tr>"
                f"<td><b>{m['Ticker']}</b></td>"
                f"<td>{m['Company']}</td>"
                f"<td>{m['Offer Amount (USD)']}</td>"
                f"<td>{m['Price']}</td>"
                f"<td>{m['Calc Method']}</td>"
                "</tr>"
            )

        body = f"""
        <html><body>
        <h2>US IPOs Today (Offer Amount &gt; $200M)</h2>
        <p><b>US market date (NY):</b> {today_ny}<br/>
           <b>Run time (Dubai):</b> {run_ts}<br/>
           <b>IPO records returned by API:</b> {total_items}</p>

        <table border="1" style="border-collapse:collapse; width:100%;">
        <tr style="background:#4CAF50;color:white;">
            <th>Ticker</th><th>Company</th><th>Offer Amount</th><th>Price</th><th>Calc</th>
        </tr>
        {rows}
        </table>
        {error_block}
        </body></html>
        """
        return subject, body

    subject = f"No US IPOs Today > $200M — {today_ny}"
    body = f"""
    <html><body>
    <h2>No US IPOs Today Above Threshold</h2>
    <p><b>US market date (NY):</b> {today_ny}<br/>
       <b>Run time (Dubai):</b> {run_ts}<br/>
       <b>IPO records returned by API:</b> {total_items}</p>
    <p>No IPOs found with offer amount &gt; $200M.</p>
    {error_block}
    </body></html>
    """
    return subject, body


# =========================
# Main job
# =========================

def ipo_monitor_job():
    print(f"Running IPO Monitor at (Dubai): {now_dubai().isoformat(timespec='seconds')}")

    session = build_session()
    today_ny = ny_market_date_str()

    errors: List[str] = []

    # Strict: fetch only today's range
    res = fetch_ipos_finnhub(session, today_ny, today_ny)
    if res.error_summary:
        errors.append(res.error_summary)

    matches = filter_today_large_ipos(res.items, today_ny) if res.items else []
    subject, body = render_email(today_ny, matches, errors, total_items=len(res.items))

    try:
        send_email(subject, body)
        print(f"Email sent successfully at {now_dubai().isoformat(timespec='seconds')}")
    except Exception as e:
        print("Failed to send email:", e)


# =========================
# Scheduler: run every day at 9 AM Dubai
# =========================

def run_daily_9am_dubai_forever():
    """
    Keeps the script running and triggers ipo_monitor_job() once per day
    when Dubai time hits 09:00.

    This avoids timezone issues with libraries like `schedule`.
    """
    last_run_date = None
    print("Scheduler started. Will run daily at 09:00 Dubai time (Asia/Dubai). Press Ctrl+C to stop.")

    while True:
        now = now_dubai()
        if now.hour == RUN_HOUR_DUBAI and now.minute == RUN_MINUTE_DUBAI:
            if last_run_date != now.date():
                ipo_monitor_job()
                last_run_date = now.date()
                # Avoid double-run within the same minute
                time.sleep(70)
                continue

        time.sleep(20)


if __name__ == "__main__":
    # Option A: one-time run (your current usage)
    # ipo_monitor_job()

    # Option B: keep running and run every day at 9 AM Dubai time
    run_daily_9am_dubai_forever()