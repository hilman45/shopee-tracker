# Database Schema

## Platform
**Supabase (PostgreSQL)** — use the `supabase-py` Python client.

All database interactions must go through `src/db.py`. No raw SQL or direct Supabase calls elsewhere.

---

## Table: `products`

The main table. One row per tracked supplier product.

```sql
CREATE TABLE products (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_name        TEXT NOT NULL,
  supplier_url        TEXT NOT NULL UNIQUE,
  stock_qty           INTEGER,                        -- null if unknown
  supplier_price_myr  DECIMAL(10, 2),                 -- latest scraped price in MYR
  selling_price_usd   DECIMAL(10, 2),                 -- your listed price on eBay/Etsy in USD
  platform            TEXT DEFAULT 'both',            -- 'ebay', 'etsy', or 'both'
  ebay_listing_id     TEXT,                           -- eBay SKU or listing ID
  etsy_listing_id     TEXT,                           -- Etsy listing ID
  status              TEXT DEFAULT 'in_stock',        -- in_stock | low_stock | out_of_stock
  net_margin_usd      DECIMAL(10, 4),                 -- calculated after each scrape
  margin_pct          DECIMAL(6, 2),                  -- percentage margin
  last_checked        TIMESTAMPTZ,                    -- last successful scrape
  alerted             BOOLEAN DEFAULT FALSE,          -- alert sent for current status?
  margin_alerted_at   TIMESTAMPTZ,                    -- last margin alert sent
  created_at          TIMESTAMPTZ DEFAULT NOW()
);
```

### Status Values
| Value | Meaning |
|---|---|
| `in_stock` | stock_qty > low stock threshold (default: 10) |
| `low_stock` | 0 < stock_qty <= threshold |
| `out_of_stock` | stock_qty = 0 or listing unavailable |

---

## Table: `fx_rates`

Stores MYR/USD exchange rate history. Fetched every 6 hours.

```sql
CREATE TABLE fx_rates (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  myr_to_usd  DECIMAL(10, 6) NOT NULL,   -- e.g. 0.214300
  fetched_at  TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Table: `sync_log`

Tracks every eBay/Etsy sync attempt for auditing and error monitoring.

```sql
CREATE TABLE sync_log (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id   UUID REFERENCES products(id),
  platform     TEXT NOT NULL,             -- 'ebay' or 'etsy'
  action       TEXT NOT NULL,             -- 'pause' or 'reactivate'
  success      BOOLEAN NOT NULL,
  error_msg    TEXT,                      -- null if success
  attempted_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Key Queries (implement in `src/db.py`)

```python
# Get all active products to scrape
get_all_products()

# Update stock and status after scrape
update_product_stock(product_id, stock_qty, supplier_price_myr, status)

# Update calculated margin
update_product_margin(product_id, net_margin_usd, margin_pct)

# Get latest FX rate
get_latest_fx_rate() -> float

# Insert new FX rate
insert_fx_rate(myr_to_usd)

# Get products that are out of stock and not yet synced
get_products_needing_sync(status='out_of_stock')

# Log a sync attempt
log_sync(product_id, platform, action, success, error_msg=None)
```

---

## Supabase Setup Notes
- Create project at supabase.com (free tier)
- Run the SQL above in the Supabase SQL editor
- Copy `SUPABASE_URL` and `SUPABASE_KEY` (anon key) to `.env`
- Enable Row Level Security (RLS) is optional for a solo project
