# Etsy Listing Sync — Spec

## File: `src/etsy_sync.py`

## Purpose
Automatically pause Etsy listings when a supplier goes out of stock, and reactivate them when stock recovers. Uses the Etsy Open API v3 with OAuth 2.0.

---

## Libraries
```
requests
loguru
tenacity
```

---

## API Details
- **API**: Etsy Open API v3
- **Base URL**: `https://openapi.etsy.com/v3/`
- **Auth**: OAuth 2.0 (PKCE flow for initial setup, then refresh tokens)
- **Rate limit**: 10 requests/second per OAuth token
- **Docs**: https://developers.etsy.com/documentation/

---

## OAuth Token Management

Etsy access tokens expire every **3600 seconds** (1 hour).

```python
def get_access_token():
    # POST to https://api.etsy.com/v3/public/oauth/token
    # with grant_type=refresh_token
    # Cache access token with expiry timestamp
    # Auto-refresh 5 minutes before expiry
```

Store in `.env`:
```
ETSY_CLIENT_ID=
ETSY_ACCESS_TOKEN=       # short-lived, refresh automatically
ETSY_REFRESH_TOKEN=      # long-lived
ETSY_SHOP_ID=            # your numeric Etsy shop ID
```

---

## Sync Actions

### Pause listing (out of stock)
```
PATCH /v3/application/shops/{shop_id}/listings/{listing_id}
```
Body: `{ "state": "inactive" }`

### Reactivate listing (stock recovered)
```
PATCH /v3/application/shops/{shop_id}/listings/{listing_id}
```
Body: `{ "state": "active", "quantity": {stock_qty} }`

---

## Trigger Conditions
| Event | Action |
|---|---|
| `status` → `out_of_stock` | Set Etsy listing state to `inactive` |
| `status` → `in_stock` or `low_stock` (was out_of_stock) | Set Etsy listing state to `active`, restore quantity |
| `status` → `low_stock` (was in_stock) | Send Telegram alert only — do NOT deactivate |

---

## Implementation Notes
- The `etsy_listing_id` column in `products` stores the Etsy listing ID (numeric)
- Skip products where `etsy_listing_id` is null or empty
- Skip products where `platform` is `'ebay'` only
- After a successful sync, log to `sync_log` table (action, success=True)
- After a failed sync, log to `sync_log` table (action, success=False, error_msg)
- Respect rate limits — add small delay between batch sync calls if syncing many products at once

---

## Retry Logic
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=10, max=60))
def sync_etsy_listing(listing_id, state, quantity=None):
    ...
```

If all retries fail:
- Log the failure to `sync_log`
- Send a Telegram alert: "Etsy sync failed for {product_name} — manual action required"

---

## Initial Setup Steps (do once)
1. Create Etsy developer account at developers.etsy.com
2. Create an app → get `Client ID`
3. Use PKCE OAuth flow to get initial `Access Token` and `Refresh Token`
   - Scopes needed: `listings_w listings_r`
4. Get your `Shop ID` from your Etsy shop settings URL
5. Add all to `.env`

---

## Finding Your Listing IDs
Run this once to get all your listing IDs and populate the `etsy_listing_id` column:
```
GET /v3/application/shops/{shop_id}/listings/active
```
Returns all active listings with their IDs and titles — match to your products manually or by title search.
