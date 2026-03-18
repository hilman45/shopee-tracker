from __future__ import annotations

import json
from unittest.mock import MagicMock, call, patch

import pytest

import config
from src import scraper
from src.scraper import (
    BotBlockError,
    RateLimitError,
    _ScrapedData,
    _determine_status,
    _extract_from_html,
    _extract_from_next_data,
    _extract_with_playwright,
    _scrape_one,
    run_scraper,
)
from tenacity import RetryError


# ---------------------------------------------------------------------------
# _determine_status
# ---------------------------------------------------------------------------


class TestDetermineStatus:
    def test_none_is_out_of_stock(self):
        assert _determine_status(None) == "out_of_stock"

    def test_zero_is_out_of_stock(self):
        assert _determine_status(0) == "out_of_stock"

    def test_low_stock_at_threshold(self):
        assert _determine_status(config.LOW_STOCK_THRESHOLD) == "low_stock"

    def test_low_stock_below_threshold(self):
        assert _determine_status(3) == "low_stock"

    def test_in_stock_above_threshold(self):
        assert _determine_status(50) == "in_stock"


# ---------------------------------------------------------------------------
# _extract_from_next_data
# ---------------------------------------------------------------------------


def _make_next_data_html(item: dict) -> str:
    payload = {
        "props": {
            "pageProps": {
                "initialData": {
                    "data": {
                        "item": item,
                    }
                }
            }
        }
    }
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'


class TestExtractFromNextData:
    def test_valid_item_returns_stock_and_price(self):
        html = _make_next_data_html({"stock": 42, "price": 1500000})
        stock, price = _extract_from_next_data(html)
        assert stock == 42
        assert price == pytest.approx(15.0)

    def test_price_scaled_down_from_shopee_units(self):
        html = _make_next_data_html({"stock": 10, "price": 2500000})
        _, price = _extract_from_next_data(html)
        assert price == pytest.approx(25.0)

    def test_price_already_small_not_scaled(self):
        # price_val <= 1000 is treated as already in real units
        html = _make_next_data_html({"stock": 5, "price": 15})
        _, price = _extract_from_next_data(html)
        assert price == pytest.approx(15.0)

    def test_missing_script_block_returns_none_none(self):
        stock, price = _extract_from_next_data("<html><body>no script</body></html>")
        assert stock is None
        assert price is None

    def test_malformed_json_returns_none_none(self):
        html = '<script id="__NEXT_DATA__" type="application/json">{bad json}</script>'
        stock, price = _extract_from_next_data(html)
        assert stock is None
        assert price is None

    def test_empty_item_returns_none_none(self):
        html = _make_next_data_html({})
        stock, price = _extract_from_next_data(html)
        assert stock is None
        assert price is None


# ---------------------------------------------------------------------------
# _scrape_one
# ---------------------------------------------------------------------------


class TestScrapeOne:
    def _product(self, **kwargs):
        base = {"id": "prod-1", "name": "Test Product", "supplier_url": "https://shopee.com/p/1"}
        base.update(kwargs)
        return base

    def test_success_in_stock(self):
        with (
            patch("src.scraper._fetch_and_parse", return_value=_ScrapedData(50, 15.0)) as mock_fetch,
            patch("src.scraper.db") as mock_db,
        ):
            result = _scrape_one(self._product())

        assert result is True
        mock_fetch.assert_called_once_with("https://shopee.com/p/1")
        mock_db.update_product_stock.assert_called_once_with("prod-1", 50, 15.0, "in_stock")

    def test_out_of_stock(self):
        with (
            patch("src.scraper._fetch_and_parse", return_value=_ScrapedData(0, 15.0)),
            patch("src.scraper.db") as mock_db,
        ):
            result = _scrape_one(self._product())

        assert result is True
        mock_db.update_product_stock.assert_called_once_with("prod-1", 0, 15.0, "out_of_stock")

    def test_no_supplier_url_returns_false_no_db(self):
        with (
            patch("src.scraper._fetch_and_parse") as mock_fetch,
            patch("src.scraper.db") as mock_db,
        ):
            result = _scrape_one(self._product(supplier_url=""))

        assert result is False
        mock_fetch.assert_not_called()
        mock_db.update_product_stock.assert_not_called()

    def test_bot_block_error_reraises(self):
        with (
            patch("src.scraper._fetch_and_parse", side_effect=BotBlockError("403")),
            patch("src.scraper.db"),
        ):
            with pytest.raises(BotBlockError):
                _scrape_one(self._product())

    def test_retry_error_returns_false(self):
        with (
            patch("src.scraper._fetch_and_parse", side_effect=RetryError(None)),
            patch("src.scraper.db") as mock_db,
        ):
            result = _scrape_one(self._product())

        assert result is False
        mock_db.update_product_stock.assert_not_called()


