from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, mock_open, patch

import pytest

import config
import alerts


# ---------------------------------------------------------------------------
# send_telegram
# ---------------------------------------------------------------------------


def test_send_telegram_success_on_first_attempt():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    with patch("alerts.requests.post", return_value=mock_resp) as mock_post:
        result = alerts.send_telegram("hello")

    assert result is True
    assert mock_post.call_count == 1


def test_send_telegram_retries_on_failure_then_succeeds():
    fail = MagicMock()
    fail.raise_for_status.side_effect = Exception("500")
    ok = MagicMock()
    ok.raise_for_status.return_value = None

    with patch("alerts.requests.post", side_effect=[fail, fail, ok]) as mock_post:
        result = alerts.send_telegram("hello")

    assert result is True
    assert mock_post.call_count == 3


def test_send_telegram_writes_log_after_3_failures(tmp_path):
    fail = MagicMock()
    fail.raise_for_status.side_effect = Exception("500")

    log_path = tmp_path / "failed_alerts.log"
    with patch("alerts.requests.post", side_effect=[fail, fail, fail]), \
         patch.object(alerts, "_FAILED_ALERTS_LOG", log_path):
        result = alerts.send_telegram("important message")

    assert result is False
    assert log_path.exists()
    assert "important message" in log_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# check_stock_alerts
# ---------------------------------------------------------------------------


def _product(**kwargs) -> dict:
    base = {
        "id": "p1", "name": "Widget", "status": "in_stock",
        "alerted": False, "stock_qty": 5, "supplier_url": "http://example.com",
    }
    base.update(kwargs)
    return base


def test_check_stock_alerts_out_of_stock_sends_alert_and_sets_alerted():
    p = _product(status="out_of_stock", alerted=False)

    with patch("alerts.send_telegram", return_value=True) as mock_tg, \
         patch("alerts.db.set_alerted") as mock_set:
        alerts.check_stock_alerts([p])

    mock_tg.assert_called_once()
    assert "OUT OF STOCK" in mock_tg.call_args.args[0]
    mock_set.assert_called_once_with("p1", True)


def test_check_stock_alerts_low_stock_sends_warning():
    p = _product(status="low_stock", alerted=False, stock_qty=3)

    with patch("alerts.send_telegram", return_value=True) as mock_tg, \
         patch("alerts.db.set_alerted") as mock_set:
        alerts.check_stock_alerts([p])

    mock_tg.assert_called_once()
    assert "LOW STOCK" in mock_tg.call_args.args[0]
    mock_set.assert_called_once_with("p1", True)


def test_check_stock_alerts_recovery_resets_alerted():
    p = _product(status="in_stock", alerted=True, stock_qty=10)

    with patch("alerts.send_telegram", return_value=True) as mock_tg, \
         patch("alerts.db.set_alerted") as mock_set:
        alerts.check_stock_alerts([p])

    mock_tg.assert_called_once()
    assert "RECOVERED" in mock_tg.call_args.args[0]
    mock_set.assert_called_once_with("p1", False)


def test_check_stock_alerts_no_duplicate_when_already_alerted():
    p = _product(status="out_of_stock", alerted=True)

    with patch("alerts.send_telegram") as mock_tg, \
         patch("alerts.db.set_alerted") as mock_set:
        alerts.check_stock_alerts([p])

    mock_tg.assert_not_called()
    mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# check_margin_alerts
# ---------------------------------------------------------------------------


def _margin_product(**kwargs) -> dict:
    base = {
        "id": "p1", "name": "Widget",
        "margin_pct": 25.0, "net_margin_usd": 10.0,
        "selling_price_usd": 50.0, "supplier_price_myr": 100.0,
        "supplier_url": "http://example.com",
        "margin_alerted_at": None,
    }
    base.update(kwargs)
    return base


def test_check_margin_alerts_negative_margin_fires():
    p = _margin_product(margin_pct=-5.0, net_margin_usd=-2.5)

    with patch("alerts.send_telegram", return_value=True) as mock_tg, \
         patch("alerts.db.set_margin_alerted_at") as mock_set:
        alerts.check_margin_alerts([p])

    mock_tg.assert_called_once()
    assert "LOSS" in mock_tg.call_args.args[0]
    mock_set.assert_called_once()


def test_check_margin_alerts_below_min_margin_fires():
    p = _margin_product(margin_pct=config.MIN_MARGIN_PCT - 1)

    with patch("alerts.send_telegram", return_value=True) as mock_tg, \
         patch("alerts.db.set_margin_alerted_at") as mock_set:
        alerts.check_margin_alerts([p])

    mock_tg.assert_called_once()
    assert "LOW MARGIN" in mock_tg.call_args.args[0]
    mock_set.assert_called_once()


def test_check_margin_alerts_debounce_skips_within_6h():
    recent_ts = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    p = _margin_product(margin_pct=-5.0, margin_alerted_at=recent_ts)

    with patch("alerts.send_telegram") as mock_tg, \
         patch("alerts.db.set_margin_alerted_at") as mock_set:
        alerts.check_margin_alerts([p])

    mock_tg.assert_not_called()
    mock_set.assert_not_called()


