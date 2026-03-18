from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from loguru import logger

import config
from src import db

_FAILED_ALERTS_LOG = Path("failed_alerts.log")


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


def send_telegram(message: str) -> bool:
    """POST *message* to the configured Telegram chat.

    Retries up to 3 times on failure. On exhaustion, appends the raw message
    to ``failed_alerts.log`` and returns ``False``. Never raises.
    """
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": config.TELEGRAM_CHAT_ID, "text": message}

    for attempt in range(1, 4):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.warning(f"Telegram send failed (attempt {attempt}): {exc}")

    logger.error("All Telegram retries exhausted — written to failed_alerts.log")
    with _FAILED_ALERTS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"[{datetime.now(timezone.utc).isoformat()}]\n{message}\n\n")
    return False


# ---------------------------------------------------------------------------
# Stock alerts
# ---------------------------------------------------------------------------


def check_stock_alerts(products: list[dict]) -> None:
    """Evaluate stock events and dispatch Telegram alerts where needed.

    Rules
    -----
    - ``out_of_stock`` + ``alerted=False``  → OUT OF STOCK alert, set alerted=True
    - ``low_stock``    + ``alerted=False``  → LOW STOCK WARNING, set alerted=True
    - ``in_stock``     + ``alerted=True``   → STOCK RECOVERED (reset), set alerted=False
    """
    now = datetime.now(timezone.utc).isoformat()

    for product in products:
        product_id = product["id"]
        name = product.get("name", product_id)
        status = product.get("status", "")
        alerted = product.get("alerted", False)
        stock_qty = product.get("stock_qty", 0) or 0
        supplier_url = product.get("supplier_url", "N/A")

        if status == "out_of_stock" and not alerted:
            msg = (
                f"🔴 OUT OF STOCK\n\n"
                f"Product: {name}\n"
                f"Stock: 0 units\n"
                f"Supplier: {supplier_url}\n"
                f"Time: {now}\n\n"
                f"eBay and Etsy listings have been paused automatically."
            )
            if send_telegram(msg):
                db.set_alerted(product_id, True)
                logger.info(f"Alert sent: out_of_stock — {name}")

        elif status == "low_stock" and not alerted:
            msg = (
                f"🟡 LOW STOCK WARNING\n\n"
                f"Product: {name}\n"
                f"Stock remaining: {stock_qty} units\n"
                f"Supplier: {supplier_url}\n"
                f"Time: {now}"
            )
            if send_telegram(msg):
                db.set_alerted(product_id, True)
                logger.info(f"Alert sent: low_stock — {name}")

        elif status == "in_stock" and alerted:
            # Recovered from a previously alerted out_of_stock or low_stock event.
            msg = (
                f"🟢 STOCK RECOVERED\n\n"
                f"Product: {name}\n"
                f"Stock: {stock_qty} units\n"
                f"Supplier: {supplier_url}\n"
                f"Listings on eBay and Etsy have been reactivated."
            )
            if send_telegram(msg):
                db.set_alerted(product_id, False)
                logger.info(f"Alert sent: stock_recovered — {name}")


# ---------------------------------------------------------------------------
# Margin alerts
# ---------------------------------------------------------------------------


