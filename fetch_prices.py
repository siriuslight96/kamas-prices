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
    # Both sites currently expose their live seller table in the HTML returned
    # to a normal HTTP client, so they can be scraped without a browser.
    "ventekamas": {"name": "VenteKamas", "url": "https://ventekamas.com/eng/vendre-des-kamas/"},
    "tryandjudge": {"name": "TryAndJudge", "url": "https://vente.tryandjudge.com/index.php"},
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


# Each scrapable site formats its price differently: period vs comma
# decimals, and a different currency suffix right after the number.
PRICE_PATTERNS = {
    "ibendouma": r"([0-9]+(?:[.,][0-9]+)?)\s*Dhs?/M",
    "leskamas": r"([0-9]+(?:[.,][0-9]+)?)\s*Dhs?/M",
    # VenteKamas lists several payment currencies in each row. We deliberately
    # target the Morocco bank-transfer column, which is the same MAD/DH unit
    # used by the other sites in this app.
    "ventekamas": r"([0-9]+(?:[.,][0-9]+)?)\s*(?:DHS?|MAD)/M",
    # The live seller page lists each server as: server ... PRICE MAD / M STATUS.
    "tryandjudge": r"([0-9]+(?:[.,][0-9]+)?)\s*MAD\s*/\s*M",
}

# status word -> True (still buying / open) or False (full / closed),
# per site. Order matters: more specific phrases first.
STATUS_WORDS = {
    "ibendouma": [("Stock complet", False), ("Ouvert", True)],
    "leskamas": [("Sourcing", True), ("Full", False)],
    "ventekamas": [("Stock complet", False), ("Incomplet", True)],
    "tryandjudge": [("Stock complet", False), ("Fermé", False), ("Ferme", False), ("Complet", False), ("Ouvert", True)],
}


def parse_site(site_id, text):
    results = {}
    price_pattern = PRICE_PATTERNS[site_id]
    status_alt = "|".join(re.escape(word) for word, _ in STATUS_WORDS[site_id])
    status_lookup = dict(STATUS_WORDS[site_id])

    # TryAndJudge's live seller page is the authoritative source for seller
    # availability.  Do not scan the whole page for a status word: that can
    # accidentally pick up unrelated text such as "Support vendeur - Ouvert
    # maintenant".  Instead, bound the match to the current server's row.
    if site_id == "tryandjudge":
        for server in SERVERS:
            for variant in variants_for(server):
                # Stop before the next server card/name.  The live page is
                # rendered as one text stream after scripts are stripped, so
                # using the server name as the anchor is safer than a global
                # price/status search.
                next_server_alt = "|".join(
                    re.escape(v) for s in SERVERS if s != server for v in variants_for(s)
                )
                pattern = re.compile(
                    re.escape(variant)
                    + r".{0,100}?" + price_pattern
                    + r".{0,55}?(" + status_alt + r")",
                    re.IGNORECASE | re.DOTALL,
                )
                match = pattern.search(text)
                if not match:
                    continue
                # Reject a match if another known server appears between the
                # requested server and its price/status. This prevents status
                # leakage from a neighbouring server.
                segment_start = match.start()
                segment_end = match.end()
                between = text[segment_start:segment_end]
                if next_server_alt and re.search(r"(?:" + next_server_alt + r")", between, re.IGNORECASE):
                    continue
                price = float(match.group(1).replace(",", "."))
                status_word = match.group(2)
                open_status = next(
                    (v for k, v in status_lookup.items() if k.lower() == status_word.lower()), None
                )
                results[server] = {"price": price, "open": open_status}
                break
        return results

    for server in SERVERS:
        match = None
        for variant in variants_for(server):
            # Keep the match inside one rendered row. The source pages currently
            # put the server name, its price and its stock label next to each
            # other, so a bounded window avoids borrowing a status from another
            # server. VenteKamas has several payment columns, hence the larger
            # window there.
            max_before_price = 360 if site_id == "ventekamas" else 180
            max_after_price = 90
            pattern = re.compile(
                re.escape(variant)
                + rf".{{0,{max_before_price}}}?"
                + price_pattern
                + rf".{{0,{max_after_price}}}?("
                + status_alt
                + r")",
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

    all_sites = SITES
    updated_at = datetime.datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")
    payload = {
        "updated_at": updated_at,
        "sites": {sid: {"name": cfg["name"], "url": cfg["url"]} for sid, cfg in all_sites.items()},
        "data": data,  # only contains entries for sites in SITES (the scrapable ones)
        "errors": errors,
        "stale_sites": stale,
        "link_only_sites": [],
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
