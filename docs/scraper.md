# Stock Watcher — Scraper Spec

## File: `src/scraper.py`

## Purpose
Periodically visit each Shopee supplier URL from the `products` table, extract stock quantity and price, and write the results back to Supabase.

---

## Schedule
- Runs every **2 hours** via cron or `schedule` library
- Triggered from `src/main.py`

---

## Libraries
```
requests
beautifulsoup4
playwright        # fallback for JS-rendered pages
loguru
tenacity          # retry logic
```

---

## Core Logic

### 1. Fetch product list
- Load all rows from `products` table via `db.get_all_products()`

### 2. Scrape each URL
For each product:
- Send HTTP GET to `supplier_url`
- Set a realistic `User-Agent` header (rotate from a list of 5+)
- Parse HTML with BeautifulSoup
- Extract:
  - `stock_qty` — integer, or 0 if "Sold Out" / unavailable
  - `supplier_price_myr` — float, strip "RM" and commas

### 3. Determine status
```python
LOW_STOCK_THRESHOLD = config.LOW_STOCK_THRESHOLD  # default 10

if stock_qty == 0:
    status = 'out_of_stock'
elif stock_qty <= LOW_STOCK_THRESHOLD:
    status = 'low_stock'
else:
    status = 'in_stock'
```

### 4. Write to database
- Call `db.update_product_stock(product_id, stock_qty, supplier_price_myr, status)`
- Update `last_checked` timestamp

### 5. Trigger downstream
After each scrape batch completes:
- Call `margin.calculate_all()` to recalculate margins
- Call `alerts.check_and_send()` to evaluate alert rules

---

## Rate Limiting & Politeness
- **Minimum 3-second delay** between each request (`time.sleep(3)`)
- Randomise delay: `time.sleep(random.uniform(3, 6))`
- Rotate User-Agent headers on every request
- If HTTP 429 received: wait 60 seconds, then retry

---

## Retry Logic
Use `tenacity` for retries:
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=5, max=30))
def scrape_product(url):
    ...
```

---

## Error Handling
- If a single product fails after 3 retries: log the error, skip it, continue with next product
- If Shopee returns a CAPTCHA or bot block (status 403/429): log warning, stop scraping for 30 minutes
- Never crash the whole run because one product failed

---

## Playwright Fallback
Some Shopee pages are JavaScript-rendered. If BeautifulSoup returns no stock data:
- Fall back to Playwright headless browser
- Use `playwright.chromium.launch(headless=True)`
- Wait for the stock element to appear before scraping

---

## Shopee Data Extraction Hints
Shopee product pages typically expose stock data in:
- A `__NEXT_DATA__` JSON script tag (preferred — parse JSON directly)
- Or HTML elements with classes like `stock`, `quantity`, `product-stock`

Always try JSON extraction first before HTML parsing.

---

## Logging
Use `loguru`. Log at minimum:
```
INFO  Scraping product: {product_name} ({url})
INFO  Result: stock={stock_qty}, price=RM{price}, status={status}
ERROR Failed to scrape {url}: {error}
WARNING Bot block detected — pausing for 30 minutes
```
