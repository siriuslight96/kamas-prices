#!/usr/bin/env python3
"""
Fetches kamas sell prices (DH/M) and stock status from iBendouma, LesKamas
and VenteKamas, and writes prices.json. Run by the GitHub Actions workflow
in .github/workflows/update-prices.yml on a schedule — this is what keeps
the published site current without any server of your own.
"""

import json
import re
import time
import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUT_DIR = Path(__file__).parent

SITES = {
    "ibendouma": {"name": "iBendouma", "url": "https://www.ibendouma.com/vendre"},
    "leskamas": {"name": "LesKamas", "url": "https://www.leskamas.com/en-gb/sell-kamas.html"},
    "ventekamas": {"name": "VenteKamas", "url": "https://ventekamas.com/vendre-des-kamas/"},
    "tryandjudge": {"name": "TryAndJudge", "url": "https://vente.tryandjudge.com/dofuskamas.php"},
}

SERVERS = [
    "Dakal", "Rafal", "Brial", "Kourial", "Orukam", "Tylezia",
    "Draconiros", "Hell Mina", "Imagiro", "Talkasha", "Ombre", "Mikhal",
    "Salar", "Blair", "Kelerog", "Tiliwan", "Talok", "Boune", "Allisteria",
    "Fallanster", "Pandora", "Ogrest", "Rubilax",
]

ALIASES = {
    "Hell Mina": ["Hell Mina", "HellMina", "Hellmina", "Hell-Mina"],
    "Talkasha": ["Talkasha", "TalKasha", "Tal Kasha"],
    "Ombre": ["Ombre(Shadow)", "Ombre (Shadow)", "Ombre"],
}


def variants_for(server):
    return ALIASES.get(server, [server])


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def fetch_text(url):
    bust_url = url + ("&" if "?" in url else "?") + f"_ts={int(datetime.datetime.utcnow().timestamp())}"
    resp = requests.get(bust_url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


# Each site formats its price differently: period vs comma decimals, and a
# different currency suffix right after the number.
PRICE_PATTERNS = {
    "ibendouma": r"([0-9]+\.[0-9]+)\s*Dhs?/M",
    "leskamas": r"([0-9]+\.[0-9]+)\s*Dhs?/M",
    "ventekamas": r"([0-9]+\.[0-9]+)\s*Dhs?/M",
    "tryandjudge": r"([0-9]+,[0-9]+)\s*\*?MAD",
}

# status word -> True (still buying / open) or False (full / closed),
# per site. Order matters: more specific phrases first.
STATUS_WORDS = {
    "ibendouma": [("Stock complet", False), ("Ouvert", True)],
    "leskamas": [("Sourcing", True), ("Full", False)],
    "ventekamas": [("Incomplet", True), ("Stock complet", False)],
    "tryandjudge": [("Stock complet", False), ("Ferme", False), ("Ferm", False), ("Ouvert", True)],
}


def parse_site(site_id, text):
    results = {}
    price_pattern = PRICE_PATTERNS[site_id]
    status_alt = "|".join(re.escape(word) for word, _ in STATUS_WORDS[site_id])
    status_lookup = dict(STATUS_WORDS[site_id])

    for server in SERVERS:
        match = None
        for variant in variants_for(server):
            # Status word must appear within a SHORT window right after the
            # price (same cell/row), never searched across the whole page,
            # so it can't pick up an unrelated server's status.
            pattern = re.compile(
                re.escape(variant) + r".{0,150}?" + price_pattern + r".{0,80}?(" + status_alt + r")",
                re.IGNORECASE | re.DOTALL,
            )
            match = pattern.search(text)
            if match:
                break
        if not match:
            continue
        price = float(match.group(1).replace(",", "."))
        status_word = match.group(2)
        open_status = next(
            (v for k, v in status_lookup.items() if k.lower() == status_word.lower()), None
        )
        results[server] = {"price": price, "open": open_status}
    return results


def fetch_site_with_retry(site_id, cfg, attempts=2):
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            text = fetch_text(cfg["url"])
            parsed = parse_site(site_id, text)
            if parsed:
                return parsed, None
            last_exc = "page fetched but no prices matched (site layout may have changed)"
        except Exception as exc:  # noqa: BLE001
            last_exc = str(exc)
        if attempt < attempts:
            time.sleep(3)
    return None, last_exc


def load_previous():
    path = OUT_DIR / "prices.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("data", {})
    except Exception:  # noqa: BLE001
        return {}


def main():
    previous = load_previous()
    data = {}
    errors = {}
    stale = []

    for site_id, cfg in SITES.items():
        parsed, err = fetch_site_with_retry(site_id, cfg)
        if parsed:
            data[site_id] = parsed
        else:
            # Keep last known good data instead of wiping it to empty, so a
            # transient block/anti-bot response doesn't blank the site out.
            data[site_id] = previous.get(site_id, {})
            errors[site_id] = err or "unknown error"
            stale.append(site_id)

    updated_at = datetime.datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")
    payload = {
        "updated_at": updated_at,
        "sites": {sid: {"name": cfg["name"], "url": cfg["url"]} for sid, cfg in SITES.items()},
        "data": data,
        "errors": errors,
        "stale_sites": stale,
    }
    (OUT_DIR / "prices.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total = sum(len(v) for v in data.values())
    print(f"[{updated_at}] Wrote {total} price points across {len(data)} sites.")
    for site_id, err in errors.items():
        print(f"  ! {site_id}: FAILED this run ({err}) - kept previous data")


if __name__ == "__main__":
    main()
