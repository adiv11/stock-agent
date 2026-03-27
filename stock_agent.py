"""
🌅 Indian Morning Investment Alert — v4 (Fixed & Enhanced)

Key Improvements over v3:
  • Gold/Silver: Multi-strategy BeautifulSoup parser + IBJA fallback (no more missed rates)
  • Falling Stocks: yfinance historical data — 52W high/low, RSI, 30D & 3M trend
  • AI Analysis: Fed with actual trend context per stock for smarter buy/wait advice
  • Change % for Gold/Silver calculated from today vs yesterday values (not fragile regex)

Data sources:
  • NSE Bhavcopy (CSV) for stock data — no rate limits
  • GoodReturns.in (BeautifulSoup) for Gold & Silver Jaipur rates
  • IBJA (ibja.co) as fallback for Gold & Silver
  • Yahoo Finance (yfinance) for 52-week highs/lows and trend data
  • NSE API for index performance
  • Gemini 1.5 Flash for AI analysis
"""

import os, re, smtplib, requests, time, zipfile, io
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from google import genai
from google.genai import types
from bs4 import BeautifulSoup

IST = ZoneInfo("Asia/Kolkata")

CONFIG = {
    "email_sender":   os.environ.get("GMAIL_SENDER",   "your_gmail@gmail.com"),
    "email_password": os.environ.get("GMAIL_PASSWORD", "your_app_password"),
    "email_receiver": os.environ.get("GMAIL_RECEIVER", "your_email@gmail.com"),
    "gemini_api_key": os.environ.get("GEMINI_API_KEY", "your_gemini_key"),
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'en-IN,en;q=0.9,hi;q=0.8',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
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
    session.headers.update(HEADERS)
    try:
        session.get("https://www.nseindia.com", timeout=15)
        time.sleep(2)
    except Exception:
        pass

    for date in get_trading_dates(5):
        date_str = date.strftime("%Y%m%d")
        url = f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date_str}_F_0000.csv.zip"
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
    sym   = next((c for c in cols if c.strip() in ['TckrSymb', 'SYMBOL']), None)
    close = next((c for c in cols if c.strip() in ['ClsPric', 'CLOSE']), None)
    prev  = next((c for c in cols if c.strip() in ['PrvsClsgPric', 'PREVCLOSE']), None)
    series= next((c for c in cols if c.strip() in ['SctySrs', 'SERIES']), None)
    return sym, close, prev, series


def fetch_stock_changes(tickers, df):
    if df is None:
        return []
    sym_col, close_col, prev_col, series_col = parse_bhavcopy_columns(df)
    if not all([sym_col, close_col, prev_col]):
        return []

    df_eq = df[df[series_col].str.strip() == 'EQ'] if series_col else df
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
#  SECTION 2 — INDEX PERFORMANCE
# ─────────────────────────────────────────────────────────────
def get_index_performance():
    result = {}
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
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
#  SECTION 3 — GOLD & SILVER (FIXED — v4)
#  Primary: GoodReturns.in with BeautifulSoup table parsing
#  Fallback: IBJA (ibja.co) — official bullion association
# ─────────────────────────────────────────────────────────────

def _extract_prices_from_table(soup, low, high):
    """
    Scan every table on the page; return a list of (value, row_text) tuples
    for cells whose numeric value falls in [low, high].
    """
    found = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            row_text = row.get_text(" ", strip=True)
            for cell in row.find_all(["td", "th"]):
                cell_text = cell.get_text(strip=True).replace(",", "")
                nums = re.findall(r"\d+", cell_text)
                for n in nums:
                    v = int(n)
                    if low <= v <= high:
                        found.append((v, row_text))
    return found


def _parse_goodreturns_gold(soup, result):
    """
    Parse GoodReturns Jaipur gold page.
    Strategy A — table-based: look for rows mentioning 22K / 24K.
    Strategy B — full-text regex fallback.
    """
    # ── Strategy A: table rows ──
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            row_text = " ".join(cells)

            # Collect all numbers in gold price range (₹40,000 – ₹2,00,000 per 10 g)
            prices = []
            for cell in cells:
                for n in re.findall(r"[\d,]+", cell):
                    try:
                        v = int(n.replace(",", ""))
                        if 40000 <= v <= 200000:
                            prices.append(v)
                    except ValueError:
                        pass

            if not prices:
                continue

            is_22k = bool(re.search(r"\b22\s*[Kk]\b", row_text))
            is_24k = bool(re.search(r"\b24\s*[Kk]\b", row_text))

            if is_22k and not result["gold_jaipur_22k"]:
                result["gold_jaipur_22k"] = prices[0]
                # Second column is often "yesterday's rate"
                if len(prices) >= 2 and not result.get("gold_yesterday"):
                    result["gold_yesterday"] = prices[1]

            if is_24k and not result["gold_jaipur_24k"]:
                result["gold_jaipur_24k"] = prices[0]
                result["gold_inr_10g"]     = prices[0]
                result["gold_today"]       = prices[0]
                if len(prices) >= 2 and not result.get("gold_yesterday"):
                    result["gold_yesterday"] = prices[1]

    # ── Strategy B: full-text regex (fallback) ──
    text = soup.get_text(" ")

    if not result["gold_jaipur_24k"]:
        for pat in [
            r"24\s*[Kk][^\d]{0,50}?([\d]{2,3},[\d]{3})",
            r"24\s*[Cc]arat[^\d]{0,50}?([\d]{2,3},[\d]{3})",
            r"([\d]{2,3},[\d]{3})[^\d]{0,20}24\s*[Kk]",
        ]:
            m = re.search(pat, text)
            if m:
                v = int(m.group(1).replace(",", ""))
                if 40000 <= v <= 200000:
                    result["gold_jaipur_24k"] = v
                    result["gold_inr_10g"]    = v
                    result["gold_today"]      = v
                    break

    if not result["gold_jaipur_22k"]:
        for pat in [
            r"22\s*[Kk][^\d]{0,50}?([\d]{2,3},[\d]{3})",
            r"22\s*[Cc]arat[^\d]{0,50}?([\d]{2,3},[\d]{3})",
            r"([\d]{2,3},[\d]{3})[^\d]{0,20}22\s*[Kk]",
        ]:
            m = re.search(pat, text)
            if m:
                v = int(m.group(1).replace(",", ""))
                if 40000 <= v <= 200000:
                    result["gold_jaipur_22k"] = v
                    break


