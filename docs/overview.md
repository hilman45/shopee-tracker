# Project Overview

## What This Is
An automated inventory monitoring system for a Malaysia-based dropshipper who sources from Shopee and sells on eBay and Etsy.

## The Problem
- Manually checking Shopee supplier stock is time-consuming and error-prone
- Out-of-stock supplier items get sold on eBay/Etsy, causing cancellations and platform penalties
- Supplier price changes in MYR silently erode USD profit margins
- No centralized view of inventory health or profitability

## The Solution
A Python-based automation that:
1. Scrapes Shopee supplier listings every 2 hours
2. Calculates real-time profit margins (MYR → USD)
3. Sends Telegram alerts for stock and margin events
4. Auto-pauses eBay and Etsy listings when stock hits zero
5. Provides a live Looker Studio dashboard

## Seller Context
| Attribute | Detail |
|---|---|
| Location | Malaysia |
| Supplier | Shopee Malaysia (MYR) |
| Selling platforms | eBay + Etsy (USD) |
| Product volume | 50–500+ active listings |
| Currency flow | Pays in MYR, earns in USD |

## Goals
- Eliminate manual stock checking
- Reduce out-of-stock order incidents by 90%
- Full margin visibility per product including FX impact
- Zero-touch listing sync on eBay and Etsy
- Total infrastructure cost: RM 0/month

## Non-Goals (v1)
- Automatic purchasing from suppliers
- Support for non-Shopee suppliers
- Automated price adjustments on eBay/Etsy
- Customer-facing features

## Success Metrics
| Metric | Target |
|---|---|
| Out-of-stock incidents | Reduce by 90% |
| Listing sync success rate | > 98% |
| Alert delivery time | < 10 minutes from event |
| Scraper uptime | > 95% |
| Time saved per week | > 3 hours |
