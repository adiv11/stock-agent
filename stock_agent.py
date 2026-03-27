"""
🌅 Indian Morning Investment Alert — v4
Data sources:
  • NSE Bhavcopy (CSV) for stock data — no rate limits
  • GoodReturns.in scraping for Gold & Silver Jaipur rates
    - Gold : https://www.goodreturns.in/gold-rates/jaipur.html
    - Silver: https://www.goodreturns.in/silver-rates/jaipur.html  ← FIXED URL
  • NSE API for index performance
  • NSE Historical API for 30-day stock trend
  • Gemini 1.5 Flash for AI analysis
"""

import os, re, smtplib, requests, time, zipfile, io, json
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
import pandas as pd
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

IST = ZoneInfo("Asia/Kolkata")

CONFIG = {
    "email_sender":   os.environ.get("GMAIL_SENDER",   "your_gmail@gmail.com"),
    "email_password": os.environ.get("GMAIL_PASSWORD", "your_app_password"),
    "email_receiver": os.environ.get("GMAIL_RECEIVER", "your_email@gmail.com"),
    "gemini_api_key": os.environ.get("GEMINI_API_KEY", "your_gemini_key"),
}

# ── Realistic browser headers to avoid 403 ──────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
    "X-Requested-With": "XMLHttpRequest",
}

# ─────────────────────────────────────────────────────────────
#  STOCK LISTS
# ─────────────────────────────────────────────────────────────
NIFTY_50 = [
    "RELIANCE","TCS","HDFCBANK","BHARTIARTL","ICICIBANK",
    "INFOSYS","SBIN","HINDUNILVR","ITC","LICI",
    "KOTAKBANK","LT","BAJFINANCE","HCLTECH","MARUTI",
    "SUNPHARMA","AXISBANK","ASIANPAINT","TITAN","ULTRACEMCO",
    "WIPRO","POWERGRID","NTPC","TECHM","NESTLEIND",
    "BAJAJFINSV","M&M","TATAMOTORS","ONGC","COALINDIA",
    "DIVISLAB","CIPLA","INDUSINDBK","JSWSTEEL","ADANIENT",
    "ADANIPORTS","HINDALCO","SBILIFE","DRREDDY","APOLLOHOSP",
    "TATACONSUM","BRITANNIA","EICHERMOT","BPCL","HDFCLIFE",
    "HEROMOTOCO","BAJAJ-AUTO","GRASIM","SHRIRAMFIN","TATASTEEL",
]
NIFTY_NEXT_50 = [
    "ADANIGREEN","ADANIPOWER","AMBUJACEM","ATGL","BANKBARODA",
    "BEL","BOSCHLTD","CANBK","CHOLAFIN","COLPAL",
    "DABUR","DLF","GODREJCP","HAVELLS","ICICIPRULI",
    "INDHOTEL","IOC","IRCTC","JINDALSTEL","JIOFIN",
    "LTIM","LUPIN","MAXHEALTH","MOTHERSON","MUTHOOTFIN",
    "NAUKRI","NMDC","OBEROIRLTY","OFSS","PAGEIND",
    "PERSISTENT","PIDILITIND","PNB","RECLTD","SIEMENS",
    "SRF","TATAELXSI","TATAPOWER","TORNTPHARM","TRENT",
    "UPL","VEDL","VOLTAS","ZYDUSLIFE","POONAWALLA",
]
NIFTY_MIDCAP = [
    "ABB","ABCAPITAL","ASTRAL","AUROPHARMA","BALKRISIND",
    "BATAINDIA","BERGEPAINT","BHARATFORG","COFORGE","CROMPTON",
    "DEEPAKNTR","DIXON","ESCORTS","EXIDEIND","FEDERALBNK",
    "GLENMARK","GODREJPROP","IDFCFIRSTB","IGL","INDIGO",
    "JUBLFOOD","KAJARIACER","KPITTECH","LAURUSLABS","LTTS",
    "MARICO","METROPOLIS","MPHASIS","MRF","POLYCAB",
]
NIFTY_SMALLCAP = [
    "AAVAS","AJANTPHARM","ALKEM","APTUS","BLUESTARCO",
    "CAMPUS","CARERATING","CEATLTD","CENTURYPLY","CRAFTSMAN",
    "CSBBANK","EASEMYTRIP","ELECON","EMCURE","ERIS",
    "FINEORG","FIRSTSOUR","FORTIS","GABRIEL","HAPPSTMNDS",
]

# ─────────────────────────────────────────────────────────────
#  SECTION 1 — NSE BHAVCOPY
# ─────────────────────────────────────────────────────────────
def get_trading_dates(n=5):
    days = []
    candidate = datetime.now(IST).date() - timedelta(days=1)
    while len(days) < n:
        if candidate.weekday() < 5:
            days.append(candidate)
        candidate -= timedelta(days=1)
    return days


def download_bhavcopy():
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com", timeout=15)
        time.sleep(2)
    except Exception:
        pass

    for date in get_trading_dates(5):
        date_str = date.strftime("%Y%m%d")
        url = (
            f"https://nsearchives.nseindia.com/content/cm/"
            f"BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
        )
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 5000:
                z = zipfile.ZipFile(io.BytesIO(resp.content))
                df = pd.read_csv(z.open(z.namelist()[0]))
                print(f"✅ Bhavcopy loaded: {date} ({len(df)} rows)")
                return df, date
        except Exception as e:
            print(f"Bhavcopy error {date}: {e}")
        time.sleep(1)

    print("❌ Could not download bhavcopy")
    return None, None


def parse_bhavcopy_columns(df):
    if df is None:
        return None, None, None, None
    cols = df.columns.tolist()
    sym   = next((c for c in cols if c.strip() in ["TckrSymb", "SYMBOL"]), None)
    close = next((c for c in cols if c.strip() in ["ClsPric", "CLOSE"]), None)
    prev  = next((c for c in cols if c.strip() in ["PrvsClsgPric", "PREVCLOSE"]), None)
    series= next((c for c in cols if c.strip() in ["SctySrs", "SERIES"]), None)
    return sym, close, prev, series


