"""Checks of the rules the page depends on. Run: python3 -I tests/test_monitor.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from monitor.build import build, compound, filed_newest_first, month_back, monthly, overlay, strike_from_title  # noqa: E402
from monitor.update import quarters_since  # noqa: E402
from datetime import date  # noqa: E402

assert month_back("2026-01", 2) == "2025-11" and month_back("2026-07", 0) == "2026-07"
assert quarters_since("2026q1", date(2026, 11, 21)) == ["2026q1", "2026q2", "2026q3"]
assert quarters_since("2025q3", date(2026, 1, 5)) == ["2025q3", "2025q4"]

# Titles as the funds write them.
assert strike_from_title("NDX US 08/21/26 C28550 SHORT") == 28550
assert strike_from_title("NVDA US 07/02/26 C182.5") == 182.5
assert strike_from_title("SPX 03/19/2027 678.8 C") is None


def report(end, vals, flows=((1.0, 0.0, 0.0),) * 3, cls="C1", options=()):
    return {"report_date": end, "returns": {cls: list(vals)}, "flows": [list(f) for f in flows],
            "options": list(options), "net_assets": 10_000_000.0}


# Two reports join into six months; a later report wins; a changed class identifier does not break the series.
ret, flow, odd = monthly([report("2026-03-31", (1, 2, 3)), report("2026-06-30", (4, 5, 6), cls="C9")])
assert sorted(ret) == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"] and ret["2026-04"] == 4
assert abs(compound(ret, ["2026-01", "2026-02"]) - 3.02) < 1e-9 and compound(ret, ["2025-12", "2026-01"]) is None
# A negative sales figure is a filing oddity: the month is reported as not used.
_, flow, odd = monthly([report("2026-03-31", (1, 2, 3), flows=((-5.0, 0.0, 1.0), (2.0, 0.0, 1.0), (2.0, 0.0, 1.0)))])
assert odd == ["2026-01"] and flow["2026-01"] is None and flow["2026-02"] == 1.0


# A fund that files newest first is recognised from its index fund, and read the right way round.
bench = {"2026-01": -5.0, "2026-02": 1.0, "2026-03": 8.0, "2026-04": 2.0, "2026-05": -6.0, "2026-06": 9.0}
flipped = [report("2026-03-31", (3.0, 0.5, -4.0)), report("2026-06-30", (3.5, -5.0, 1.5))]
assert filed_newest_first(flipped, bench)["newest_first"]
assert monthly(flipped, newest_first=True)[0]["2026-01"] == -4.0
straight = [report("2026-03-31", (-4.0, 0.5, 3.0)), report("2026-06-30", (1.5, -5.0, 3.5))]
assert not filed_newest_first(straight, bench)["newest_first"]
# Months before a fund existed (filed as zero) and its first part month are dropped.
ret, _, _ = monthly([report("2026-03-31", (0, 2.0, 1.0)), report("2026-06-30", (0, 1.0, 1.0))])
assert sorted(ret) == ["2026-03", "2026-04", "2026-05", "2026-06"] and ret["2026-04"] == 0


def call(title, balance, strike, unit="NC"):
    return {"put_or_call": "Call", "written_or_purchased": "Written", "title": title, "balance": str(balance),
            "unit": unit, "strike_as_filed": str(strike), "expiration": "2026-08-21", "reference": "",
            "pct_net_assets": "-1.0"}


# A strike cut short is repaired only when the filed number is the tail of the titled one.
o = overlay(report("2026-07-31", (0, 0, 0), options=[call("NDX US 08/21/26 C28550 SHORT", -2, 550)]))
assert o["strikes_repaired"] == 1 and abs(o["notional_pct"] - 2 * 100 * 28550 / 10_000_000 * 100) < 1e-9
o = overlay(report("2026-07-31", (0, 0, 0), options=[call("XYZ US 08/21/26 C700", -10, 650)]))
assert o["strikes_repaired"] == 0 and o["positions"][0]["strike"] == 650

# The stored data builds, and the page carries the same numbers as the data file.
import json, tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    d = build(Path(tmp))
    assert len(d["detail"]) == 5 and d["meta"]["funds_in_category"] > 50
    order = {f["ticker"]: f["returns_order"]["newest_first"] for f in d["detail"]}
    assert order == {"QYLD": True, "XYLD": True, "RYLD": True, "JEPI": False, "JEPQ": False}, order
    for f in d["detail"]:
        assert f["window"]["months"] >= 12, f["ticker"]
        months = [m["month"] for m in f["months"]]
        assert months == sorted(months) and all(month_back(b, 1) == a for a, b in zip(months, months[1:]))
    assert json.dumps(d, separators=(",", ":")) in (Path(tmp) / "index.html").read_text(encoding="utf-8")
    # The files for programs and AI agents are written, agree with the page, and say how months are ordered.
    funds = json.loads((Path(tmp) / "funds.json").read_text(encoding="utf-8"))["funds"]
    assert sum(1 for f in funds if f["role"] == "fund" and f["still_reporting"]) == d["meta"]["funds_in_category"]
    assert {f["month_order"]["order"] for f in funds} <= {"as filed", "reversed", "not determined"}
    reversed_funds = [f["name"] for f in funds if f["month_order"]["order"] == "reversed"]
    assert reversed_funds and all(n.startswith("Global X") for n in reversed_funds), reversed_funds
    import csv  # noqa: E402
    rows = list(csv.DictReader((Path(tmp) / "monthly.csv").open(encoding="utf-8")))
    jepi = {r["month"]: float(r["total_return_pct"]) for r in rows if r["ticker"] == "JEPI" and r["total_return_pct"]}
    page = {m["month"]: m["fund"] for f in d["detail"] if f["ticker"] == "JEPI" for m in f["months"]}
    assert all(abs(jepi[m] - v) < 1e-5 for m, v in page.items())
    # Credit travels with the data: licence and citation are inside the JSON files and the data package.
    doc = json.loads((Path(tmp) / "funds.json").read_text(encoding="utf-8"))
    pkg = json.loads((Path(tmp) / "datapackage.json").read_text(encoding="utf-8"))
    assert doc["licence"]["name"] == "CC-BY-4.0" and "Papadogiannis" in doc["cite_as"] == pkg["citation"]
    assert d["meta"]["credit"]["cite_as"] == doc["cite_as"] and doc["cite_as"] in (Path(tmp) / "llms.txt").read_text(encoding="utf-8")
    header = (Path(tmp) / "monthly.csv").open(encoding="utf-8").readline().strip().split(",")
    assert header == [f["name"] for f in pkg["resources"][0]["schema"]["fields"]]
    header = (Path(tmp) / "reports.csv").open(encoding="utf-8").readline().strip().split(",")
    assert header == [f["name"] for f in pkg["resources"][1]["schema"]["fields"]]
    for name in ("llms.txt", "reports.csv"):
        assert (Path(tmp) / name).stat().st_size > 1000, name
print("all checks pass")
