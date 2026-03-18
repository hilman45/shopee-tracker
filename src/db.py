from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from supabase import Client, create_client

from config import SUPABASE_KEY, SUPABASE_URL

_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------


def get_all_products() -> list[dict]:
    """Return every row in the products table."""
    response = _client.table("products").select("*").execute()
    return response.data


def update_product_stock(
    product_id: str,
    stock_qty: Optional[int],
    supplier_price_myr: Optional[float],
    status: str,
) -> dict:
    """Update stock, price and status after a scrape.

    Also stamps last_checked to now and resets alerted so that a fresh alert
    can be sent if the status has changed.
    """
    payload: dict = {
        "stock_qty": stock_qty,
        "status": status,
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "alerted": False,
    }
    if supplier_price_myr is not None:
        payload["supplier_price_myr"] = supplier_price_myr

    response = (
        _client.table("products")
        .update(payload)
        .eq("id", product_id)
        .execute()
    )
    return response.data


def update_product_margin(
    product_id: str,
    net_margin_usd: float,
    margin_pct: float,
) -> dict:
    """Update the calculated margin fields on a product."""
    response = (
        _client.table("products")
        .update({"net_margin_usd": net_margin_usd, "margin_pct": margin_pct})
        .eq("id", product_id)
        .execute()
    )
    return response.data


def set_alerted(product_id: str, alerted: bool) -> dict:
    """Set the alerted flag on a product."""
    response = (
        _client.table("products")
        .update({"alerted": alerted})
        .eq("id", product_id)
        .execute()
    )
    return response.data


def set_margin_alerted_at(product_id: str, ts: str) -> dict:
    """Stamp the margin_alerted_at timestamp on a product."""
    response = (
        _client.table("products")
        .update({"margin_alerted_at": ts})
        .eq("id", product_id)
        .execute()
    )
    return response.data


# ---------------------------------------------------------------------------
# fx_rates
# ---------------------------------------------------------------------------


def get_latest_fx_rate() -> Optional[float]:
    """Return the most recent MYR→USD rate, or None if the table is empty."""
    response = (
        _client.table("fx_rates")
        .select("myr_to_usd")
        .order("fetched_at", desc=True)
        .limit(1)
        .execute()
    )
    if response.data:
        return float(response.data[0]["myr_to_usd"])
    return None


def get_two_latest_fx_rates() -> tuple[Optional[float], Optional[float]]:
    """Return (previous_rate, latest_rate).

    Returns (None, None) when fewer than two rows exist in fx_rates.
    Used by the FX alert to detect significant rate shifts between scrape cycles.
    """
    response = (
        _client.table("fx_rates")
        .select("myr_to_usd")
        .order("fetched_at", desc=True)
        .limit(2)
        .execute()
    )
    if len(response.data) >= 2:
        # data[0] = most recent, data[1] = second most recent
        return float(response.data[1]["myr_to_usd"]), float(response.data[0]["myr_to_usd"])
    return None, None


def insert_fx_rate(myr_to_usd: float) -> dict:
    """Insert a new FX rate snapshot."""
    response = (
        _client.table("fx_rates").insert({"myr_to_usd": myr_to_usd}).execute()
    )
    return response.data


# ---------------------------------------------------------------------------
# sync_log
# ---------------------------------------------------------------------------


def log_sync(
    product_id: str,
    platform: str,
    action: str,
    success: bool,
    error_msg: Optional[str] = None,
) -> dict:
    """Record one eBay or Etsy sync attempt."""
    response = (
        _client.table("sync_log")
        .insert(
            {
                "product_id": product_id,
                "platform": platform,
                "action": action,
                "success": success,
                "error_msg": error_msg,
            }
        )
        .execute()
    )
    return response.data
