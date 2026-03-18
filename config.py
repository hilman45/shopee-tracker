# config.py — All configurable values. Edit these to tune system behaviour.

import os
from dotenv import load_dotenv

load_dotenv()

# ── Supabase ──────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# ── Telegram ──────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ── eBay ──────────────────────────────────────────────────────
EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
EBAY_REFRESH_TOKEN = os.getenv("EBAY_REFRESH_TOKEN")
EBAY_SANDBOX = os.getenv("EBAY_SANDBOX", "False").lower() == "true"
EBAY_BASE_URL = "https://api.sandbox.ebay.com" if EBAY_SANDBOX else "https://api.ebay.com"
EBAY_FEE_RATE = 0.1325          # 13.25% final value fee
MAX_EBAY_QUANTITY = 999          # cap when restoring stock

# ── Etsy ──────────────────────────────────────────────────────
ETSY_CLIENT_ID = os.getenv("ETSY_CLIENT_ID")
ETSY_REFRESH_TOKEN = os.getenv("ETSY_REFRESH_TOKEN")
ETSY_SHOP_ID = os.getenv("ETSY_SHOP_ID")
ETSY_FEE_RATE = 0.065           # 6.5% transaction fee
ETSY_LISTING_FEE = 0.20         # $0.20 per transaction

# ── FX Rate ───────────────────────────────────────────────────
FX_API_URL = "https://api.frankfurter.app/latest?from=MYR&to=USD"
FX_FETCH_INTERVAL_HOURS = 6
FX_ALERT_THRESHOLD = 0.02       # alert if rate shifts > 2% in 24h

# ── Stock Thresholds ──────────────────────────────────────────
LOW_STOCK_THRESHOLD = 10        # units — below this = low_stock
SCRAPE_INTERVAL_HOURS = 2
SCRAPE_DELAY_MIN = 3.0          # seconds between scrape requests
SCRAPE_DELAY_MAX = 6.0          # seconds between scrape requests (random)
SYNC_DELAY_SECS = 1.0           # seconds between API calls in sync loops

# ── Margin ────────────────────────────────────────────────────
MIN_MARGIN_PCT = 20.0           # alert when margin falls below this %
MARGIN_ALERT_DEBOUNCE_HOURS = 6 # min hours between same margin alert

# ── Startup validation ────────────────────────────────────────

_REQUIRED = {
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    "EBAY_CLIENT_ID": EBAY_CLIENT_ID,
    "EBAY_CLIENT_SECRET": EBAY_CLIENT_SECRET,
    "EBAY_REFRESH_TOKEN": EBAY_REFRESH_TOKEN,
    "ETSY_CLIENT_ID": ETSY_CLIENT_ID,
    "ETSY_REFRESH_TOKEN": ETSY_REFRESH_TOKEN,
    "ETSY_SHOP_ID": ETSY_SHOP_ID,
}

for _name, _value in _REQUIRED.items():
    if _value is None:
        raise ValueError(
            f"Required environment variable {_name!r} is not set. "
            "Add it to your .env file or shell environment."
        )

del _REQUIRED, _name, _value
