from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

# Set dummy credentials before config.py is imported so startup validation passes.
_DUMMY_ENV = {
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_KEY": "test-key",
    "TELEGRAM_BOT_TOKEN": "test-token",
    "TELEGRAM_CHAT_ID": "123456",
    "EBAY_CLIENT_ID": "test-ebay-id",
    "EBAY_CLIENT_SECRET": "test-ebay-secret",
    "EBAY_REFRESH_TOKEN": "test-ebay-refresh",
    "ETSY_CLIENT_ID": "test-etsy-id",
    "ETSY_REFRESH_TOKEN": "test-etsy-refresh",
    "ETSY_SHOP_ID": "test-shop-id",
}
for _k, _v in _DUMMY_ENV.items():
    os.environ.setdefault(_k, _v)

# Stub out supabase so db.py can be imported without real credentials.
sys.modules.setdefault("supabase", MagicMock())

# Stub out playwright so scraper.py can be imported without browsers installed.
sys.modules.setdefault("playwright", MagicMock())
sys.modules.setdefault("playwright.sync_api", MagicMock())
