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

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

OUT_DIR = Path(__file__).parent

SITES = {
    "ibendouma": {"name": "iBendouma", "url": "https://www.ibendouma.com/vendre"},
    "leskamas": {"name": "LesKamas", "url": "https://www.leskamas.com/en-gb/sell-kamas.html"},
    # VenteKamas is rendered/updated in the browser, so use Playwright and
    # read the exact Virement Maroc (DHS/M) table column.
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


def fetch_html(url):
    """Return browser-rendered HTML for sites whose live tables are dynamic."""
    if sync_playwright is None:
        raise RuntimeError("Playwright is required for TryAndJudge rendering")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=HEADERS["User-Agent"],
            locale="fr-FR",
        )
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Both dynamic seller tables are rendered/updated in the browser.
            # Wait for a real table (VenteKamas) or market row (TryAndJudge).
            selector = "button.market-row" if "tryandjudge" in url.lower() else "table tr"
            page.wait_for_selector(selector, timeout=20000)
            # Allow the page's own JS/API calls to finish updating the prices.
            page.wait_for_timeout(2500)
            return page.content()
        finally:
            browser.close()


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

    if site_id == "ventekamas":
        # VenteKamas has several prices in every row (EUR, USDT, and Morocco
        # bank transfer). Never regex the whole row for a DHS price: that can
        # accidentally select stale/hidden markup. Instead, locate the exact
        # table column from the header, then read that same cell for each row.
        soup = BeautifulSoup(text, "html.parser")
        results = {}

        def norm_name(value):
            value = re.sub(r"\s+", " ", value or "").strip().lower()
            value = value.replace("-", " ")
            return re.sub(r"\s+", " ", value).strip()

        wanted = {}
        for server in SERVERS:
            for variant in variants_for(server):
                wanted[norm_name(variant)] = server

        for table in soup.select("table"):
            header_rows = table.select("thead tr") or table.select("tr")[:1]
            if not header_rows:
                continue

            header_cells = header_rows[0].find_all(["th", "td"])
            headers = [norm_name(c.get_text(" ", strip=True)) for c in header_cells]

            # Current VenteKamas header is: Serveur, PayPal, Skrill, Bitcoin,
            # USDT / USDC, Virement Maroc, Stock. We find the column by name so
            # a future insertion/removal of another payment column won't break it.
            price_col = next(
                (i for i, h in enumerate(headers) if "virement maroc" in h or "maroc" in h and "dhs" in h),
                None,
            )
            stock_col = next(
                (i for i, h in enumerate(headers) if h == "stock" or "stock" in h),
                None,
            )
            if price_col is None:
                # Fallback for markup where the header text is split but the
                # column is still identifiable as a DHS/M column.
                price_col = next((
                    i for i, h in enumerate(headers)
                    if "dhs" in h or "mad" in h
                ), None)
            if price_col is None:
                continue

            rows = table.select("tbody tr") or table.select("tr")[1:]
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) <= price_col:
                    continue

                cell_texts = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip() for c in cells]
                canonical = wanted.get(norm_name(cell_texts[0]))
                if not canonical:
                    continue

                # The screenshot/DOM shows the authoritative value as a span
                # inside this exact cell, e.g. 6.654 + DHS/M.
                price_text = cell_texts[price_col]
                pm = re.search(r"([0-9]+(?:[.,][0-9]+)?)\s*(?:DHS?|MAD)\s*/\s*M", price_text, re.IGNORECASE)
                if not pm:
                    continue
                price = float(pm.group(1).replace(",", "."))

                status_text = ""
                if stock_col is not None and len(cells) > stock_col:
                    status_text = norm_name(cell_texts[stock_col])
                else:
                    status_text = norm_name(cell_texts[-1])

                if "stock complet" in status_text or status_text == "complet":
                    open_status = False
                elif "incomplet" in status_text or "ouvert" in status_text:
                    open_status = True
                else:
                    open_status = None

                results[canonical] = {"price": price, "open": open_status}

            if results:
                return results

        return results

    if site_id == "tryandjudge":
        # TryAndJudge exposes the authoritative status in each individual
        # .market-row. Only read the price/status from the same row as the
        # selected server.
        soup = BeautifulSoup(text, "html.parser")
        results = {}

        def norm_name(value):
            value = re.sub(r"\s+", " ", value or "").strip().lower()
            value = value.replace("(shadow)", "").replace("-", " ")
            return re.sub(r"\s+", " ", value).strip()

        wanted = {}
        for server in SERVERS:
            for variant in variants_for(server):
                wanted[norm_name(variant)] = server

        rows = soup.select("button.market-row")
        for row in rows:
            name_el = row.select_one(".market-name")
            price_el = row.select_one(".market-price")
            status_el = row.select_one(".market-status")
            if not name_el or not price_el or not status_el:
                continue

            canonical = wanted.get(norm_name(name_el.get_text(" ", strip=True)))
            if not canonical:
                continue

            pm = re.search(r"([0-9]+(?:[.,][0-9]+)?)", price_el.get_text(" ", strip=True))
            if not pm:
                continue
            price = float(pm.group(1).replace(",", "."))

            status_text = re.sub(r"\s+", " ", status_el.get_text(" ", strip=True)).strip().lower()
            status_classes = {c.lower() for c in status_el.get("class", [])}
            if "full" in status_classes or "complet" in status_text or "stock complet" in status_text:
                open_status = False
            elif "open" in status_classes or "ouvert" in status_text:
                open_status = True
            elif "closed" in status_classes or "fermé" in status_text or "ferme" in status_text:
                open_status = False
            else:
                open_status = None

            results[canonical] = {"price": price, "open": open_status}

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
            text = fetch_html(cfg["url"]) if site_id in {"tryandjudge", "ventekamas"} else fetch_text(cfg["url"])
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
