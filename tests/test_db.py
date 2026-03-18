from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client():
    """Return a patched supabase client mock wired through db._client."""
    return patch.object(db, "_client")


def _table_response(data):
    """Build a mock Supabase response with .data = data."""
    resp = MagicMock()
    resp.data = data
    return resp


def _chain(*args, return_value=None):
    """Build a fluent mock chain where each method returns the next mock,
    and the final .execute() returns *return_value*."""
    root = MagicMock()
    current = root
    for method_name in args:
        nxt = MagicMock()
        getattr(current, method_name).return_value = nxt
        current = nxt
    current.execute.return_value = return_value
    return root


# ---------------------------------------------------------------------------
# get_all_products
# ---------------------------------------------------------------------------


def test_get_all_products_returns_data():
    rows = [{"id": "p1"}, {"id": "p2"}]
    with _mock_client() as mock_c:
        mock_c.table.return_value.select.return_value.execute.return_value = _table_response(rows)
        result = db.get_all_products()
    assert result == rows


def test_get_all_products_empty():
    with _mock_client() as mock_c:
        mock_c.table.return_value.select.return_value.execute.return_value = _table_response([])
        result = db.get_all_products()
    assert result == []


# ---------------------------------------------------------------------------
# update_product_stock
# ---------------------------------------------------------------------------


def test_update_product_stock_calls_correct_table():
    with _mock_client() as mock_c:
        chain = mock_c.table.return_value
        chain.update.return_value.eq.return_value.execute.return_value = _table_response([{"id": "p1"}])

        result = db.update_product_stock("p1", 50, 25.0, "in_stock")

    mock_c.table.assert_called_with("products")
    update_call = chain.update.call_args[0][0]
    assert update_call["stock_qty"] == 50
    assert update_call["supplier_price_myr"] == 25.0
    assert update_call["status"] == "in_stock"
    assert update_call["alerted"] is False
    assert "last_checked" in update_call


def test_update_product_stock_with_none_values():
    with _mock_client() as mock_c:
        chain = mock_c.table.return_value
        chain.update.return_value.eq.return_value.execute.return_value = _table_response([])
        db.update_product_stock("p1", None, None, "out_of_stock")

    update_call = chain.update.call_args[0][0]
    assert update_call["stock_qty"] is None
    assert update_call["supplier_price_myr"] is None


# ---------------------------------------------------------------------------
# update_product_margin
# ---------------------------------------------------------------------------


def test_update_product_margin_passes_correct_fields():
    with _mock_client() as mock_c:
        chain = mock_c.table.return_value
        chain.update.return_value.eq.return_value.execute.return_value = _table_response([])

        db.update_product_margin("p1", 5.25, 18.5)

    update_call = chain.update.call_args[0][0]
    assert update_call == {"net_margin_usd": 5.25, "margin_pct": 18.5}


# ---------------------------------------------------------------------------
# set_alerted
# ---------------------------------------------------------------------------


def test_set_alerted_true():
    with _mock_client() as mock_c:
        chain = mock_c.table.return_value
        chain.update.return_value.eq.return_value.execute.return_value = _table_response([])
        db.set_alerted("p1", True)

    update_call = chain.update.call_args[0][0]
    assert update_call == {"alerted": True}


def test_set_alerted_false():
    with _mock_client() as mock_c:
        chain = mock_c.table.return_value
        chain.update.return_value.eq.return_value.execute.return_value = _table_response([])
        db.set_alerted("p1", False)

    update_call = chain.update.call_args[0][0]
    assert update_call == {"alerted": False}


# ---------------------------------------------------------------------------
# set_margin_alerted_at
# ---------------------------------------------------------------------------


def test_set_margin_alerted_at_passes_timestamp():
    ts = "2026-01-01T00:00:00+00:00"
    with _mock_client() as mock_c:
        chain = mock_c.table.return_value
        chain.update.return_value.eq.return_value.execute.return_value = _table_response([])
        db.set_margin_alerted_at("p1", ts)

    update_call = chain.update.call_args[0][0]
    assert update_call == {"margin_alerted_at": ts}


