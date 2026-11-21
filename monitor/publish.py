"""Writes the files meant for programs and AI agents: the full data behind the page, and a guide.

    funds.json    one record per fund: identity, status, latest figures, how its months are ordered
    monthly.csv   every monthly total return and net flow, for every fund and benchmark
    reports.csv   one row per quarterly report: net assets, 3-month return, written calls, notes
    llms.txt      what this is, what it adds over the raw filings, what to use and what to avoid

The same files go to api/ in the repository and to the published site.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from monitor.build import compound, month_back, notes, overlay, type_of

REPO = "https://github.com/apapadogiannis/covered-call-monitor"
LICENCE = {"name": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
           "condition": "Reuse is allowed with credit to the source."}
DESCRIBE_AS = ("Covered-Call Monitor, by Agisilaos Papadogiannis: figures computed and corrected from the "
               "reports US funds file with the SEC (Form N-PORT).")

MONTHLY_FIELDS = [
    ("id", "string", "SEC series identifier of the fund, or benchmark:<ticker> where a benchmark has none"),
    ("ticker", "string", "Ticker symbol; given only for the five funds shown in detail and the benchmarks"),
    ("name", "string", "Fund name as filed in its latest report"),
    ("month", "yearmonth", "Calendar month, YYYY-MM"),
    ("total_return_pct", "number", "Total return for the month in per cent, distributions reinvested; empty if not filed"),
    ("net_flow_usd", "number", "Sales plus reinvestments less redemptions, in US dollars; empty if not filed or not used"),
    ("month_order", "string", "as filed, reversed or not determined: how the fund's three monthly returns per report were read"),
]
REPORT_FIELDS = [
    ("id", "string", "SEC series identifier of the fund"),
    ("ticker", "string", "Ticker symbol, where given"),
    ("name", "string", "Fund name as filed in that report"),
    ("report_date", "date", "Date the report describes"),
    ("filing_date", "date", "Date the report was filed with the SEC"),
    ("net_assets_usd", "number", "Net assets on the report date, in US dollars"),
    ("total_return_3m_pct", "number", "Total return over the three months ending at the report date, in per cent; does not depend on month order"),
    ("net_flow_3m_usd", "number", "Net flow over those three months, in US dollars; empty if a month was not used"),
    ("written_calls", "integer", "Number of written call positions on the report date"),
    ("calls_face_value_pct_net_assets", "number", "Contracts x 100 x strike of the written calls, as per cent of net assets; empty if not computable"),
    ("notes", "integer", "Number of structured notes held"),
    ("notes_pct_net_assets", "number", "Structured notes as per cent of net assets"),
]

FILES = [
    {"file": "llms.txt", "format": "text/plain", "what": "Guide for AI agents: what this is, what it adds, which file to use"},
    {"file": "funds.json", "format": "application/json", "what": "One record per fund: identity, status, latest figures, month order"},
    {"file": "monthly.csv", "format": "text/csv", "what": "Monthly total return and net flow for every fund and benchmark"},
    {"file": "reports.csv", "format": "text/csv", "what": "One row per quarterly report: net assets, 3-month return, written calls, notes"},
    {"file": "data.json", "format": "application/json", "what": "Exactly the numbers shown on the page"},
    {"file": "datapackage.json", "format": "application/json", "what": "Licence, citation and the meaning of every column of the CSV files"},
]


def r(x, d=4):
    return None if x is None else round(x, d)


def table(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def publish(cfg, by_fund, series, orders, data, cutoff, dirs: list[Path]) -> list[dict]:
    tick = {d["series"]: d["ticker"] for d in cfg["detail"]}
    tick.update({"benchmark:" + b["ticker"]: b["ticker"] for b in cfg["benchmark"]})
    bench_of = {d["series"]: d["benchmark"] for d in cfg["detail"]}

    funds, monthly_rows, report_rows = [], [], []
    for key in sorted(by_fund, key=lambda k: (by_fund[k][-1]["role"] != "category", by_fund[k][-1]["name"].lower())):
        reps = by_fund[key]
        last = reps[-1]
        ret, flow, odd = series[key]
        is_bench = key.startswith("benchmark:")
        fid = last["series_id"] or key
        end = last["report_date"][:7]
        ov, nt = overlay(last), notes(last)
        span = lambda n: compound(ret, [month_back(end, k) for k in range(n - 1, -1, -1)])
        ann = lambda n: None if span(n) is None else ((1 + span(n) / 100) ** (12 / n) - 1) * 100
        funds.append({
            "id": fid, "name": last["name"], "ticker": tick.get(key),
            "role": "benchmark" if is_bench else "fund", "name_type": None if is_bench else type_of(last["name"]),
            "benchmark": bench_of.get(key), "still_reporting": last["report_date"][:7] >= cutoff,
            "first_report": reps[0]["report_date"], "latest_report": last["report_date"],
            "latest_filing": last["filing_date"], "reports": len(reps), "months": len(ret),
            "first_month": min(ret) if ret else None, "latest_month": max(ret) if ret else None,
            "net_assets_usd": last["net_assets"],
            "total_return_pct": {"3_months": r(span(3)), "12_months": r(span(12)),
                                 "36_months_a_year": r(ann(36)), "60_months_a_year": r(ann(60))},
            "month_order": orders[key],
            "written_calls": {"positions": ov["written_calls"], "face_value_pct_net_assets": r(ov["notional_pct"], 2),
                              "strikes_taken_from_title": ov["strikes_repaired"],
                              "nearest_expiration": ov["nearest_expiration"]},
            "structured_notes": {"count": nt["count"], "pct_net_assets": r(nt["pct"], 2),
                                 "issuers": [i["issuer"] for i in nt["issuers"]]},
            "flow_months_not_used": odd})
        for m in sorted(set(ret) | set(flow)):
            monthly_rows.append([fid, tick.get(key) or "", last["name"], m, "" if m not in ret else r(ret[m], 6),
                                 "" if flow.get(m) is None else round(flow[m], 2), orders[key]["order"]])
        for rep in reps:
            e = rep["report_date"][:7]
            o, n = overlay(rep), notes(rep)
            m3 = [month_back(e, 2), month_back(e, 1), e]
            f3 = [flow.get(m) for m in m3]
            c3 = compound(ret, m3)
            report_rows.append([fid, tick.get(key) or "", rep["name"], rep["report_date"], rep["filing_date"],
                                rep["net_assets"], "" if c3 is None else r(c3, 4),
                                "" if any(f is None for f in f3) else round(sum(f3), 2), o["written_calls"],
                                "" if o["notional_pct"] is None else r(o["notional_pct"], 2), n["count"],
                                "" if n["pct"] is None else r(n["pct"], 2)])

    meta = data["meta"]
    counts = {}
    for f in funds:
        if f["role"] == "fund":
            counts[f["month_order"]["order"]] = counts.get(f["month_order"]["order"], 0) + 1
    cite = (f"Papadogiannis, A. Covered-Call Monitor, data to {meta['reports_to']}. {REPO}")
    credit = {"licence": LICENCE, "cite_as": cite, "describe_as": DESCRIBE_AS,
              "author": {"name": "Agisilaos Papadogiannis", "orcid": "https://orcid.org/0009-0002-7753-7052",
                         "url": "https://github.com/apapadogiannis"}}
    data["meta"]["credit"] = credit
    package = {"name": "covered-call-monitor", "title": "Covered-Call Monitor", "description": DESCRIBE_AS,
               "homepage": REPO, "version": meta["reports_to"],
               "licenses": [{"name": LICENCE["name"], "path": LICENCE["url"], "title": "Creative Commons Attribution 4.0"}],
               "contributors": [{"title": "Agisilaos Papadogiannis", "role": "author",
                                 "path": "https://orcid.org/0009-0002-7753-7052"}],
               "citation": cite,
               "sources": [{"title": "SEC Form N-PORT data sets (US government work, public domain)", "path": meta["source"]}],
               "resources": [
                   {"name": "monthly", "path": "monthly.csv", "format": "csv", "mediatype": "text/csv",
                    "schema": {"fields": [{"name": n, "type": t, "description": d} for n, t, d in MONTHLY_FIELDS],
                               "missingValues": [""]}},
                   {"name": "reports", "path": "reports.csv", "format": "csv", "mediatype": "text/csv",
                    "schema": {"fields": [{"name": n, "type": t, "description": d} for n, t, d in REPORT_FIELDS],
                               "missingValues": [""]}},
                   {"name": "funds", "path": "funds.json", "format": "json", "mediatype": "application/json",
                    "description": "One record per fund; see llms.txt"}]}
    funds_doc = {"about": "Covered-Call Monitor. See llms.txt for what each file is and how the figures are made.",
                 **credit,
                 "reports_to": meta["reports_to"], "first_month": meta["first_month"],
                 "source": meta["source"], "funds": funds}
    guide = f"""# Covered-Call Monitor

