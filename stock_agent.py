"""
🌅 Indian Morning Investment Alert — v3
Data sources:
  • NSE Bhavcopy (CSV) for stock data — no rate limits
  • GoodReturns.in scraping for Gold & Silver Jaipur rates
  • NSE API for index performance
  • Gemini 1.5 Flash for AI analysis
"""

import os, re, smtplib, requests, time, zipfile, io
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
import pandas as pd
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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Referer': 'https://www.nseindia.com/',
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
#  SECTION 1 — NSE BHAVCOPY (reliable stock data)
# ─────────────────────────────────────────────────────────────
def get_trading_dates(n=5):
    """Return last n weekdays from today"""
    days = []
    candidate = datetime.now(IST).date() - timedelta(days=1)
    while len(days) < n:
        if candidate.weekday() < 5:
            days.append(candidate)
        candidate -= timedelta(days=1)
    return days


def download_bhavcopy():
    """Download NSE bhavcopy CSV for most recent trading day"""
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
    """Detect column names (NSE changes format sometimes)"""
    if df is None:
        return None, None, None, None
    cols = df.columns.tolist()
    sym   = next((c for c in cols if c.strip() in ['TckrSymb', 'SYMBOL']), None)
    close = next((c for c in cols if c.strip() in ['ClsPric', 'CLOSE']), None)
    prev  = next((c for c in cols if c.strip() in ['PrvsClsgPric', 'PREVCLOSE']), None)
    series= next((c for c in cols if c.strip() in ['SctySrs', 'SERIES']), None)
    return sym, close, prev, series


def fetch_stock_changes(tickers, df):
    """Get % change for list of tickers from bhavcopy"""
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
    """Fetch index data from NSE API"""
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
                "NIFTY 50":       "Nifty 50",
                "NIFTY BANK":     "Nifty Bank",
                "NIFTY NEXT 50":  "Nifty Next 50",
                "NIFTY MIDCAP 50":"Nifty Midcap",
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
#  SECTION 3 — GOLD & SILVER (GoodReturns scraping)
# ─────────────────────────────────────────────────────────────
def get_gold_silver_prices():
    result = {
        "gold_inr_10g": None, "silver_inr_kg": None,
        "gold_jaipur_22k": None, "gold_jaipur_24k": None,
        "silver_jaipur_kg": None,
        "gold_change_pct": None, "silver_change_pct": None,
        "usd_inr": None,
    }
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })

        # ── Gold ──
        r = session.get("https://www.goodreturns.in/gold-rates/jaipur.html", timeout=20)
        if r.status_code == 200:
            text = r.text
            # Extract 22K rate (per 10 grams)
            m22 = re.search(r'22\s*[Kk][^<\d]{0,30}?([\d,]{5,8})', text)
            m24 = re.search(r'24\s*[Kk][^<\d]{0,30}?([\d,]{5,8})', text)
            if m22:
                val = float(m22.group(1).replace(',', ''))
                if 40000 < val < 200000:   # sanity check
                    result['gold_jaipur_22k'] = val
            if m24:
                val = float(m24.group(1).replace(',', ''))
                if 40000 < val < 200000:
                    result['gold_jaipur_24k'] = val
                    result['gold_inr_10g'] = round(val * 0.95, 0)  # approx intl base

            # Try to get yesterday's rate for % change
            m22_y = re.findall(r'([\d,]{5,8})', text)
            # Change % will show in the page
            pct_match = re.search(r'([+-]?\d+\.?\d*)\s*%', text)
            if pct_match:
                result['gold_change_pct'] = float(pct_match.group(1))

        time.sleep(1)

        # ── Silver ──
        r2 = session.get("https://www.goodreturns.in/silver-rate/jaipur.html", timeout=20)
        if r2.status_code == 200:
            text2 = r2.text
            # Silver per kg in Jaipur range: 80,000–1,50,000
            matches = re.findall(r'([\d,]{5,7})', text2)
            for m in matches:
                val = float(m.replace(',', ''))
                if 70000 < val < 200000:
                    result['silver_jaipur_kg'] = val
                    result['silver_inr_kg'] = round(val * 0.97, 0)
                    break
            pct_match2 = re.search(r'([+-]?\d+\.?\d*)\s*%', text2)
            if pct_match2:
                result['silver_change_pct'] = float(pct_match2.group(1))

    except Exception as e:
        print(f"Gold/Silver error: {e}")

    return result