def _parse_goodreturns_silver(soup, result):
    """
    Parse GoodReturns Jaipur silver page.
    Silver per kg in Jaipur: typically ₹80,000 – ₹1,50,000.
    Strategy A — table rows | Strategy B — full-text regex.
    """
    silver_today = None
    silver_yesterday = None

    # ── Strategy A: table rows ──
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            row_text = " ".join(cells)

            prices = []
            for cell in cells:
                for n in re.findall(r"[\d,]+", cell):
                    try:
                        v = int(n.replace(",", ""))
                        if 70000 <= v <= 200000:   # per kg
                            prices.append(v)
                        elif 70 <= v <= 200:        # per gram → convert
                            prices.append(v * 1000)
                    except ValueError:
                        pass

            if prices:
                if silver_today is None:
                    silver_today = prices[0]
                if len(prices) >= 2 and silver_yesterday is None:
                    silver_yesterday = prices[1]

    # ── Strategy B: text fallback ──
    if silver_today is None:
        text = soup.get_text(" ")
        # per-kg price
        for m in re.finditer(r"([\d]{2,3},[\d]{3})", text):
            v = int(m.group(1).replace(",", ""))
            if 70000 <= v <= 200000:
                silver_today = v
                break
        # per-gram price → convert
        if silver_today is None:
            for m in re.finditer(r"\b(\d{2,3})\s*(?:/|-|per)?\s*g(?:ram)?", text, re.IGNORECASE):
                v = int(m.group(1))
                if 70 <= v <= 200:
                    silver_today = v * 1000
                    break

    if silver_today:
        result["silver_jaipur_kg"] = silver_today
        result["silver_inr_kg"]    = silver_today

    if silver_today and silver_yesterday and silver_yesterday != 0:
        pct = (silver_today - silver_yesterday) / silver_yesterday * 100
        if -20 < pct < 20:
            result["silver_change_pct"] = round(pct, 2)


def _fetch_ibja_rates(session, result):
    """
    Fallback: IBJA (India Bullion & Jewellers Association) official rates.
    URL: https://www.ibja.co/  — publishes Gold 999 / 995 and Silver 999 per 10 g / kg.
    """
    try:
        r = session.get("https://www.ibja.co/", timeout=15)
        if r.status_code != 200:
            return
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text(" ")

        # Gold 999 ≈ 24K, Gold 995 ≈ 22K (per 10 g)
        for pat, key in [
            (r"Gold\s*999[^\d]{0,30}?([\d]{2,3},[\d]{3})", "gold_jaipur_24k"),
            (r"Gold\s*995[^\d]{0,30}?([\d]{2,3},[\d]{3})", "gold_jaipur_22k"),
        ]:
            if result.get(key):
                continue
            m = re.search(pat, text)
            if m:
                v = int(m.group(1).replace(",", ""))
                if 40000 <= v <= 200000:
                    result[key] = v
                    if key == "gold_jaipur_24k":
                        result["gold_inr_10g"] = v
                        result["gold_today"]   = v
                        result["source"]       = "ibja.co"

        # Silver 999 per kg
        if not result.get("silver_jaipur_kg"):
            m = re.search(r"Silver\s*999[^\d]{0,30}?([\d]{2,3},[\d]{3})", text)
            if m:
                v = int(m.group(1).replace(",", ""))
                if 70000 <= v <= 200000:
                    result["silver_jaipur_kg"] = v
                    result["silver_inr_kg"]    = v
                    if "source" not in result:
                        result["source"] = "ibja.co"
    except Exception as e:
        print(f"IBJA fallback error: {e}")