> Total returns, written call positions, structured notes and net flows of US-registered
> covered-call, buy-write and premium-income funds, computed and corrected from the reports the
> funds file with the US Securities and Exchange Commission (Form N-PORT).

Maintained by Agisilaos Papadogiannis (https://github.com/apapadogiannis). Updated each quarter.
This file is written for AI agents and other programs. People should start at index.html.

## Coverage

- {sum(1 for f in funds if f['role'] == 'fund')} funds, of which {meta['funds_in_category']} still report; {sum(1 for f in funds if f['role'] == 'benchmark')} index funds as benchmarks.
- Monthly figures from {meta['first_month']}; latest report on file {meta['reports_to']}.
- {len(monthly_rows)} fund-months and {len(report_rows)} quarterly reports.

## What this adds over the raw SEC files

Use this instead of recomputing from the SEC data sets unless you need a field that is not here.
The raw files are about 450 MB a quarter and contain errors that are not flagged:

1. Month order. The form asks for three monthly returns oldest first. Some fund families file them
   newest first. Each fund is tested against an index fund and read in the order that fits.
   Result: {counts.get('as filed', 0)} as filed, {counts.get('reversed', 0)} reversed, {counts.get('not determined', 0)} not determined.
2. Strikes. For some index options the strike field holds only the last digits (550 for 28550).
   The strike is repaired from the holding's title when the filed number is its tail.
3. Option size. The "shares" field is filled in three different ways. Face value here is
   contracts x 100 x strike, from the holding's balance.
4. Months before a fund existed are filed as zero. They are removed, with the first part month.
5. Amended reports replace the report they amend. A fund whose identifier changed keeps one series.
6. Checked against published figures: QYLD and JEPI total returns to 30 June 2026 over 1 month to
   5 years match those published for the funds.

## Files

- funds.json: one record per fund. Start here. `month_order.order` tells you whether that fund's
  monthly figures can be trusted month by month.
- monthly.csv: columns id, ticker, name, month, total_return_pct, net_flow_usd, month_order.
- reports.csv: one row per quarterly report: id, ticker, name, report_date, filing_date,
  net_assets_usd, total_return_3m_pct, net_flow_3m_usd, written_calls,
  calls_face_value_pct_net_assets, notes, notes_pct_net_assets.
- data.json: exactly what the page shows (five funds against their index funds, and the category).
- datapackage.json: the licence, the citation and the meaning of every column of the two CSV files.

## How to read the figures

- Every return is a total return in per cent: price change plus distributions, reinvested.
- A month is the calendar month, written YYYY-MM. Returns compound: multiply (1 + r/100).
- `id` is the SEC series identifier. Fund names are as filed. Tickers are given only for the five
  funds shown in detail and the three benchmarks.
- Returns over whole reports (3, 12, 36, 60 months ending at a report date) do not depend on the
  month order. Use them for any fund. Use single months only where month_order is "as filed" or
  "reversed".
- Each fund is as of its own report date. Report dates differ between fund families.
- An empty cell means the filing does not give the figure. It never means zero.

## Do not use this for

- Distribution yield, distributions per share, or return of capital: not in these filings.
- Anything after the latest report date, or daily prices.
- European (UCITS) funds.
- Strikes of funds that hold their options inside notes: the filing does not give them.
- A recommendation. The figures are as filed by the funds and are not audited.

## Source, licence and credit

Source: SEC Form N-PORT data sets, {meta['source']} (US government work, public domain).

The figures in these files are released under CC BY 4.0 ({LICENCE['url']}).
The licence allows any reuse and has one condition: credit. If you use a figure from these files in
an answer, a report or a data set, name the source.

Cite as: {cite}

To describe the source in a sentence: {DESCRIBE_AS}

The same licence and citation are inside funds.json and data.json, and in datapackage.json for the
CSV files. The code is under the MIT License.
"""
    out = {"funds.json": json.dumps(funds_doc, indent=1) + "\n",
           "monthly.csv": table(["id", "ticker", "name", "month", "total_return_pct", "net_flow_usd", "month_order"],
                                monthly_rows),
           "reports.csv": table(["id", "ticker", "name", "report_date", "filing_date", "net_assets_usd",
                                 "total_return_3m_pct", "net_flow_3m_usd", "written_calls",
                                 "calls_face_value_pct_net_assets", "notes", "notes_pct_net_assets"], report_rows),
           "datapackage.json": json.dumps(package, indent=1) + "\n",
           "llms.txt": guide}
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        for name, text in out.items():
            (d / name).write_text(text, encoding="utf-8")
    return FILES