def fetch_stock_changes(tickers, df):
    if df is None:
        return []
    sym_col, close_col, prev_col, series_col = parse_bhavcopy_columns(df)
    if not all([sym_col, close_col, prev_col]):
        return []

    df_eq = df[df[series_col].str.strip() == "EQ"] if series_col else df
    df_eq = df_eq.copy()
    df_eq[sym_col] = df_eq[sym_col].str.strip()

    results = []
    for ticker in tickers:
        try:
            row = df_eq[df_eq[sym_col] == ticker]
            if row.empty:
                continue
            last = float(row[close_col].iloc[0])
            prev = float(row[prev_col].iloc[0])
            if prev == 0:
                continue
            pct = ((last - prev) / prev) * 100
            results.append({
                "ticker": ticker,
                "prev_close": round(prev, 2),
                "last_close": round(last, 2),
                "pct_change": round(pct, 2),
            })
        except Exception:
            continue
    return sorted(results, key=lambda x: x["pct_change"])


# ─────────────────────────────────────────────────────────────
#  SECTION 2 — NSE HISTORICAL TREND (30-day) FOR STOCKS
# ─────────────────────────────────────────────────────────────
def get_stock_historical_trend(ticker, session=None):
    """
    Fetch last 30 calendar days of OHLCV from NSE historical API.
    Returns a dict with trend summary, 52w high/low, avg, slope direction.
    """
    if session is None:
        session = requests.Session()
        session.headers.update(NSE_HEADERS)
        try:
            session.get("https://www.nseindia.com", timeout=10)
            time.sleep(1)
        except Exception:
            pass

    end_dt   = datetime.now(IST).date()
    start_dt = end_dt - timedelta(days=45)   # fetch 45 days, use last 30 trading
    end_str  = end_dt.strftime("%d-%m-%Y")
    start_str= start_dt.strftime("%d-%m-%Y")

    url = (
        f"https://www.nseindia.com/api/historical/cm/equity"
        f"?symbol={ticker}&series=[%22EQ%22]"
        f"&from={start_str}&to={end_str}"
    )
    try:
        resp = session.get(url, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", [])
        if len(data) < 5:
            return None

        closes = [float(d["CH_CLOSING_PRICE"]) for d in data if d.get("CH_CLOSING_PRICE")]
        highs  = [float(d["CH_TRADE_HIGH_PRICE"]) for d in data if d.get("CH_TRADE_HIGH_PRICE")]
        lows   = [float(d["CH_TRADE_LOW_PRICE"])  for d in data if d.get("CH_TRADE_LOW_PRICE")]

        if not closes:
            return None

        current   = closes[-1]
        oldest    = closes[0]
        high_30   = max(highs)
        low_30    = min(lows)
        avg_30    = round(sum(closes) / len(closes), 2)
        change_30d= round(((current - oldest) / oldest) * 100, 2) if oldest else 0

        # Simple linear slope: compare first-half avg vs second-half avg
        mid = len(closes) // 2
        first_half_avg  = sum(closes[:mid]) / mid if mid else current
        second_half_avg = sum(closes[mid:]) / (len(closes) - mid) if (len(closes) - mid) else current
        if second_half_avg > first_half_avg * 1.01:
            trend_dir = "UPTREND 📈"
        elif second_half_avg < first_half_avg * 0.99:
            trend_dir = "DOWNTREND 📉"
        else:
            trend_dir = "SIDEWAYS ➡️"

        # Is current price near 30d low? (potential buy zone)
        near_low  = current <= low_30  * 1.05   # within 5% of 30d low
        near_high = current >= high_30 * 0.95   # within 5% of 30d high

        buy_signal = "🟢 Near 30d Low — Potential Support" if near_low else (
                     "🔴 Near 30d High — May Face Resistance" if near_high else
                     "🟡 Mid-range — Neutral Zone")

        return {
            "trend_dir":    trend_dir,
            "change_30d":   change_30d,
            "high_30d":     round(high_30, 2),
            "low_30d":      round(low_30, 2),
            "avg_30d":      avg_30,
            "buy_signal":   buy_signal,
            "data_points":  len(closes),
        }
    except Exception as e:
        print(f"  History error {ticker}: {e}")
        return None


def enrich_top_fallers_with_trend(falling_dict, top_n=5):
    """
    Pick the top N fallers across ALL categories, fetch their 30d history,
    and annotate each with trend info.
    """
    all_fallers = []
    for cat, stocks in falling_dict.items():
        for s in stocks:
            s["category"] = cat
            all_fallers.append(s)

    # Sort by worst % change, pick top_n
    top_fallers = sorted(all_fallers, key=lambda x: x["pct_change"])[:top_n]

    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com", timeout=10)
        time.sleep(1)
    except Exception:
        pass

    for stock in top_fallers:
        print(f"  📊 Fetching 30d trend: {stock['ticker']}...")
        trend = get_stock_historical_trend(stock["ticker"], session)
        stock["trend"] = trend
        time.sleep(0.8)   # polite crawl delay

    return top_fallers


# ─────────────────────────────────────────────────────────────
#  SECTION 3 — INDEX PERFORMANCE
# ─────────────────────────────────────────────────────────────
def get_index_performance():
    result = {}
    try:
        session = requests.Session()
        session.headers.update(NSE_HEADERS)
        session.get("https://www.nseindia.com", timeout=15)
        time.sleep(2)
        resp = session.get("https://www.nseindia.com/api/allIndices", timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            targets = {
                "NIFTY 50":        "Nifty 50",
                "NIFTY BANK":      "Nifty Bank",
                "NIFTY NEXT 50":   "Nifty Next 50",
                "NIFTY MIDCAP 50": "Nifty Midcap",
            }
            for item in data.get("data", []):
                name = item.get("index", "").strip()
                if name in targets:
                    last = float(item.get("last", 0))
                    prev = float(item.get("previousClose", 1))
                    result[targets[name]] = {
                        "value":  round(last, 2),
                        "change": round(float(item.get("percentChange", 0)), 2),
                        "points": round(last - prev, 2),
                    }
    except Exception as e:
        print(f"Index fetch error: {e}")
    return result


# ─────────────────────────────────────────────────────────────
#  SECTION 4 — GOLD & SILVER (GoodReturns scraping — FIXED)
# ─────────────────────────────────────────────────────────────
def _make_goodreturns_session():
    """Create a session that mimics a real browser visit."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9,hi;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
    })
    # Warm-up visit to homepage (sets cookies)
    try:
        s.get("https://www.goodreturns.in/", timeout=15)
        time.sleep(1.5)
    except Exception:
        pass
    return s


def _clean_price(text):
    """Strip commas, ₹ symbols, whitespace; return float or None."""
    cleaned = re.sub(r"[₹,\s]", "", text.strip())
    try:
        val = float(cleaned)
        return val if val > 0 else None
    except ValueError:
        return None


def _extract_rate_from_soup(soup, karat_hint=None):
    """
    Multi-strategy extractor for GoodReturns rate pages.
    Tries <table>, then structured <div>, then raw text regex.
    Returns (rate_per_10g_or_kg, change_pct) or (None, None).
    """
    # ── Strategy 1: Look for the main rate table ──────────────
    # GoodReturns uses tables with class "gold-silver-table", "table-rate", etc.
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        header_text = " ".join(headers)
        # Check if this table is about rates
        if not any(k in header_text for k in ["gram", "rate", "price", "today", "karat", "kg"]):
            continue
        for row in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 2:
                continue
            row_text = " ".join(cells).lower()
            if karat_hint and karat_hint.lower() not in row_text:
                continue
            # Find the first cell that looks like a price (5-7 digit number)
            for cell in cells[1:]:
                val = _clean_price(cell)
                if val and 5000 < val < 2_000_000:
                    return val, None

    # ── Strategy 2: Look for rate inside <span> or <div> with class patterns ──
    rate_classes = [
        "gold-rate", "silver-rate", "rate-price", "price-value",
        "gld_txt", "sylvr_txt", "today-rate", "current-rate",
        "rupee", "rate", "price"
    ]
    for cls in rate_classes:
        for tag in soup.find_all(class_=re.compile(cls, re.I)):
            val = _clean_price(tag.get_text())
            if val and 5000 < val < 2_000_000:
                return val, None

    # ── Strategy 3: Structured data (JSON-LD) ──────────────────
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            for key in ["price", "lowPrice", "highPrice"]:
                if key in data:
                    val = float(data[key])
                    if 5000 < val < 2_000_000:
                        return val, None
        except Exception:
            pass

    # ── Strategy 4: Fallback broad regex on full page text ─────
    page_text = soup.get_text(" ", strip=True)
    # Look for patterns like "₹9,450" or "9,450" near karat hint
    if karat_hint:
        # Find positions of the karat hint
        pattern = rf"{re.escape(karat_hint)}.{{0,80}}?(\d{{1,3}}(?:,\d{{3}})+(?:\.\d{{1,2}})?)"
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            val = _clean_price(match.group(1))
            if val and 5000 < val < 2_000_000:
                return val, None

    # Broad: any 5-6 digit number in a realistic range
    candidates = re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?)(?!\d)", page_text)
    found = []
    for c in candidates:
        val = _clean_price(c)
        if val:
            found.append(val)

    return None, None


def _extract_change_pct(soup):
    """Extract the day's % change from the page."""
    page_text = soup.get_text(" ", strip=True)
    # Look for patterns like "+0.25%" or "-1.2%" or "0.30%"
    for m in re.finditer(r"([+\-]?\d{1,2}\.\d{1,3})\s*%", page_text):
        val = float(m.group(1))
        if -15 < val < 15 and val != 0:
            return round(val, 2)
    return None


def get_gold_silver_prices():
    """
    Fetch Jaipur Gold & Silver rates from GoodReturns.
    Uses correct URLs:
      Gold  : https://www.goodreturns.in/gold-rates/jaipur.html
      Silver: https://www.goodreturns.in/silver-rates/jaipur.html   ← note 'rates'
    """
    result = {
        "gold_jaipur_22k":    None,
        "gold_jaipur_24k":    None,
        "silver_jaipur_kg":   None,
        "gold_change_pct":    None,
        "silver_change_pct":  None,
        "fetch_status":       {},
    }

    session = _make_goodreturns_session()

    # ── GOLD ─────────────────────────────────────────────────
    gold_url = "https://www.goodreturns.in/gold-rates/jaipur.html"
    print(f"  🥇 Fetching gold: {gold_url}")
    try:
        r = session.get(gold_url, timeout=25)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        result["fetch_status"]["gold_http"] = r.status_code

        # Try to find 22K and 24K separately
        gold22, _ = _extract_rate_from_soup(soup, karat_hint="22")
        gold24, _ = _extract_rate_from_soup(soup, karat_hint="24")
        chg       = _extract_change_pct(soup)

        # Sanity check: 22K should be ~91.7% of 24K; both in plausible range
        if gold22 and 40_000 < gold22 < 1_50_000:
            result["gold_jaipur_22k"] = round(gold22, 0)
        if gold24 and 40_000 < gold24 < 1_80_000:
            result["gold_jaipur_24k"] = round(gold24, 0)
        # If one is missing, derive the other
        if result["gold_jaipur_22k"] and not result["gold_jaipur_24k"]:
            result["gold_jaipur_24k"] = round(result["gold_jaipur_22k"] / 0.916 * 0.9999, 0)
        if result["gold_jaipur_24k"] and not result["gold_jaipur_22k"]:
            result["gold_jaipur_22k"] = round(result["gold_jaipur_24k"] * 0.916, 0)
        if chg:
            result["gold_change_pct"] = chg

        print(f"  ✅ Gold 22K={result['gold_jaipur_22k']} 24K={result['gold_jaipur_24k']} Δ={chg}%")
    except Exception as e:
        result["fetch_status"]["gold_error"] = str(e)
        print(f"  ❌ Gold fetch error: {e}")

    time.sleep(2)

    # ── SILVER ──────────────────────────────────────────────
    # Correct URL uses "silver-rates" (plural), not "silver-rate"
    silver_url = "https://www.goodreturns.in/silver-rates/jaipur.html"
    print(f"  🥈 Fetching silver: {silver_url}")
    try:
        r2 = session.get(silver_url, timeout=25)
        r2.raise_for_status()
        soup2 = BeautifulSoup(r2.text, "lxml")
        result["fetch_status"]["silver_http"] = r2.status_code

        # Silver is quoted per kg; plausible range 70,000–2,00,000 INR/kg
        silver_kg, _ = _extract_rate_from_soup(soup2, karat_hint="kg")
        if not silver_kg:
            silver_kg, _ = _extract_rate_from_soup(soup2)   # try without hint
        chg2 = _extract_change_pct(soup2)

        if silver_kg and 70_000 < silver_kg < 2_50_000:
            result["silver_jaipur_kg"] = round(silver_kg, 0)
        if chg2:
            result["silver_change_pct"] = chg2

        print(f"  ✅ Silver/kg={result['silver_jaipur_kg']} Δ={chg2}%")
    except Exception as e:
        result["fetch_status"]["silver_error"] = str(e)
        print(f"  ❌ Silver fetch error: {e}")

    return result


# ─────────────────────────────────────────────────────────────
#  SECTION 5 — DIVERSIFICATION DATA
# ─────────────────────────────────────────────────────────────
DIVERSIFICATION_WATCHLIST = {
    "ETFs (like a basket of stocks — easy & low cost)": [
        ("NIFTYBEES",  "Nifty 50 ETF",       "Tracks the top 50 companies. Best starting point for beginners."),
        ("GOLDBEES",   "Gold ETF",            "Invest in gold without buying physical gold. Safe haven."),
        ("JUNIORBEES", "Next 50 ETF",         "Tracks the next 50 large companies after Nifty 50."),
        ("SILVERBEES", "Silver ETF",          "Invest in silver digitally — no locker needed."),
        ("MOM100",     "Momentum 100 ETF",    "Invests in 100 stocks with strong recent price momentum."),
    ],
    "REITs (earn rental income without buying property)": [
        ("EMBASSY",   "Embassy Office Parks REIT",     "India's largest REIT. Owns premium offices in Bengaluru, Mumbai."),
        ("MINDSPACE", "Mindspace Business Parks REIT", "Office parks REIT. Pays quarterly rental income."),
        ("NEXUS",     "Nexus Select Trust REIT",       "India's first retail (malls) REIT. Dividend income."),
    ],
    "InvITs (earn from infrastructure like roads, power lines)": [
        ("INDIGRID", "IndiGrid InvIT", "Power transmission towers. Steady quarterly income."),
        ("IRB",      "IRB InvIT",      "Highway toll roads. Income from tolls you pay on highways."),
    ],
}


def fetch_diversification_data(df):
    output = {}
    sym_col, close_col, prev_col, _ = parse_bhavcopy_columns(df)
    for category, items in DIVERSIFICATION_WATCHLIST.items():
        cat_results = []
        for ticker, name, description in items:
            entry = {"symbol": ticker, "name": name, "description": description,
                     "price": None, "pct_change": None}
            if df is not None and sym_col and close_col and prev_col:
                try:
                    df_copy = df.copy()
                    df_copy[sym_col] = df_copy[sym_col].str.strip()
                    row = df_copy[df_copy[sym_col] == ticker]
                    if not row.empty:
                        last = float(row[close_col].iloc[0])
                        prev = float(row[prev_col].iloc[0])
                        pct  = round(((last - prev) / prev) * 100, 2) if prev else None
                        entry["price"]      = round(last, 2)
                        entry["pct_change"] = pct
                except Exception:
                    pass
            cat_results.append(entry)
        output[category] = cat_results
    return output


# ─────────────────────────────────────────────────────────────
#  SECTION 6 — GEMINI AI ANALYSIS (enhanced with trend context)
# ─────────────────────────────────────────────────────────────
def _build_stock_trend_lines(enriched_fallers):
    """Format enriched faller data for the AI prompt."""
    lines = []
    for s in enriched_fallers:
        t = s.get("trend")
        base = (
            f"  {s['ticker']} ({s.get('category','?')}): "
            f"fell {abs(s['pct_change']):.1f}% to ₹{s['last_close']}"
        )
        if t:
            base += (
                f" | 30d trend: {t['trend_dir']} | "
                f"30d change: {t['change_30d']:+.1f}% | "
                f"30d range: ₹{t['low_30d']}–₹{t['high_30d']} | "
                f"Avg: ₹{t['avg_30d']} | {t['buy_signal']}"
            )
        lines.append(base)
    return "\n".join(lines) if lines else "  No major fallers data."


def get_ai_analysis(index_perf, falling_stocks, gold_silver, div_data, enriched_fallers):
    client = genai.Client(api_key=CONFIG["gemini_api_key"])

    index_lines = "\n".join([
        f"  {k}: {v['change']:+.2f}% (now at {v['value']:,.0f})"
        for k, v in index_perf.items()
    ]) or "  Data unavailable"

    stock_trend_lines = _build_stock_trend_lines(enriched_fallers)

    gs = gold_silver
    gold_22k   = gs.get("gold_jaipur_22k")
    gold_24k   = gs.get("gold_jaipur_24k")
    silver_kg  = gs.get("silver_jaipur_kg")
    gold_chg   = gs.get("gold_change_pct")
    silver_chg = gs.get("silver_change_pct")

    gold_line   = (
        f"Gold Jaipur — 22K: ₹{gold_22k:,.0f}/10g | 24K: ₹{gold_24k:,.0f}/10g"
        f"{f' | Change: {gold_chg:+.2f}%' if gold_chg is not None else ''}"
        if gold_22k else "Gold: data unavailable"
    )
    silver_line = (
        f"Silver Jaipur — ₹{silver_kg:,.0f}/kg"
        f"{f' | Change: {silver_chg:+.2f}%' if silver_chg is not None else ''}"
        if silver_kg else "Silver: data unavailable"
    )

    today = datetime.now(IST).strftime("%d %B %Y")

    prompt = f"""
Today is {today}. You are writing a friendly morning investment update for a complete beginner in Jaipur, India.
Use simple plain-English — NO jargon. Write like you're texting a smart friend, not a finance textbook.

=== MARKET DATA ===

STOCK INDICES (yesterday's change):
{index_lines}

TOP FALLING STOCKS WITH 30-DAY TREND ANALYSIS:
{stock_trend_lines}

GOLD & SILVER — LIVE JAIPUR RATES:
{gold_line}
{silver_line}

=== YOUR TASK ===

Write EXACTLY these 6 sections. Keep each SHORT (3–5 lines). NO bullet points — short sentences only.

== WHY DID THE MARKET MOVE? ==
In 3 simple sentences explain what probably caused yesterday's move. Mention global cues briefly if relevant.

== TOP FALLING STOCKS — BUY, WAIT, OR AVOID? ==
For EACH stock in the "TOP FALLING STOCKS" list above, give a one-line verdict:
  • Is it a good BUY at this level? (use the 30-day trend + current price vs avg/range)
  • Or should the beginner WAIT for further correction?
  • Or AVOID (if trend is clearly broken)?
Use the 30d data to justify your verdict. Be specific — mention the stock name and price.

== GOLD & SILVER — INVEST NOW OR WAIT? ==
Based on the live rates above:
  - Is gold at 22K ₹X,XXX/10g a good entry point today, or is it near a recent high?
  - Is silver at ₹X,XXX/kg attractive, or should you wait?
  - For each: state clearly → "Good time to add a small amount" OR "Wait for a dip to ₹X,XXX".
  - Mention whether Gold ETF (GOLDBEES) or physical gold makes more sense for a beginner right now.

== TODAY'S SIMPLE INVESTMENT TIP ==
ONE specific actionable tip for someone with ₹1,000–₹10,000. Name the exact instrument (ETF ticker, stock, SGB, etc.).

== MARKET MOOD & SHORT-TERM OUTLOOK ==
Two sentences: what to expect in the next 2–3 trading sessions. Mention any key support/resistance levels simply.

== BEGINNER'S 3-STEP ACTION PLAN FOR THIS WEEK ==
Give exactly 3 steps (numbered 1, 2, 3), each a single sentence. Make them concrete and doable.

Tone: warm, encouraging, honest. Never sensationalise. Never promise returns.
"""

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.35,
                max_output_tokens=1400,
            ),
        )
        return response.text if response.text else _fallback_analysis(
            index_perf, enriched_fallers, gold_silver
        )
    except Exception as e:
        print(f"Gemini error: {e}")
        return _fallback_analysis(index_perf, enriched_fallers, gold_silver)