def get_gold_silver_prices():
    """
    Fetch accurate Jaipur gold & silver rates.
    1) GoodReturns.in (primary) — BeautifulSoup table + regex
    2) IBJA.co (fallback)       — official bullion association
    Change % is derived from today vs yesterday values (not fragile page-text regex).
    """
    result = {
        "gold_inr_10g":       None,
        "silver_inr_kg":      None,
        "gold_jaipur_22k":    None,
        "gold_jaipur_24k":    None,
        "silver_jaipur_kg":   None,
        "gold_change_pct":    None,
        "silver_change_pct":  None,
        "gold_today":         None,
        "gold_yesterday":     None,
        "usd_inr":            None,
        "source":             None,
    }

    session = requests.Session()
    session.headers.update(HEADERS)

    # ── Primary: GoodReturns Gold (Jaipur) ──
    try:
        print("   Fetching gold from GoodReturns (Jaipur)…")
        r = session.get("https://www.goodreturns.in/gold-rates/jaipur.html", timeout=20)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            _parse_goodreturns_gold(soup, result)
            if result["gold_jaipur_24k"]:
                result["source"] = "goodreturns.in"
                print(f"   ✅ Gold 24K: ₹{result['gold_jaipur_24k']:,} | 22K: ₹{result['gold_jaipur_22k']:,}")
            else:
                print("   ⚠️  GoodReturns gold parse returned nothing — will try IBJA")
        else:
            print(f"   ⚠️  GoodReturns gold HTTP {r.status_code}")
    except Exception as e:
        print(f"   ❌ GoodReturns gold error: {e}")

    time.sleep(1)

    # ── Primary: GoodReturns Silver (Jaipur) ──
    try:
        print("   Fetching silver from GoodReturns (Jaipur)…")
        r2 = session.get("https://www.goodreturns.in/silver-rate/jaipur.html", timeout=20)
        if r2.status_code == 200:
            soup2 = BeautifulSoup(r2.text, "html.parser")
            _parse_goodreturns_silver(soup2, result)
            if result["silver_jaipur_kg"]:
                print(f"   ✅ Silver/kg: ₹{result['silver_jaipur_kg']:,}")
            else:
                print("   ⚠️  GoodReturns silver parse returned nothing")
        else:
            print(f"   ⚠️  GoodReturns silver HTTP {r2.status_code}")
    except Exception as e:
        print(f"   ❌ GoodReturns silver error: {e}")

    time.sleep(1)

    # ── Fallback: IBJA if either gold or silver is still missing ──
    if not result["gold_jaipur_24k"] or not result["silver_jaipur_kg"]:
        print("   Trying IBJA fallback…")
        _fetch_ibja_rates(session, result)

    # ── Derive change % from scraped today/yesterday values ──
    if result.get("gold_today") and result.get("gold_yesterday") and result["gold_yesterday"] != 0:
        pct = (result["gold_today"] - result["gold_yesterday"]) / result["gold_yesterday"] * 100
        if -20 < pct < 20:
            result["gold_change_pct"] = round(pct, 2)

    g24  = f"₹{result['gold_jaipur_24k']:,}" if result['gold_jaipur_24k'] else 'N/A'
    g22  = f"₹{result['gold_jaipur_22k']:,}" if result['gold_jaipur_22k'] else 'N/A'
    silv = f"₹{result['silver_jaipur_kg']:,}" if result['silver_jaipur_kg'] else 'N/A'
    print(f"   Final rates — Gold 24K: {g24} | Gold 22K: {g22} | Silver/kg: {silv} | Source: {result.get('source','unknown')}")

    return result


# ─────────────────────────────────────────────────────────────
#  SECTION 4 — HISTORICAL STOCK DATA (NEW in v4)
#  Uses yfinance to get 52-week range, 30D/3M trends, and RSI
#  for the top fallen stocks — gives AI real context to advise
# ─────────────────────────────────────────────────────────────

def _calc_rsi(closes, period=14):
    """Simple Wilder RSI — returns None if not enough data."""
    try:
        if len(closes) < period + 2:
            return None
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains  = [max(d, 0) for d in deltas]
        losses = [max(-d, 0) for d in deltas]
        avg_g  = sum(gains[:period])  / period
        avg_l  = sum(losses[:period]) / period
        for i in range(period, len(deltas)):
            avg_g = (avg_g * (period - 1) + gains[i])  / period
            avg_l = (avg_l * (period - 1) + losses[i]) / period
        if avg_l == 0:
            return 100.0
        rs = avg_g / avg_l
        return round(100 - 100 / (1 + rs), 1)
    except Exception:
        return None