# ---------------------------------------------------------------------------
# get_latest_fx_rate
# ---------------------------------------------------------------------------


def test_get_latest_fx_rate_returns_float_when_data_present():
    with _mock_client() as mock_c:
        (
            mock_c.table.return_value
            .select.return_value
            .order.return_value
            .limit.return_value
            .execute.return_value
        ) = _table_response([{"myr_to_usd": "0.2300"}])
        result = db.get_latest_fx_rate()
    assert result == pytest.approx(0.23)


def test_get_latest_fx_rate_returns_none_when_empty():
    with _mock_client() as mock_c:
        (
            mock_c.table.return_value
            .select.return_value
            .order.return_value
            .limit.return_value
            .execute.return_value
        ) = _table_response([])
        result = db.get_latest_fx_rate()
    assert result is None


# ---------------------------------------------------------------------------
# get_two_latest_fx_rates
# ---------------------------------------------------------------------------


def test_get_two_latest_fx_rates_returns_previous_and_latest():
    rows = [{"myr_to_usd": "0.24"}, {"myr_to_usd": "0.22"}]  # desc order
    with _mock_client() as mock_c:
        (
            mock_c.table.return_value
            .select.return_value
            .order.return_value
            .limit.return_value
            .execute.return_value
        ) = _table_response(rows)
        prev, latest = db.get_two_latest_fx_rates()
    assert prev == pytest.approx(0.22)   # second most recent
    assert latest == pytest.approx(0.24) # most recent


def test_get_two_latest_fx_rates_returns_none_none_when_fewer_than_two():
    with _mock_client() as mock_c:
        (
            mock_c.table.return_value
            .select.return_value
            .order.return_value
            .limit.return_value
            .execute.return_value
        ) = _table_response([{"myr_to_usd": "0.23"}])
        prev, latest = db.get_two_latest_fx_rates()
    assert prev is None
    assert latest is None


def test_get_two_latest_fx_rates_returns_none_none_when_empty():
    with _mock_client() as mock_c:
        (
            mock_c.table.return_value
            .select.return_value
            .order.return_value
            .limit.return_value
            .execute.return_value
        ) = _table_response([])
        prev, latest = db.get_two_latest_fx_rates()
    assert prev is None
    assert latest is None


# ---------------------------------------------------------------------------
# insert_fx_rate
# ---------------------------------------------------------------------------


def test_insert_fx_rate_inserts_correct_value():
    with _mock_client() as mock_c:
        chain = mock_c.table.return_value
        chain.insert.return_value.execute.return_value = _table_response([{"id": 1}])
        db.insert_fx_rate(0.23)

    mock_c.table.assert_called_with("fx_rates")
    insert_call = chain.insert.call_args[0][0]
    assert insert_call == {"myr_to_usd": 0.23}


# ---------------------------------------------------------------------------
# log_sync
# ---------------------------------------------------------------------------


def test_log_sync_inserts_all_fields():
    with _mock_client() as mock_c:
        chain = mock_c.table.return_value
        chain.insert.return_value.execute.return_value = _table_response([])

        db.log_sync("p1", "ebay", "pause", success=True)

    mock_c.table.assert_called_with("sync_log")
    insert_call = chain.insert.call_args[0][0]
    assert insert_call["product_id"] == "p1"
    assert insert_call["platform"] == "ebay"
    assert insert_call["action"] == "pause"
    assert insert_call["success"] is True
    assert insert_call["error_msg"] is None


def test_log_sync_includes_error_msg_on_failure():
    with _mock_client() as mock_c:
        chain = mock_c.table.return_value
        chain.insert.return_value.execute.return_value = _table_response([])

        db.log_sync("p1", "etsy", "reactivate", success=False, error_msg="timeout")

    insert_call = chain.insert.call_args[0][0]
    assert insert_call["success"] is False
    assert insert_call["error_msg"] == "timeout"
    assert insert_call["action"] == "reactivate"
