"""Recomputes published fund returns from the stored SEC filings. Run: python3 -I tests/test_published.py

For each row of reference/published_returns.csv the same return is compounded from the monthly
figures the monitor derives from the filings, and compared with the published one.
"""
import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from monitor.build import build, month_back  # noqa: E402

TOLERANCE = 0.06   # percentage points: published figures are rounded to one decimal

with tempfile.TemporaryDirectory() as tmp:
    build(Path(tmp))
    monthly = {}
    for r in csv.DictReader((Path(tmp) / "monthly.csv").open(encoding="utf-8")):
        if r["ticker"] and r["total_return_pct"]:
            monthly.setdefault(r["ticker"], {})[r["month"]] = float(r["total_return_pct"])

worst, n = 0.0, 0
for ref in csv.DictReader((ROOT / "reference" / "published_returns.csv").open(encoding="utf-8")):
    series, end = monthly[ref["ticker"]], ref["as_of"][:7]
    months = {"1 month": 1, "3 months": 3, "year to date": int(end[5:7]), "1 year": 12,
              "3 years a year": 36, "5 years a year": 60}[ref["period"]]
    growth = 1.0
    for k in range(months):
        growth *= 1 + series[month_back(end, k)] / 100
    value = ((growth ** (12 / months) - 1) if "a year" in ref["period"] else growth - 1) * 100
    diff = abs(value - float(ref["published_pct"]))
    worst, n = max(worst, diff), n + 1
    print(f"{ref['ticker']:5} {ref['period']:15} published {float(ref['published_pct']):6.1f}   from filings {value:7.2f}")
    assert diff <= TOLERANCE, f"{ref['ticker']} {ref['period']}: {value:.2f} against published {ref['published_pct']}"
print(f"{n} published returns reproduced; largest difference {worst:.3f} percentage points")