def get_historical_stock_data(falling_stocks_dict, top_n=10):
    """
    For the top-N fallen stocks (across all categories), fetch from Yahoo Finance:
      - 52-week high and low
      - How far current price is from 52W high and low
      - 30-day and 3-month price trend (%)
      - 14-day RSI
      - Verdict flags: near_52w_low, oversold (RSI<35), in_downtrend

    Returns dict: { "TICKER": { ...data... }, ... }
    """
    all_fallen = []
    for stocks in falling_stocks_dict.values():
        all_fallen.extend(stocks)

    # Take top_n biggest fallers today
    top_fallen = sorted(all_fallen, key=lambda x: x["pct_change"])[:top_n]

    print(f"   Fetching 52W history for {len(top_fallen)} stocks via yfinance…")
    result = {}

    for stock in top_fallen:
        ticker_ns = stock["ticker"] + ".NS"
        try:
            yf_ticker = yf.Ticker(ticker_ns)
            hist = yf_ticker.history(period="1y", interval="1d", auto_adjust=True)

            if hist.empty or len(hist) < 30:
                print(f"   ⚠️  {stock['ticker']}: insufficient history ({len(hist)} rows)")
                continue

            closes = hist["Close"].tolist()
            current = stock["last_close"]

            high_52w = round(float(hist["High"].max()), 2)
            low_52w  = round(float(hist["Low"].min()),  2)

            pct_from_high = round((current - high_52w) / high_52w * 100, 2)
            pct_from_low  = round((current - low_52w)  / low_52w  * 100, 2) if low_52w > 0 else None

            # 30-day trend (last ~22 trading days)
            closes_30d  = closes[-22:] if len(closes) >= 22 else closes
            trend_30d   = round((closes_30d[-1] - closes_30d[0]) / closes_30d[0] * 100, 2) if closes_30d[0] > 0 else None

            # 3-month trend (last ~65 trading days)
            closes_90d  = closes[-65:] if len(closes) >= 65 else closes
            trend_90d   = round((closes_90d[-1] - closes_90d[0]) / closes_90d[0] * 100, 2) if closes_90d[0] > 0 else None

            rsi = _calc_rsi(closes[-30:])

            near_low   = pct_from_low  is not None and pct_from_low  <= 15
            oversold   = rsi is not None and rsi < 35
            downtrend  = trend_30d is not None and trend_30d < -8

            result[stock["ticker"]] = {
                "high_52w":      high_52w,
                "low_52w":       low_52w,
                "pct_from_high": pct_from_high,
                "pct_from_low":  pct_from_low,
                "trend_30d":     trend_30d,
                "trend_90d":     trend_90d,
                "rsi_14":        rsi,
                "near_52w_low":  near_low,
                "oversold":      oversold,
                "in_downtrend":  downtrend,
            }

            flag = ""
            if near_low:   flag += " 🟢 Near 52W Low"
            if oversold:   flag += " 💙 Oversold (RSI<35)"
            if downtrend:  flag += " 🔴 Downtrend"
            print(f"   ✅ {stock['ticker']}: 52W {low_52w:,}–{high_52w:,} | "
                  f"From Low: {pct_from_low:+.1f}% | RSI: {rsi}{flag}")

            time.sleep(0.4)   # polite delay to Yahoo

        except Exception as e:
            print(f"   ❌ yfinance error for {ticker_ns}: {e}")

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
                    df[sym_col] = df[sym_col].str.strip()
                    row = df[df[sym_col] == ticker]
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
#  SECTION 6 — GEMINI AI ANALYSIS (v4 — enriched with history)
# ─────────────────────────────────────────────────────────────

def _build_historical_context(historical_data):
    """Format historical stock data into a readable prompt block."""
    if not historical_data:
        return "  Historical data unavailable today."
    lines = []
    for ticker, d in historical_data.items():
        rsi_str = f"RSI={d['rsi_14']}" if d.get("rsi_14") else "RSI=N/A"
        low_str = f"{d['pct_from_low']:+.1f}% from 52W low" if d.get("pct_from_low") is not None else ""
        high_str= f"{d['pct_from_high']:+.1f}% from 52W high"
        t30     = f"30D trend={d['trend_30d']:+.1f}%" if d.get("trend_30d") is not None else ""
        t90     = f"3M trend={d['trend_90d']:+.1f}%" if d.get("trend_90d") is not None else ""
        flags   = []
        if d.get("near_52w_low"):   flags.append("⚠ NEAR 52W LOW")
        if d.get("oversold"):       flags.append("⚠ OVERSOLD")
        if d.get("in_downtrend"):   flags.append("⚠ DOWNTREND")
        flag_str = " | ".join(flags) if flags else "No special flags"
        lines.append(
            f"  {ticker}: 52W Low=₹{d['low_52w']:,} / High=₹{d['high_52w']:,} | "
            f"{low_str} | {high_str} | {t30} | {t90} | {rsi_str} → {flag_str}"
        )
    return "\n".join(lines)


