# PokeAlert — Ethical Pokémon Stock Alert System

A modular, respectful stock-alert system that monitors Pokémon product availability across major US retailers and sends alerts to Discord, Telegram, or email when items come back in stock.

> ⚠️ **Ethics first.** This tool is designed only for **monitoring** — it does **not** bypass anti-bot protections, solve CAPTCHAs, skip queues, or auto-checkout. It uses official APIs where available and respects `robots.txt`, rate limits, and retailer Terms of Service. You are responsible for how you use it.

---

## Features

- ✅ **Modular checkers** — one file per retailer, easy to add more
- ✅ **Official APIs preferred** — Best Buy Products API, Target RedSky, Amazon PA-API
- ✅ **Polite by default** — identifies itself via User-Agent, throttles requests, honors `robots.txt`
- ✅ **Change detection** — alerts fire only on *transitions* (OOS → In Stock), not on every check
- ✅ **Cooldown / dedup** — prevents alert spam
- ✅ **Multi-channel alerts** — Discord webhook, Telegram bot, SMTP email, desktop
- ✅ **SQLite state store** — persists previous stock state across restarts
- ✅ **Docker support** — one-command deployment

## Supported Retailers

| Retailer | Method | Works from Railway/Cloud? |
|---|---|---|
| Pokémon Center | Public product pages | ✅ Yes |
| Target | RedSky API (public) | ⛔ Blocked by robots.txt — needs proxy |
| Best Buy | Official Products API | ✅ Yes, with `BESTBUY_API_KEY` |
| Walmart | Public product pages | ⛔ WAF 412 — needs residential proxy |
| GameStop | Public product pages | ⛔ WAF 403 — needs residential proxy |
| Amazon | PA-API 5.0 (affiliate key required) | ✅ Yes, with PA-API creds |
| Costco | Public product pages | ⚠️ Sometimes — may need proxy |

### Why do some retailers show "BLOCKED"?

Major retailers actively block requests coming from cloud/datacenter IPs
(Railway, Fly, Render, AWS, etc.). This is **not** something an API key
can fix for GameStop/Walmart/Target — their WAFs look at the source IP's
reputation, not your credentials.

**The fix is a residential or mobile proxy.** Set `PROXY_URL` in your
environment (see `.env.example` for format and recommended providers).
When set, PokeAlert automatically:
- Routes all traffic through the proxy
- Switches to a rotating browser User-Agent
- Adds standard browser headers

Without a proxy, PokeAlert marks those retailers as `BLOCKED` (a distinct
state from `ERROR`) and continues polling the retailers that *do* work
from cloud IPs (Pokémon Center, Best Buy via API, Amazon via API).

## Quickstart

```bash
# 1. Clone or unzip the project
cd pokemon-stock-alerts

# 2. Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Copy config and env templates
cp config/config.example.yaml config/config.yaml
cp .env.example .env

# 4. Edit config/config.yaml — add the products you want to track
# 5. Edit .env — add your Discord webhook, Telegram token, etc.

# 6. Run it
python -m pokealert.main run --config config/config.yaml
```

Or with Docker:

```bash
docker compose up -d
```

## Configuration

Products are defined in `config/config.yaml`:

```yaml
products:
  - name: "Pokémon 151 Elite Trainer Box"
    retailer: pokemoncenter
    url: https://www.pokemoncenter.com/product/XXXXXXX
    min_interval_seconds: 120

  - name: "Scarlet & Violet Booster Box"
    retailer: target
    tcin: "89264024"
    min_interval_seconds: 90
```

## Ethics & Compliance

Read `docs/ETHICS.md` before use. Key rules this tool enforces:

1. **Identifies itself** in User-Agent so admins can block if desired
2. **Minimum 60s interval** between checks of the same product on the same retailer (configurable higher)
3. **Exponential backoff** on 429/503 responses
4. **Respects `robots.txt`** where applicable
5. **No cart interaction, no checkout, no session hijacking, no CAPTCHA bypass**

If a retailer asks you to stop, stop. Don't be a jerk — bots that hammer retailers are what caused the Pokémon shortage alert chaos in the first place.

## License

MIT. No warranty. Use responsibly.