def _fallback_analysis(index_perf, enriched_fallers, gold_silver):
    """Pure-Python fallback when Gemini is unavailable."""
    nifty = index_perf.get("Nifty 50", {})
    chg   = nifty.get("change", 0)

    if chg < -1.5:
        why  = f"The market had a rough day, Nifty down {abs(chg):.2f}%. This often happens on global sell-offs or FII outflows. Dips like this are normal and can be buying opportunities."
        mood = "Market may open cautiously today — watch for recovery signals."
    elif chg < 0:
        why  = f"Nifty slipped {abs(chg):.2f}% — a small, healthy correction. Nothing alarming here."
        mood = "Likely to start steady today."
    else:
        why  = f"Markets rose {chg:.2f}% — positive sentiment and broad-based buying."
        mood = "Likely to continue steady or slightly positive today."

    stock_verdicts = []
    for s in enriched_fallers[:5]:
        t = s.get("trend")
        if t:
            if t["buy_signal"].startswith("🟢") and t["change_30d"] > -15:
                verdict = f"{s['ticker']}: Near 30d low at ₹{s['last_close']} — consider a small buy."
            elif t["trend_dir"].startswith("DOWNTREND") and t["change_30d"] < -10:
                verdict = f"{s['ticker']}: Downtrend in place ({t['change_30d']:.1f}% in 30d) — wait for trend reversal before buying."
            else:
                verdict = f"{s['ticker']}: Fell {abs(s['pct_change']):.1f}% today, mid-range in 30d trend — cautious buy or wait."
        else:
            verdict = f"{s['ticker']}: Fell {abs(s['pct_change']):.1f}% — check chart before buying."
        stock_verdicts.append(verdict)

    gs = gold_silver
    gold_note = "Gold data unavailable."
    if gs.get("gold_jaipur_22k"):
        gold_note = (
            f"Gold 22K in Jaipur is ₹{gs['gold_jaipur_22k']:,.0f}/10g today. "
            "For a beginner, a Gold ETF like GOLDBEES is better than physical gold — "
            "no making charges, easy to buy/sell on Groww or Zerodha."
        )
    silver_note = ""
    if gs.get("silver_jaipur_kg"):
        silver_note = (
            f" Silver is at ₹{gs['silver_jaipur_kg']:,.0f}/kg — "
            "SILVERBEES ETF lets you invest with just ₹500."
        )

    stocks_text = "\n".join(stock_verdicts) or "No significant fallers today."

    return f"""== WHY DID THE MARKET MOVE? ==
{why}

== TOP FALLING STOCKS — BUY, WAIT, OR AVOID? ==
{stocks_text}

== GOLD & SILVER — INVEST NOW OR WAIT? ==
{gold_note}{silver_note}
Sovereign Gold Bonds (SGB) remain the best long-term gold option — they pay 2.5% annual interest over the gold price gain.

== TODAY'S SIMPLE INVESTMENT TIP ==
Start or top up a monthly SIP of ₹1,000 in NIFTYBEES (Nifty 50 ETF) via Groww or Zerodha. Set it once, let it run automatically.

== MARKET MOOD & SHORT-TERM OUTLOOK ==
{mood} Keep a watchlist ready — if Nifty holds above its recent support, a bounce is likely within 2–3 sessions.

== BEGINNER'S 3-STEP ACTION PLAN FOR THIS WEEK ==
1. Check if your existing SIP is running — don't pause it during dips, that's when it buys cheap.
2. If you have ₹2,000–₹5,000 free, consider adding to NIFTYBEES or GOLDBEES in small lots.
3. Don't check your portfolio more than once a day — short-term noise causes panic selling."""