def get_ai_analysis(index_perf, falling_stocks, gold_silver, div_data, historical_data=None):
    client = genai.Client(api_key=CONFIG["gemini_api_key"])

    top_fallers = sorted(
        falling_stocks.get("nifty50", []) + falling_stocks.get("next50", []),
        key=lambda x: x["pct_change"]
    )[:8]

    index_lines = "\n".join([
        f"  {k}: {v['change']:+.2f}% (now at {v['value']:,.0f})"
        for k, v in index_perf.items()
    ]) or "  Data unavailable"

    stock_lines = "\n".join([
        f"  {s['ticker']}: fell {abs(s['pct_change']):.1f}% to ₹{s['last_close']} (was ₹{s['prev_close']})"
        for s in top_fallers
    ]) or "  No major fallers today — market was stable"

    gs = gold_silver
    gold_line   = (f"Gold 22K Jaipur: ₹{gs['gold_jaipur_22k']:,.0f}/10g | "
                   f"24K: ₹{gs['gold_jaipur_24k']:,.0f}/10g | "
                   f"Change: {gs['gold_change_pct']:+.2f}%" if gs.get("gold_jaipur_24k") and gs.get("gold_change_pct") is not None
                   else f"Gold 22K: ₹{gs['gold_jaipur_22k']:,.0f}/10g | 24K: ₹{gs['gold_jaipur_24k']:,.0f}/10g" if gs.get("gold_jaipur_24k")
                   else "Gold: data unavailable")
    silver_line = (f"Silver Jaipur: ₹{gs['silver_jaipur_kg']:,.0f}/kg | "
                   f"Change: {gs['silver_change_pct']:+.2f}%" if gs.get("silver_jaipur_kg") and gs.get("silver_change_pct") is not None
                   else f"Silver Jaipur: ₹{gs['silver_jaipur_kg']:,.0f}/kg" if gs.get("silver_jaipur_kg")
                   else "Silver: data unavailable")

    hist_block = _build_historical_context(historical_data)
    today = datetime.now(IST).strftime("%d %B %Y")

    prompt = f"""
Today is {today}. You are writing a friendly morning investment update for a complete beginner in Jaipur, India.
They want simple plain-English advice — NO complicated finance jargon.

═══════════════════════════════
YESTERDAY'S MARKET DATA
═══════════════════════════════

STOCK MARKET INDICES:
{index_lines}

BIGGEST STOCK FALLS (today's session):
{stock_lines}

HISTORICAL TREND DATA FOR THESE FALLEN STOCKS (from past 12 months — use this to judge if it's a buying opportunity):
{hist_block}

GOLD & SILVER — Jaipur Rates (source: GoodReturns.in / IBJA):
{gold_line}
{silver_line}

═══════════════════════════════
YOUR TASK
═══════════════════════════════
Write a friendly morning update with EXACTLY these 5 sections.
Use simple language a Class 10 student can understand. Keep each section SHORT (3-5 sentences).
Do NOT use bullet points — write in short sentences.

IMPORTANT RULES for the stock & metals sections:
- For each fallen stock, look at its historical data. If it is "NEAR 52W LOW" or "OVERSOLD" (RSI < 35)
  AND the 3M trend is not deeply negative, say it MAY be a buying opportunity.
  If it is still far from its 52W low and in downtrend, advise waiting for further adjustment.
- For Gold/Silver: if the change % is positive (rising), say it may not be the ideal moment to buy;
  if negative (falling), say it could be a dip worth watching.
  Comment on whether SGB, Gold ETF (GOLDBEES), or physical gold suits a beginner best.

== WHY DID THE MARKET MOVE? ==
Based on the data above, explain in 3 simple sentences what happened. Pretend you're texting a friend.

== IS THIS A GOOD TIME TO BUY STOCKS? ==
Based on today's falls AND the historical data, mention 2-3 specific stocks by name.
For each, say clearly: "Good time to consider" OR "Wait for further adjustment" — and give the simple reason (e.g., "it's near its yearly low" or "still falling, wait").

== GOLD & SILVER UPDATE ==
Comment on whether gold/silver is at a good level to buy today based on the rate and change.
Should someone in Jaipur buy physical gold, Gold ETF (GOLDBEES), or Sovereign Gold Bond?
Give one clear, specific recommendation.

== TODAY'S SIMPLE INVESTMENT TIP ==
Give ONE simple, actionable tip for a beginner with ₹1,000–₹10,000 to invest this week. Be very specific.

== MARKET MOOD FOR TODAY ==
One sentence prediction for today's market. Use everyday words — "market may start steady", "likely to recover", etc.

Write in a warm, encouraging tone. The reader is just starting their investment journey.
"""

    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.4,
                max_output_tokens=1200,
            ),
        )
        return response.text if response.text else generate_fallback_analysis(index_perf, falling_stocks, gold_silver, historical_data)
    except Exception as e:
        print(f"Gemini error: {e}")
        return generate_fallback_analysis(index_perf, falling_stocks, gold_silver, historical_data)


