"""Downloads the SEC's quarterly Form N-PORT data sets and stores the monitor's extract of each.

    SEC_CONTACT=... python3 update.py

This is the only code that uses the network. For each quarter that the configuration asks for and
that is not yet in data/nport/, it downloads the SEC's zip to a temporary file, cuts it down with
monitor/extract.py, and deletes the zip. A stored quarter is never downloaded or rewritten again.

The SEC asks every automated client to say who it is. The contact is read from the environment
variable SEC_CONTACT (a repository variable on GitHub) and is never written to a file.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

from monitor.extract import extract

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "nport"
SOURCES = ROOT / "data" / "sources.json"
PAUSE = 5          # seconds between requests
ATTEMPTS = 4


def agent() -> str:
    contact = os.environ.get("SEC_CONTACT", "").strip()
    if not contact:
        sys.exit("SEC_CONTACT is not set. The SEC requires a declared contact for automated requests.")
    return f"covered-call-monitor {contact}"


def fetch(url: str, dest: Path | None = None) -> bytes | None:
    """GET with the declared contact, a pause, and patient retries. Streams to dest when given."""
    last = None
    for attempt in range(ATTEMPTS):
        time.sleep(PAUSE * (attempt * 6 + 1))
        req = urllib.request.Request(url, headers={"User-Agent": agent(), "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                if dest is None:
                    return r.read()
                with dest.open("wb") as f:
                    while chunk := r.read(1 << 20):
                        f.write(chunk)
                return None
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                raise
            print(f"  attempt {attempt + 1}: HTTP {e.code} for {url}", flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            print(f"  attempt {attempt + 1}: {e!r}", flush=True)
    raise RuntimeError(f"could not retrieve {url}: {last!r}")


def quarters_since(first: str, today: date) -> list[str]:
    """Every calendar quarter from `first` to the last one that has ended, oldest first, as '2026q3'."""
    y, q = int(first[:4]), int(first[5])
    end = (today.year, (today.month - 1) // 3 + 1)      # the quarter in progress, not included
    out = []
    while (y, q) < end:
        out.append(f"{y}q{q}")
        y, q = (y, q + 1) if q < 4 else (y + 1, 1)
    return out


def published(cfg: dict) -> dict[str, str]:
    """Quarter -> address, read from the SEC's own listing. Empty if the page cannot be read."""
    try:
        html = fetch(cfg["source"]["page"]).decode("utf-8", "replace")
    except Exception as e:  # the listing is a convenience; the address pattern is the fallback
        print(f"  listing not read ({e!r}); using the address pattern", flush=True)
        return {}
    found = {}
    for href in re.findall(r'href="([^"]+?_nport\.zip)"', html):
        q = re.search(r"(\d{4}q[1-4])_nport\.zip$", href)
        if q:
            found[q.group(1)] = href if href.startswith("http") else "https://www.sec.gov" + href
    return found


def main() -> int:
    cfg = tomllib.loads((ROOT / "config" / "funds.toml").read_text(encoding="utf-8"))
    wanted = quarters_since(cfg["source"]["first_quarter"], date.today())
    missing = [q for q in wanted if not (STORE / q / "funds.csv").exists()]
    if not missing:
        print("Nothing to download: every wanted quarter is stored.")
        return 0

    listing = published(cfg)
    sources = json.loads(SOURCES.read_text(encoding="utf-8")) if SOURCES.exists() else {"quarters": {}}
    loaded = 0
    for q in sorted(missing):
        url = listing.get(q, cfg["source"]["file"].format(quarter=q))
        print(f"{q}: {url}", flush=True)
        with tempfile.TemporaryDirectory() as tmp:
            z = Path(tmp) / f"{q}_nport.zip"
            try:
                fetch(url, z)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    print("  not published yet (404); skipped")
                    continue
                raise
            digest = hashlib.sha256()
            with z.open("rb") as f:
                while chunk := f.read(1 << 20):
                    digest.update(chunk)
            counts = extract(z, cfg, STORE / q)
            sources["quarters"][q] = {
                "url": url, "bytes": z.stat().st_size, "sha256": digest.hexdigest(),
                "retrieved": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **counts}
            print(f"  stored {counts}", flush=True)
            loaded += 1
        sources["quarters"] = dict(sorted(sources["quarters"].items()))
        SOURCES.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    print(f"Loaded {loaded} quarter(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
