# Looker Studio Dashboard — SQL Views & Setup

Run each SQL block in **Supabase → SQL Editor**. Once all four views exist, connect Looker Studio using the PostgreSQL connector.

---

## SQL Views

### 1. `v_inventory_health`

One row per product — current stock status, margin, and last scrape time.

```sql
CREATE OR REPLACE VIEW v_inventory_health AS
SELECT
    id,
    name,
    platform,
    status,
    stock_qty,
    ROUND(margin_pct::numeric, 2)       AS margin_pct,
    ROUND(net_margin_usd::numeric, 4)   AS net_margin_usd,
    selling_price_usd,
    supplier_price_myr,
    last_checked
FROM products
ORDER BY name;
```

---

### 2. `v_margin_summary`

Counts by margin band (negative / below minimum / healthy) plus average margin across all products.

```sql
CREATE OR REPLACE VIEW v_margin_summary AS
SELECT
    COUNT(*) FILTER (WHERE margin_pct < 0)                          AS negative_count,
    COUNT(*) FILTER (WHERE margin_pct >= 0 AND margin_pct < 20)     AS below_min_count,
    COUNT(*) FILTER (WHERE margin_pct >= 20)                        AS healthy_count,
    COUNT(*)                                                         AS total_count,
    ROUND(AVG(margin_pct)::numeric, 2)                              AS avg_margin_pct
FROM products
WHERE margin_pct IS NOT NULL;
```

> The `< 20` threshold matches `MIN_MARGIN_PCT = 20.0` in `config.py`. Update both if you change the threshold.

---

### 3. `v_sync_success_rate`

Per-platform success/failure counts and success percentage from `sync_log` over the last 7 days.

```sql
CREATE OR REPLACE VIEW v_sync_success_rate AS
SELECT
    platform,
    COUNT(*) FILTER (WHERE success = true)  AS success_count,
    COUNT(*) FILTER (WHERE success = false) AS failure_count,
    COUNT(*)                                AS total_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE success = true) / NULLIF(COUNT(*), 0),
        1
    )                                       AS success_pct
FROM sync_log
WHERE attempted_at >= NOW() - INTERVAL '7 days'
GROUP BY platform
ORDER BY platform;
```

---

### 4. `v_fx_rate_history`

All FX rate snapshots ordered by fetch time — use this for a time-series line chart.

```sql
CREATE OR REPLACE VIEW v_fx_rate_history AS
SELECT
    id,
    ROUND(myr_to_usd::numeric, 6) AS myr_to_usd,
    fetched_at
FROM fx_rates
ORDER BY fetched_at ASC;
```

---

## Looker Studio Setup

### 1. Obtain Supabase database credentials

In your Supabase project go to **Settings → Database** and note:

| Field | Where to find it |
|---|---|
| Host | `db.<project-ref>.supabase.co` |
| Port | `5432` |
| Database name | `postgres` |
| User | `postgres` |
| Password | The password you set when creating the project |

---

### 2. Add a data source in Looker Studio

1. Open [Looker Studio](https://lookerstudio.google.com) → **Create → Data source**.
2. Select the **PostgreSQL** connector.
3. Enter the Supabase credentials from above and click **Authenticate**.
4. Under **Table**, choose a view (e.g. `v_inventory_health`).
5. Click **Connect** → **Create Report**.

Repeat steps 1–5 for each of the four views. You will end up with four data sources.

---

### 3. Suggested charts

| View | Chart type | Key fields |
|---|---|---|
| `v_inventory_health` | Table with heatmap | `margin_pct`, `stock_qty`, `status` |
| `v_margin_summary` | Donut / Pie | `negative_count`, `below_min_count`, `healthy_count` |
| `v_sync_success_rate` | Bar chart | `platform` (dimension), `success_pct` (metric) |
| `v_fx_rate_history` | Time series line | `fetched_at` (dimension), `myr_to_usd` (metric) |

---

### 4. Refresh schedule

Looker Studio caches data by default. To keep charts current:

- Go to **Resource → Manage added data sources → Edit** for each source.
- Set **Data freshness** to **15 minutes** (minimum for the free PostgreSQL connector).