def generate_fallback_analysis(index_perf, falling_stocks, gold_silver, historical_data=None):
    """Pure Python analysis when Gemini is unavailable"""
    nifty = index_perf.get("Nifty 50", {})
    chg   = nifty.get("change", 0)

    if chg < -1.5:
        why  = (f"The market had a rough day yesterday, with Nifty falling {abs(chg):.2f}%. "
                "This often happens due to global sell-offs or rising interest rate fears. "
                "These dips are a normal part of the market cycle.")
        mood = "Market may open cautiously today — watch for recovery signals."
    elif chg < 0:
        why  = (f"The market dipped slightly, with Nifty down {abs(chg):.2f}%. "
                "This is a minor correction and very normal — markets don't go up every day.")
        mood = "Market likely to start steady — yesterday's minor fall shouldn't cause big concern."
    else:
        why  = (f"The market did well yesterday, with Nifty up {chg:.2f}%. "
                "Positive days like this show investor confidence is high.")
        mood = "Market likely to continue positively today — good momentum from yesterday."

    # Stock advice using historical data
    all_fallen = sorted(
        falling_stocks.get("nifty50", []) + falling_stocks.get("next50", []),
        key=lambda x: x["pct_change"]
    )[:5]
    stock_notes = []
    for s in all_fallen:
        hist = (historical_data or {}).get(s["ticker"])
        if hist:
            if hist.get("near_52w_low") or hist.get("oversold"):
                stock_notes.append(
                    f"{s['ticker']} (₹{s['last_close']}) looks interesting — "
                    f"it's near its yearly low (52W low: ₹{hist['low_52w']:,}). Could be a cautious buy."
                )
            elif hist.get("in_downtrend"):
                stock_notes.append(
                    f"{s['ticker']} (₹{s['last_close']}) is still in a downtrend — "
                    f"better to wait for it to stabilise before investing."
                )
    buy_text = "When the market falls, quality stocks go on sale. " + (
        " ".join(stock_notes[:2]) if stock_notes
        else "Consider adding to a Nifty 50 ETF (NIFTYBEES) during dips."
    )

    # Gold/silver note
    gs = gold_silver
    if gs.get("gold_jaipur_24k"):
        chg_g = gs.get("gold_change_pct", 0) or 0
        direction = "rising slightly" if chg_g > 0 else "dipping today"
        gold_note = (
            f"Gold 24K in Jaipur is ₹{gs['gold_jaipur_24k']:,.0f} per 10g ({direction}). "
            "For most beginners a Gold ETF (GOLDBEES) beats physical gold — no making charges, "
            "no storage risk, and you can start with ₹500."
        )
    else:
        gold_note = "Gold data unavailable. Consider GOLDBEES (Gold ETF) for easy digital gold exposure."

    return f"""== WHY DID THE MARKET MOVE? ==
{why}

== IS THIS A GOOD TIME TO BUY STOCKS? ==
{buy_text}

== GOLD & SILVER UPDATE ==
{gold_note} Sovereign Gold Bonds are the best long-term option when available — they earn 2.5% interest per year on top of gold's price rise.

== TODAY'S SIMPLE INVESTMENT TIP ==
Start a SIP of ₹500–₹1,000/month in NIFTYBEES (Nifty 50 ETF) through Groww or Zerodha. Set it once and forget it — this one habit beats most other strategies for a beginner.

== MARKET MOOD FOR TODAY ==
{mood}"""


# ─────────────────────────────────────────────────────────────
#  EMAIL BUILDER  (visual unchanged from v3)
# ─────────────────────────────────────────────────────────────

def pct_badge(pct):
    if pct is None:
        return '<span style="color:#888;font-size:12px">No data</span>'
    color = "#c0392b" if pct < 0 else "#27ae60"
    arrow = "▼" if pct < 0 else "▲"
    return f'<span style="color:{color};font-weight:bold">{arrow} {abs(pct):.2f}%</span>'


def stock_table(stocks, threshold, historical_data=None):
    filtered = [s for s in stocks if s["pct_change"] <= threshold]
    if not filtered:
        top_fallers = sorted(stocks, key=lambda x: x["pct_change"])[:5]
        if not top_fallers:
            return '<p style="color:#27ae60;font-size:13px;margin:6px 0">✅ No data available for this group.</p>'
        note    = f'<p style="color:#27ae60;font-size:12px;margin:0 0 6px">✅ No stocks fell beyond {abs(threshold)}% — showing top 5 movers instead.</p>'
        display = top_fallers
    else:
        note    = ""
        display = filtered

    rows = ""
    for s in display:
        hist  = (historical_data or {}).get(s["ticker"], {})
        badge = ""
        tip   = ""
        if hist.get("near_52w_low"):
            badge = ' <span style="background:#27ae60;color:white;font-size:10px;padding:1px 5px;border-radius:8px">Near 52W Low</span>'
            tip   = f'<div style="font-size:10px;color:#27ae60;margin-top:2px">↳ 52W Low: ₹{hist["low_52w"]:,}</div>'
        elif hist.get("oversold"):
            badge = ' <span style="background:#2980b9;color:white;font-size:10px;padding:1px 5px;border-radius:8px">Oversold</span>'
        elif hist.get("in_downtrend"):
            badge = ' <span style="background:#e67e22;color:white;font-size:10px;padding:1px 5px;border-radius:8px">Downtrend</span>'
            tip   = '<div style="font-size:10px;color:#e67e22;margin-top:2px">↳ Wait for stabilisation</div>'

        trend_cell = ""
        if hist.get("trend_30d") is not None:
            tc = "#c0392b" if hist["trend_30d"] < 0 else "#27ae60"
            trend_cell = f'<span style="color:{tc};font-size:11px">{hist["trend_30d"]:+.1f}% (30D)</span>'

        rows += f"""
        <tr style="border-bottom:1px solid #fce8e8">
          <td style="padding:8px 10px">
            <span style="font-weight:600;font-size:13px">{s['ticker']}</span>{badge}
            {tip}
          </td>
          <td style="padding:8px 10px;font-size:13px;text-align:right">₹{s['last_close']:,.2f}</td>
          <td style="padding:8px 10px;text-align:right">{pct_badge(s['pct_change'])}</td>
          <td style="padding:8px 10px;font-size:12px;text-align:right">{trend_cell}</td>
        </tr>"""

    return note + f"""
    <table style="width:100%;border-collapse:collapse;margin-top:4px">
      <tr style="background:#c0392b;color:white;font-size:12px">
        <th style="padding:8px 10px;text-align:left">Stock</th>
        <th style="padding:8px 10px;text-align:right">Price</th>
        <th style="padding:8px 10px;text-align:right">Today</th>
        <th style="padding:8px 10px;text-align:right">30D Trend</th>
      </tr>{rows}
    </table>"""


