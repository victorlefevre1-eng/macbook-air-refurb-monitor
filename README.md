# MacBook Air refurb monitor

Checks the **US Apple Refurbished store** every ~5 minutes for a
**13-inch MacBook Air, M4 chip, 24GB memory** and sends a Telegram alert
when one appears.

Runs entirely on GitHub Actions (free on public repos) — works 24/7 even
with your Mac off.

## How it works
- `monitor.py` fetches `apple.com/shop/refurbished/mac/macbook-air`, parses the
  embedded product tiles, and filters for `screensize=13inch` + `memory=24gb` +
  title containing `M4` / `MacBook Air`.
- On a match it posts to Telegram and records the part number in `state.json`
  so it won't re-alert for the same SKU (re-alerts if it disappears and returns).

## Secrets (Settings → Secrets and variables → Actions)
- `TELEGRAM_BOT_TOKEN` — Telegram bot token
- `TELEGRAM_CHAT_ID` — chat ID to notify
- `MAX_PRICE` *(optional)* — only alert at or below this USD price

## Notes
- GitHub cron minimum interval is 5 min and runs are best-effort (may lag under
  load). For sub-minute reactivity, run `monitor.py` locally too.
- No credentials live in the repo — they are stored as encrypted GitHub Secrets.
