"""
🌅 Indian Morning Investment Alert — v2
Sends daily email at 5 AM IST with:
  • Falling stocks (Nifty 50, Next 50, Midcap, Smallcap)
  • Gold & Silver prices (with Jaipur local rate estimate)
  • Beginner-friendly diversification ideas (REITs, InvITs, ETFs, Bonds, MFs)
  • Plain-English AI news + what-to-do suggestions
"""

import yfinance as yf
import os, re, smtplib, json, requests
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
import google.generativeai as genai
from google.generativeai.types import Tool, GenerateContentConfig

# ─────────────────────────────────────────────────────────────
#  CONFIG  (reads from GitHub Secrets / env vars)
#  For local testing, replace the defaults with your real values
# ─────────────────────────────────────────────────────────────
CONFIG = {
    "email_sender":   os.environ.get("GMAIL_SENDER",   "your_gmail@gmail.com"),
    "email_password": os.environ.get("GMAIL_PASSWORD", "your_app_password"),
    "email_receiver": os.environ.get("GMAIL_RECEIVER", "your_email@gmail.com"),
    "gemini_api_key": os.environ.get("GEMINI_API_KEY", "your_gemini_key"),
}

IST = ZoneInfo("Asia/Kolkata")

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
#  SECTION 1 — STOCK DATA
# ─────────────────────────────────────────────────────────────
def fetch_stock_changes(tickers):
    symbols = [f"{t}.NS" for t in tickers]
    try:
        data = yf.download(symbols, period="5d", progress=False, auto_adjust=True)
        results = []
        for ticker, symbol in zip(tickers, symbols):
            try:
                close = data["Close"][symbol].dropna()
                if len(close) < 2:
                    continue
                prev, last = float(close.iloc[-2]), float(close.iloc[-1])
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
    except Exception as e:
        print(f"Stock fetch error: {e}")
        return []


def get_index_performance():
    indices = {
        "Nifty 50":    "^NSEI",
        "Sensex":      "^BSESN",
        "Nifty Bank":  "^NSEBANK",
        "Nifty Midcap":"^NSEMDCP50",
    }
    results = {}
    for name, sym in indices.items():
        try:
            hist = yf.Ticker(sym).history(period="5d")
            if len(hist) >= 2:
                prev, last = hist["Close"].iloc[-2], hist["Close"].iloc[-1]
                results[name] = {
                    "value":  round(float(last), 2),
                    "change": round(float((last - prev) / prev * 100), 2),
                    "points": round(float(last - prev), 2),
                }
        except Exception:
            pass
    return results


# ─────────────────────────────────────────────────────────────
#  SECTION 2 — GOLD & SILVER
# ─────────────────────────────────────────────────────────────
def get_gold_silver_prices():
    """
    Fetches international gold/silver in USD, converts to INR,
    then calculates Jaipur retail estimate (includes GST + making charges).
    """
    result = {
        "gold_intl_usd_oz": None, "gold_inr_10g": None,
        "silver_intl_usd_oz": None, "silver_inr_kg": None,
        "gold_jaipur_22k": None, "gold_jaipur_24k": None,
        "silver_jaipur_kg": None,
        "gold_change_pct": None, "silver_change_pct": None,
        "usd_inr": None,
    }
    try:
        # USD/INR rate
        fx = yf.Ticker("INR=X").history(period="5d")
        usd_inr = float(fx["Close"].iloc[-1]) if len(fx) >= 1 else 83.5
        result["usd_inr"] = round(usd_inr, 2)

        # Gold (GC=F is COMEX Gold Futures, $/troy oz)
        gold = yf.Ticker("GC=F").history(period="5d")
        if len(gold) >= 2:
            gold_usd_oz = float(gold["Close"].iloc[-1])
            gold_prev    = float(gold["Close"].iloc[-2])
            # 1 troy oz = 31.1035 g → price per gram → per 10g
            gold_inr_10g = (gold_usd_oz / 31.1035) * 10 * usd_inr
            result["gold_intl_usd_oz"] = round(gold_usd_oz, 2)
            result["gold_inr_10g"]     = round(gold_inr_10g, 0)
            result["gold_change_pct"]  = round((gold_usd_oz - gold_prev) / gold_prev * 100, 2)

            # Jaipur retail estimate:
            # 24K = MCX price + ~2% import duty + ~3% GST ≈ multiply by 1.05 + small retail margin
            # 22K = 24K × (22/24)
            gold_24k_jaipur = gold_inr_10g * 1.06   # rough retail markup
            gold_22k_jaipur = gold_24k_jaipur * (22 / 24)
            result["gold_jaipur_24k"] = round(gold_24k_jaipur, 0)
            result["gold_jaipur_22k"] = round(gold_22k_jaipur, 0)

        # Silver (SI=F is COMEX Silver Futures, $/troy oz)
        silver = yf.Ticker("SI=F").history(period="5d")
        if len(silver) >= 2:
            silver_usd_oz = float(silver["Close"].iloc[-1])
            silver_prev   = float(silver["Close"].iloc[-2])
            # 1 kg = 32.1507 troy oz
            silver_inr_kg = silver_usd_oz * 32.1507 * usd_inr
            result["silver_intl_usd_oz"] = round(silver_usd_oz, 2)
            result["silver_inr_kg"]      = round(silver_inr_kg, 0)
            result["silver_change_pct"]  = round((silver_usd_oz - silver_prev) / silver_prev * 100, 2)
            result["silver_jaipur_kg"]   = round(silver_inr_kg * 1.03, 0)  # +3% GST retail

    except Exception as e:
        print(f"Gold/Silver fetch error: {e}")

    return result