def gold_silver_section(gs):
    def row(label, value, change, note=""):
        badge = pct_badge(change)
        return f"""
        <tr style="border-bottom:1px solid #f5f0e8">
          <td style="padding:10px 12px;font-weight:600;font-size:13px">{label}</td>
          <td style="padding:10px 12px;font-size:14px;font-weight:bold;color:#b8860b">
            {f'₹{value:,.0f}' if value else '—'}
          </td>
          <td style="padding:10px 12px">{badge}</td>
          <td style="padding:10px 12px;font-size:11px;color:#888">{note}</td>
        </tr>"""

    source_note = f'Source: {gs.get("source","GoodReturns.in / IBJA")}' if gs.get("source") else "GoodReturns.in"
    return f"""
    <table style="width:100%;border-collapse:collapse;margin-top:8px">
      <tr style="background:#b8860b;color:white;font-size:12px">
        <th style="padding:8px 12px;text-align:left">Metal</th>
        <th style="padding:8px 12px;text-align:left">Rate</th>
        <th style="padding:8px 12px;text-align:left">Change</th>
        <th style="padding:8px 12px;text-align:left">Note</th>
      </tr>
      {row("Gold 22K (Jaipur)", gs.get("gold_jaipur_22k"), gs.get("gold_change_pct"), "Per 10 grams · retail")}
      {row("Gold 24K (Jaipur)", gs.get("gold_jaipur_24k"), gs.get("gold_change_pct"), "Per 10 grams · retail")}
      {row("Silver (Jaipur)",   gs.get("silver_jaipur_kg"), gs.get("silver_change_pct"), "Per kg · retail")}
    </table>
    <p style="font-size:11px;color:#aaa;margin:6px 0 0">
      ⚠️ Rates from {source_note} — always confirm with your local jeweller before buying.
    </p>"""


def diversification_section(div_data):
    html  = ""
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
        "WHY DID THE MARKET MOVE?":           ("📰", "#8e44ad"),
        "IS THIS A GOOD TIME TO BUY STOCKS?": ("🛒", "#c0392b"),
        "GOLD & SILVER UPDATE":               ("🥇", "#b8860b"),
        "TODAY'S SIMPLE INVESTMENT TIP":      ("💡", "#27ae60"),
        "MARKET MOOD FOR TODAY":              ("🔮", "#2980b9"),
    }
    html = ""
    for title, (icon, color) in sections.items():
        pattern = rf"==\s*{re.escape(title)}\s*=="
        match   = re.search(pattern, text, re.IGNORECASE)
        if match:
            start      = match.end()
            next_match = re.search(r"==\s*[A-Z]", text[start:], re.IGNORECASE)
            content    = text[start: start + next_match.start()].strip() if next_match else text[start:].strip()
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


