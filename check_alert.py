import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "alert_config.json"
PRICES = ROOT / "prices.json"


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Telegram secrets are missing")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urlencode({"chat_id": chat_id, "text": message}).encode()
    req = Request(url, data=body, method="POST")
    with urlopen(req, timeout=20) as response:
        if response.status != 200:
            raise RuntimeError(f"Telegram returned HTTP {response.status}")


def main():
    config = load(CONFIG, {})
    if not config.get("enabled"):
        print("Alert disabled")
        return

    server = str(config.get("server", "")).strip()
    target = float(config.get("target_price", 0))
    if not server or target <= 0:
        print("Invalid alert configuration")
        return

    payload = load(PRICES, {})
    sites = payload.get("sites", {})
    data = payload.get("data", {})
    hits = []

    for site_id, site_data in data.items():
        entry = site_data.get(server)
        if not entry:
            continue
        price = entry.get("price")
        if price is None:
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        # Only alert on sellers that are currently open/available.
        if entry.get("open") is True and price >= target:
            hits.append((site_id, sites.get(site_id, {}).get("name", site_id), price))

    if not hits:
        # Reset the latch so a later fresh crossing can alert again.
        if config.get("triggered"):
            config["triggered"] = False
            CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"No seller reached {target:.2f} DH/M on {server}.")
        return

    if config.get("notify_once", True) and config.get("triggered"):
        print("Target already alerted; waiting for price to fall below target before alerting again.")
        return

    best = max(hits, key=lambda x: x[2])
    lines = [
        "🔔 Kamas price alert!",
        f"Server: {server}",
        f"Target: {target:.2f} DH/M",
        f"Reached: {best[2]:.2f} DH/M on {best[1]}",
        "",
        "Other sellers at/above target:",
    ]
    lines.extend(f"- {name}: {price:.2f} DH/M" for _, name, price in hits)
    send_telegram("\n".join(lines))

    config["triggered"] = True
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Alert sent for {server} at target {target:.2f} DH/M")


if __name__ == "__main__":
    main()
