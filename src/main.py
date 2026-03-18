from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time

import schedule
from loguru import logger

import config
import ebay_sync
import etsy_sync
import margin
import scraper

logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("logs/main.log", rotation="10 MB", retention=5, level="DEBUG")


def run_pipeline() -> None:
    logger.info("Pipeline started")

    try:
        scraper.run_scraper()
    except Exception as exc:
        logger.error(f"scraper.run_scraper() failed: {exc}")

    try:
        ebay_sync.run_ebay_sync()
    except Exception as exc:
        logger.error(f"ebay_sync.run_ebay_sync() failed: {exc}")

    try:
        etsy_sync.run_etsy_sync()
    except Exception as exc:
        logger.error(f"etsy_sync.run_etsy_sync() failed: {exc}")

    logger.info("Pipeline finished")


def main() -> None:
    run_pipeline()
    schedule.every(config.SCRAPE_INTERVAL_HOURS).hours.do(run_pipeline)
    schedule.every(config.FX_FETCH_INTERVAL_HOURS).hours.do(margin.fetch_fx_rate)
    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_pipeline()
    else:
        main()