def build_email(index_perf, falling, gold_silver, div_data, ai_text, trade_date, historical_data=None):
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
        <div style="flex:1;min-width:120px;background:white;border:1px solid {c};
                    border-radius:8px;padding:12px;text-align:center">
          <div style="font-size:11px;color:#666;margin-bottom:3px">{name}</div>
          <div style="font-size:17px;font-weight:bold;color:#222">{d['value']:,.0f}</div>
          <div style="font-size:13px;font-weight:bold;color:{c}">{a} {abs(d['change']):.2f}%</div>
        </div>"""

    ai_html = parse_ai_sections(ai_text)

    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif">
<div style="max-width:680px;margin:16px auto;background:white;border-radius:14px;
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
    👋 <strong>New to investing?</strong> Numbers with ▼ mean price fell. Numbers with ▲ mean price rose.
    <strong>"Near 52W Low"</strong> = the stock is cheap compared to its past year price.
    You don't need to act on everything — just read and learn!
  </div>

  <div style="padding:22px 28px">

    <h2 style="font-size:15px;color:#2c3e50;margin:0 0 10px">📊 Yesterday's Big Picture</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:22px">{cards}</div>

    <h2 style="font-size:15px;color:#2c3e50;margin:0 0 4px">🥇 Gold & Silver — Jaipur Rates</h2>
    <p style="font-size:12px;color:#888;margin:0 0 8px">
      Rates fetched from GoodReturns.in / IBJA. Buying today? Compare with yesterday's rate shown.
    </p>
    {gold_silver_section(gold_silver)}

    <h2 style="font-size:15px;color:#2c3e50;margin:22px 0 4px">📉 Stocks That Fell Yesterday</h2>
    <p style="font-size:12px;color:#888;margin:0 0 8px">
      <strong>"Near 52W Low"</strong> badge = stock is near its cheapest in a year — potentially interesting.
      <strong>"Downtrend"</strong> = still falling — consider waiting.
    </p>

    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#c0392b;margin-bottom:4px">🔴 Nifty 50 — fell more than 2%</div>
      {stock_table(falling.get("nifty50", []), -2, historical_data)}
    </div>

    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#e67e22;margin-bottom:4px">🟠 Next 50 — fell more than 2%</div>
      {stock_table(falling.get("next50", []), -2, historical_data)}
    </div>

    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#2980b9;margin-bottom:4px">🔵 Midcap — fell more than 3%</div>
      {stock_table(falling.get("midcap", []), -3, historical_data)}
    </div>

    <div style="margin-bottom:22px">
      <div style="font-size:13px;font-weight:600;color:#8e44ad;margin-bottom:4px">🟣 Smallcap — fell more than 3%</div>
      {stock_table(falling.get("smallcap", []), -3, historical_data)}
    </div>

    <h2 style="font-size:15px;color:#1a3a6b;margin:0 0 4px">🌈 Other Ways to Invest — Not Just Stocks</h2>
    <p style="font-size:12px;color:#888;margin:0 0 8px">
      All can be bought from your Zerodha / Groww / Upstox app.
    </p>
    {diversification_section(div_data)}

    <div style="margin-top:22px;background:#f0f4ff;border-radius:8px;padding:14px 16px">
      <div style="font-size:13px;font-weight:600;color:#1a3a6b;margin-bottom:8px">📖 Quick Glossary</div>
      <div style="font-size:12px;color:#444;line-height:2">
        <b>ETF</b> = A basket of stocks in one click. Like buying a thali instead of cooking each dish.<br>
        <b>REIT</b> = You own part of office buildings and earn rent every 3 months.<br>
        <b>InvIT</b> = Same idea but for roads, power lines and pipelines.<br>
        <b>SIP</b> = Auto-invest a fixed amount every month. Best beginner habit.<br>
        <b>52W Low</b> = The lowest price that stock has traded in the past year.<br>
        <b>RSI &lt;35</b> = "Oversold" — may bounce back soon (not guaranteed).<br>
        <b>Nifty 50</b> = Index of India's top 50 companies. If it goes up, market is happy.
      </div>
    </div>

    <h2 style="font-size:15px;color:#2c3e50;margin:22px 0 8px">🤖 Your AI Investment Advisor Says...</h2>
    {ai_html}

    <div style="margin-top:20px;padding:12px 14px;background:#f8f8f8;border-radius:8px;
                font-size:11px;color:#999;text-align:center;line-height:1.6">
      ⚠️ This email is for learning purposes only — not professional financial advice.<br>
      Always invest based on your own research or consult a SEBI-registered advisor.
    </div>

  </div>

  <div style="background:#2c3e50;padding:14px 28px;color:#aaa;font-size:11px;text-align:center">
    Morning Investment Brief · v4 · Gemini AI + NSE Bhavcopy + yfinance · Made for Jaipur 🌄
  </div>

</div>
</body></html>"""


# ─────────────────────────────────────────────────────────────
#  SEND EMAIL
# ─────────────────────────────────────────────────────────────
def send_email(html, subject):
    msg            = MIMEMultipart("alternative")
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
    print(f"\n🌅 Morning Investment Alert v4 — {datetime.now(IST).strftime('%d %b %Y %H:%M IST')}\n")

    print("📥 Downloading NSE Bhavcopy…")
    df, trade_date = download_bhavcopy()

    print("📊 Fetching index performance…")
    index_perf = get_index_performance()

    print("📉 Processing stock falls…")
    falling = {
        "nifty50":  fetch_stock_changes(NIFTY_50,        df),
        "next50":   fetch_stock_changes(NIFTY_NEXT_50,   df),
        "midcap":   fetch_stock_changes(NIFTY_MIDCAP,    df),
        "smallcap": fetch_stock_changes(NIFTY_SMALLCAP,  df),
    }

    print("📈 Fetching 52-week historical data for fallen stocks…")
    historical_data = get_historical_stock_data(falling, top_n=10)

    print("🥇 Fetching Gold & Silver from GoodReturns / IBJA…")
    gold_silver = get_gold_silver_prices()

    print("🌈 Processing diversification data…")
    div_data = fetch_diversification_data(df)

    print("🤖 Getting Gemini AI analysis…")
    ai_text = get_ai_analysis(index_perf, falling, gold_silver, div_data, historical_data)

    print("📧 Sending email…")
    nifty_chg = index_perf.get("Nifty 50", {}).get("change", 0)
    date_str  = datetime.now(IST).strftime("%d %b")
    subject   = f"🌅 {date_str} Morning Brief: Nifty {nifty_chg:+.2f}% | Daily Investment Update"
    html      = build_email(index_perf, falling, gold_silver, div_data, ai_text, trade_date, historical_data)
    send_email(html, subject)

    print("✅ Done!\n")


if __name__ == "__main__":
    run()
