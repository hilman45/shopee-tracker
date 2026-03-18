from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, call

import pytest
from tenacity import RetryError

import ebay_sync


# ---------------------------------------------------------------------------
# _should_skip
# ---------------------------------------------------------------------------


def test_should_skip_missing_ebay_listing_id():
    product = {"id": "p1", "name": "Widget", "platform": "ebay"}
    reason = ebay_sync._should_skip(product)
    assert reason == "no ebay_listing_id"


def test_should_skip_platform_etsy():
    product = {"id": "p1", "name": "Widget",
               "ebay_listing_id": "SKU-001", "platform": "etsy"}
    reason = ebay_sync._should_skip(product)
    assert reason == "platform=etsy"


def test_should_skip_returns_none_for_valid_product():
    product = {"id": "p1", "name": "Widget",
               "ebay_listing_id": "SKU-001", "platform": "ebay"}
    reason = ebay_sync._should_skip(product)
    assert reason is None


def test_should_skip_returns_none_for_both_platform():
    product = {"id": "p1", "name": "Widget",
               "ebay_listing_id": "SKU-001", "platform": "both"}
    reason = ebay_sync._should_skip(product)
    assert reason is None


# ---------------------------------------------------------------------------
# run_ebay_sync
# ---------------------------------------------------------------------------


def _product(**kwargs) -> dict:
    base = {
        "id": "p1", "name": "Widget",
        "ebay_listing_id": "SKU-001", "platform": "ebay",
        "status": "in_stock", "alerted": False, "stock_qty": 5,
    }
    base.update(kwargs)
    return base


def test_run_ebay_sync_out_of_stock_not_alerted_calls_pause():
    p = _product(status="out_of_stock", alerted=False)

    with patch("ebay_sync.db.get_all_products", return_value=[p]), \
         patch("ebay_sync.pause_listing") as mock_pause, \
         patch("ebay_sync.restore_listing") as mock_restore:
        ebay_sync.run_ebay_sync()

    mock_pause.assert_called_once_with(p)
    mock_restore.assert_not_called()


def test_run_ebay_sync_in_stock_alerted_calls_restore():
    p = _product(status="in_stock", alerted=True)

    with patch("ebay_sync.db.get_all_products", return_value=[p]), \
         patch("ebay_sync.pause_listing") as mock_pause, \
         patch("ebay_sync.restore_listing") as mock_restore:
        ebay_sync.run_ebay_sync()

    mock_restore.assert_called_once_with(p)
    mock_pause.assert_not_called()


def test_run_ebay_sync_no_action_for_already_alerted_out_of_stock():
    p = _product(status="out_of_stock", alerted=True)

    with patch("ebay_sync.db.get_all_products", return_value=[p]), \
         patch("ebay_sync.pause_listing") as mock_pause, \
         patch("ebay_sync.restore_listing") as mock_restore:
        ebay_sync.run_ebay_sync()

    mock_pause.assert_not_called()
    mock_restore.assert_not_called()


def test_run_ebay_sync_skips_etsy_only_products():
    p = _product(status="out_of_stock", alerted=False,
                 ebay_listing_id="SKU-001", platform="etsy")

    with patch("ebay_sync.db.get_all_products", return_value=[p]), \
         patch("ebay_sync.pause_listing") as mock_pause, \
         patch("ebay_sync.restore_listing") as mock_restore:
        ebay_sync.run_ebay_sync()

    mock_pause.assert_not_called()
    mock_restore.assert_not_called()


def test_run_ebay_sync_sleeps_after_pause():
    p = _product(status="out_of_stock", alerted=False)

    with patch("ebay_sync.db.get_all_products", return_value=[p]), \
         patch("ebay_sync.pause_listing"), \
         patch("ebay_sync.time.sleep") as mock_sleep:
        ebay_sync.run_ebay_sync()

    mock_sleep.assert_called_once()


def test_run_ebay_sync_sleeps_after_restore():
    p = _product(status="in_stock", alerted=True)

    with patch("ebay_sync.db.get_all_products", return_value=[p]), \
         patch("ebay_sync.restore_listing"), \
         patch("ebay_sync.time.sleep") as mock_sleep:
        ebay_sync.run_ebay_sync()

    mock_sleep.assert_called_once()


def test_run_ebay_sync_no_sleep_when_no_action():
    p = _product(status="in_stock", alerted=False)

    with patch("ebay_sync.db.get_all_products", return_value=[p]), \
         patch("ebay_sync.time.sleep") as mock_sleep:
        ebay_sync.run_ebay_sync()

    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# get_access_token
# ---------------------------------------------------------------------------


