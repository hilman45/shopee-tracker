from __future__ import annotations

import json
import random
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup
from loguru import logger
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

import config
from src import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BOT_BLOCK_PAUSE_SECONDS = 30 * 60  # 30 minutes
_RATE_LIMIT_PAUSE_SECONDS = 60

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
]


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class BotBlockError(Exception):
    """Raised when Shopee returns a 403 or 429 indicating a bot block."""


class RateLimitError(Exception):
    """Raised on HTTP 429 to trigger a short back-off before tenacity retries."""


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def _random_headers() -> dict:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def _extract_from_next_data(html: str) -> tuple[Optional[int], Optional[float]]:
    """Parse stock and price from Shopee's __NEXT_DATA__ JSON blob."""
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        return None, None
    try:
        data = json.loads(match.group(1))
        # Traverse common Shopee NEXT_DATA paths
        props = data.get("props", {}).get("pageProps", {})
        item = (
            props.get("initialData", {})
            .get("data", {})
            .get("item", {})
        )
        if not item:
            # Alternative path
            item = props.get("product", {})

        stock_qty: Optional[int] = None
        price: Optional[float] = None

        raw_stock = item.get("stock") or item.get("stock_info_v2", {}).get(
            "total_reserved_stock"
        )
        if raw_stock is not None:
            stock_qty = int(raw_stock)

        raw_price = item.get("price") or item.get("price_min")
        if raw_price is not None:
            # Shopee prices are stored in 100,000× units (e.g. 1500000 = RM15.00)
            price_val = float(raw_price)
            price = price_val / 100_000 if price_val > 1_000 else price_val

        return stock_qty, price
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None, None


def _extract_from_html(html: str) -> tuple[Optional[int], Optional[float]]:
    """BeautifulSoup fallback extraction."""
    soup = BeautifulSoup(html, "html.parser")

    stock_qty: Optional[int] = None
    price: Optional[float] = None

    # --- stock ---
    for selector in [
        {"class": re.compile(r"stock", re.I)},
        {"class": re.compile(r"quantity", re.I)},
        {"class": re.compile(r"product-stock", re.I)},
    ]:
        tag = soup.find(attrs=selector)
        if tag:
            text = tag.get_text(strip=True)
            nums = re.findall(r"\d+", text)
            if nums:
                stock_qty = int(nums[0])
                break

    # Explicit "Sold Out" markers
    sold_out_tag = soup.find(string=re.compile(r"sold\s*out", re.I))
    if sold_out_tag:
        stock_qty = 0

    # --- price ---
    for selector in [
        {"class": re.compile(r"price", re.I)},
        {"itemprop": "price"},
    ]:
        tag = soup.find(attrs=selector)
        if tag:
            raw = tag.get("content") or tag.get_text(strip=True)
            cleaned = re.sub(r"[^\d.]", "", raw)
            if cleaned:
                try:
                    price = float(cleaned)
                    break
                except ValueError:
                    pass

    return stock_qty, price


def _extract_with_playwright(url: str) -> tuple[Optional[int], Optional[float]]:
    """Last-resort Playwright headless extraction."""
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(extra_http_headers=_random_headers())
            page.goto(url, wait_until="networkidle", timeout=30_000)

            # Try to wait for stock element
            try:
                page.wait_for_selector(
                    '[class*="stock"],[class*="quantity"]', timeout=5_000
                )
            except Exception:
                pass

            html = page.content()
            browser.close()

        stock, price = _extract_from_next_data(html)
        if stock is None or price is None:
            bs_stock, bs_price = _extract_from_html(html)
            stock = stock if stock is not None else bs_stock
            price = price if price is not None else bs_price

        return stock, price
    except Exception as exc:
        logger.warning(f"Playwright extraction failed: {exc}")
        return None, None


# ---------------------------------------------------------------------------
# Core scrape logic (retried by tenacity)
# ---------------------------------------------------------------------------


class _ScrapedData:
    __slots__ = ("stock_qty", "price")

    def __init__(self, stock_qty: Optional[int], price: Optional[float]):
        self.stock_qty = stock_qty
        self.price = price


