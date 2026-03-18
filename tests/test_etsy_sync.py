from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from tenacity import RetryError

import etsy_sync


# ---------------------------------------------------------------------------
# _should_skip
# ---------------------------------------------------------------------------


def test_should_skip_missing_etsy_listing_id():
    product = {"id": "p1", "name": "Widget", "platform": "etsy"}
    reason = etsy_sync._should_skip(product)
    assert reason == "no etsy_listing_id"


def test_should_skip_platform_ebay():
    product = {"id": "p1", "name": "Widget",
               "etsy_listing_id": "12345678", "platform": "ebay"}
    reason = etsy_sync._should_skip(product)
    assert reason == "platform=ebay"


def test_should_skip_returns_none_for_valid_product():
    product = {"id": "p1", "name": "Widget",
               "etsy_listing_id": "12345678", "platform": "etsy"}
    reason = etsy_sync._should_skip(product)
    assert reason is None


def test_should_skip_returns_none_for_both_platform():
    product = {"id": "p1", "name": "Widget",
               "etsy_listing_id": "12345678", "platform": "both"}
    reason = etsy_sync._should_skip(product)
    assert reason is None


# ---------------------------------------------------------------------------
# run_etsy_sync
# ---------------------------------------------------------------------------


def _product(**kwargs) -> dict:
    base = {
        "id": "p1", "name": "Widget",
        "etsy_listing_id": "12345678", "platform": "etsy",
        "status": "in_stock", "alerted": False, "stock_qty": 5,
    }
    base.update(kwargs)
    return base


def test_run_etsy_sync_out_of_stock_not_alerted_calls_pause():
    p = _product(status="out_of_stock", alerted=False)

    with patch("etsy_sync.db.get_all_products", return_value=[p]), \
         patch("etsy_sync.pause_listing") as mock_pause, \
         patch("etsy_sync.restore_listing") as mock_restore:
        etsy_sync.run_etsy_sync()

    mock_pause.assert_called_once_with(p)
    mock_restore.assert_not_called()


def test_run_etsy_sync_in_stock_alerted_calls_restore():
    p = _product(status="in_stock", alerted=True)

    with patch("etsy_sync.db.get_all_products", return_value=[p]), \
         patch("etsy_sync.pause_listing") as mock_pause, \
         patch("etsy_sync.restore_listing") as mock_restore:
        etsy_sync.run_etsy_sync()

    mock_restore.assert_called_once_with(p)
    mock_pause.assert_not_called()


def test_run_etsy_sync_no_action_for_already_alerted_out_of_stock():
    p = _product(status="out_of_stock", alerted=True)

    with patch("etsy_sync.db.get_all_products", return_value=[p]), \
         patch("etsy_sync.pause_listing") as mock_pause, \
         patch("etsy_sync.restore_listing") as mock_restore:
        etsy_sync.run_etsy_sync()

    mock_pause.assert_not_called()
    mock_restore.assert_not_called()


def test_run_etsy_sync_skips_ebay_only_products():
    p = _product(status="out_of_stock", alerted=False,
                 etsy_listing_id="12345678", platform="ebay")

    with patch("etsy_sync.db.get_all_products", return_value=[p]), \
         patch("etsy_sync.pause_listing") as mock_pause, \
         patch("etsy_sync.restore_listing") as mock_restore:
        etsy_sync.run_etsy_sync()

    mock_pause.assert_not_called()
    mock_restore.assert_not_called()


def test_run_etsy_sync_sleeps_after_pause():
    p = _product(status="out_of_stock", alerted=False)

    with patch("etsy_sync.db.get_all_products", return_value=[p]), \
         patch("etsy_sync.pause_listing"), \
         patch("etsy_sync.time.sleep") as mock_sleep:
        etsy_sync.run_etsy_sync()

    mock_sleep.assert_called_once()


def test_run_etsy_sync_sleeps_after_restore():
    p = _product(status="in_stock", alerted=True)

    with patch("etsy_sync.db.get_all_products", return_value=[p]), \
         patch("etsy_sync.restore_listing"), \
         patch("etsy_sync.time.sleep") as mock_sleep:
        etsy_sync.run_etsy_sync()

    mock_sleep.assert_called_once()


def test_run_etsy_sync_no_sleep_when_no_action():
    p = _product(status="in_stock", alerted=False)

    with patch("etsy_sync.db.get_all_products", return_value=[p]), \
         patch("etsy_sync.time.sleep") as mock_sleep:
        etsy_sync.run_etsy_sync()

    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# get_access_token
# ---------------------------------------------------------------------------


def test_get_access_token_returns_cached_when_valid():
    etsy_sync._token_cache["access_token"] = "cached-token"
    etsy_sync._token_cache["expires_at"] = time.time() + 7200

    token = etsy_sync.get_access_token()

    assert token == "cached-token"


