from __future__ import annotations

import requests
from loguru import logger

import config
from src import db

_cached_rate: float | None = None


def fetch_fx_rate() -> float | None:
    """Fetch live MYR→USD rate from Frankfurter, persist it, and update cache.

    Falls back to the in-memory cache, then the DB. Returns None only when no
    rate is available from any source.
    """
    global _cached_rate

    try:
        response = requests.get(config.FX_API_URL, timeout=10)
        response.raise_for_status()
        rate = float(response.json()["rates"]["USD"])
        db.insert_fx_rate(rate)
        _cached_rate = rate
        logger.info(f"FX rate fetched: 1 MYR = {rate} USD")
        return rate
    except Exception:
        fallback = _cached_rate if _cached_rate is not None else db.get_latest_fx_rate()
        if fallback is not None:
            logger.warning(f"FX API failed — using cached rate: {fallback}")
            return fallback
        logger.critical("No FX rate available — skipping margin calculation")
        return None


def calculate_margin(
    supplier_price_myr: float,
    selling_price_usd: float,
    myr_to_usd: float,
    platform: str,
) -> tuple[float, float]:
    """Return (net_margin_usd, margin_pct) for one product.

    platform: 'ebay' | 'etsy' | 'both'  ('both' uses eBay fee as conservative estimate)
    """
    supplier_cost_usd = supplier_price_myr * myr_to_usd

    if platform == "etsy":
        platform_fee = (selling_price_usd * config.ETSY_FEE_RATE) + config.ETSY_LISTING_FEE
    else:
        platform_fee = selling_price_usd * config.EBAY_FEE_RATE

    net_margin_usd = selling_price_usd - supplier_cost_usd - platform_fee
    margin_pct = (net_margin_usd / selling_price_usd) * 100

    return round(net_margin_usd, 4), round(margin_pct, 2)


def calculate_all() -> None:
    """Recalculate and persist margins for every product.

    Skips products that lack supplier_price_myr or selling_price_usd.
    """
    rate = fetch_fx_rate()
    if rate is None:
        return

    products = db.get_all_products()
    for product in products:
        supplier_price = product.get("supplier_price_myr")
        selling_price = product.get("selling_price_usd")

        if supplier_price is None or selling_price is None:
            logger.debug(
                f"Skipping margin for '{product.get('name', product.get('id'))}' "
                "— missing supplier_price_myr or selling_price_usd"
            )
            continue

        platform = product.get("platform", "both")
        net_margin_usd, margin_pct = calculate_margin(
            float(supplier_price), float(selling_price), rate, platform
        )

        db.update_product_margin(product["id"], net_margin_usd, margin_pct)
        logger.info(
            f"Margin updated: {product.get('name', product['id'])} "
            f"— {margin_pct}% (net USD {net_margin_usd})"
        )
