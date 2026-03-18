from __future__ import annotations

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

# Refresh 5 minutes before actual expiry
_EARLY_REFRESH_SECS = 300


def get_access_token() -> str:
    """Return a valid Etsy OAuth access token, refreshing if near expiry."""
    if (
        _token_cache["access_token"]
        and time.time() < _token_cache["expires_at"] - _EARLY_REFRESH_SECS
    ):
        return _token_cache["access_token"]

    response = requests.post(
        "https://api.etsy.com/v3/public/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "client_id": config.ETSY_CLIENT_ID,
            "refresh_token": config.ETSY_REFRESH_TOKEN,
        },
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    logger.debug("Etsy access token refreshed")
    return _token_cache["access_token"]


# ---------------------------------------------------------------------------
# Core API call
# ---------------------------------------------------------------------------


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=10, max=60))
def sync_etsy_listing(listing_id: str, state: str, quantity: Optional[int] = None) -> None:
    """PATCH the Etsy listing *state* (and optionally *quantity*).

    Decorated with tenacity: 3 attempts, exponential back-off 10–60 s.
    Raises on final failure so callers can catch RetryError.
    """
    token = get_access_token()
    url = (
        f"https://openapi.etsy.com/v3/application/shops"
        f"/{config.ETSY_SHOP_ID}/listings/{listing_id}"
    )
    payload: dict = {"state": state}
    if quantity is not None:
        payload["quantity"] = quantity

    response = requests.patch(
        url,
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "x-api-key": config.ETSY_CLIENT_ID,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    response.raise_for_status()
    logger.debug(f"Etsy PATCH {listing_id} → state={state}, qty={quantity} ({response.status_code})")


# ---------------------------------------------------------------------------
# High-level actions
# ---------------------------------------------------------------------------


def pause_listing(product: dict) -> None:
    """Set listing state to inactive and log the result."""
    listing_id = str(product["etsy_listing_id"])
    product_id = product["id"]
    name = product.get("name", product_id)

    try:
        sync_etsy_listing(listing_id, state="inactive")
        db.log_sync(product_id, "etsy", "pause", success=True)
        logger.info(f"Etsy paused: {name} (listing_id={listing_id})")
    except RetryError as exc:
        error_msg = str(exc)
        db.log_sync(product_id, "etsy", "pause", success=False, error_msg=error_msg)
        send_telegram(
            f"❌ Etsy sync failed for {name} — manual action required\n"
            f"Action: pause\nError: {error_msg}"
        )
        logger.error(f"Etsy pause failed after retries: {name} — {error_msg}")


def restore_listing(product: dict) -> None:
    """Set listing state to active with current stock_qty and log the result."""
    listing_id = str(product["etsy_listing_id"])
    product_id = product["id"]
    name = product.get("name", product_id)
    stock_qty: int = int(product.get("stock_qty") or 0)

    try:
        sync_etsy_listing(listing_id, state="active", quantity=stock_qty)
        db.log_sync(product_id, "etsy", "reactivate", success=True)
        logger.info(f"Etsy restored: {name} (listing_id={listing_id}, qty={stock_qty})")
    except RetryError as exc:
        error_msg = str(exc)
        db.log_sync(product_id, "etsy", "reactivate", success=False, error_msg=error_msg)
        send_telegram(
            f"❌ Etsy sync failed for {name} — manual action required\n"
            f"Action: reactivate\nError: {error_msg}"
        )
        logger.error(f"Etsy restore failed after retries: {name} — {error_msg}")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _should_skip(product: dict) -> Optional[str]:
    """Return a skip reason string, or None if the product should be processed."""
    if not product.get("etsy_listing_id"):
        return "no etsy_listing_id"
    if product.get("platform") == "ebay":
        return "platform=ebay"
    return None


def run_etsy_sync() -> None:
    """Evaluate all products and pause/restore Etsy listings as needed.

    Trigger logic
    -------------
    - status=out_of_stock  + alerted=False → pause listing
    - status in {in_stock, low_stock} + alerted=True → restore listing
    """
    all_products = db.get_all_products()

    for product in all_products:
        reason = _should_skip(product)
        if reason:
            logger.debug(f"Etsy skip {product.get('name', product['id'])}: {reason}")
            continue

        status = product.get("status", "")
        alerted = product.get("alerted", False)
        name = product.get("name", product["id"])

        if status == "out_of_stock" and not alerted:
            logger.info(f"Etsy trigger pause: {name}")
            pause_listing(product)
            time.sleep(config.SYNC_DELAY_SECS)

        elif status in ("in_stock", "low_stock") and alerted:
            logger.info(f"Etsy trigger restore: {name}")
            restore_listing(product)
            time.sleep(config.SYNC_DELAY_SECS)

        else:
            logger.debug(f"Etsy no action: {name} (status={status}, alerted={alerted})")