# ─────────────────────────────────────────────────────────────
#  EMAIL BUILDER
# ─────────────────────────────────────────────────────────────
def pct_badge(pct):
    if pct is None:
        return '<span style="color:#888;font-size:12px">No data</span>'
    color = "#c0392b" if pct < 0 else "#27ae60"
    arrow = "▼" if pct < 0 else "▲"
    return f'<span style="color:{color};font-weight:bold">{arrow} {abs(pct):.2f}%</span>'


def stock_table(stocks, threshold):
    filtered = [s for s in stocks if s["pct_change"] <= threshold]
    if not filtered:
        top_fallers = sorted(stocks, key=lambda x: x["pct_change"])[:5]
        if not top_fallers:
            return '<p style="color:#27ae60;font-size:13px;margin:6px 0">✅ No data available.</p>'
        note = f'<p style="color:#27ae60;font-size:12px;margin:0 0 6px">✅ No stocks fell beyond {abs(threshold)}% — showing top 5 movers.</p>'
        display = top_fallers
    else:
        note = ""
        display = filtered

    rows = "".join(f"""
    <tr style="border-bottom:1px solid #fce8e8">
      <td style="padding:8px 10px;font-weight:600;font-size:13px">{s['ticker']}</td>
      <td style="padding:8px 10px;font-size:13px;text-align:right">₹{s['last_close']:,.2f}</td>
      <td style="padding:8px 10px;text-align:right">{pct_badge(s['pct_change'])}</td>
      <td style="padding:8px 10px;font-size:12px;color:#888;text-align:right">was ₹{s['prev_close']:,.2f}</td>
    </tr>""" for s in display)

    return note + f"""
    <table style="width:100%;border-collapse:collapse;margin-top:4px">
      <tr style="background:#c0392b;color:white;font-size:12px">
        <th style="padding:8px 10px;text-align:left">Stock</th>
        <th style="padding:8px 10px;text-align:right">Price</th>
        <th style="padding:8px 10px;text-align:right">Change</th>
        <th style="padding:8px 10px;text-align:right">Previous</th>
      </tr>{rows}
    </table>"""


