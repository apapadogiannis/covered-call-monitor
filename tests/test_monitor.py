"""Checks of the rules the page depends on. Run: python3 -I tests/test_monitor.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from monitor.build import build, compound, month_back, monthly, overlay, strike_from_title  # noqa: E402
from monitor.update import quarters_before  # noqa: E402
from datetime import date  # noqa: E402

assert month_back("2026-01", 2) == "2025-11" and month_back("2026-07", 0) == "2026-07"
assert quarters_before(date(2026, 11, 21), 3) == ["2026q3", "2026q2", "2026q1"]
assert quarters_before(date(2026, 1, 5), 2) == ["2025q4", "2025q3"]

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
    for f in d["detail"]:
        assert f["window"]["months"] >= 12, f["ticker"]
        months = [m["month"] for m in f["months"]]
        assert months == sorted(months) and all(month_back(b, 1) == a for a, b in zip(months, months[1:]))
    assert json.dumps(d, separators=(",", ":")) in (Path(tmp) / "index.html").read_text(encoding="utf-8")
print("all checks pass")