# ---------------------------------------------------------------------------
# run_scraper
# ---------------------------------------------------------------------------


class TestRunScraper:
    def _make_products(self, n: int = 2) -> list[dict]:
        return [
            {"id": f"prod-{i}", "name": f"Product {i}", "supplier_url": f"https://shopee.com/p/{i}"}
            for i in range(n)
        ]

    def test_iterates_all_products_and_calls_downstream(self):
        products = self._make_products(3)

        with (
            patch("src.scraper.db") as mock_db,
            patch("src.scraper._scrape_one", return_value=True) as mock_scrape,
            patch("time.sleep"),
            patch("src.margin.calculate_all") as mock_margin,
            patch("src.alerts.run_alerts") as mock_alerts,
        ):
            mock_db.get_all_products.return_value = products
            run_scraper()

        assert mock_scrape.call_count == 3
        mock_margin.assert_called_once()
        mock_alerts.assert_called_once()

    def test_margin_called_once_after_loop(self):
        products = self._make_products(2)

        with (
            patch("src.scraper.db") as mock_db,
            patch("src.scraper._scrape_one", return_value=True),
            patch("time.sleep"),
            patch("src.margin.calculate_all") as mock_margin,
            patch("src.alerts.run_alerts"),
        ):
            mock_db.get_all_products.return_value = products
            run_scraper()

        mock_margin.assert_called_once_with()

    def test_alerts_called_once_after_loop(self):
        products = self._make_products(2)

        with (
            patch("src.scraper.db") as mock_db,
            patch("src.scraper._scrape_one", return_value=True),
            patch("time.sleep"),
            patch("src.margin.calculate_all"),
            patch("src.alerts.run_alerts") as mock_alerts,
        ):
            mock_db.get_all_products.return_value = products
            run_scraper()

        mock_alerts.assert_called_once_with()

    def test_sleep_patched_no_real_delay(self):
        products = self._make_products(2)

        with (
            patch("src.scraper.db") as mock_db,
            patch("src.scraper._scrape_one", return_value=True),
            patch("time.sleep") as mock_sleep,
            patch("src.margin.calculate_all"),
            patch("src.alerts.run_alerts"),
        ):
            mock_db.get_all_products.return_value = products
            run_scraper()

        # sleep is called once per product (polite delay)
        assert mock_sleep.call_count == len(products)

    def test_bot_block_mid_loop_retries_after_pause(self):
        """Bot block on first attempt should pause then retry the same product."""
        products = self._make_products(1)

        scrape_calls = [BotBlockError("403"), True]
        scrape_iter = iter(scrape_calls)

        def fake_scrape(product):
            val = next(scrape_iter)
            if isinstance(val, Exception):
                raise val
            return val

        with (
            patch("src.scraper.db") as mock_db,
            patch("src.scraper._scrape_one", side_effect=fake_scrape) as mock_scrape,
            patch("time.sleep"),
            patch("src.margin.calculate_all"),
            patch("src.alerts.run_alerts"),
            patch("src.alerts.check_price_increase_alert"),
        ):
            mock_db.get_all_products.return_value = products
            run_scraper()

        assert mock_scrape.call_count == 2

    def test_price_increase_triggers_check_price_increase_alert(self):
        """When _scrape_one stamps _price_old/_price_new on the product dict,
        run_scraper should call check_price_increase_alert with that product."""
        product = self._make_products(1)[0]

        def fake_scrape(p):
            p["_price_old"] = 10.0
            p["_price_new"] = 15.0
            return True

        with (
            patch("src.scraper.db") as mock_db,
            patch("src.scraper._scrape_one", side_effect=fake_scrape),
            patch("time.sleep"),
            patch("src.margin.calculate_all"),
            patch("src.alerts.run_alerts"),
            patch("src.alerts.check_price_increase_alert") as mock_price_alert,
        ):
            mock_db.get_all_products.return_value = [product]
            run_scraper()

        mock_price_alert.assert_called_once()
        called_products = mock_price_alert.call_args.args[0]
        assert len(called_products) == 1
        assert called_products[0]["_price_old"] == 10.0


# ---------------------------------------------------------------------------
# _extract_from_html
# ---------------------------------------------------------------------------