def test_check_margin_alerts_fires_after_debounce_window():
    old_ts = (
        datetime.now(timezone.utc) - timedelta(hours=7)
    ).isoformat()
    p = _margin_product(margin_pct=-5.0, margin_alerted_at=old_ts)

    with patch("alerts.send_telegram", return_value=True) as mock_tg, \
         patch("alerts.db.set_margin_alerted_at"):
        alerts.check_margin_alerts([p])

    mock_tg.assert_called_once()


# ---------------------------------------------------------------------------
# check_fx_alert
# ---------------------------------------------------------------------------


def test_check_fx_alert_fires_when_change_exceeds_threshold():
    products = [_margin_product(margin_pct=15.0)]
    old_rate = 0.23
    new_rate = old_rate * (1 + config.FX_ALERT_THRESHOLD + 0.01)

    with patch("alerts.send_telegram") as mock_tg:
        alerts.check_fx_alert(old_rate, new_rate, products)

    mock_tg.assert_called_once()
    assert "FX RATE" in mock_tg.call_args.args[0]


def test_check_fx_alert_skips_when_change_below_threshold():
    products = [_margin_product()]
    old_rate = 0.23
    new_rate = old_rate * (1 + config.FX_ALERT_THRESHOLD / 2)

    with patch("alerts.send_telegram") as mock_tg:
        alerts.check_fx_alert(old_rate, new_rate, products)

    mock_tg.assert_not_called()


def test_check_fx_alert_handles_empty_product_list():
    old_rate = 0.23
    new_rate = old_rate * (1 + config.FX_ALERT_THRESHOLD + 0.01)

    with patch("alerts.send_telegram") as mock_tg:
        alerts.check_fx_alert(old_rate, new_rate, [])

    mock_tg.assert_called_once()
    call_text = mock_tg.call_args.args[0]
    assert "0 products" in call_text


def test_check_fx_alert_old_rate_zero_is_noop():
    """When old_rate is 0 the function returns early without sending."""
    with patch("alerts.send_telegram") as mock_tg:
        alerts.check_fx_alert(0.0, 0.25, [_margin_product()])
    mock_tg.assert_not_called()


# ---------------------------------------------------------------------------
# check_margin_alerts — unparseable margin_alerted_at
# ---------------------------------------------------------------------------


def test_check_margin_alerts_unparseable_alerted_at_still_fires():
    """A margin_alerted_at that cannot be parsed as ISO datetime must not suppress the alert."""
    p = _margin_product(margin_pct=-5.0, margin_alerted_at="not-a-date")

    with patch("alerts.send_telegram", return_value=True) as mock_tg, \
         patch("alerts.db.set_margin_alerted_at"):
        alerts.check_margin_alerts([p])

    mock_tg.assert_called_once()


# ---------------------------------------------------------------------------
# check_price_increase_alert
# ---------------------------------------------------------------------------


def test_check_price_increase_alert_fires_when_price_rose():
    p = _margin_product()
    p["_price_old"] = 100.0
    p["_price_new"] = 120.0

    with patch("alerts.send_telegram") as mock_tg:
        alerts.check_price_increase_alert([p])

    mock_tg.assert_called_once()
    msg = mock_tg.call_args.args[0]
    assert "SUPPLIER PRICE INCREASE" in msg
    assert "RM100.00" in msg
    assert "RM120.00" in msg


def test_check_price_increase_alert_skips_when_price_unchanged():
    p = _margin_product()
    p["_price_old"] = 100.0
    p["_price_new"] = 100.0

    with patch("alerts.send_telegram") as mock_tg:
        alerts.check_price_increase_alert([p])

    mock_tg.assert_not_called()


def test_check_price_increase_alert_skips_when_price_decreased():
    p = _margin_product()
    p["_price_old"] = 120.0
    p["_price_new"] = 100.0

    with patch("alerts.send_telegram") as mock_tg:
        alerts.check_price_increase_alert([p])

    mock_tg.assert_not_called()


def test_check_price_increase_alert_skips_missing_price_keys():
    p = _margin_product()  # no _price_old / _price_new

    with patch("alerts.send_telegram") as mock_tg:
        alerts.check_price_increase_alert([p])

    mock_tg.assert_not_called()


# ---------------------------------------------------------------------------
# run_alerts
# ---------------------------------------------------------------------------


def test_run_alerts_calls_all_checks():
    products = [_product(status="out_of_stock", alerted=False)]

    with patch("alerts.db.get_all_products", return_value=products), \
         patch("alerts.db.get_two_latest_fx_rates", return_value=(None, None)), \
         patch("alerts.check_stock_alerts") as mock_stock, \
         patch("alerts.check_margin_alerts") as mock_margin, \
         patch("alerts.check_fx_alert") as mock_fx:
        alerts.run_alerts()

    mock_stock.assert_called_once_with(products)
    mock_margin.assert_called_once_with(products)
    mock_fx.assert_not_called()  # no FX rates available


def test_run_alerts_fires_fx_check_when_rates_available():
    products = [_product()]

    with patch("alerts.db.get_all_products", return_value=products), \
         patch("alerts.db.get_two_latest_fx_rates", return_value=(0.22, 0.25)), \
         patch("alerts.check_stock_alerts"), \
         patch("alerts.check_margin_alerts"), \
         patch("alerts.check_fx_alert") as mock_fx:
        alerts.run_alerts()

    mock_fx.assert_called_once_with(0.22, 0.25, products)
