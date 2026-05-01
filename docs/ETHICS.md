# Ethics & Compliance Guide

## Why This Matters

The Pokémon TCG resale ecosystem has been plagued by aggressive bots that:
- Hammer retailer websites with thousands of requests per second
- Bypass CAPTCHAs and anti-bot systems
- Automate checkout to buy out inventory before humans can click
- Resell at 2–10x retail, hurting kids and collectors

**This tool is the opposite of that.** It is a monitor — it tells *you* when something is in stock, then you decide whether to open the page and buy it like a normal human.

## Hard Rules Enforced by This Code

### 1. Identifies Itself
Every request sends a `User-Agent` header like:
```
PokeAlert/1.0 (+https://github.com/yourname/pokealert; ethical-stock-monitor)
```
Retailers can block this User-Agent in seconds if they want to. That's fine.

### 2. Respects Rate Limits
- Hard minimum 60 seconds between checks of the same URL.
- Default 120–300 seconds recommended.
- Exponential backoff on `429 Too Many Requests` or `503 Service Unavailable`.
- Circuit breaker: if a retailer returns >5 errors in a row, pause that retailer for 10 minutes.

### 3. Respects `robots.txt`
On first check of a retailer, the tool fetches `/robots.txt` and caches it for 24h. If a product URL is disallowed, the checker skips it and logs a warning.

### 4. Uses Official APIs When Available
- **Best Buy**: Official Products API (developer.bestbuy.com) — free key required
- **Amazon**: Product Advertising API 5.0 — requires Amazon Associates account
- **Target**: RedSky is a public API used by target.com itself; no auth bypass
- Others: public product pages only

### 5. Does NOT Do Any of These
- ❌ Solve CAPTCHAs (no 2Captcha, Anti-Captcha, etc.)
- ❌ Bypass queues (e.g. Queue-It on Pokémon Center)
- ❌ Rotate residential proxies to evade bans
- ❌ Simulate browser fingerprints to look human
- ❌ Automate add-to-cart or checkout
- ❌ Use retailer session cookies or log in on your behalf
- ❌ Scrape at rates that could be mistaken for a DDoS

If you want any of the above, you want a different tool. Please don't fork this to add them.

## What YOU Are Responsible For

1. **Read the Terms of Service** of each retailer you monitor. Some prohibit *any* automated access. If so, don't monitor them with this tool — use their official notify-me features instead (most retailers offer email/SMS notifications natively).
2. **Don't share alerts publicly to huge groups** if your goal is to flip. If you're running a community Discord, encourage members to buy 1 and leave stock for others.
3. **Stop if asked.** If a retailer sends a cease-and-desist, or blocks your IP, respect it.

## Retailer-Specific Notes

### Pokémon Center
Pokémon Center uses Queue-It during high-demand drops. This tool will *detect* that a queue is active (by checking response patterns) and simply report "queue active" — it will **not** attempt to join, bypass, or automate the queue.

### Target
RedSky is Target's public backend API. It's used by target.com itself and is widely documented. Polling it at reasonable rates (60s+) is standard practice for price comparison tools.

### Best Buy
Use the official Products API: https://developer.bestbuy.com/. Free, documented, and intended for exactly this use case.

### Amazon
Use the Product Advertising API 5.0. You need an Associates account. Scraping amazon.com product pages is against their ToS — this tool does not do that.

### Walmart / GameStop / Costco
Public product pages only, with extended intervals (180s+ recommended). If you can use their official affiliate APIs, prefer those.

## The Golden Rule

> Treat the retailer's servers the way you'd want someone to treat yours.

That's it. If you follow that, you're fine.