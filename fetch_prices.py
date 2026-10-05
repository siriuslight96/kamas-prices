#!/usr/bin/env python3
"""
Fetches kamas sell prices (DH/M) and stock status from iBendouma, LesKamas
and VenteKamas, and writes prices.json. Run by the GitHub Actions workflow
in .github/workflows/update-prices.yml on a schedule — this is what keeps
the published site current without any server of your own.
"""

import json
import re
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
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
}


def fetch_flat_text(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n")


def status_from_window(site_id, window):
    if site_id == "ibendouma":
        if "Stock complet" in window:
            return False
        if "Ouvert" in window:
            return True
    elif site_id == "leskamas":
        if "Sourcing" in window:
            return True
        if "Full" in window:
            return False
    elif site_id == "ventekamas":
        if "Incomplet" in window:
            return True
        if "Stock complet" in window:
            return False
    elif site_id == "tryandjudge":
        if "Stock complet" in window or "Ferm" in window:
            return False
        if "Ouvert" in window:
            return True
    return None


# Each site formats its price differently: period vs comma decimals, and a
# different currency suffix right after the number.
PRICE_PATTERNS = {
    "ibendouma": r"([0-9]+\.[0-9]+)\s*Dhs?/M",
    "leskamas": r"([0-9]+\.[0-9]+)\s*Dhs?/M",
    "ventekamas": r"([0-9]+\.[0-9]+)\s*Dhs?/M",
    "tryandjudge": r"([0-9]+,[0-9]+)\s*\*?MAD",
}


def parse_site(site_id, text):
    results = {}
    price_pattern = PRICE_PATTERNS[site_id]
    for server in SERVERS:
        match = None
        for variant in variants_for(server):
            pattern = re.compile(
                re.escape(variant) + r".{0,400}?" + price_pattern,
                re.IGNORECASE | re.DOTALL,
            )
            match = pattern.search(text)
            if match:
                break
        if not match:
            continue
        price = float(match.group(1).replace(",", "."))
        window = text[match.start():match.start() + 600]
        results[server] = {"price": price, "open": status_from_window(site_id, window)}
    return results


def main():
    data = {}
    errors = {}
    for site_id, cfg in SITES.items():
        try:
            text = fetch_flat_text(cfg["url"])
            data[site_id] = parse_site(site_id, text)
        except Exception as exc:  # noqa: BLE001
            data[site_id] = {}
            errors[site_id] = str(exc)

    updated_at = datetime.datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")
    payload = {
        "updated_at": updated_at,
        "sites": {sid: {"name": cfg["name"], "url": cfg["url"]} for sid, cfg in SITES.items()},
        "data": data,
        "errors": errors,
    }
    (OUT_DIR / "prices.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total = sum(len(v) for v in data.values())
    print(f"[{updated_at}] Wrote {total} price points across {len(data)} sites.")
    for site_id, err in errors.items():
        print(f"  ! {site_id}: {err}")


if __name__ == "__main__":
    main()