def enriched_faller_table(enriched_fallers):
    """Detailed table for top N fallers with 30d trend data."""
    if not enriched_fallers:
        return "<p style='color:#888;font-size:13px'>No enriched faller data available.</p>"

    rows = ""
    for s in enriched_fallers:
        t = s.get("trend")
        trend_html = ""
        if t:
            dir_color = "#27ae60" if "UP" in t["trend_dir"] else (
                        "#c0392b" if "DOWN" in t["trend_dir"] else "#e67e22")
            signal_color = "#27ae60" if "🟢" in t["buy_signal"] else (
                           "#c0392b" if "🔴" in t["buy_signal"] else "#e67e22")
            trend_html = f"""
              <div style="font-size:11px;margin-top:4px;color:#555;line-height:1.7">
                <span style="color:{dir_color};font-weight:600">{t['trend_dir']}</span>
                &nbsp;|&nbsp; 30d: <b>{t['change_30d']:+.1f}%</b>
                &nbsp;|&nbsp; Range: ₹{t['low_30d']:,.0f}–₹{t['high_30d']:,.0f}
                &nbsp;|&nbsp; Avg: ₹{t['avg_30d']:,.0f}<br>
                <span style="color:{signal_color}">{t['buy_signal']}</span>
              </div>"""
        else:
            trend_html = '<div style="font-size:11px;color:#aaa;margin-top:3px">Trend data unavailable</div>'

        rows += f"""
        <tr style="border-bottom:1px solid #fce8e8;vertical-align:top">
          <td style="padding:10px 12px">
            <div style="font-weight:700;font-size:14px;color:#c0392b">{s['ticker']}</div>
            <div style="font-size:11px;color:#888">{s.get('category','').replace('_',' ').title()}</div>
          </td>
          <td style="padding:10px 12px;text-align:right">
            <div style="font-size:14px;font-weight:bold">₹{s['last_close']:,.2f}</div>
            <div style="font-size:11px;color:#888">was ₹{s['prev_close']:,.2f}</div>
          </td>
          <td style="padding:10px 12px;text-align:right">{pct_badge(s['pct_change'])}</td>
          <td style="padding:10px 12px">{trend_html}</td>
        </tr>"""

    return f"""
    <table style="width:100%;border-collapse:collapse;margin-top:6px">
      <tr style="background:#8e1a0e;color:white;font-size:11px">
        <th style="padding:8px 12px;text-align:left">Stock</th>
        <th style="padding:8px 12px;text-align:right">Price</th>
        <th style="padding:8px 12px;text-align:right">Today</th>
        <th style="padding:8px 12px;text-align:left">30-Day Trend</th>
      </tr>{rows}
    </table>"""


