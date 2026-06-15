#!/usr/bin/env python3
"""
Apple US Refurbished monitor — alerts on Telegram when a target MacBook Air
configuration appears in the refurbished store.

Target (default): 13-inch, Apple M4 chip, 24GB unified memory.
Runs once per invocation; schedule it every 10 min with launchd/cron.

Config is read from monitor.env (same folder) or environment variables:
  TELEGRAM_BOT_TOKEN   required
  TELEGRAM_CHAT_ID     required
  MAX_PRICE            optional, e.g. 1200  (only alert at/below this USD price)
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "state.json"
LOG_FILE = HERE / "monitor.log"
ENV_FILE = HERE / "monitor.env"

PAGE_URL = "https://www.apple.com/shop/refurbished/mac/macbook-air"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")

# --- Target filter -----------------------------------------------------------
TARGET_SCREEN = "13inch"
TARGET_MEMORY = "24gb"
TARGET_CHIP = "M4"          # must appear in title
TARGET_PRODUCT = "MacBook Air"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def load_env() -> None:
    if ENV_FILE.exists():
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def fetch_html() -> str:
    req = urllib.request.Request(PAGE_URL, headers={"User-Agent": UA,
                                                    "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_tiles(html: str):
    """Locate the embedded product array and return it as a list of dicts."""
    i = html.find('"filters":{"dimensions"')
    if i == -1:
        raise RuntimeError("product data not found in page (layout changed?)")
    # walk back to the enclosing '['
    depth = 0
    start = None
    for j in range(i, -1, -1):
        c = html[j]
        if c == "]":
            depth += 1
        elif c == "[":
            if depth == 0:
                start = j
                break
            depth -= 1
    if start is None:
        raise RuntimeError("could not locate start of product array")
    depth = 0
    end = None
    for j in range(start, len(html)):
        c = html[j]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    return json.loads(html[start:end])


def matches(tile: dict) -> bool:
    dims = tile.get("filters", {}).get("dimensions", {})
    title = tile.get("title", "") or ""
    # 13-inch via either the dimension field OR the title (more robust: the
    # screensize dimension can vanish when stock churns, but the title is stable)
    is_13 = dims.get("dimensionScreensize") == TARGET_SCREEN or "13-inch" in title
    return (
        is_13
        and dims.get("tsMemorySize") == TARGET_MEMORY
        and TARGET_CHIP in title
        and TARGET_PRODUCT in title
    )


def price_of(tile: dict):
    raw = tile.get("price", {}).get("currentPrice", {}).get("raw_amount")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def link_of(tile: dict) -> str:
    url = tile.get("productDetailsUrl") or ""
    if url.startswith("/"):
        url = "https://www.apple.com" + url
    return url or PAGE_URL


def send_telegram(token: str, chat_id: str, text: str) -> bool:
    api = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(api, data=data), timeout=20) as r:
            ok = json.loads(r.read().decode()).get("ok", False)
            if not ok:
                log("Telegram API returned ok=false")
            return ok
    except Exception as e:  # noqa: BLE001
        log(f"Telegram send failed: {e}")
        return False


def load_state() -> set:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            return set()
    return set()


def save_state(seen: set) -> None:
    STATE_FILE.write_text(json.dumps(sorted(seen)))


def main() -> int:
    load_env()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    max_price = os.environ.get("MAX_PRICE")
    max_price = float(max_price) if max_price else None

    if not token or not chat_id:
        log("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set (see monitor.env)")
        return 2

    # --test sends a Telegram message and exits, to verify credentials
    if "--test" in sys.argv:
        ok = send_telegram(token, chat_id,
                           "✅ MacBook Air monitor is live. I'll ping you when a "
                           "13\" M4 / 24GB refurb appears (US store).")
        log(f"test message sent: {ok}")
        return 0 if ok else 1

    try:
        html = fetch_html()
        tiles = parse_tiles(html)
    except Exception as e:  # noqa: BLE001
        log(f"fetch/parse error: {e}")
        return 1

    hits = [t for t in tiles if matches(t)]
    if max_price is not None:
        hits = [t for t in hits if (price_of(t) or 1e9) <= max_price]

    seen = load_state()
    new = [t for t in hits if t.get("partNumber") not in seen]

    log(f"checked: {len(tiles)} tiles, {len(hits)} target match(es), "
        f"{len(new)} new")

    for t in new:
        price = price_of(t)
        pstr = f"${price:,.2f}" if price is not None else "n/a"
        savings = t.get("price", {}).get("savings", "")
        title = t.get("title", "")
        msg = (
            "🚨 <b>MacBook Air 13\" M4 / 24GB dispo en refurb US !</b>\n\n"
            f"<b>{title}</b>\n"
            f"💵 {pstr}  {savings}\n"
            f"🔗 {link_of(t)}\n\n"
            f"<i>Part: {t.get('partNumber')}</i>"
        )
        if send_telegram(token, chat_id, msg):
            seen.add(t.get("partNumber"))
            log(f"ALERT sent for {t.get('partNumber')} @ {pstr}")

    # keep only part numbers still listed, so a SKU re-alerts if it returns later
    current = {t.get("partNumber") for t in hits}
    save_state(seen & current)
    return 0


if __name__ == "__main__":
    sys.exit(main())
