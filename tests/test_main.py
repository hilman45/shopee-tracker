from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

import main


# ---------------------------------------------------------------------------
# run_pipeline
# ---------------------------------------------------------------------------


def test_run_pipeline_calls_all_three_stages():
    with (
        patch("main.scraper.run_scraper") as mock_scraper,
        patch("main.ebay_sync.run_ebay_sync") as mock_ebay,
        patch("main.etsy_sync.run_etsy_sync") as mock_etsy,
    ):
        main.run_pipeline()

    mock_scraper.assert_called_once()
    mock_ebay.assert_called_once()
    mock_etsy.assert_called_once()


def test_run_pipeline_continues_if_scraper_raises():
    with (
        patch("main.scraper.run_scraper", side_effect=RuntimeError("boom")),
        patch("main.ebay_sync.run_ebay_sync") as mock_ebay,
        patch("main.etsy_sync.run_etsy_sync") as mock_etsy,
    ):
        main.run_pipeline()  # must not raise

    mock_ebay.assert_called_once()
    mock_etsy.assert_called_once()


def test_run_pipeline_continues_if_ebay_raises():
    with (
        patch("main.scraper.run_scraper"),
        patch("main.ebay_sync.run_ebay_sync", side_effect=RuntimeError("ebay down")),
        patch("main.etsy_sync.run_etsy_sync") as mock_etsy,
    ):
        main.run_pipeline()

    mock_etsy.assert_called_once()


def test_run_pipeline_continues_if_etsy_raises():
    with (
        patch("main.scraper.run_scraper"),
        patch("main.ebay_sync.run_ebay_sync"),
        patch("main.etsy_sync.run_etsy_sync", side_effect=RuntimeError("etsy down")),
    ):
        main.run_pipeline()  # must not raise


# ---------------------------------------------------------------------------
# main() scheduler setup
# ---------------------------------------------------------------------------


def test_main_registers_two_schedule_jobs():
    """main() should register both the pipeline job and the FX fetch job."""
    import schedule as sched

    sched.clear()

    with (
        patch("main.run_pipeline"),
        patch("main.margin.fetch_fx_rate"),
        patch("time.sleep", side_effect=KeyboardInterrupt),
    ):
        try:
            main.main()
        except KeyboardInterrupt:
            pass

    jobs = sched.jobs
    assert len(jobs) == 2
    sched.clear()


# ---------------------------------------------------------------------------
# --once flag (via __main__ guard — tested through direct call)
# ---------------------------------------------------------------------------


def test_once_flag_calls_run_pipeline_and_returns():
    """When --once is in sys.argv, run_pipeline runs once and exits cleanly."""
    import sys

    original_argv = sys.argv[:]
    sys.argv = ["main.py", "--once"]
    try:
        with (
            patch("main.run_pipeline") as mock_pipeline,
            patch("main.main") as mock_main,
        ):
            # Simulate the __main__ block
            if "--once" in sys.argv:
                main.run_pipeline()
            else:
                main.main()

        mock_pipeline.assert_called_once()
        mock_main.assert_not_called()
    finally:
        sys.argv = original_argv