def test_get_access_token_returns_cached_when_valid():
    ebay_sync._token_cache["access_token"] = "cached-token"
    ebay_sync._token_cache["expires_at"] = time.time() + 7200

    token = ebay_sync.get_access_token()

    assert token == "cached-token"


def test_get_access_token_refreshes_when_expired():
    ebay_sync._token_cache["access_token"] = None
    ebay_sync._token_cache["expires_at"] = 0.0

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "new-token", "expires_in": 7200}

    with patch("ebay_sync.requests.post", return_value=mock_resp) as mock_post:
        token = ebay_sync.get_access_token()

    assert token == "new-token"
    assert ebay_sync._token_cache["access_token"] == "new-token"
    mock_post.assert_called_once()

    # cleanup
    ebay_sync._token_cache["access_token"] = None
    ebay_sync._token_cache["expires_at"] = 0.0


def test_get_access_token_raises_on_http_error():
    ebay_sync._token_cache["access_token"] = None
    ebay_sync._token_cache["expires_at"] = 0.0

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("401 Unauthorized")

    with patch("ebay_sync.requests.post", return_value=mock_resp):
        with pytest.raises(Exception, match="401"):
            ebay_sync.get_access_token()

    ebay_sync._token_cache["access_token"] = None
    ebay_sync._token_cache["expires_at"] = 0.0


# ---------------------------------------------------------------------------
# sync_ebay_listing
# ---------------------------------------------------------------------------


def test_sync_ebay_listing_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 204

    with patch("ebay_sync.get_access_token", return_value="tok"), \
         patch("ebay_sync.requests.put", return_value=mock_resp) as mock_put:
        ebay_sync.sync_ebay_listing.__wrapped__("SKU-1", 10)

    mock_put.assert_called_once()
    _, kwargs = mock_put.call_args
    assert "Bearer tok" in kwargs["headers"]["Authorization"]


def test_sync_ebay_listing_raises_on_http_error():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("500")

    with patch("ebay_sync.get_access_token", return_value="tok"), \
         patch("ebay_sync.requests.put", return_value=mock_resp):
        with pytest.raises(Exception):
            ebay_sync.sync_ebay_listing.__wrapped__("SKU-1", 10)


# ---------------------------------------------------------------------------
# pause_listing
# ---------------------------------------------------------------------------


def test_pause_listing_success_logs_to_db():
    p = _product(status="out_of_stock", alerted=False)

    with patch("ebay_sync.sync_ebay_listing"), \
         patch("ebay_sync.db.log_sync") as mock_log:
        ebay_sync.pause_listing(p)

    mock_log.assert_called_once_with("p1", "ebay", "pause", success=True)


def test_pause_listing_retry_error_logs_failure_and_sends_telegram():
    p = _product(status="out_of_stock", alerted=False)

    with patch("ebay_sync.sync_ebay_listing", side_effect=RetryError(None)), \
         patch("ebay_sync.db.log_sync") as mock_log, \
         patch("ebay_sync.send_telegram") as mock_tg:
        ebay_sync.pause_listing(p)

    mock_log.assert_called_once_with("p1", "ebay", "pause", success=False, error_msg=mock_log.call_args.kwargs["error_msg"])
    mock_tg.assert_called_once()


# ---------------------------------------------------------------------------
# restore_listing
# ---------------------------------------------------------------------------


def test_restore_listing_logs_reactivate_action():
    p = _product(status="in_stock", alerted=True, stock_qty=50)

    with patch("ebay_sync.sync_ebay_listing"), \
         patch("ebay_sync.db.log_sync") as mock_log:
        ebay_sync.restore_listing(p)

    mock_log.assert_called_once_with("p1", "ebay", "reactivate", success=True)


def test_restore_listing_caps_quantity_at_max():
    p = _product(status="in_stock", alerted=True, stock_qty=9999)

    with patch("ebay_sync.sync_ebay_listing") as mock_sync, \
         patch("ebay_sync.db.log_sync"):
        ebay_sync.restore_listing(p)

    _, qty = mock_sync.call_args.args
    import config
    assert qty == config.MAX_EBAY_QUANTITY


def test_restore_listing_retry_error_logs_failure():
    p = _product(status="in_stock", alerted=True)

    with patch("ebay_sync.sync_ebay_listing", side_effect=RetryError(None)), \
         patch("ebay_sync.db.log_sync") as mock_log, \
         patch("ebay_sync.send_telegram"):
        ebay_sync.restore_listing(p)

    mock_log.assert_called_once()
    assert mock_log.call_args.kwargs["success"] is False
    assert mock_log.call_args[0][2] == "reactivate"