def test_get_access_token_refreshes_when_expired():
    etsy_sync._token_cache["access_token"] = None
    etsy_sync._token_cache["expires_at"] = 0.0

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "new-etsy-token", "expires_in": 3600}

    with patch("etsy_sync.requests.post", return_value=mock_resp) as mock_post:
        token = etsy_sync.get_access_token()

    assert token == "new-etsy-token"
    assert etsy_sync._token_cache["access_token"] == "new-etsy-token"
    mock_post.assert_called_once()

    etsy_sync._token_cache["access_token"] = None
    etsy_sync._token_cache["expires_at"] = 0.0


def test_get_access_token_raises_on_http_error():
    etsy_sync._token_cache["access_token"] = None
    etsy_sync._token_cache["expires_at"] = 0.0

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("401 Unauthorized")

    with patch("etsy_sync.requests.post", return_value=mock_resp):
        with pytest.raises(Exception, match="401"):
            etsy_sync.get_access_token()

    etsy_sync._token_cache["access_token"] = None
    etsy_sync._token_cache["expires_at"] = 0.0


# ---------------------------------------------------------------------------
# sync_etsy_listing
# ---------------------------------------------------------------------------


def test_sync_etsy_listing_success_with_quantity():
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("etsy_sync.get_access_token", return_value="tok"), \
         patch("etsy_sync.requests.patch", return_value=mock_resp) as mock_patch:
        etsy_sync.sync_etsy_listing.__wrapped__("123", state="active", quantity=5)

    mock_patch.assert_called_once()
    _, kwargs = mock_patch.call_args
    assert kwargs["json"] == {"state": "active", "quantity": 5}


def test_sync_etsy_listing_success_without_quantity():
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("etsy_sync.get_access_token", return_value="tok"), \
         patch("etsy_sync.requests.patch", return_value=mock_resp) as mock_patch:
        etsy_sync.sync_etsy_listing.__wrapped__("123", state="inactive")

    _, kwargs = mock_patch.call_args
    assert "quantity" not in kwargs["json"]


def test_sync_etsy_listing_raises_on_http_error():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("429 Too Many Requests")

    with patch("etsy_sync.get_access_token", return_value="tok"), \
         patch("etsy_sync.requests.patch", return_value=mock_resp):
        with pytest.raises(Exception):
            etsy_sync.sync_etsy_listing.__wrapped__("123", state="inactive")


# ---------------------------------------------------------------------------
# pause_listing
# ---------------------------------------------------------------------------


def test_pause_listing_success_logs_to_db():
    p = _product(status="out_of_stock", alerted=False)

    with patch("etsy_sync.sync_etsy_listing"), \
         patch("etsy_sync.db.log_sync") as mock_log:
        etsy_sync.pause_listing(p)

    mock_log.assert_called_once_with("p1", "etsy", "pause", success=True)


def test_pause_listing_retry_error_logs_failure_and_sends_telegram():
    p = _product(status="out_of_stock", alerted=False)

    with patch("etsy_sync.sync_etsy_listing", side_effect=RetryError(None)), \
         patch("etsy_sync.db.log_sync") as mock_log, \
         patch("etsy_sync.send_telegram") as mock_tg:
        etsy_sync.pause_listing(p)

    mock_log.assert_called_once_with("p1", "etsy", "pause", success=False, error_msg=mock_log.call_args.kwargs["error_msg"])
    mock_tg.assert_called_once()


# ---------------------------------------------------------------------------
# restore_listing
# ---------------------------------------------------------------------------


def test_restore_listing_logs_reactivate_action():
    p = _product(status="in_stock", alerted=True, stock_qty=20)

    with patch("etsy_sync.sync_etsy_listing"), \
         patch("etsy_sync.db.log_sync") as mock_log:
        etsy_sync.restore_listing(p)

    mock_log.assert_called_once_with("p1", "etsy", "reactivate", success=True)


def test_restore_listing_passes_stock_qty():
    p = _product(status="in_stock", alerted=True, stock_qty=7)

    with patch("etsy_sync.sync_etsy_listing") as mock_sync, \
         patch("etsy_sync.db.log_sync"):
        etsy_sync.restore_listing(p)

    mock_sync.assert_called_once_with("12345678", state="active", quantity=7)


def test_restore_listing_retry_error_logs_failure():
    p = _product(status="in_stock", alerted=True)

    with patch("etsy_sync.sync_etsy_listing", side_effect=RetryError(None)), \
         patch("etsy_sync.db.log_sync") as mock_log, \
         patch("etsy_sync.send_telegram"):
        etsy_sync.restore_listing(p)

    mock_log.assert_called_once()
    assert mock_log.call_args.kwargs["success"] is False
    assert mock_log.call_args[0][2] == "reactivate"