@retry(
    retry=retry_if_exception_type(RateLimitError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=5, max=30),
    reraise=True,
)
def _fetch_and_parse(url: str) -> _ScrapedData:
    """Fetch a URL and extract stock/price data with tiered extraction strategy."""
    response = requests.get(url, headers=_random_headers(), timeout=20)

    if response.status_code == 429:
        logger.warning(f"HTTP 429 from {url} — waiting {_RATE_LIMIT_PAUSE_SECONDS}s")
        time.sleep(_RATE_LIMIT_PAUSE_SECONDS)
        raise RateLimitError(f"Rate limited by {url}")

    if response.status_code == 403:
        raise BotBlockError(f"Bot block (403) from {url}")

    response.raise_for_status()
    html = response.text

    # Tier 1: __NEXT_DATA__ JSON
    stock, price = _extract_from_next_data(html)

    # Tier 2: BeautifulSoup HTML fallback
    if stock is None or price is None:
        bs_stock, bs_price = _extract_from_html(html)
        stock = stock if stock is not None else bs_stock
        price = price if price is not None else bs_price

    # Tier 3: Playwright headless browser
    if stock is None or price is None:
        logger.info(f"Falling back to Playwright for {url}")
        pw_stock, pw_price = _extract_with_playwright(url)
        stock = stock if stock is not None else pw_stock
        price = price if price is not None else pw_price

    return _ScrapedData(stock_qty=stock, price=price)


# ---------------------------------------------------------------------------
# Status determination
# ---------------------------------------------------------------------------


def _determine_status(stock_qty: Optional[int]) -> str:
    if stock_qty is None or stock_qty == 0:
        return "out_of_stock"
    if stock_qty <= config.LOW_STOCK_THRESHOLD:
        return "low_stock"
    return "in_stock"


# ---------------------------------------------------------------------------
# Per-product scrape (outer wrapper with full error isolation)
# ---------------------------------------------------------------------------


def _scrape_one(product: dict) -> bool:
    """Scrape a single product. Returns True on success, False on failure.

    When the supplier price has increased since the last scrape, stamps
    ``_price_old`` and ``_price_new`` onto the *product* dict so the caller
    can dispatch a price-increase alert.
    """
    url: str = product.get("supplier_url", "")
    name: str = product.get("name", product.get("id", "unknown"))
    product_id: str = product["id"]

    if not url:
        logger.warning(f"Product '{name}' has no supplier_url — skipping")
        return False

    logger.info(f"Scraping product: {name} ({url})")

    old_price: Optional[float] = product.get("supplier_price_myr")
    if old_price is not None:
        old_price = float(old_price)

    try:
        scraped = _fetch_and_parse(url)
    except BotBlockError as exc:
        logger.warning(f"Bot block detected for {url}: {exc}")
        raise  # re-raise so run_scraper can handle the pause
    except RetryError as exc:
        logger.error(f"Failed to scrape {url} after retries: {exc}")
        return False
    except Exception as exc:
        logger.error(f"Failed to scrape {url}: {exc}")
        return False

    stock_qty = scraped.stock_qty
    price = scraped.price
    status = _determine_status(stock_qty)

    logger.info(
        f"Result: stock={stock_qty}, price=RM{price}, status={status} — {name}"
    )

    try:
        db.update_product_stock(product_id, stock_qty, price, status)
    except Exception as exc:
        logger.error(f"DB write failed for product '{name}' ({product_id}): {exc}")
        return False

    # Flag price increase for the caller to dispatch an alert
    if old_price is not None and price is not None and price > old_price:
        product["_price_old"] = old_price
        product["_price_new"] = price

    return True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_scraper() -> None:
    """Scrape all products, then trigger margin recalculation and alerts."""
    # Import downstream modules lazily to avoid circular imports at module load
    from src import alerts, margin  # noqa: PLC0415

    products = db.get_all_products()
    logger.info(f"Starting scrape batch — {len(products)} product(s)")

    success_count = 0
    fail_count = 0
    price_increased_products: list[dict] = []

    for product in products:
        try:
            ok = _scrape_one(product)
        except BotBlockError:
            logger.warning(
                f"Bot block detected — pausing scraper for "
                f"{_BOT_BLOCK_PAUSE_SECONDS // 60} minutes"
            )
            time.sleep(_BOT_BLOCK_PAUSE_SECONDS)
            # Attempt to continue after the pause
            try:
                ok = _scrape_one(product)
            except Exception as exc:
                logger.error(f"Still failing after bot-block pause: {exc}")
                ok = False

        if ok:
            if "_price_old" in product:
                price_increased_products.append(product)
            success_count += 1
        else:
            fail_count += 1

        # Polite delay between requests
        delay = random.uniform(config.SCRAPE_DELAY_MIN, config.SCRAPE_DELAY_MAX)
        time.sleep(delay)

    logger.info(
        f"Scrape batch complete — {success_count} succeeded, {fail_count} failed"
    )

    # Downstream pipeline
    try:
        margin.calculate_all()
    except Exception as exc:
        logger.error(f"margin.calculate_all() failed: {exc}")

    try:
        alerts.run_alerts()
    except Exception as exc:
        logger.error(f"alerts.check_and_send() failed: {exc}")

    if price_increased_products:
        try:
            alerts.check_price_increase_alert(price_increased_products)
        except Exception as exc:
            logger.error(f"alerts.check_price_increase_alert() failed: {exc}")
