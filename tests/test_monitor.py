"""Checks of the rules the page depends on. Run: python3 -I tests/test_monitor.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT_API = Path(__file__).resolve().parent.parent / "api"
from monitor.build import build, compound, distributions, filed_newest_first, month_back, monthly, overlay, risk, strike_from_title  # noqa: E402
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
# Redemptions filed as a negative number are an outflow of that size: the month is used.
_, flow, odd = monthly([report("2026-03-31", (1, 2, 3), flows=((5.0, 1.0, -2.0), (5.0, 1.0, 2.0), (2.0, 0.0, 1.0)))])
assert odd == [] and flow["2026-01"] == flow["2026-02"] == 4.0


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
# A fund that started in the first month of its first report files no zero before it. When the fund
# enters the data after the form's first year, that first month is its part month and is dropped.
new = [report("2026-03-31", (0.4, 2.0, 1.0)), report("2026-06-30", (3.0, 1.0, 1.0))]
assert sorted(monthly(new, entered_late=True)[0]) == ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
assert sorted(monthly(new)[0])[0] == "2026-01"                       # a fund on file from the start keeps it
assert sorted(monthly([report("2026-03-31", (1.0, 2.0, 0.4))], newest_first=True, entered_late=True)[0]) == ["2026-02", "2026-03"]

# What a fund paid out is implied by its filings. A fund that starts a quarter with 100, earns 1% a month
# with distributions counted as reinvested, takes in nothing and ends with 100 has paid out its return.
two = [dict(report("2026-03-31", (1, 1, 1), flows=((0.0, 0.0, 0.0),) * 3), net_assets=100.0),
       dict(report("2026-06-30", (1, 1, 1), flows=((0.0, 0.0, 0.0),) * 3), net_assets=100.0)]
ret2, flow2, _ = monthly(two)
d = distributions(two, ret2, flow2)
assert len(d["quarters"]) == 1 and abs(d["quarters"][0]["rate"] - (1.01 ** 3 - 1) * 100) < 1e-9 and d["last_12_months"] is None
two[1]["net_assets"] = 100.0 * 1.01 ** 3                 # it kept everything: it paid out nothing
assert abs(distributions(two, ret2, flow2)["quarters"][0]["rate"]) < 1e-9
two[1]["net_assets"] = 30.0                              # more than 40% gone in a quarter is not a distribution
assert distributions(two, ret2, flow2)["quarters"] == []

# Market risk beside the index fund. A fund that is exactly half index fund and half Treasury bills has
# a beta of one half, half the volatility, and no gap to the mix with the same market risk.
idx = [4.0, -6.0, 3.0, 1.5, -2.5, 5.0, 0.5, -1.0] * 3
half = [{"fund": 0.3 + 0.5 * (b - 0.3), "benchmark": b, "cash": 0.3} for b in idx]
k = risk(half, 1)
assert abs(k["beta"] - 0.5) < 1e-12 and abs(k["gap_to_matched_mix"]) < 1e-9 and abs(k["correlation"] - 1) < 1e-12
assert abs(k["volatility_fund"] / k["volatility_benchmark"] - 0.5) < 1e-12 and k["gap_a_year"] < 0
assert k["largest_fall_benchmark"] < k["largest_fall_fund"] < 0 and k["periods"] == 24
assert risk(half[:23], 1) is None and risk(half[:12], 3) is not None and risk(half[:11], 3) is None
assert risk([{**half[0], "cash": None}] + half[1:], 1) is None        # no bill rate, no mix


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
    page = (Path(tmp) / "index.html").read_text(encoding="utf-8")
    assert json.dumps(d, separators=(",", ":")) in page
    # The page says what it is, and gives a summary, without JavaScript; no placeholder is left behind.
    assert "<!--" not in page.split("<script>")[0].replace("<!-- =", "") and "/*LD*/" not in page
    assert f"each of {d['meta']['funds_in_category']} US funds" in page and "<noscript>" in page
    assert all(f["ticker"] + ": " in page for f in d["detail"])
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
    # Every fund still reporting can be opened on the page, in steps that match what is known of its months.
    # A fund with no full period on file yet (one report, started inside it) is in the category table only.
    shown = {f["id"] for f in d["funds"]}
    absent = [c for c in d["category"] if (c["series_id"] or c["name"]) not in shown]
    assert len(d["funds"]) + len(absent) == d["meta"]["funds_in_category"] and all(f["months"] for f in d["funds"])
    assert len(absent) <= 3 and all(c["return_3m"] is None for c in absent), absent
    assert all(f["step"] == (1 if f["month_order"] in ("as filed", "reversed") else 3) for f in d["funds"])
    assert all((f["benchmark"] is None) == (f["months"][0]["benchmark"] is None) for f in d["funds"])
    assert "10.3905/jbis.2026.001" in doc["related_article"]["doi"]
    # No skill of its own: the guide and the page point to the one skill of the whole account.
    assert not (Path(tmp) / "SKILL.md").exists() and "apapadogiannis/main/skill/SKILL.md" in (Path(tmp) / "llms.txt").read_text(encoding="utf-8")
    # What each fund paid out is implied from net assets, returns and flows. The index funds are the control:
    # their dividend yields are known and small. A covered-call fund pays out far more.
    paid = {f["ticker"]: f["distributions"]["last_12_months"]["pct_net_assets"] for f in funds if f["ticker"] and f["distributions"]["last_12_months"]}
    assert -1 < paid["QQQ"] < 2 and 0 < paid["IVV"] < 2.5 and 0 < paid["IWM"] < 3, paid
    assert 8 < paid["QYLD"] < 16 and 5 < paid["JEPI"] < 12 and 7 < paid["JEPQ"] < 14, paid
    for f in funds:
        qs = f["distributions"]["quarters"]
        assert all(-1 <= q["pct_net_assets"] <= 40 for q in qs) and [q["to"] for q in qs] == sorted(q["to"] for q in qs)
    # Each fund beside its index fund carries its market risk, and the equal-risk mix lies between bills and the index fund.
    by_ticker = {f["ticker"]: f for f in funds if f["ticker"]}
    for t in ("QYLD", "XYLD", "RYLD", "JEPI", "JEPQ"):
        a = by_ticker[t]["against_benchmark"]
        k, w = a["risk"], a["longest_common_period"]
        assert 0.3 < k["beta"] < 0.9 and k["volatility_fund"] < k["volatility_benchmark"], (t, k)
        assert 0 < k["matched_mix"] < w["benchmark"] and abs(k["gap_to_matched_mix"] - (w["fund"] - k["matched_mix"])) < 1e-3
        assert abs(k["gap_a_year"] - w["gap_a_year"]) < 1e-3 and k["periods"] == w["months"]
    # Funds that stopped reporting keep their comparison, so the files have no survivorship gap.
    gone = [f for f in funds if f["role"] == "fund" and not f["still_reporting"]]
    assert any(f["against_benchmark"] for f in gone) and all((f["benchmark"] is None) == (f["against_benchmark"] is None) for f in gone)
    # Negative redemptions are used; only negative sales or reinvestments leave a month out.
    assert sum(len(f["flow_months_not_used"]) for f in funds) < 40
    # Every fund has its own small file, listed in a short index, and it says what funds.json says.
    index = json.loads((Path(tmp) / "index.json").read_text(encoding="utf-8"))
    assert len(index["funds"]) == len(funds) == len({f["file"] for f in funds})
    assert (Path(tmp) / "index.json").stat().st_size < 40_000
    for f in funds:
        one = json.loads((Path(tmp) / f["file"]).read_text(encoding="utf-8"))
        assert one["fund"] == f and len(one["reports"]) == f["reports"] and one["cite_as"] == doc["cite_as"]
        assert sum(1 for m in one["monthly"] if m["total_return_pct"] is not None) == f["months"]
    assert {p.name for p in (ROOT_API / "funds").glob("*.json")} == {f["file"].split("/")[1] for f in funds}, "a stale file in api/funds"
    for name in ("llms.txt", "reports.csv"):
        assert (Path(tmp) / name).stat().st_size > 1000, name
print("all checks pass")
