from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import config
import margin


@pytest.fixture(autouse=True)
def reset_cached_rate():
    """Reset the in-memory FX cache before and after every test."""
    margin._cached_rate = None
    yield
    margin._cached_rate = None


# ---------------------------------------------------------------------------
# calculate_margin
# ---------------------------------------------------------------------------


def test_calculate_margin_ebay():
    # supplier_cost = 100 * 0.23 = 23.0
    # platform_fee  = 50 * 0.1325 = 6.625
    # net_margin    = 50 - 23 - 6.625 = 20.375
    # margin_pct    = (20.375 / 50) * 100 = 40.75
    net, pct = margin.calculate_margin(100.0, 50.0, 0.23, "ebay")
    assert net == round(20.375, 4)
    assert pct == round(40.75, 2)


def test_calculate_margin_etsy():
    # supplier_cost = 100 * 0.23 = 23.0
    # platform_fee  = (50 * 0.065) + 0.20 = 3.25 + 0.20 = 3.45
    # net_margin    = 50 - 23 - 3.45 = 23.55
    # margin_pct    = (23.55 / 50) * 100 = 47.1
    net, pct = margin.calculate_margin(100.0, 50.0, 0.23, "etsy")
    assert net == round(23.55, 4)
    assert pct == round(47.1, 2)


def test_calculate_margin_both_uses_ebay_fee():
    net_both, pct_both = margin.calculate_margin(100.0, 50.0, 0.23, "both")
    net_ebay, pct_ebay = margin.calculate_margin(100.0, 50.0, 0.23, "ebay")
    assert net_both == net_ebay
    assert pct_both == pct_ebay


def test_calculate_margin_negative():
    # supplier_cost = 200 * 0.23 = 46.0
    # platform_fee  = 30 * 0.1325 = 3.975
    # net_margin    = 30 - 46 - 3.975 = -19.975
    # margin_pct    = (-19.975 / 30) * 100 ≈ -66.58
    net, pct = margin.calculate_margin(200.0, 30.0, 0.23, "ebay")
    assert net < 0
    assert pct < 0


# ---------------------------------------------------------------------------
# fetch_fx_rate
# ---------------------------------------------------------------------------


def test_fetch_fx_rate_success():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"rates": {"USD": 0.23}}

    with patch("margin.requests.get", return_value=mock_resp) as mock_get, \
         patch("margin.db.insert_fx_rate") as mock_insert:
        rate = margin.fetch_fx_rate()

    assert rate == 0.23
    mock_get.assert_called_once()
    mock_insert.assert_called_once_with(0.23)
    assert margin._cached_rate == 0.23


def test_fetch_fx_rate_api_failure_uses_memory_cache():
    margin._cached_rate = 0.21

    with patch("margin.requests.get", side_effect=Exception("timeout")), \
         patch("margin.db.get_latest_fx_rate") as mock_db:
        rate = margin.fetch_fx_rate()

    assert rate == 0.21
    mock_db.assert_not_called()


def test_fetch_fx_rate_api_failure_no_cache_uses_db():
    margin._cached_rate = None

    with patch("margin.requests.get", side_effect=Exception("timeout")), \
         patch("margin.db.get_latest_fx_rate", return_value=0.19):
        rate = margin.fetch_fx_rate()

    assert rate == 0.19


def test_fetch_fx_rate_all_sources_missing_returns_none():
    margin._cached_rate = None

    with patch("margin.requests.get", side_effect=Exception("timeout")), \
         patch("margin.db.get_latest_fx_rate", return_value=None):
        rate = margin.fetch_fx_rate()

    assert rate is None


# ---------------------------------------------------------------------------
# calculate_all
# ---------------------------------------------------------------------------


def test_calculate_all_skips_products_missing_prices():
    products = [
        {"id": "p1", "name": "No supplier price", "selling_price_usd": 50.0,
         "supplier_price_myr": None, "platform": "ebay"},
        {"id": "p2", "name": "No selling price", "selling_price_usd": None,
         "supplier_price_myr": 100.0, "platform": "ebay"},
    ]

    with patch("margin.fetch_fx_rate", return_value=0.23), \
         patch("margin.db.get_all_products", return_value=products), \
         patch("margin.db.update_product_margin") as mock_update:
        margin.calculate_all()

    mock_update.assert_not_called()


def test_calculate_all_updates_valid_products():
    products = [
        {"id": "p1", "name": "Widget", "selling_price_usd": 50.0,
         "supplier_price_myr": 100.0, "platform": "ebay"},
        {"id": "p2", "name": "Gizmo", "selling_price_usd": 40.0,
         "supplier_price_myr": 80.0, "platform": "etsy"},
    ]

    with patch("margin.fetch_fx_rate", return_value=0.23), \
         patch("margin.db.get_all_products", return_value=products), \
         patch("margin.db.update_product_margin") as mock_update:
        margin.calculate_all()

    assert mock_update.call_count == 2
    call_ids = {c.args[0] for c in mock_update.call_args_list}
    assert call_ids == {"p1", "p2"}


def test_calculate_all_aborts_when_no_fx_rate():
    with patch("margin.fetch_fx_rate", return_value=None), \
         patch("margin.db.get_all_products") as mock_get, \
         patch("margin.db.update_product_margin") as mock_update:
        margin.calculate_all()

    mock_get.assert_not_called()
    mock_update.assert_not_called()
