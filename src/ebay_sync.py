from __future__ import annotations

import base64
import time
from typing import Optional

import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError

import config
from src import db
from src.alerts import send_telegram

# ---------------------------------------------------------------------------
# Token cache
# ---------------------------------------------------------------------------

_token_cache: dict = {"access_token": None, "expires_at": 0.0}


def get_access_token() -> str:
    """Return a valid eBay OAuth access token, refreshing if near expiry."""
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    credentials = f"{config.EBAY_CLIENT_ID}:{config.EBAY_CLIENT_SECRET}"
    encoded = base64.b64encode(credentials.encode()).decode()

    response = requests.post(
        f"{config.EBAY_BASE_URL}/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": config.EBAY_REFRESH_TOKEN,
            "scope": "https://api.ebay.com/oauth/api_scope/sell.inventory",
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + int(data.get("expires_in", 7200))
    logger.debug("eBay access token refreshed")
    return _token_cache["access_token"]


# ---------------------------------------------------------------------------
# Core API call
# ---------------------------------------------------------------------------


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=10, max=60))
def sync_ebay_listing(sku: str, quantity: int) -> None:
    """PUT inventory_item for *sku* with the given *quantity*.

    Decorated with tenacity: 3 attempts, exponential back-off 10–60 s.
    Raises on final failure so callers can catch RetryError.
    """
    token = get_access_token()
    url = f"{config.EBAY_BASE_URL}/sell/inventory/v1/inventory_item/{sku}"
    payload = {
        "availability": {
            "shipToLocationAvailability": {
                "quantity": quantity,
            }
        }
    }
    response = requests.put(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Content-Language": "en-US",
        },
        timeout=15,
    )
    response.raise_for_status()
    logger.debug(f"eBay PUT {sku} → qty={quantity} ({response.status_code})")


# ---------------------------------------------------------------------------
# High-level actions
# ---------------------------------------------------------------------------


def pause_listing(product: dict) -> None:
    """Set quantity to 0 for *product*'s eBay listing and log the result."""
    sku = product["ebay_listing_id"]
    product_id = product["id"]
    name = product.get("name", product_id)

    try:
        sync_ebay_listing(sku, 0)
        db.log_sync(product_id, "ebay", "pause", success=True)
        logger.info(f"eBay paused: {name} (sku={sku})")
    except RetryError as exc:
        error_msg = str(exc)
        db.log_sync(product_id, "ebay", "pause", success=False, error_msg=error_msg)
        send_telegram(
            f"❌ eBay sync failed for {name} — manual action required\n"
            f"Action: pause\nError: {error_msg}"
        )
        logger.error(f"eBay pause failed after retries: {name} — {error_msg}")


def restore_listing(product: dict) -> None:
    """Restore quantity (capped at MAX_EBAY_QUANTITY) and log the result."""
    sku = product["ebay_listing_id"]
    product_id = product["id"]
    name = product.get("name", product_id)
    stock_qty: int = int(product.get("stock_qty") or 0)
    quantity = min(stock_qty, config.MAX_EBAY_QUANTITY)

    try:
        sync_ebay_listing(sku, quantity)
        db.log_sync(product_id, "ebay", "reactivate", success=True)
        logger.info(f"eBay restored: {name} (sku={sku}, qty={quantity})")
    except RetryError as exc:
        error_msg = str(exc)
        db.log_sync(product_id, "ebay", "reactivate", success=False, error_msg=error_msg)
        send_telegram(
            f"❌ eBay sync failed for {name} — manual action required\n"
            f"Action: reactivate\nError: {error_msg}"
        )
        logger.error(f"eBay restore failed after retries: {name} — {error_msg}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _should_skip(product: dict) -> Optional[str]:
    """Return a skip reason string, or None if the product should be processed."""
    if not product.get("ebay_listing_id"):
        return "no ebay_listing_id"
    if product.get("platform") == "etsy":
        return "platform=etsy"
    return None


def run_ebay_sync() -> None:
    """Evaluate all products and pause/restore eBay listings as needed.

    Trigger logic
    -------------
    - status=out_of_stock  + alerted=False → pause listing
    - status in {in_stock, low_stock} + alerted=True → restore listing
    """
    all_products = db.get_all_products()

    for product in all_products:
        reason = _should_skip(product)
        if reason:
            logger.debug(f"eBay skip {product.get('name', product['id'])}: {reason}")
            continue

        status = product.get("status", "")
        alerted = product.get("alerted", False)
        name = product.get("name", product["id"])

        if status == "out_of_stock" and not alerted:
            logger.info(f"eBay trigger pause: {name}")
            pause_listing(product)
            time.sleep(config.SYNC_DELAY_SECS)

        elif status in ("in_stock", "low_stock") and alerted:
            logger.info(f"eBay trigger restore: {name}")
            restore_listing(product)
            time.sleep(config.SYNC_DELAY_SECS)

        else:
            logger.debug(f"eBay no action: {name} (status={status}, alerted={alerted})")
