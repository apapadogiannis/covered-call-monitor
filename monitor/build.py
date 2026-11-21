"""Builds the page and its data file from the stored extracts. Uses no network.

    python3 -I build.py [OUT_DIR]

Everything shown is computed here from data/nport/<quarter>/*.csv and config/funds.toml.
The same numbers are written to OUT_DIR/data.json and embedded in OUT_DIR/index.html.
"""
from __future__ import annotations

import csv
import json
import math
import re
import sys
import tomllib
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "nport"


def rows(q: Path, name: str):
    with (q / name).open(encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def num(x: str):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def month_back(ym: str, k: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    i = y * 12 + (m - 1) - k
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def strike_from_title(title: str):
    """The strike named in a holding's title, or None. Titles look like 'NDX US 08/21/26 C28550'."""
    t = title.replace(",", "")
    for pat in (r"\b[CP]\s?(\d+(?:\.\d+)?)\s*(?:SHORT|LONG)?\s*$", r"(?i)\b(?:call|put)\s+option\s+(\d+(?:\.\d+)?)\b",
                r"(?i)strike\s*(?:price)?\s*:?\s*\$?(\d+(?:\.\d+)?)", r"(?i)\b(?:call|put)\s*@\s*\$?(\d+(?:\.\d+)?)"):
        m = re.search(pat, t)
        if m:
            return float(m.group(1))
    return None


def load(cfg: dict) -> dict:
    """All stored reports, one per fund and report date, the latest filing winning."""
    reports: dict[tuple, dict] = {}
    for q in sorted(p for p in STORE.iterdir() if (p / "funds.csv").exists()):
        acc = {}
        for r in rows(q, "funds.csv"):
            key = r["role"] if r["role"].startswith("benchmark:") else (r["series_id"] or r["series_name"])
            rep = {"key": key, "name": r["series_name"], "role": r["role"], "series_id": r["series_id"],
                   "report_date": r["report_date"], "filing_date": r["filing_date"], "quarter": q.name,
                   "net_assets": num(r["net_assets"]),
                   "flows": [[num(r[f"{k}_m{m}"]) for k in ("sales", "reinvested", "redeemed")] for m in (1, 2, 3)],
                   "returns": {}, "composition": [], "options": [], "notes": []}
            acc[r["accession"]] = rep
        for r in rows(q, "returns.csv"):
            if r["accession"] in acc:
                acc[r["accession"]]["returns"][r["class_id"]] = [num(r[f"return_m{m}"]) for m in (1, 2, 3)]
        for r in rows(q, "composition.csv"):
            if r["accession"] in acc:
                acc[r["accession"]]["composition"].append(
                    (r["asset_cat"], r["derivative_cat"], int(r["holdings"]), num(r["pct_net_assets"])))
        for r in rows(q, "options.csv"):
            if r["accession"] in acc:
                acc[r["accession"]]["options"].append(r)
        for r in rows(q, "notes.csv"):
            if r["accession"] in acc:
                acc[r["accession"]]["notes"].append(r)
        for rep in acc.values():
            k = (rep["key"], rep["report_date"])
            if k not in reports or rep["filing_date"] >= reports[k]["filing_date"]:
                reports[k] = rep
    by_fund: dict[str, list[dict]] = defaultdict(list)
    for (_, _), rep in sorted(reports.items(), key=lambda kv: kv[0][1]):
        by_fund[rep["key"]].append(rep)
    return by_fund


def triple(rep: dict):
    """The three monthly returns of a report as filed, for its first share class in sort order."""
    return rep["returns"][min(rep["returns"])] if rep["returns"] else None


def filed_newest_first(reps: list[dict], bench: dict[str, float]) -> dict:
    """Whether a fund files its three monthly returns newest first instead of oldest first.

    The form asks for the three months in order of time. Some fund families file them the other
    way round. The two readings are told apart by which one tracks the fund's index fund more
    closely, month by month, over all of the fund's reports: the sum of squared differences is
    computed both ways, and the fund is read newest-first when that reading at least halves it.
    """
    fwd = rev = 0.0
    n = 0
    for r in reps:
        v = triple(r)
        end = r["report_date"][:7]
        ms = [month_back(end, 2), month_back(end, 1), end]
        if not v or None in v or any(m not in bench for m in ms):
            continue
        b = [bench[m] for m in ms]
        fwd += sum((x - y) ** 2 for x, y in zip(v, b))
        rev += sum((x - y) ** 2 for x, y in zip(v[::-1], b))
        n += 1
    return {"newest_first": bool(n) and rev < 0.5 * fwd, "reports_compared": n,
            "misfit_as_filed": round(fwd, 1), "misfit_reversed": round(rev, 1)}


def month_order(reps: list[dict], benches: dict[str, dict[str, float]]) -> dict:
    """How a fund orders its three monthly returns: "as filed", "reversed" or "not determined".

    The fund is compared with each benchmark in turn (see filed_newest_first) and the benchmark it
    tracks most closely decides. One reading must at least halve the misfit of the other over four
    or more reports; otherwise the order is not determined and the months are left as filed.
    """
    best = None
    for ticker, bench in benches.items():
        r = filed_newest_first(reps, bench)
        if r["reports_compared"] >= 4 and (best is None or min(r["misfit_as_filed"], r["misfit_reversed"])
                                           < min(best["misfit_as_filed"], best["misfit_reversed"])):
            best = {**r, "compared_with": ticker}
    if best is None:
        return {"order": "not determined", "compared_with": None, "reports_compared": 0,
                "misfit_as_filed": None, "misfit_reversed": None}
    f, r = best["misfit_as_filed"], best["misfit_reversed"]
    order = "reversed" if r < 0.5 * f else "as filed" if f < 0.5 * r else "not determined"
    return {"order": order, "compared_with": best["compared_with"], "reports_compared": best["reports_compared"],
            "misfit_as_filed": f, "misfit_reversed": r}


def monthly(reps: list[dict], newest_first: bool = False) -> tuple[dict[str, float], dict[str, float | None], list[str]]:
    """Monthly total return (%) and net flow, by month, joined across a fund's reports.

    Each report carries the three months that end at its report date. A later report overrides an
    earlier one for the same month. Where a report lists several share classes, the first class
    identifier in sort order is used; a fund whose identifier changes (as when a trust is
    reorganised) therefore keeps one unbroken series.

    A fund's first report can cover months before it existed, filed as zero, and the month in
    which it started, which is not a full month. Those months are dropped.
    """
    ret: dict[str, float] = {}
    flow: dict[str, float | None] = {}
    odd: list[str] = []
    for k, r in enumerate(reps):
        end = r["report_date"][:7]
        vals = triple(r)
        if vals and newest_first:
            vals = vals[::-1]
        start = 0
        if k == 0 and vals:
            while start < 3 and vals[start] in (0, 0.0, None):
                start += 1
            if 0 < start < 3:
                start += 1          # the month the fund started in is a part month
        for i in range(3):
            ym = month_back(end, 2 - i)
            if vals and i >= start and vals[i] is not None:
                ret[ym] = vals[i]
            s, v, d = r["flows"][i]
            if None in (s, v, d):
                continue
            if s < 0 or v < 0 or d < 0:      # a filing oddity: reported, not used
                flow[ym] = None
                odd.append(ym)
            else:
                flow[ym] = s + v - d
    return ret, flow, sorted(set(odd))


def compound(ret: dict[str, float], months: list[str]):
    if not months or any(m not in ret for m in months):
        return None
    g = 1.0
    for m in months:
        g *= 1 + ret[m] / 100
    return (g - 1) * 100


CONTRACT = 100   # shares per listed US option contract, equity and index alike
FACE_LIMIT = 200  # per cent of net assets; above this the face value is not shown
STILL_REPORTING = 6  # months; a fund whose last report is older than this is no longer listed


def overlay(rep: dict) -> dict:
    """The written calls of one report.

    Face value is contracts x 100 x strike. The number of contracts is the holding's balance, which
    every filer reports in contracts; the "shares" field is not used because filers fill it in
    three different ways. A strike is taken from the holding's title only when the filed strike is
    the tail of the titled one (550 for 28550), which is how the data set cuts some strikes short.
    """
    calls = [o for o in rep["options"] if o["put_or_call"] == "Call" and o["written_or_purchased"] == "Written"]
    out, notional, known, repaired = [], 0.0, True, 0
    for o in calls:
        filed, named = num(o["strike_as_filed"]), strike_from_title(o["title"])
        strike, basis = filed, "as filed"
        if (named is not None and filed is not None and named > filed and filed == int(filed)
                and named == int(named) and str(int(named)).endswith(str(int(filed)))):
            strike, basis = named, "from title"
            repaired += 1
        contracts = abs(num(o["balance"]) or 0.0) if o["unit"] == "NC" else None
        if strike is None or not contracts:
            known = False
        else:
            notional += contracts * CONTRACT * strike
        out.append({"title": o["title"], "reference": o["reference"], "strike": strike, "strike_basis": basis,
                    "strike_as_filed": filed, "expiration": o["expiration"], "contracts": contracts,
                    "value_pct": num(o["pct_net_assets"])})
    na = rep["net_assets"]
    exps = sorted({o["expiration"] for o in out if o["expiration"]})
    face = (notional / na * 100) if (out and known and na) else None
    if face is not None and face > FACE_LIMIT:   # options on foreign indices, struck in other currencies
        face = None
    return {"written_calls": len(out), "strikes_repaired": repaired,
            "notional_pct": face,
            "value_pct": sum(o["value_pct"] or 0 for o in out) if out else None,
            "nearest_expiration": exps[0] if exps else None,
            "days_to_nearest": ((date.fromisoformat(exps[0]) - date.fromisoformat(rep["report_date"])).days
                                if exps else None),
            "positions": sorted(out, key=lambda o: -((o["contracts"] or 0) * (o["strike"] or 0)))[:12]}


def notes(rep: dict) -> dict:
    by: dict[str, list] = defaultdict(lambda: [0, 0.0])
    for n in rep["notes"]:
        by[n["issuer"]][0] += 1
        by[n["issuer"]][1] += num(n["pct_net_assets"]) or 0.0
    return {"count": len(rep["notes"]), "pct": sum(v[1] for v in by.values()) if by else None,
            "issuers": [{"issuer": k, "notes": v[0], "pct": v[1]}
                        for k, v in sorted(by.items(), key=lambda kv: -kv[1][1])]}


TYPES = [("Covered call", r"(?i)covered[ -]call"), ("Buy-write", r"(?i)buy-?write"),
         ("Premium income", r"(?i)premium income")]


def type_of(name: str) -> str:
    """Which of the three names a fund carries. The first that matches, in the order above."""
    for label, pat in TYPES:
        if re.search(pat, name):
            return label
    return "Other"


def median(xs: list[float]):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def static_text(data: dict) -> dict[str, str]:
    """The sentences and the summary table written into the page itself, so that a reader without
    JavaScript (a search engine, a program, an AI agent that does not run scripts) still gets them."""
    from html import escape
    m = data["meta"]
    day = lambda d: f"{int(d[8:10])} {MONTHS[int(d[5:7]) - 1]} {d[:4]}"
    mon = lambda d: f"{MONTHS[int(d[5:7]) - 1][:3]} {d[:4]}"
    pct = lambda x: "" if x is None else f"{'+' if x > 0 else '−' if x < 0 else ''}{abs(x):.1f}%"
    bn = f"${m['category_net_assets'] / 1e9:.1f} billion"
    rows = []
    for f in data["detail"]:
        w = f["window"]
        g3 = b3 = None
        if len(f["months"]) >= 36:
            g3 = b3 = 1.0
            for x in f["months"][-36:]:
                g3 *= 1 + x["fund"] / 100
                b3 *= 1 + x["benchmark"] / 100
        rows.append(f"<tr><td>{escape(f['ticker'])}: {escape(f['name'])}</td><td>{escape(f['benchmark'])}</td>"
                    f"<td>{pct(None if g3 is None else (g3 - 1) * 100)}</td><td>{pct(None if b3 is None else (b3 - 1) * 100)}</td>"
                    f"<td>{mon(w['from'])} to {mon(w['to'])}</td><td>{pct(w['fund'])}</td><td>{pct(w['benchmark'])}</td></tr>")
    table = ("<table><thead><tr><th>Fund</th><th>Index fund</th><th>Fund, total return, 3 years</th>"
             "<th>Index fund, total return, 3 years</th><th>Longest period on file</th><th>Fund, total return</th>"
             "<th>Index fund, total return</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
             "<p class=\"note\">Total return with every distribution reinvested. Three years to "
             f"{mon(data['detail'][0]['months'][-1]['month'])}. The longest period on file is each fund's own, "
             "from the first month in the SEC's data sets or the fund's first full month, and the index fund is "
             "measured over the same months.</p>")
    return {
        "<!--LEDE-->": (f"This site measures what covered-call funds earned once their distributions are counted. For "
                        f"each of {m['funds_in_category']} US funds it shows the total return, with every distribution "
                        "reinvested, the options the fund had written on its last report date, and the money moving in "
                        "and out. Where a fund follows a well-known index, its return is set beside an index fund on the "
                        "same market, so the cost of the option strategy can be read off directly."),
        "<!--STAMP-->": f"{m['funds_in_category']} funds · reports to {day(m['reports_to'])} · updated quarterly",
        "<!--LEDECAT-->": (f"Every US-registered fund whose name says covered call, buy-write or premium income: "
                           f"{m['funds_in_category']} funds with {bn} in net assets. Funds built around buffers, "
                           f"barriers or written puts are left out, as are {m['funds_no_longer_reporting']} funds that "
                           "have stopped reporting."),
        "<!--STATIC-->": table,
    }


def build(out: Path) -> dict:
    cfg = tomllib.loads((ROOT / "config" / "funds.toml").read_text(encoding="utf-8"))
    by_fund = load(cfg)
    series = {k: monthly(v) for k, v in by_fund.items()}
    bench = {b["ticker"]: b for b in cfg["benchmark"]}
    benches = {b["ticker"]: series["benchmark:" + b["ticker"]][0] for b in cfg["benchmark"]
               if "benchmark:" + b["ticker"] in series}
    orders = {}
    for k, v in by_fund.items():
        if k.startswith("benchmark:"):
            orders[k] = {"order": "as filed", "compared_with": None, "reports_compared": 0,
                         "misfit_as_filed": None, "misfit_reversed": None}
            continue
        orders[k] = month_order(v, benches)
        if orders[k]["order"] == "reversed":
            series[k] = monthly(v, newest_first=True)
    order = {}
    for d in cfg["detail"]:
        if d["series"] in by_fund:
            order[d["series"]] = filed_newest_first(by_fund[d["series"]],
                                                    series.get("benchmark:" + d["benchmark"], ({},))[0])
            series[d["series"]] = monthly(by_fund[d["series"]], newest_first=order[d["series"]]["newest_first"])
            orders[d["series"]] = {"order": "reversed" if order[d["series"]]["newest_first"] else "as filed",
                                   "compared_with": d["benchmark"],
                                   "reports_compared": order[d["series"]]["reports_compared"],
                                   "misfit_as_filed": order[d["series"]]["misfit_as_filed"],
                                   "misfit_reversed": order[d["series"]]["misfit_reversed"]}

    def record(key: str, ticker, bench_ticker, kind) -> dict:
        """Everything the page shows for one fund, against its index fund where one is assigned.

        A fund whose month order is known is given month by month. One whose order is not determined
        is given in three-month steps ending at its report dates, which do not depend on the order.
        """
        reps = by_fund[key]
        last = reps[-1]
        ret, flow, odd = series[key]
        bret = series.get("benchmark:" + bench_ticker, ({}, {}, []))[0] if bench_ticker else None
        step = 1 if orders[key]["order"] in ("as filed", "reversed") else 3
        if step == 1:
            ends = sorted(ret)
        else:
            ends = sorted({r["report_date"][:7] for r in reps})
        span_of = lambda e: [month_back(e, k) for k in range(step - 1, -1, -1)]
        usable = [e for e in ends if all(m in ret for m in span_of(e))
                  and (bret is None or all(m in bret for m in span_of(e)))]
        run = []                                   # the longest unbroken run that ends at the latest period
        for e in reversed(usable):
            if run and month_back(run[0], step) != e:
                break
            run.insert(0, e)
        gf = gb = 1.0
        path = []
        for e in run:
            rf = compound(ret, span_of(e))
            rb = compound(bret, span_of(e)) if bret is not None else None
            gf *= 1 + rf / 100
            if rb is not None:
                gb *= 1 + rb / 100
            path.append({"month": e, "fund": rf, "benchmark": rb, "fund_cum": (gf - 1) * 100,
                         "benchmark_cum": (gb - 1) * 100 if rb is not None else None})
        ov, nt = overlay(last), notes(last)
        if not kind:
            kind = ("Holds equity-linked or other structured notes" if nt["count"] else
                    "Had written calls on the report date" if ov["written_calls"] else
                    "Had no written call on the report date")
        n = len(run) * step
        last12 = run[-(12 // step):] if n >= 12 else None
        return {
            "id": last["series_id"] or key, "ticker": ticker, "name": last["name"], "type": type_of(last["name"]),
            "overlay_kind": kind, "benchmark": bench_ticker,
            "benchmark_index": bench[bench_ticker]["index"] if bench_ticker else None,
            "report_date": last["report_date"], "filing_date": last["filing_date"],
            "net_assets": last["net_assets"], "step": step, "months": path,
            "window": {"from": month_back(run[0], step - 1), "to": run[-1], "months": n,
                       "fund": (gf - 1) * 100, "benchmark": (gb - 1) * 100 if bret is not None else None,
                       "gap": (gf - gb) * 100 if bret is not None else None} if run else None,
            "last12": {"fund": compound(ret, [m for e in last12 for m in span_of(e)]),
                       "benchmark": compound(bret, [m for e in last12 for m in span_of(e)]) if bret is not None else None}
            if last12 else None,
            "month_order": orders[key]["order"],
            "returns_order": order.get(key),
            "flows": [{"month": m, "net": flow[m]} for m in sorted(flow)],
            "flow_months_not_used": odd, "overlay": ov, "notes": nt}

    detail = [record(d["series"], d["ticker"], d["benchmark"], d["overlay"])
              for d in cfg["detail"] if d["series"] in by_fund]
    featured = {d["series"]: d for d in cfg["detail"]}

    def benchmark_for(name: str):
        """The index fund a fund is set beside, from its name. None when the name names no such index."""
        for b in cfg["benchmark"]:
            if b.get("funds") and re.search(b["funds"], name):
                return b["ticker"]
        return None

    latest = max(r["report_date"] for v in by_fund.values() for r in v)
    cutoff = month_back(latest[:7], STILL_REPORTING)
    category, gone = [], 0
    for key, reps in by_fund.items():
        last = reps[-1]
        if last["role"] != "category":
            continue
        if last["report_date"][:7] < cutoff:      # closed, merged or renamed out of the category
            gone += 1
            continue
        ret, flow, odd = series[key]
        end = last["report_date"][:7]
        m3 = [month_back(end, 2), month_back(end, 1), end]
        m12 = [month_back(end, k) for k in range(11, -1, -1)]
        f3 = [flow.get(m) for m in m3]
        ov, nt = overlay(last), notes(last)
        category.append({
            "name": last["name"], "type": type_of(last["name"]), "series_id": last["series_id"],
            "report_date": last["report_date"],
            "net_assets": last["net_assets"], "return_3m": compound(ret, m3), "return_12m": compound(ret, m12),
            "net_flow_3m": sum(f3) if all(f is not None for f in f3) else None,
            "written_calls": ov["written_calls"], "notional_pct": ov["notional_pct"],
            "strikes_repaired": ov["strikes_repaired"], "notes_pct": nt["pct"], "notes_count": nt["count"]})
    category.sort(key=lambda r: -(r["net_assets"] or 0))

    funds = []
    for key, reps in by_fund.items():
        last = reps[-1]
        if last["role"] != "category" or last["report_date"][:7] < cutoff:
            continue
        if key in featured:
            funds.append(next(d for d in detail if d["id"] == (last["series_id"] or key)))
        else:
            funds.append(record(key, None, benchmark_for(last["name"]), None))
    funds = [f for f in funds if f["months"]]
    funds.sort(key=lambda f: -(f["net_assets"] or 0))

    types = []
    for label, _ in TYPES:
        rs = [r for r in category if r["type"] == label]
        types.append({"type": label, "funds": len(rs), "net_assets": sum(r["net_assets"] or 0 for r in rs),
                      "with_written_calls": sum(1 for r in rs if r["written_calls"]),
                      "with_notes": sum(1 for r in rs if r["notes_count"]),
                      "median_calls_written": median([r["notional_pct"] for r in rs if r["notional_pct"] is not None]),
                      "median_return_12m": median([r["return_12m"] for r in rs if r["return_12m"] is not None])})

    quarters = sorted(p.name for p in STORE.iterdir() if (p / "funds.csv").exists())
    dates = [r["report_date"] for v in by_fund.values() for r in v]
    first_month = min((m for d in detail for m in (d["months"][:1])), key=lambda m: m["month"])["month"]
    data = {"meta": {"quarters": quarters, "reports_from": min(dates), "reports_to": max(dates),
                     "first_month": first_month,
                     "funds_in_category": len(category), "funds_no_longer_reporting": gone,
                     "funds_with_index_fund": sum(1 for f in funds if f["benchmark"]),
                     "funds_in_three_month_steps": sum(1 for f in funds if f["step"] == 3),
                     "category_net_assets": sum(r["net_assets"] or 0 for r in category),
                     "source": cfg["source"]["page"]},
            "detail": detail, "funds": funds, "types": types, "category": category}

    out.mkdir(parents=True, exist_ok=True)
    from monitor.publish import publish          # the files written for programs and AI agents
    data["meta"]["files"] = publish(cfg, by_fund, series, orders, data, cutoff, [ROOT / "api", out])
    (out / "data.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    template = (ROOT / "site" / "template.html").read_text(encoding="utf-8")
    ld = {"@context": "https://schema.org", "@type": "Dataset", "name": "Covered-Call Monitor",
          "description": "Total returns, written call positions, structured notes and net flows of US-registered "
                         "covered-call, buy-write and premium-income funds, computed and corrected from SEC Form "
                         "N-PORT filings.",
          "creator": {"@type": "Person", "name": "Agisilaos Papadogiannis", "url": "https://github.com/apapadogiannis",
                      "identifier": "https://orcid.org/0009-0002-7753-7052"},
          "license": "https://creativecommons.org/licenses/by/4.0/", "isAccessibleForFree": True,
          "identifier": "https://doi.org/10.5281/zenodo.24418592",
          "url": "https://apapadogiannis.github.io/covered-call-monitor/",
          "temporalCoverage": f"{data['meta']['first_month']}/{data['meta']['reports_to']}",
          "dateModified": data["meta"]["reports_to"], "isBasedOn": cfg["source"]["page"],
          "distribution": [{"@type": "DataDownload", "encodingFormat": f["format"], "contentUrl": f["file"],
                            "description": f["what"]} for f in data["meta"]["files"]]}
    html = (template.replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
            .replace("/*LD*/", json.dumps(ld, separators=(",", ":"))))
    for mark, text in static_text(data).items():        # readable without JavaScript
        html = html.replace(mark, text)
    (out / "index.html").write_text(html, encoding="utf-8")
    return data


if __name__ == "__main__":
    d = build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_site")
    print(f"{d['meta']['funds_in_category']} funds, reports {d['meta']['reports_from']} to {d['meta']['reports_to']}")
