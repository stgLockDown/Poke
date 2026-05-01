# PokeAlert Quickstart (5 minutes)

## 1. Install

```bash
cd pokemon-stock-alerts
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Create your config

```bash
cp config/config.example.yaml config/config.yaml
cp .env.example .env
```

## 3. Get a Discord webhook (easiest notifier)

1. Open your Discord server → **Server Settings** → **Integrations** → **Webhooks**
2. **New Webhook** → pick a channel → **Copy Webhook URL**
3. Paste into `.env` as `DISCORD_WEBHOOK_URL=...`

## 4. Find product IDs

| Retailer | What you need | Where to find it |
|---|---|---|
| Pokémon Center | URL | Copy from browser |
| Target | TCIN | Look in URL: `/-/A-89264024` → TCIN is `89264024` |
| Best Buy | SKU | Look in URL: `.p?skuId=6522738` → SKU is `6522738` |
| Walmart | URL | Copy from browser |
| GameStop | URL | Copy from browser |
| Amazon | ASIN | Look in URL: `/dp/B0C8N1SM4R` → ASIN is `B0C8N1SM4R` |
| Costco | URL | Copy from browser |

## 5. Edit `config/config.yaml`

Keep only the products you actually want to track. Delete or comment out the rest.
Each product needs `min_interval_seconds >= 60` (hard floor enforced by the code).

## 6. Do a dry run

```bash
python -m pokealert.main check-once --config config/config.yaml
```

You should see one log line per product with its current state. No alerts are
sent during `check-once` — it just seeds the state DB.

## 7. Start the monitor

```bash
python -m pokealert.main run --config config/config.yaml
```

Or in the background with Docker:

```bash
docker compose up -d
docker compose logs -f
```

## 8. Test an alert (optional)

Temporarily delete `data/state.db` and restart. On the next check, every in-stock
product will fire as a "first observation" alert so you can verify your
Discord/Telegram/email is wired up correctly. Delete again after testing.

## Troubleshooting

- **No alerts firing?** Run with `--log-level DEBUG`. Check that `check_done`
  logs show `state=in_stock` — if they all show `state=out_of_stock`, nothing
  is actually in stock right now.
- **`robots_disallowed` in logs?** The retailer's `robots.txt` forbids the path.
  This is working as designed. Use their official API or the retailer's own
  email notify-me feature instead.
- **Repeated `HTTP 503` from Pokémon Center?** A drop is live and Queue-It is
  active. The checker will correctly report `queue_active` and alert you; go
  open the page in a browser and wait in line like everyone else.
- **Amazon errors about creds?** You need an Associates account and PA-API
  access. If you don't have one, remove Amazon products from your config.