class TestExtractFromHtml:
    def test_extracts_stock_from_class_stock(self):
        html = '<div class="stock">42 available</div>'
        stock, price = scraper._extract_from_html(html)
        assert stock == 42

    def test_extracts_price_from_class_price(self):
        html = '<div class="price">RM 25.50</div>'
        stock, price = scraper._extract_from_html(html)
        assert price == pytest.approx(25.50)

    def test_sold_out_text_sets_stock_to_zero(self):
        html = '<div class="status">Sold Out</div>'
        stock, price = scraper._extract_from_html(html)
        assert stock == 0

    def test_itemprop_price_extracted(self):
        html = '<span itemprop="price" content="19.99">RM19.99</span>'
        stock, price = scraper._extract_from_html(html)
        assert price == pytest.approx(19.99)

    def test_no_matching_elements_returns_none_none(self):
        html = "<html><body><p>Nothing here</p></body></html>"
        stock, price = scraper._extract_from_html(html)
        assert stock is None
        assert price is None


# ---------------------------------------------------------------------------
# _extract_from_next_data — alternative props.product path
# ---------------------------------------------------------------------------


class TestExtractFromNextDataAltPath:
    def test_alt_product_path_extracted(self):
        import json

        payload = {
            "props": {
                "pageProps": {
                    "product": {"stock": 7, "price": 800000}
                }
            }
        }
        html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        stock, price = scraper._extract_from_next_data(html)
        assert stock == 7
        assert price == pytest.approx(8.0)

    def test_stock_info_v2_path_extracted(self):
        import json

        payload = {
            "props": {
                "pageProps": {
                    "initialData": {
                        "data": {
                            "item": {
                                "stock_info_v2": {"total_reserved_stock": 15},
                                "price_min": 1200000,
                            }
                        }
                    }
                }
            }
        }
        html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
        stock, price = scraper._extract_from_next_data(html)
        assert stock == 15
        assert price == pytest.approx(12.0)


# ---------------------------------------------------------------------------
# _extract_with_playwright
# ---------------------------------------------------------------------------


class TestExtractWithPlaywright:
    def test_returns_none_none_when_playwright_raises(self):
        import sys

        # playwright.sync_api is a MagicMock stub from conftest; make sync_playwright raise.
        sync_api_mod = sys.modules["playwright.sync_api"]
        original = sync_api_mod.sync_playwright
        sync_api_mod.sync_playwright = MagicMock(side_effect=Exception("no browser"))
        try:
            stock, price = scraper._extract_with_playwright("https://example.com")
        finally:
            sync_api_mod.sync_playwright = original

        assert stock is None
        assert price is None

    def test_playwright_fallback_parses_html(self):
        import sys

        mock_page = MagicMock()
        mock_page.content.return_value = (
            '<div class="stock">30</div><div class="price">RM18.00</div>'
        )
        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_p = MagicMock()
        mock_p.chromium.launch.return_value = mock_browser
        mock_pw_ctx = MagicMock()
        mock_pw_ctx.__enter__ = MagicMock(return_value=mock_p)
        mock_pw_ctx.__exit__ = MagicMock(return_value=False)

        sync_api_mod = sys.modules["playwright.sync_api"]
        original = sync_api_mod.sync_playwright
        sync_api_mod.sync_playwright = MagicMock(return_value=mock_pw_ctx)
        try:
            stock, price = scraper._extract_with_playwright("https://shopee.my/test")
        finally:
            sync_api_mod.sync_playwright = original

        assert stock == 30
        assert price == pytest.approx(18.0)


# ---------------------------------------------------------------------------
# _fetch_and_parse
# ---------------------------------------------------------------------------


class TestFetchAndParse:
    def test_success_returns_scraped_data(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"initialData":{"data":{"item":{"stock":5,"price":1500000}}}}}}</script>'

        with patch("src.scraper.requests.get", return_value=mock_resp):
            result = scraper._fetch_and_parse.__wrapped__("https://shopee.my/test")

        assert result.stock_qty == 5
        assert result.price == pytest.approx(15.0)

    def test_403_raises_bot_block_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("src.scraper.requests.get", return_value=mock_resp):
            with pytest.raises(BotBlockError):
                scraper._fetch_and_parse.__wrapped__("https://shopee.my/test")

    def test_429_raises_rate_limit_error(self):
        from src.scraper import RateLimitError

        mock_resp = MagicMock()
        mock_resp.status_code = 429

        with patch("src.scraper.requests.get", return_value=mock_resp), \
             patch("time.sleep"):
            with pytest.raises(RateLimitError):
                scraper._fetch_and_parse.__wrapped__("https://shopee.my/test")