def gold_silver_section(gs):
    def row(label, value, change, note=""):
        badge = pct_badge(change)
        return f"""
        <tr style="border-bottom:1px solid #f5f0e8">
          <td style="padding:10px 12px;font-weight:600;font-size:13px">{label}</td>
          <td style="padding:10px 12px;font-size:15px;font-weight:bold;color:#b8860b">
            {f'₹{value:,.0f}' if value else '—'}
          </td>
          <td style="padding:10px 12px">{badge}</td>
          <td style="padding:10px 12px;font-size:11px;color:#888">{note}</td>
        </tr>"""

    return f"""
    <table style="width:100%;border-collapse:collapse;margin-top:8px">
      <tr style="background:#b8860b;color:white;font-size:12px">
        <th style="padding:8px 12px;text-align:left">Metal</th>
        <th style="padding:8px 12px;text-align:left">Rate</th>
        <th style="padding:8px 12px;text-align:left">Change</th>
        <th style="padding:8px 12px;text-align:left">Note</th>
      </tr>
      {row("Gold 22K (Jaipur)", gs.get("gold_jaipur_22k"), gs.get("gold_change_pct"), "Per 10g · retail")}
      {row("Gold 24K (Jaipur)", gs.get("gold_jaipur_24k"), gs.get("gold_change_pct"), "Per 10g · retail")}
      {row("Silver (Jaipur)",   gs.get("silver_jaipur_kg"), gs.get("silver_change_pct"), "Per kg · retail")}
    </table>
    <p style="font-size:11px;color:#aaa;margin:6px 0 0">
      ⚠️ Rates from GoodReturns.in — confirm with your local jeweller before buying.
      Source: <a href="https://www.goodreturns.in/gold-rates/jaipur.html" style="color:#b8860b">Gold</a> ·
      <a href="https://www.goodreturns.in/silver-rates/jaipur.html" style="color:#888">Silver</a>
    </p>"""


