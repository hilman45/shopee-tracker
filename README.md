# Shopee Supplier Stock Tracker

Automated inventory monitoring for a Malaysia-based dropshipper selling on eBay and Etsy.

- **Supplier**: Shopee Malaysia (MYR)
- **Sales**: eBay + Etsy (USD)
- **Stack**: Python, Supabase, Telegram Bot, eBay API, Etsy API

## Quick Start

```bash
# 1. Clone and install
pip install -r requirements.txt
playwright install chromium

# 2. Copy and fill in your secrets
cp .env.example .env

# 3. Set up Supabase — run the SQL in docs/schema.md in the Supabase SQL editor

# 4. Run the system
python src/main.py
```

## Project Docs
All feature specs are in `/docs`. Reference these when working with Cursor AI:

| File | Contents |
|---|---|
| `docs/overview.md` | Goals, context, success metrics |
| `docs/schema.md` | Full database schema + key queries |
| `docs/scraper.md` | Shopee stock watcher spec |
| `docs/margin.md` | FX rate fetcher + margin calculator |
| `docs/alerts.md` | Telegram alert types and message formats |
| `docs/ebay_sync.md` | eBay Inventory API sync spec |
| `docs/etsy_sync.md` | Etsy Open API v3 sync spec |

## Environment Variables
See `.env.example` for all required variables.

## Build Order
1. Database setup (Supabase schema)
2. Stock watcher (`src/scraper.py`)
3. FX fetcher + margin calculator (`src/margin.py`)
4. Telegram alerts (`src/alerts.py`)
5. eBay sync (`src/ebay_sync.py`)
6. Etsy sync (`src/etsy_sync.py`)
7. Main scheduler (`src/main.py`)