# ─────────────────────────────────────────────────────────────
#  SECTION 4 — DIVERSIFICATION DATA (from bhavcopy)
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
        ("EMBASSY",   "Embassy Office Parks REIT",    "India's largest REIT. Owns premium offices in Bengaluru, Mumbai."),
        ("MINDSPACE", "Mindspace Business Parks REIT","Office parks REIT. Pays quarterly rental income."),
        ("NEXUS",     "Nexus Select Trust REIT",      "India's first retail (malls) REIT. Dividend income."),
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
                        entry["price"] = round(last, 2)
                        entry["pct_change"] = pct
                except Exception:
                    pass
            cat_results.append(entry)
        output[category] = cat_results
    return output


# ─────────────────────────────────────────────────────────────
#  SECTION 5 — GEMINI AI ANALYSIS (1.5 Flash, no search needed)
# ─────────────────────────────────────────────────────────────
def get_ai_analysis(index_perf, falling_stocks, gold_silver, div_data):
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
        f"  {s['ticker']}: fell {abs(s['pct_change']):.1f}% to ₹{s['last_close']}"
        for s in top_fallers
    ]) or "  No major fallers today — market was stable"

    gs = gold_silver
    gold_line   = f"Gold 22K Jaipur: ₹{gs['gold_jaipur_22k']:,.0f}/10g | 24K: ₹{gs['gold_jaipur_24k']:,.0f}/10g" if gs.get("gold_jaipur_22k") else "Gold: data unavailable"
    silver_line = f"Silver Jaipur: ₹{gs['silver_jaipur_kg']:,.0f}/kg" if gs.get("silver_jaipur_kg") else "Silver: data unavailable"

    today = datetime.now(IST).strftime("%d %B %Y")

    prompt = f"""
Today is {today}. You are writing a friendly morning investment update for a complete beginner in Jaipur, India.
They want simple plain-English advice — NO complicated finance jargon.

Here is yesterday's market data:

STOCK MARKET:
{index_lines}

BIGGEST STOCK FALLS:
{stock_lines}

GOLD & SILVER (Jaipur rates):
{gold_line}
{silver_line}

Please write a friendly morning update with EXACTLY these 5 sections.
Use simple language a Class 10 student can understand. Keep each section SHORT (3-5 lines max).
Do NOT use bullet points — write in short sentences.

== WHY DID THE MARKET MOVE? ==
Based on the data above, explain in 3 simple sentences what happened. Pretend you're texting a friend.

== IS THIS A GOOD TIME TO BUY STOCKS? ==
Based on the data, should a beginner consider buying? Give one clear opinion. Mention 1-2 specific stocks if relevant.

== GOLD & SILVER UPDATE ==
Comment on whether gold/silver is at a good level to buy. Should someone in Jaipur buy physical gold, Gold ETF, or Sovereign Gold Bond?

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
                max_output_tokens=1000,
            ),
        )
        return response.text if response.text else "AI analysis not available today."
    except Exception as e:
        print(f"Gemini error: {e}")
        return f"AI analysis unavailable today. Please check tomorrow's email for full analysis."


# ─────────────────────────────────────────────────────────────
#  EMAIL BUILDER (unchanged from v2)
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
        return '<p style="color:#27ae60;font-size:13px;margin:6px 0">✅ No stocks crossed this threshold yesterday — market held up here.</p>'
    rows = "".join(f"""
    <tr style="border-bottom:1px solid #fce8e8">
      <td style="padding:8px 10px;font-weight:600;font-size:13px">{s['ticker']}</td>
      <td style="padding:8px 10px;font-size:13px;text-align:right">₹{s['last_close']:,.2f}</td>
      <td style="padding:8px 10px;text-align:right">{pct_badge(s['pct_change'])}</td>
      <td style="padding:8px 10px;font-size:12px;color:#888;text-align:right">was ₹{s['prev_close']:,.2f}</td>
    </tr>""" for s in filtered)
    return f"""
    <table style="width:100%;border-collapse:collapse;margin-top:8px">
      <tr style="background:#c0392b;color:white;font-size:12px">
        <th style="padding:8px 10px;text-align:left">Stock</th>
        <th style="padding:8px 10px;text-align:right">Price</th>
        <th style="padding:8px 10px;text-align:right">Fall</th>
        <th style="padding:8px 10px;text-align:right">Previous</th>
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
      ⚠️ Rates from GoodReturns.in — always confirm with your local jeweller before buying.
    </p>"""


def diversification_section(div_data):
    html = ""
    icons = {"ETFs": "📦", "REITs": "🏢", "InvITs": "🏗️", "Government": "🏛️"}
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


def build_email(index_perf, falling, gold_silver, div_data, ai_text, trade_date):
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
    You don't need to act on everything — just read and learn!
  </div>

  <div style="padding:22px 28px">

    <h2 style="font-size:15px;color:#2c3e50;margin:0 0 10px">📊 Yesterday's Big Picture</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:22px">{cards}</div>

    <h2 style="font-size:15px;color:#2c3e50;margin:0 0 4px">🥇 Gold & Silver — Jaipur Rates</h2>
    <p style="font-size:12px;color:#888;margin:0 0 8px">
      Buying gold? These rates help you know if today is cheaper or pricier than yesterday.
    </p>
    {gold_silver_section(gold_silver)}

    <h2 style="font-size:15px;color:#2c3e50;margin:22px 0 4px">📉 Stocks That Fell Yesterday</h2>
    <p style="font-size:12px;color:#888;margin:0 0 8px">
      A fall isn't always bad — sometimes it's a chance to buy good companies cheaper.
    </p>

    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#c0392b;margin-bottom:4px">🔴 Nifty 50 — fell more than 2%</div>
      <div style="font-size:11px;color:#888;margin-bottom:6px">India's 50 biggest companies.</div>
      {stock_table(falling.get("nifty50", []), -2)}
    </div>

    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#e67e22;margin-bottom:4px">🟠 Next 50 — fell more than 2%</div>
      <div style="font-size:11px;color:#888;margin-bottom:6px">The next 50 biggest companies.</div>
      {stock_table(falling.get("next50", []), -2)}
    </div>

    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#2980b9;margin-bottom:4px">🔵 Midcap — fell more than 3%</div>
      <div style="font-size:11px;color:#888;margin-bottom:6px">Medium-sized companies.</div>
      {stock_table(falling.get("midcap", []), -3)}
    </div>

    <div style="margin-bottom:22px">
      <div style="font-size:13px;font-weight:600;color:#8e44ad;margin-bottom:4px">🟣 Smallcap — fell more than 3%</div>
      <div style="font-size:11px;color:#888;margin-bottom:6px">Smaller companies. Most risky.</div>
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
    Morning Investment Brief · Powered by Gemini AI + NSE Data · Made for Jaipur 🌄
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

    print("🥇 Fetching Gold & Silver from GoodReturns...")
    gold_silver = get_gold_silver_prices()

    print("🌈 Processing diversification data...")
    div_data = fetch_diversification_data(df)

    print("🤖 Getting Gemini AI analysis...")
    ai_text = get_ai_analysis(index_perf, falling, gold_silver, div_data)

    print("📧 Sending email...")
    nifty_chg = index_perf.get("Nifty 50", {}).get("change", 0)
    date_str  = datetime.now(IST).strftime("%d %b")
    subject   = f"🌅 {date_str} Morning Brief: Nifty {nifty_chg:+.2f}% | Your Daily Investment Update"
    html      = build_email(index_perf, falling, gold_silver, div_data, ai_text, trade_date)
    send_email(html, subject)

    print("✅ Done!\n")


if __name__ == "__main__":
    run()