# ─────────────────────────────────────────────────────────────
#  SECTION 3 — DIVERSIFICATION OPTIONS
# ─────────────────────────────────────────────────────────────

# Hand-picked beginner-friendly options with Yahoo Finance symbols
DIVERSIFICATION_WATCHLIST = {
    "ETFs (like a basket of stocks — easy & low cost)": [
        ("NIFTYBEES.NS",  "Nifty 50 ETF",        "Tracks the top 50 companies. Best starting point for beginners."),
        ("GOLDBEES.NS",   "Gold ETF",             "Invest in gold without buying physical gold. Safe haven."),
        ("JUNIORBEES.NS", "Next 50 ETF",          "Tracks the next 50 large companies after Nifty 50."),
        ("SILVERBEES.NS", "Silver ETF",           "Invest in silver digitally — no locker needed."),
        ("MOM100.NS",     "Momentum 100 ETF",     "Invests in 100 stocks with strong recent price momentum."),
    ],
    "REITs (earn rental income without buying property)": [
        ("EMBASSY.NS",    "Embassy Office Parks REIT", "India's largest REIT. Owns premium offices in Bengaluru, Mumbai."),
        ("MINDSPACE.NS",  "Mindspace Business Parks REIT", "Office parks REIT. Pays quarterly rental income."),
        ("NEXUS.NS",      "Nexus Select Trust REIT",   "India's first retail (malls) REIT. Dividend income."),
    ],
    "InvITs (earn from infrastructure like roads, power lines)": [
        ("INDIGRID.NS",   "IndiGrid InvIT",      "Power transmission towers. Steady quarterly income."),
        ("POWERGRID-NXT.NS", "PowerGrid InvIT",  "Govt-backed power grid infrastructure. Very stable."),
        ("IRB.NS",        "IRB InvIT",           "Highway toll roads. Income from tolls you pay on highways."),
    ],
    "Government Bonds & Safe Options": [
        ("^GSEC10",       "10-Year G-Sec Yield", "Government bond yield. Higher = bonds more attractive vs stocks."),
    ],
}

def fetch_diversification_data():
    """Fetch price & change for all diversification options"""
    output = {}
    for category, items in DIVERSIFICATION_WATCHLIST.items():
        cat_results = []
        for symbol, name, description in items:
            try:
                hist = yf.Ticker(symbol).history(period="5d")
                if len(hist) >= 2:
                    prev = float(hist["Close"].iloc[-2])
                    last = float(hist["Close"].iloc[-1])
                    pct  = round((last - prev) / prev * 100, 2)
                    cat_results.append({
                        "symbol": symbol, "name": name,
                        "description": description,
                        "price": round(last, 2),
                        "pct_change": pct,
                    })
                else:
                    cat_results.append({
                        "symbol": symbol, "name": name,
                        "description": description,
                        "price": None, "pct_change": None,
                    })
            except Exception:
                cat_results.append({
                    "symbol": symbol, "name": name,
                    "description": description,
                    "price": None, "pct_change": None,
                })
        output[category] = cat_results
    return output


