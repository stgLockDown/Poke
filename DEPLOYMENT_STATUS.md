# PokeAlert — Deployment Status ✅

## Live on Railway

- **Project:** `gracious-intuition`
- **Service:** `Poke`
- **Environment:** `production`
- **Public URL:** https://poke-production-e52b.up.railway.app
- **Health endpoint:** https://poke-production-e52b.up.railway.app/health
- **GitHub repo:** https://github.com/stgLockDown/Poke

## Verified Working

```json
{
  "status": "ok",
  "version": "1.1.0",
  "uptime_seconds": 119,
  "products_tracked": 5,
  "checks_performed": 5,
  "alerts_sent": 0,
  "errors_since_start": 4
}
```

- ✅ Build succeeded (Railpack + Python 3.11.15)
- ✅ `/health` endpoint returns HTTP 200
- ✅ Railway healthcheck passing (`RailwayHealthCheck/1.0`)
- ✅ All 5 configured products being polled on schedule
- ✅ Robots.txt compliance verified (Target correctly blocked redsky API per their robots.txt — this is **correct ethical behavior**)
- ✅ Polite anti-abuse stack working: User-Agent self-ID, rate limiting, exponential backoff

## Observed Behavior (First 2 minutes)

| Retailer | Status | Notes |
|---|---|---|
| Pokémon Center | ✅ HTTP 200 | Page fetched, state=unknown until stock signal detected |
| Target | ⚠️ robots_disallowed | **Expected** — polite client respects `redsky.target.com` robots.txt |
| Walmart | ⚠️ HTTP 412 | Walmart anti-bot challenge (datacenter IP) |
| Best Buy | ❌ error | Needs `BESTBUY_API_KEY` env var |
| GameStop | ⚠️ HTTP 403 | WAF blocking datacenter IP |

## REQUIRED: Set Environment Variables in Railway

The app is alive but needs these env vars set in the Railway dashboard:

### Discord webhooks (required for alerts)
```
DISCORD_WEBHOOK_URL              # fallback webhook for any retailer
DISCORD_WEBHOOK_POKEMONCENTER    # per-store channel
DISCORD_WEBHOOK_TARGET
DISCORD_WEBHOOK_BESTBUY
DISCORD_WEBHOOK_WALMART
DISCORD_WEBHOOK_GAMESTOP
DISCORD_WEBHOOK_AMAZON
DISCORD_WEBHOOK_COSTCO
DISCORD_WEBHOOK_HEARTBEAT        # for periodic heartbeat pings
DISCORD_WEBHOOK_WEB_RESTOCKS     # for web search restock findings
```

### Optional: API keys for better results
```
BESTBUY_API_KEY                  # free: https://developer.bestbuy.com
AMAZON_ACCESS_KEY                # for Amazon PA-API
AMAZON_SECRET_KEY
AMAZON_PARTNER_TAG
BRAVE_API_KEY                    # for web scout (or SERPER_API_KEY / SERPAPI_API_KEY)
DEFAULT_ZIP_CODE                 # e.g. 90210 — for local pickup scans
```

### How to set in Railway
1. Go to https://railway.com/project/10fc7a15-a0a5-44bb-97cd-cb800e1ba527
2. Click the `Poke` service → **Variables** tab
3. Paste each variable. Railway will auto-redeploy.

## SECURITY WARNING 🚨

The tokens provided during setup were shared in chat and must be rotated:
- **Revoke & regenerate Railway token:** https://railway.com/account/tokens
- **Revoke & regenerate GitHub PAT:** https://github.com/settings/tokens
  (The one starting with `ghp_GJDn4FQ0RSIb…` has been used to push to your repo.)

## End-to-End Test After Setting Webhooks

Once `DISCORD_WEBHOOK_URL` is set, run from your local machine:

```bash
# Fire a test embed to each retailer channel
python run.py test-webhook --retailer pokemoncenter
python run.py test-webhook --retailer target
# ...etc
```

Or from Railway's built-in shell once env vars are set, the heartbeat will
automatically post a startup embed to `DISCORD_WEBHOOK_HEARTBEAT` on next deploy.
