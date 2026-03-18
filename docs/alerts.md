# Alert Engine — Spec

## File: `src/alerts.py`

## Purpose
Evaluate stock and margin rules after each scrape/margin cycle and send Telegram notifications when thresholds are breached.

---

## Libraries
```
requests
loguru
```

---

## Telegram Setup
- Create a bot via @BotFather on Telegram → get `TELEGRAM_BOT_TOKEN`
- Get your `TELEGRAM_CHAT_ID` by messaging @userinfobot
- Send messages via: `POST https://api.telegram.org/bot{token}/sendMessage`

---

## Alert Types

### 1. Out of Stock
**Trigger**: `status` changed to `out_of_stock` AND `alerted = False`

**Message format**:
```
🔴 OUT OF STOCK

Product: {product_name}
Stock: 0 units
Supplier: {supplier_url}
Time: {timestamp}

eBay and Etsy listings have been paused automatically.
```

### 2. Low Stock
**Trigger**: `status` changed to `low_stock` AND `alerted = False`

**Message format**:
```
🟡 LOW STOCK WARNING

Product: {product_name}
Stock remaining: {stock_qty} units
Supplier: {supplier_url}
Time: {timestamp}
```

### 3. Stock Recovered
**Trigger**: `status` changed from `out_of_stock` to `in_stock` or `low_stock`

**Message format**:
```
🟢 STOCK RECOVERED

Product: {product_name}
Stock: {stock_qty} units
Supplier: {supplier_url}
Listings on eBay and Etsy have been reactivated.
```

### 4. Margin Below Minimum
**Trigger**: `margin_pct < MIN_MARGIN_PCT` AND last alert > 6 hours ago

**Message format**:
```
⚠️ LOW MARGIN ALERT

Product: {product_name}
Current margin: {margin_pct}% (minimum: {MIN_MARGIN_PCT}%)
Net profit: ${net_margin_usd} USD
Selling price: ${selling_price_usd} USD
Supplier cost: RM{supplier_price_myr} (≈ ${supplier_cost_usd} USD)

Check if you need to raise your listing price.
```

### 5. Negative Margin (URGENT)
**Trigger**: `margin_pct < 0`

**Message format**:
```
🚨 URGENT — SELLING AT A LOSS

Product: {product_name}
Margin: {margin_pct}%
Loss per sale: ${abs(net_margin_usd)} USD

Action required: pause or reprice this listing immediately.
Supplier URL: {supplier_url}
```

### 6. Supplier Price Increase
**Trigger**: `supplier_price_myr` increased since last scrape

**Message format**:
```
📈 SUPPLIER PRICE INCREASE

Product: {product_name}
Old price: RM{old_price}
New price: RM{new_price} (+{pct_change}%)
New margin: {margin_pct}%

Review your listing price on eBay/Etsy.
```

### 7. FX Rate Shift
**Trigger**: MYR/USD rate changed by > 2% compared to 24 hours ago

**Message format**:
```
💱 FX RATE SHIFT

New rate: 1 MYR = {rate} USD
Change: {direction} {pct_change}% in 24h

{n} products affected.
Worst margin impact: {product_name} → {margin_pct}%
```

---

## Alert Logic Rules
- After sending an alert, set `alerted = True` on the product
- Reset `alerted = False` when status recovers (so next event triggers fresh alert)
- Margin alerts: check `margin_alerted_at` — skip if alerted within 6 hours
- Update `margin_alerted_at` after sending a margin alert
- Never send duplicate alerts for the same unresolved event

---

## Error Handling
- If Telegram API call fails: retry up to 3 times
- If all retries fail: log the error and write unsent alert to a local `failed_alerts.log`
- Never crash the main process because an alert failed to send