def check_margin_alerts(products: list[dict]) -> None:
    """Send margin alerts for products that breach configured thresholds.

    Debounce: skip if ``margin_alerted_at`` is within the last
    ``MARGIN_ALERT_DEBOUNCE_HOURS`` hours to avoid alert floods.
    """
    now = datetime.now(timezone.utc)
    debounce_cutoff = now - timedelta(hours=config.MARGIN_ALERT_DEBOUNCE_HOURS)

    for product in products:
        margin_pct = product.get("margin_pct")
        if margin_pct is None:
            continue

        margin_pct = float(margin_pct)

        # Debounce check
        margin_alerted_at = product.get("margin_alerted_at")
        if margin_alerted_at:
            try:
                last_alerted = datetime.fromisoformat(margin_alerted_at)
                if last_alerted.tzinfo is None:
                    last_alerted = last_alerted.replace(tzinfo=timezone.utc)
                if last_alerted > debounce_cutoff:
                    continue
            except ValueError:
                pass

        product_id = product["id"]
        name = product.get("name", product_id)
        net_margin_usd = float(product.get("net_margin_usd") or 0)
        selling_price_usd = float(product.get("selling_price_usd") or 0)
        supplier_price_myr = float(product.get("supplier_price_myr") or 0)
        supplier_url = product.get("supplier_url", "N/A")
        ts = now.isoformat()

        # Supplier cost in USD for display (best-effort, no rate needed for display)
        supplier_cost_usd = selling_price_usd - net_margin_usd  # approximate

        if margin_pct < 0:
            msg = (
                f"🚨 URGENT — SELLING AT A LOSS\n\n"
                f"Product: {name}\n"
                f"Margin: {margin_pct}%\n"
                f"Loss per sale: ${abs(net_margin_usd):.2f} USD\n\n"
                f"Action required: pause or reprice this listing immediately.\n"
                f"Supplier URL: {supplier_url}"
            )
            if send_telegram(msg):
                db.set_margin_alerted_at(product_id, ts)
                logger.info(f"Alert sent: negative_margin — {name}")

        elif margin_pct < config.MIN_MARGIN_PCT:
            msg = (
                f"⚠️ LOW MARGIN ALERT\n\n"
                f"Product: {name}\n"
                f"Current margin: {margin_pct}% (minimum: {config.MIN_MARGIN_PCT}%)\n"
                f"Net profit: ${net_margin_usd:.2f} USD\n"
                f"Selling price: ${selling_price_usd:.2f} USD\n"
                f"Supplier cost: RM{supplier_price_myr:.2f} (≈ ${supplier_cost_usd:.2f} USD)\n\n"
                f"Check if you need to raise your listing price."
            )
            if send_telegram(msg):
                db.set_margin_alerted_at(product_id, ts)
                logger.info(f"Alert sent: low_margin — {name}")


# ---------------------------------------------------------------------------
# FX alert
# ---------------------------------------------------------------------------


def check_fx_alert(old_rate: float, new_rate: float, products: list[dict]) -> None:
    """Fire an FX rate shift alert if the change exceeds ``FX_ALERT_THRESHOLD``.

    Identifies the worst-affected product (lowest current margin_pct).
    """
    if old_rate == 0:
        return

    pct_change = (new_rate - old_rate) / old_rate
    if abs(pct_change) <= config.FX_ALERT_THRESHOLD:
        return

    direction = "▲" if pct_change > 0 else "▼"
    pct_display = round(abs(pct_change) * 100, 2)
    n_affected = len(products)

    worst: dict | None = None
    for p in products:
        if p.get("margin_pct") is not None:
            if worst is None or float(p["margin_pct"]) < float(worst["margin_pct"]):
                worst = p

    worst_line = ""
    if worst:
        worst_name = worst.get("name", worst["id"])
        worst_margin = float(worst["margin_pct"])
        worst_line = f"Worst margin impact: {worst_name} → {worst_margin}%"

    msg = (
        f"💱 FX RATE SHIFT\n\n"
        f"New rate: 1 MYR = {new_rate} USD\n"
        f"Change: {direction} {pct_display}% in 24h\n\n"
        f"{n_affected} products affected.\n"
        f"{worst_line}"
    )
    send_telegram(msg)
    logger.info(f"Alert sent: fx_rate_shift — {direction}{pct_display}%")


# ---------------------------------------------------------------------------
# Supplier price increase alert
# ---------------------------------------------------------------------------


def check_price_increase_alert(products: list[dict]) -> None:
    """Fire a supplier price increase alert for each product whose price rose.

    Expects each dict to contain ``_price_old`` and ``_price_new`` keys set by
    the scraper when it detects a price increase.
    """
    for product in products:
        old_price = product.get("_price_old")
        new_price = product.get("_price_new")
        if old_price is None or new_price is None or new_price <= old_price:
            continue

        pct_change = (new_price - old_price) / old_price * 100
        name = product.get("name", product["id"])
        margin_pct = product.get("margin_pct")
        margin_line = f"New margin: {margin_pct}%" if margin_pct is not None else ""

        msg = (
            f"📈 SUPPLIER PRICE INCREASE\n\n"
            f"Product: {name}\n"
            f"Old price: RM{old_price:.2f}\n"
            f"New price: RM{new_price:.2f} (+{pct_change:.1f}%)\n"
            f"{margin_line}\n\n"
            f"Review your listing price on eBay/Etsy."
        )
        send_telegram(msg)
        logger.info(f"Alert sent: supplier_price_increase — {name} (+{pct_change:.1f}%)")


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------


def run_alerts() -> None:
    """Load all products and run every alert check. Called after each scrape + margin cycle."""
    products = db.get_all_products()
    check_stock_alerts(products)
    check_margin_alerts(products)

    old_rate, new_rate = db.get_two_latest_fx_rates()
    if old_rate is not None and new_rate is not None:
        check_fx_alert(old_rate, new_rate, products)
