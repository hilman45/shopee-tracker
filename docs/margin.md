# Margin Tracker — Spec

## File: `src/margin.py`

## Purpose
Fetch the live MYR/USD exchange rate and calculate real-time profit margin per product after every scrape cycle. Alert the user when margins fall below acceptable thresholds.

---

## Libraries
```
requests
loguru
```

---

## Part 1: FX Rate Fetcher

### API
- **URL**: `https://api.frankfurter.app/latest?from=MYR&to=USD`
- Free, no API key required
- Returns JSON: `{ "rates": { "USD": 0.2143 } }`

### Schedule
- Fetch every **6 hours** (independent of scrape schedule)
- Store each fetch as a new row in `fx_rates` table
- Cache the last known rate in memory — use as fallback if API is down

### Fallback
- If API fails: use the most recent rate from the `fx_rates` table
- If no rate exists at all: log a critical error and skip margin calculation

### Logging
```
INFO  FX rate fetched: 1 MYR = {rate} USD
WARNING FX API failed — using cached rate: {rate}
CRITICAL No FX rate available — skipping margin calculation
```

---

## Part 2: Margin Calculator

### Formula
```python
def calculate_margin(supplier_price_myr, selling_price_usd, myr_to_usd, platform):
    supplier_cost_usd = supplier_price_myr * myr_to_usd

    if platform == 'ebay':
        platform_fee = selling_price_usd * config.EBAY_FEE_RATE        # 0.1325
    elif platform == 'etsy':
        platform_fee = (selling_price_usd * config.ETSY_FEE_RATE) + config.ETSY_LISTING_FEE  # 0.065, 0.20
    else:  # 'both' — use the higher fee for conservative estimate
        platform_fee = selling_price_usd * config.EBAY_FEE_RATE

    net_margin_usd = selling_price_usd - supplier_cost_usd - platform_fee
    margin_pct = (net_margin_usd / selling_price_usd) * 100

    return round(net_margin_usd, 4), round(margin_pct, 2)
```

### When to run
- After every scrape batch completes
- After every FX rate fetch (margins may change even if stock didn't)

### What to update
- Write `net_margin_usd` and `margin_pct` back to the `products` table

---

## Part 3: Margin Alert Rules

All alert logic lives in `src/alerts.py` but margin thresholds are defined here in `config.py`.

| Trigger | Default Threshold | Alert Content |
|---|---|---|
| Margin below minimum | `margin_pct < 20%` | Product name, current margin %, cause (price or FX) |
| Supplier price increased | Any increase from last scrape | Old price MYR, new price MYR, new margin % |
| FX rate daily shift | `> 2%` change in 24h | New rate, number of affected products, worst margin drop |
| Negative margin | `margin_pct < 0` | URGENT — product name, loss amount in USD |

### Debounce Rule
- Do not re-alert the same product for the same trigger within **6 hours**
- Track last alert time in `margin_alerted_at` column on `products` table

---

## Config Values (in `config.py`)
```python
MIN_MARGIN_PCT = 20.0          # alert when margin drops below this
EBAY_FEE_RATE = 0.1325         # 13.25%
ETSY_FEE_RATE = 0.065          # 6.5%
ETSY_LISTING_FEE = 0.20        # $0.20 per transaction
FX_ALERT_THRESHOLD = 0.02      # alert on > 2% daily FX shift
MARGIN_ALERT_DEBOUNCE_HOURS = 6
```