# ─────────────────────────────────────────────────────────────
#  SECTION 4 — GEMINI AI ANALYSIS
# ─────────────────────────────────────────────────────────────
def get_ai_analysis(index_perf, falling_stocks, gold_silver, div_data):
    """
    Calls Gemini 2.0 Flash with Google Search grounding.
    Returns beginner-friendly plain-English analysis.
    """
    genai.configure(api_key=CONFIG["gemini_api_key"])

    # Build context for Gemini
    top_fallers = (falling_stocks.get("nifty50", []) + falling_stocks.get("next50", []))
    top_fallers = sorted(top_fallers, key=lambda x: x["pct_change"])[:8]

    index_lines = "\n".join([
        f"  {k}: {v['change']:+.2f}% (now at {v['value']:,.0f})"
        for k, v in index_perf.items()
    ]) or "  Data unavailable"

    stock_lines = "\n".join([
        f"  {s['ticker']}: fell {abs(s['pct_change']):.1f}% to ₹{s['last_close']}"
        for s in top_fallers
    ]) or "  No major fallers"

    gs = gold_silver
    gold_line   = f"Gold:   ₹{gs['gold_inr_10g']:,.0f}/10g (international), Jaipur 22K ≈ ₹{gs['gold_jaipur_22k']:,.0f} | Change: {gs['gold_change_pct']:+.2f}%" if gs["gold_inr_10g"] else "Gold: data unavailable"
    silver_line = f"Silver: ₹{gs['silver_inr_kg']:,.0f}/kg (international), Jaipur ≈ ₹{gs['silver_jaipur_kg']:,.0f}/kg | Change: {gs['silver_change_pct']:+.2f}%" if gs["silver_inr_kg"] else "Silver: data unavailable"

    today = datetime.now(IST).strftime("%d %B %Y")

    prompt = f"""
Today is {today}. You are writing a friendly morning investment update for a complete beginner in Jaipur, India.
They are busy, don't have much time, and want simple plain-English advice — NO complicated finance jargon.
If you must use a term, explain it in brackets immediately.

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
Do NOT use bullet points inside sections — write in short sentences.

== WHY DID THE MARKET FALL? ==
Search for yesterday's real news. Explain in 3 simple sentences why the market fell. Pretend you're texting a friend.

== IS THIS A GOOD TIME TO BUY STOCKS? ==
Based on the fall, should a beginner consider buying? Give one clear opinion. Mention 1-2 specific fallen stocks that look like decent value and why (very simply).

== GOLD & SILVER UPDATE ==
Comment on whether gold/silver went up or down yesterday. Is it a good time to buy gold or silver? Should someone in Jaipur buy physical gold, Gold ETF (buying gold digitally through stock market), or Sovereign Gold Bond (government gold scheme with extra 2.5% interest)?

== TODAY'S SIMPLE INVESTMENT TIP ==
Give ONE simple, actionable tip for a beginner with ₹1,000–₹10,000 to invest this week. Be very specific (name the exact ETF, fund, or option).

== MARKET MOOD FOR TODAY ==
One sentence prediction for today's market opening. Use everyday words — "market may start low", "likely to recover", etc.

Write in a warm, encouraging tone. The reader is just starting their investment journey.
"""

    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            tools=[Tool(google_search={})]
        )
        response = model.generate_content(
            prompt,
            generation_config=GenerateContentConfig(temperature=0.4, max_output_tokens=1200)
        )
        return response.text if response.text else "AI analysis not available today."
    except Exception as e:
        print(f"Gemini error: {e}")
        try:
            model = genai.GenerativeModel("gemini-2.0-flash")
            response = model.generate_content(prompt)
            return response.text + "\n\n*(Live news search was unavailable today)*"
        except Exception as e2:
            return f"AI analysis unavailable: {e2}"


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
      {row("Gold 22K (Jaipur)", gs.get("gold_jaipur_22k"), gs.get("gold_change_pct"), "Per 10 grams · retail estimate")}
      {row("Gold 24K (Jaipur)", gs.get("gold_jaipur_24k"), gs.get("gold_change_pct"), "Per 10 grams · retail estimate")}
      {row("Gold (International)", gs.get("gold_inr_10g"), gs.get("gold_change_pct"), f"MCX base · USD/INR ≈ {gs.get('usd_inr','—')}")}
      {row("Silver (Jaipur)", gs.get("silver_jaipur_kg"), gs.get("silver_change_pct"), "Per kg · retail estimate")}
      {row("Silver (International)", gs.get("silver_inr_kg"), gs.get("silver_change_pct"), "Per kg · MCX base")}
    </table>
    <p style="font-size:11px;color:#aaa;margin:6px 0 0">
      ⚠️ Jaipur rates are estimates based on international MCX price + GST + retail margin.
      Always confirm with your local jeweller or app like GoodReturns before buying.
    </p>"""


def diversification_section(div_data):
    html = ""
    icons = {
        "ETFs": "📦", "REITs": "🏢", "InvITs": "🏗️", "Government": "🏛️"
    }
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
    """Split AI response into labeled sections for styled rendering"""
    sections = {
        "WHY DID THE MARKET FALL?":       ("📰", "#8e44ad"),
        "IS THIS A GOOD TIME TO BUY STOCKS?": ("🛒", "#c0392b"),
        "GOLD & SILVER UPDATE":           ("🥇", "#b8860b"),
        "TODAY'S SIMPLE INVESTMENT TIP":  ("💡", "#27ae60"),
        "MARKET MOOD FOR TODAY":          ("🔮", "#2980b9"),
    }
    html = ""
    remaining = text
    for title, (icon, color) in sections.items():
        pattern = rf"==\s*{re.escape(title)}\s*=="
        match = re.search(pattern, remaining, re.IGNORECASE)
        if match:
            start = match.end()
            next_match = re.search(r"==\s*[A-Z]", remaining[start:], re.IGNORECASE)
            content = remaining[start: start + next_match.start()].strip() if next_match else remaining[start:].strip()
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


def build_email(index_perf, falling, gold_silver, div_data, ai_text):
    today     = datetime.now(IST).strftime("%A, %d %B %Y")
    nifty_chg = index_perf.get("Nifty 50", {}).get("change", 0)
    bearish   = nifty_chg < 0
    hdr_color = "#b83232" if bearish else "#1e7e34"
    mood      = "BEARISH 🔴 — Falling Day" if bearish else "BULLISH 🟢 — Rising Day"

    # Index summary cards
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

  <!-- HEADER -->
  <div style="background:{hdr_color};padding:22px 28px;color:white">
    <div style="font-size:12px;opacity:.8;margin-bottom:4px">📅 {today} | Your Morning Investment Brief</div>
    <div style="font-size:22px;font-weight:700">Market is {mood}</div>
    <div style="font-size:12px;margin-top:6px;opacity:.85">
      Nifty 50: {nifty_chg:+.2f}% &nbsp;|&nbsp; Sent at 5:00 AM IST &nbsp;|&nbsp; Jaipur, Rajasthan
    </div>
  </div>

  <!-- BEGINNER NOTE -->
  <div style="background:#fffbe6;padding:10px 28px;border-bottom:1px solid #ffe082;
              font-size:12px;color:#7a5c00">
    👋 <strong>New to investing?</strong> This email is written in plain language.
    Numbers with ▼ mean price fell. Numbers with ▲ mean price rose. 
    You don't need to act on everything — just read and learn!
  </div>

  <div style="padding:22px 28px">

    <!-- INDEX CARDS -->
    <h2 style="font-size:15px;color:#2c3e50;margin:0 0 10px">📊 Yesterday's Big Picture</h2>
    <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:22px">{cards}</div>

    <!-- GOLD & SILVER -->
    <h2 style="font-size:15px;color:#2c3e50;margin:0 0 4px">🥇 Gold & Silver — Jaipur Rates</h2>
    <p style="font-size:12px;color:#888;margin:0 0 8px">
      Buying gold? These rates help you know if today is cheaper or pricier than yesterday.
    </p>
    {gold_silver_section(gold_silver)}

    <!-- FALLING STOCKS -->
    <h2 style="font-size:15px;color:#2c3e50;margin:22px 0 4px">📉 Stocks That Fell Yesterday</h2>
    <p style="font-size:12px;color:#888;margin:0 0 8px">
      These are companies whose share price dropped. A fall isn't always bad — 
      sometimes it's a chance to buy good companies cheaper.
    </p>

    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#c0392b;margin-bottom:4px">
        🔴 Nifty 50 stocks — fell more than 2%
      </div>
      <div style="font-size:11px;color:#888;margin-bottom:6px">
        These are India's 50 biggest companies. Very reliable but can also fall on bad days.
      </div>
      {stock_table(falling.get("nifty50", []), -2)}
    </div>

    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#e67e22;margin-bottom:4px">
        🟠 Next 50 stocks — fell more than 2%
      </div>
      <div style="font-size:11px;color:#888;margin-bottom:6px">
        The next biggest 50 companies. Slightly more risky but also more growth potential.
      </div>
      {stock_table(falling.get("next50", []), -2)}
    </div>

    <div style="margin-bottom:14px">
      <div style="font-size:13px;font-weight:600;color:#2980b9;margin-bottom:4px">
        🔵 Midcap stocks — fell more than 3%
      </div>
      <div style="font-size:11px;color:#888;margin-bottom:6px">
        Medium-sized companies. Higher risk, but can give better returns over 3–5 years.
      </div>
      {stock_table(falling.get("midcap", []), -3)}
    </div>

    <div style="margin-bottom:22px">
      <div style="font-size:13px;font-weight:600;color:#8e44ad;margin-bottom:4px">
        🟣 Smallcap stocks — fell more than 3%
      </div>
      <div style="font-size:11px;color:#888;margin-bottom:6px">
        Smaller companies. Most risky — only invest here when you understand the company.
      </div>
      {stock_table(falling.get("smallcap", []), -3)}
    </div>

    <!-- DIVERSIFICATION OPTIONS -->
    <h2 style="font-size:15px;color:#1a3a6b;margin:0 0 4px">
      🌈 Other Ways to Invest — Not Just Stocks
    </h2>
    <p style="font-size:12px;color:#888;margin:0 0 8px">
      Smart investors don't put all money in one place. Here are some beginner-friendly 
      alternatives — all can be bought from your Zerodha / Groww / Upstox app.
    </p>
    {diversification_section(div_data)}

    <!-- QUICK GLOSSARY -->
    <div style="margin-top:22px;background:#f0f4ff;border-radius:8px;padding:14px 16px">
      <div style="font-size:13px;font-weight:600;color:#1a3a6b;margin-bottom:8px">
        📖 Quick Glossary (save this!)
      </div>
      <div style="font-size:12px;color:#444;line-height:2">
        <b>ETF</b> = A basket of stocks you buy in one click. Like buying a thali instead of cooking each dish.<br>
        <b>REIT</b> = You own a tiny part of office buildings and earn rent every 3 months.<br>
        <b>InvIT</b> = Same idea but for roads, power lines, and pipelines.<br>
        <b>Sovereign Gold Bond</b> = Govt gives you gold in paper form + 2.5% extra interest per year.<br>
        <b>SIP</b> = Auto-invest a fixed amount every month. Best habit for beginners.<br>
        <b>NAV</b> = Price of one unit of a mutual fund (like a share price for funds).<br>
        <b>Nifty 50</b> = Index of India's top 50 companies. If it goes up, market is happy.
      </div>
    </div>

    <!-- AI ANALYSIS -->
    <h2 style="font-size:15px;color:#2c3e50;margin:22px 0 8px">
      🤖 Your AI Investment Advisor Says...
    </h2>
    {ai_html}

    <!-- DISCLAIMER -->
    <div style="margin-top:20px;padding:12px 14px;background:#f8f8f8;border-radius:8px;
                font-size:11px;color:#999;text-align:center;line-height:1.6">
      ⚠️ This email is for learning purposes only — not professional financial advice.<br>
      Always invest based on your own research or consult a SEBI-registered advisor.<br>
      Gold rates are estimates — confirm with GoodReturns.in or your local jeweller.
    </div>

  </div>

  <!-- FOOTER -->
  <div style="background:#2c3e50;padding:14px 28px;color:#aaa;font-size:11px;text-align:center">
    Morning Investment Brief · Powered by Gemini AI + Yahoo Finance · Made for Jaipur 🌄
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
    print(f"\n🌅 Starting Morning Investment Alert — {datetime.now(IST).strftime('%d %b %Y %H:%M IST')}\n")

    print("📊 Fetching index performance...")
    index_perf = get_index_performance()

    print("📉 Fetching stock falls...")
    n50   = fetch_stock_changes(NIFTY_50)
    nn50  = fetch_stock_changes(NIFTY_NEXT_50)
    mid   = fetch_stock_changes(NIFTY_MIDCAP)
    small = fetch_stock_changes(NIFTY_SMALLCAP)
    falling = {"nifty50": n50, "next50": nn50, "midcap": mid, "smallcap": small}

    print("🥇 Fetching Gold & Silver prices...")
    gold_silver = get_gold_silver_prices()

    print("🌈 Fetching diversification options...")
    div_data = fetch_diversification_data()

    print("🤖 Getting Gemini AI analysis...")
    ai_text = get_ai_analysis(index_perf, falling, gold_silver, div_data)

    print("📧 Building and sending email...")
    nifty_chg = index_perf.get("Nifty 50", {}).get("change", 0)
    gs_str = ""
    if gold_silver.get("gold_change_pct"):
        gs_str = f" | Gold {gold_silver['gold_change_pct']:+.1f}%"
    date_str = datetime.now(IST).strftime("%d %b")
    subject  = f"🌅 {date_str} Morning Brief: Nifty {nifty_chg:+.2f}%{gs_str} | Your Daily Investment Update"
    html     = build_email(index_perf, falling, gold_silver, div_data, ai_text)
    send_email(html, subject)

    print("✅ Done!\n")


if __name__ == "__main__":
    run()