def diversification_section(div_data):
    html = ""
    icons = {"ETFs": "📦", "REITs": "🏢", "InvITs": "🏗️"}
    for category, items in div_data.items():
        icon = next((v for k, v in icons.items() if k in category), "💡")
        rows = ""
        for item in items:
            price_str = f"₹{item['price']:,.2f}" if item["price"] else "—"
            rows += f"""
            <tr style="border-bottom:1px solid #eef4ff">
              <td style="padding:9px 10px">
                <div style="font-weight:600;font-size:13px;color:#2c3e50">{item['name']}</div>
                <div style="font-size:11px;color:#888;margin-top:2px">{item['description']}</div>
              </td>
              <td style="padding:9px 10px;text-align:right;font-size:13px;font-weight:bold">{price_str}</td>
              <td style="padding:9px 10px;text-align:right">{pct_badge(item['pct_change'])}</td>
            </tr>"""
        html += f"""
        <div style="margin-top:20px">
          <div style="font-size:14px;font-weight:600;color:#1a3a6b;margin-bottom:6px">{icon} {category}</div>
          <table style="width:100%;border-collapse:collapse">
            <tr style="background:#1a3a6b;color:white;font-size:11px">
              <th style="padding:7px 10px;text-align:left">Option</th>
              <th style="padding:7px 10px;text-align:right">Price</th>
              <th style="padding:7px 10px;text-align:right">Change</th>
            </tr>{rows}
          </table>
        </div>"""
    return html


def parse_ai_sections(text):
    sections = {
        "WHY DID THE MARKET MOVE?":               ("📰", "#8e44ad"),
        "TOP FALLING STOCKS — BUY, WAIT, OR AVOID?": ("🎯", "#c0392b"),
        "GOLD & SILVER — INVEST NOW OR WAIT?":    ("🥇", "#b8860b"),
        "TODAY'S SIMPLE INVESTMENT TIP":          ("💡", "#27ae60"),
        "MARKET MOOD & SHORT-TERM OUTLOOK":       ("🔮", "#2980b9"),
        "BEGINNER'S 3-STEP ACTION PLAN FOR THIS WEEK": ("📋", "#16a085"),
    }
    html = ""
    for title, (icon, color) in sections.items():
        pattern = rf"==\s*{re.escape(title)}\s*=="
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            start = match.end()
            next_match = re.search(r"==\s*[A-Z]", text[start:], re.IGNORECASE)
            content = text[start: start + next_match.start()].strip() if next_match else text[start:].strip()
            content_html = "".join(
                f'<p style="margin:5px 0;font-size:13px;line-height:1.7;color:#333">{line}</p>'
                for line in content.split("\n") if line.strip()
            )
            html += f"""
            <div style="margin-bottom:16px;padding:14px 16px;background:#fafafa;
                        border-left:4px solid {color};border-radius:0 8px 8px 0">
              <div style="font-size:13px;font-weight:600;color:{color};margin-bottom:6px">
                {icon} {title.title()}
              </div>
              {content_html}
            </div>"""
    if not html:
        html = f'<p style="font-size:13px;color:#333;line-height:1.7">{text}</p>'
    return html


