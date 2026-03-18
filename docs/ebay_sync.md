# eBay Listing Sync — Spec

## File: `src/ebay_sync.py`

## Purpose
Automatically pause eBay listings when a supplier goes out of stock, and reactivate them when stock recovers. Uses the eBay Inventory API with OAuth 2.0.

---

## Libraries
```
requests
loguru
tenacity
```

---

## API Details
- **API**: eBay Inventory API (REST)
- **Base URL**: `https://api.ebay.com/sell/inventory/v1/`
- **Auth**: OAuth 2.0 — use refresh token to get access token
- **Docs**: https://developer.ebay.com/api-docs/sell/inventory/overview.html

---

## OAuth Token Management

eBay access tokens expire every **2 hours**. Use the refresh token to get a new one automatically.

```python
def get_access_token():
    # POST to https://api.ebay.com/identity/v1/oauth2/token
    # with grant_type=refresh_token
    # Store access token in memory with expiry time
    # Auto-refresh before expiry
```

Store in `.env`:
```
EBAY_CLIENT_ID=
EBAY_CLIENT_SECRET=
EBAY_REFRESH_TOKEN=      # long-lived, obtained during initial OAuth setup
```

---

## Sync Actions

### Pause listing (out of stock)
```
PUT /sell/inventory/v1/inventory_item/{sku}
```
Set `availability.shipToLocationAvailability.quantity` to `0`.

eBay automatically marks the listing as out of stock when quantity = 0.

### Reactivate listing (stock recovered)
Same endpoint — restore quantity to the product's current `stock_qty` (capped at `config.MAX_EBAY_QUANTITY`).

---

## Trigger Conditions
| Event | Action |
|---|---|
| `status` → `out_of_stock` | Set eBay quantity to 0 |
| `status` → `in_stock` or `low_stock` (was out_of_stock) | Restore eBay quantity |
| `status` → `low_stock` (was in_stock) | Send Telegram alert only — do NOT pause |

---

## Implementation Notes
- The `ebay_listing_id` column in `products` stores the eBay SKU
- Skip products where `ebay_listing_id` is null or empty
- Skip products where `platform` is `'etsy'` only
- After a successful sync, log to `sync_log` table (action, success=True)
- After a failed sync, log to `sync_log` table (action, success=False, error_msg)

---

## Retry Logic
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=10, max=60))
def sync_ebay_listing(sku, quantity):
    ...
```

If all retries fail:
- Log the failure to `sync_log`
- Send a Telegram alert: "eBay sync failed for {product_name} — manual action required"

---

## Initial Setup Steps (do once)
1. Create eBay developer account at developer.ebay.com
2. Create an app → get `Client ID` and `Client Secret`
3. Use OAuth flow to get initial `Refresh Token` (production scope: `sell.inventory`)
4. Add all three to `.env`

---

## Sandbox Testing
- Use `https://api.sandbox.ebay.com/` for testing
- Set `EBAY_SANDBOX=True` in `.env` during development
- Switch to production URL before going live