def build_email(index_perf, falling, gold_silver, div_data, enriched_fallers,
                ai_text, trade_date):
    today     = datetime.now(IST).strftime("%A, %d %B %Y")
    nifty_chg = index_perf.get("Nifty 50", {}).get("change", 0)
    bearish   = nifty_chg < 0
    hdr_color = "#b83232" if bearish else "#1e7e34"
    mood      = "BEARISH 🔴 — Falling Day" if bearish else "BULLISH 🟢 — Rising Day"
    data_date = trade_date.strftime("%d %b %Y") if trade_date else "Latest available"

    cards = ""
    for name, d in index_perf.items():
        c = "#c0392b" if d["change"] < 0 else "#27ae60"
        a = "▼" if d["change"] < 0 else "▲"
        cards += f"""
        <div style="flex:1;min-width:130px;background:white;border:1px solid {c};
                    border-radius:8px;padding:12px;text-align:center">
          <div style="font-size:11px;color:#666;margin-bottom:3px">{name}</div>
          <div style="font-size:17px;font-weight:bold;color:#222">{d['value']:,.0f}</div>
          <div style="font-size:13px;font-weight:bold;color:{c}">{a} {abs(d['change']):.2f}%</div>
        </div>"""

    ai_html = parse_ai_sections(ai_text)

    fetch_notes = ""
    fs = gold_silver.get("fetch_status", {})
    if fs:
        fetch_notes = (
            f'<p style="font-size:10px;color:#bbb;margin:4px 0">'
            f'Gold HTTP {fs.get("gold_http","—")} · Silver HTTP {fs.get("silver_http","—")}'
            f'</p>'
        )

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif">
<div style="max-width:700px;margin:16px auto;background:white;border-radius:14px;
            overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.10)">

  <div style="background:{hdr_color};padding:22px 28px;color:white">
    <div style="font-size:12px;opacity:.8;margin-bottom:4px">📅 {today} | Your Morning Investment Brief</div>
    <div style="font-size:22px;font-weight:700">Market is {mood}</div>
    <div style="font-size:12px;margin-top:6px;opacity:.85">
      Nifty 50: {nifty_chg:+.2f}% &nbsp;|&nbsp; Data: {data_date} &nbsp;|&nbsp; Jaipur, Rajasthan
    </div>
  </div>

  <div style="background:#fffbe6;padding:10px 28px;border-bottom:1px solid #ffe082;
              font-size:12px;color:#7a5c00">
    👋 <strong>New to investing?</strong> ▼ = price fell &nbsp;·&nbsp; ▲ = price rose.
    You don't need to act on everything — just read and learn!
  </div>

  <div style="padding:22px 28px">

    <h2 style="font-size:15px;color:#2c3e50;margin:0 0 10px">📊 Yesterday's Big Picture</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:22px">{cards}</div>

    <h2 style="font-size:15px;color:#b8860b;margin:0 0 4px">🥇 Gold & Silver — Live Jaipur Rates</h2>
    <p style="font-size:12px;color:#888;margin:0 0 8px">
      Updated from GoodReturns.in — Jaipur local market rates.
    </p>
    {gold_silver_section(gold_silver)}
    {fetch_notes}

    <h2 style="font-size:15px;color:#8e1a0e;margin:22px 0 4px">
      🔍 Top Falling Stocks — With 30-Day Trend Analysis
    </h2>
    <p style="font-size:12px;color:#888;margin:0 0 8px">
      Each stock shows today's fall PLUS its 30-day price trend — so you can judge whether it's a dip to buy or a fall to avoid.
    </p>
    {enriched_faller_table(enriched_fallers)}

    <h2 style="font-size:15px;color:#2c3e50;margin:22px 0 4px">📉 All Falling Stocks by Category</h2>

    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#c0392b;margin-bottom:4px">🔴 Nifty 50 — fell more than 2%</div>
      {stock_table(falling.get("nifty50", []), -2)}
    </div>
    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#e67e22;margin-bottom:4px">🟠 Next 50 — fell more than 2%</div>
      {stock_table(falling.get("next50", []), -2)}
    </div>
    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#2980b9;margin-bottom:4px">🔵 Midcap — fell more than 3%</div>
      {stock_table(falling.get("midcap", []), -3)}
    </div>
    <div style="margin-bottom:22px">
      <div style="font-size:13px;font-weight:600;color:#8e44ad;margin-bottom:4px">🟣 Smallcap — fell more than 3%</div>
      {stock_table(falling.get("smallcap", []), -3)}
    </div>

    <h2 style="font-size:15px;color:#1a3a6b;margin:0 0 4px">🌈 Other Ways to Invest — Not Just Stocks</h2>
    <p style="font-size:12px;color:#888;margin:0 0 8px">
      All can be bought from your Zerodha / Groww / Upstox app.
    </p>
    {diversification_section(div_data)}

    <div style="margin-top:22px;background:#f0f4ff;border-radius:8px;padding:14px 16px">
      <div style="font-size:13px;font-weight:600;color:#1a3a6b;margin-bottom:8px">📖 Quick Glossary</div>
      <div style="font-size:12px;color:#444;line-height:2">
        <b>ETF</b> = A basket of stocks you buy in one click. Like buying a thali instead of cooking each dish.<br>
        <b>REIT</b> = You own a tiny part of office buildings and earn rent every 3 months.<br>
        <b>InvIT</b> = Same idea but for roads, power lines, and pipelines.<br>
        <b>SIP</b> = Auto-invest a fixed amount every month. Best habit for beginners.<br>
        <b>Nifty 50</b> = Index of India's top 50 companies.<br>
        <b>30d Trend</b> = Whether the stock's been going up, down, or sideways for the last 30 days.<br>
        <b>Support</b> = A price where buyers usually step in — falling to this level may be a buying chance.
      </div>
    </div>

    <h2 style="font-size:15px;color:#2c3e50;margin:22px 0 8px">🤖 AI Investment Advisor</h2>
    {ai_html}

    <div style="margin-top:20px;padding:12px 14px;background:#f8f8f8;border-radius:8px;
                font-size:11px;color:#999;text-align:center;line-height:1.6">
      ⚠️ This email is for learning purposes only — not professional financial advice.<br>
      Always invest based on your own research or consult a SEBI-registered advisor.
    </div>

  </div>

  <div style="background:#2c3e50;padding:14px 28px;color:#aaa;font-size:11px;text-align:center">
    Morning Investment Brief · Powered by Gemini AI + NSE Data + GoodReturns · Made for Jaipur 🌄
  </div>

</div>
</body></html>"""


# ─────────────────────────────────────────────────────────────
#  SEND EMAIL
# ─────────────────────────────────────────────────────────────
def send_email(html, subject):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = CONFIG["email_sender"]
    msg["To"]      = CONFIG["email_receiver"]
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(CONFIG["email_sender"], CONFIG["email_password"])
            s.sendmail(CONFIG["email_sender"], CONFIG["email_receiver"], msg.as_string())
        print("✅ Email sent!")
    except Exception as e:
        print(f"❌ Email failed: {e}")


# ─────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────
def run():
    print(f"\n🌅 Morning Investment Alert — {datetime.now(IST).strftime('%d %b %Y %H:%M IST')}\n")

    print("📥 Downloading NSE Bhavcopy...")
    df, trade_date = download_bhavcopy()

    print("📊 Fetching index performance...")
    index_perf = get_index_performance()

    print("📉 Processing stock falls...")
    falling = {
        "nifty50":  fetch_stock_changes(NIFTY_50, df),
        "next50":   fetch_stock_changes(NIFTY_NEXT_50, df),
        "midcap":   fetch_stock_changes(NIFTY_MIDCAP, df),
        "smallcap": fetch_stock_changes(NIFTY_SMALLCAP, df),
    }

    print("🔍 Enriching top 5 fallers with 30-day NSE historical trend...")
    enriched_fallers = enrich_top_fallers_with_trend(falling, top_n=5)

    print("🥇 Fetching Gold & Silver from GoodReturns (Jaipur)...")
    gold_silver = get_gold_silver_prices()

    print("🌈 Processing diversification data...")
    div_data = fetch_diversification_data(df)

    print("🤖 Getting Gemini AI analysis (with trend context)...")
    ai_text = get_ai_analysis(index_perf, falling, gold_silver, div_data, enriched_fallers)

    print("📧 Building and sending email...")
    nifty_chg = index_perf.get("Nifty 50", {}).get("change", 0)
    date_str  = datetime.now(IST).strftime("%d %b")
    subject   = (
        f"🌅 {date_str} Morning Brief: Nifty {nifty_chg:+.2f}% | "
        f"Gold ₹{gold_silver.get('gold_jaipur_22k') or '?'}/10g | Your Daily Investment Update"
    )
    html = build_email(
        index_perf, falling, gold_silver, div_data,
        enriched_fallers, ai_text, trade_date
    )
    send_email(html, subject)
    print("✅ Done!\n")


if __name__ == "__main__":
    run()
