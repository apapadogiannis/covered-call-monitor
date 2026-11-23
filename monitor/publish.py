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
import re
from pathlib import Path

from monitor.build import compound, distributions, month_back, notes, overlay, type_of

REPO = "https://github.com/apapadogiannis/covered-call-monitor"
SITE = "https://apapadogiannis.github.io/covered-call-monitor/"
DOI = "10.5281/zenodo.24418592"          # all versions; always resolves to the latest release
LICENCE = {"name": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/",
           "condition": "Reuse is allowed with credit to the source."}
DESCRIBE_AS = ("Covered-Call Monitor, by Agisilaos Papadogiannis: figures computed and corrected from the "
               "reports US funds file with the SEC (Form N-PORT).")

ARTICLE = {"citation": "Papadogiannis, A. (2026). High Yield, Capped Gains: Mechanics, Trade-Offs, and Practical "
                       "Diagnostics for Covered-Call ETFs. The Journal of Beta Investment Strategies, 17(2), 110-123.",
           "doi": "https://doi.org/10.3905/jbis.2026.001",
           "relation": "Background on the strategy and on what to look at in a covered-call fund. The figures in "
                       "these files are not taken from the article."}

MONTHLY_FIELDS = [
    ("id", "string", "SEC series identifier of the fund (S followed by nine digits). A few funds, mostly closed-end, have none; their id is the fund name as filed"),
    ("ticker", "string", "Ticker symbol of the fund, or of its first share class, from the SEC's list of fund tickers; empty where that list has none (closed-end funds, and funds no longer listed)"),
    ("name", "string", "Fund name as filed in its latest report"),
    ("month", "yearmonth", "Calendar month, YYYY-MM"),
    ("total_return_pct", "number", "Total return on net asset value for the month in per cent, distributions reinvested, to the precision filed; empty if not filed or if the month is before the fund's first full month"),
    ("net_flow_usd", "number", "Sales plus reinvestments less redemptions, in US dollars; empty if not filed or not used. For a fund whose month_order is reversed the flows are in the order filed, which may also be reversed: use sums over the three months of a report"),
    ("month_order", "string", "as filed, reversed or not determined: how the fund's three monthly returns per report were read"),
]
REPORT_FIELDS = [
    ("id", "string", "SEC series identifier of the fund, or the fund name where it has none"),
    ("ticker", "string", "Ticker symbol, where given"),
    ("name", "string", "Fund name as filed in that report"),
    ("report_date", "date", "Date the report describes"),
    ("filing_date", "date", "Date the report was filed with the SEC"),
    ("net_assets_usd", "number", "Net assets on the report date, in US dollars"),
    ("total_return_3m_pct", "number", "Total return over the three months ending at the report date, in per cent; does not depend on month order"),
    ("net_flow_3m_usd", "number", "Net flow over those three months, in US dollars; empty if a month was not used"),
    ("written_calls", "integer", "Number of written call positions listed on the report date. Zero for a fund that takes its call exposure through structured notes: see notes"),
    ("distributions_3m_pct_net_assets", "number", "Distributions over the three months ending at the report date as implied by the filings, per cent of the average of opening and closing net assets: an estimate, see `distributions` in funds.json. Empty for a fund's first report and where it cannot be computed"),
    ("calls_face_value_pct_net_assets", "number", "Contracts x 100 x strike of the written calls, as per cent of net assets. Can exceed 100. Empty if there are no calls, if it cannot be computed, or if it comes out above 200 (options on foreign indices struck in another currency), where it is not shown"),
    ("notes", "integer", "Number of structured notes held"),
    ("notes_pct_net_assets", "number", "Market value of the structured notes as per cent of net assets. This is not the share of the portfolio that calls are written against"),
]

FUND_FIELDS = [   # funds.json, one record per fund
    ("id", "As in the CSV files: the SEC series identifier, or the fund name where the fund has none"),
    ("name", "Fund name as filed in its latest report"),
    ("ticker", "Ticker symbol of the fund, or of its first share class, from the SEC's list of fund tickers; null where that list has none (closed-end funds, and funds no longer listed). Find those by name"),
    ("role", "fund, or benchmark for the three index funds used for comparison"),
    ("name_type", "Which of the three words the fund's name uses: Covered call, Buy-write or Premium income"),
    ("file", "Path of this fund's own small file, relative to the address of funds.json: its record, every month and every report"),
    ("benchmark", "Ticker of the index fund this fund is set beside, chosen from the index its name states; null where the name states none of the three. Given for funds that stopped reporting too"),
    ("against_benchmark", "The fund and its index fund over the same months. `last_12_months` and `longest_common_period` each give `from`, `to`, the fund's and the index fund's total return in per cent over those months. The longest period is the longest unbroken run of months ending at the fund's latest month; it also gives `months`, `gap` (the fund's cumulative return less the index fund's, in percentage points, not annualised, so not comparable between funds with different periods) and, for periods over a year, `fund_a_year`, `benchmark_a_year` and `gap_a_year`, the same as yearly rates. Use this, not two records' own figures, to compare a fund with its index fund. Null where there is no benchmark"),
    ("against_benchmark.risk", "Market risk of the fund beside its index fund over the longest common period. `periods` and `months_per_period` (1, or 3 for a fund read in three-month steps); `beta` (slope of the fund's return above Treasury bills on the index fund's); `correlation`; `volatility_fund` and `volatility_benchmark` (standard deviation of period returns as a yearly figure, per cent); `largest_fall_fund` and `largest_fall_benchmark` (largest fall from an earlier period-end, per cent, negative; falls within a period are not seen); `matched_mix` (cumulative total return, per cent, of beta in the index fund and the rest in four-week Treasury bills, rebalanced each period) and `gap_to_matched_mix` (the fund's cumulative return less that, in points); and the yearly rates `fund_a_year`, `benchmark_a_year`, `matched_mix_a_year`, `gap_a_year`, `gap_to_matched_mix_a_year`. The gap to the index fund mixes two things, lower market exposure and the result of the options; the gap to the matched mix removes the first. Beta is measured over the same period, so the mix is a reading in hindsight, not a portfolio one could have chosen in advance. Null under two years of months (three years in three-month steps)"),
    ("still_reporting", "False if the fund's latest report is more than six months older than the newest report on file. Such funds are kept, so the history has no survivorship gap, but they are not counted in the category"),
    ("first_report, latest_report, latest_filing", "Dates of the first and latest quarterly report on file and the date the latest was filed"),
    ("reports", "Number of quarterly reports on file"),
    ("months, first_month, latest_month", "Number of months with a total return, and the first and last of them. monthly.csv can hold earlier rows for the same fund that carry a net flow but no return. For a fund whose month order is not determined, first_month can be off by up to two months"),
    ("net_assets_usd", "Net assets on latest_report, in US dollars"),
    ("total_return_pct", "Total returns on net asset value, in per cent, over the 3, 12, 36 and 60 months ending at `to` (the month of latest_report). The 36 and 60 month figures are annualised. Null where the fund has too few months"),
    ("month_order.order", "as filed, reversed or not determined: how the three monthly returns of each report were read"),
    ("month_order.compared_with", "Ticker of the index fund whose months fitted this fund best, out of the three benchmarks. It is used only to decide the order and need not be the fund's own market; null if fewer than four reports could be compared"),
    ("month_order.misfit_as_filed, misfit_reversed", "Sum over the compared reports of the squared differences, in percentage points, between the fund's and the index fund's monthly returns, under each reading. The order is decided only if one misfit is less than half the other"),
    ("month_order.reports_compared", "Number of reports used in that comparison"),
    ("written_calls.positions", "Number of written call positions listed in the latest report"),
    ("written_calls.face_value_pct_net_assets", "Contracts x 100 x strike, as per cent of net assets. Can exceed 100 when a fund writes calls on more than it holds or the index is above the strike basis. Null if there are no calls, if it cannot be computed, or if it comes out above 200, where it is not shown"),
    ("written_calls.strikes_taken_from_title", "Number of positions whose strike was repaired from the holding's title"),
    ("written_calls.nearest_expiration", "Earliest expiration date among the written calls, as filed"),
    ("call_exposure_in_notes", "True if the fund lists no written calls but holds structured notes. Its call exposure sits inside the notes, and the filing gives neither strikes nor the share of the portfolio covered"),
    ("no_overlay_on_report_date", "True if the latest report lists neither written calls nor structured notes. This does not mean the fund writes no options: a fund that writes options expiring the same day, or that had rolled out of its position, has none on its books at the report date"),
    ("structured_notes", "Number of structured notes, their market value as per cent of net assets, and their issuers"),
    ("distributions", "What the fund paid out, as implied by its filings: an estimate, not a figure the fund files. `last_12_months` gives `from`, `to` and `pct_net_assets`, the distributions of the last four quarters as per cent of net assets (each quarter on the average of its opening and closing net assets); null unless four quarters in a row can be computed. `quarters` lists each quarter with the month it ends (`to`) and `pct_net_assets`. Method: net assets at the start of the quarter are carried forward at the fund's total return with each month's net flow added at mid-month; what the fund holds less than that at the end is what it paid out. It includes every kind of distribution (income, capital gains, return of capital) and is a rate on net asset value, not a yield on the market price. It is good to within a point or two a year, less for a fund with very large flows; a single quarter is noisier, can be off by a point or more, and can come out slightly negative. A quarter is left out when a flow or a return is missing or the result falls outside -1% to 40%"),
    ("flow_months_not_used", "Months whose net flow is left out because the filing reports negative sales or reinvestments. Redemptions filed as negative numbers are read as outflows of that size and used"),
]

FILES = [
    {"file": "llms.txt", "format": "text/plain", "what": "Guide for AI agents: what this is, what it adds, which file to use"},
    {"file": "index.json", "format": "application/json", "what": "Short list of every fund: id, ticker, name, benchmark, and the address of its own file"},
    {"file": "funds.json", "format": "application/json", "what": "One record per fund: identity, status, latest figures, month order"},
    {"file": "monthly.csv", "format": "text/csv", "what": "Monthly total return and net flow for every fund and benchmark"},
    {"file": "reports.csv", "format": "text/csv", "what": "One row per quarterly report: net assets, 3-month return, written calls, notes"},
    {"file": "data.json", "format": "application/json", "what": "Exactly the numbers shown on the page"},
    {"file": "datapackage.json", "format": "application/json", "what": "Licence, citation and the meaning of every column of the CSV files"},
]

RAW = "https://raw.githubusercontent.com/apapadogiannis/covered-call-monitor/main/api/"
# One skill covers every tool and paper of the account. It sends an agent to this guide.
SKILL_FOR_AGENTS = "https://raw.githubusercontent.com/apapadogiannis/apapadogiannis/main/skill/SKILL.md"


def r(x, d=4):
    return None if x is None else round(x, d)


def table(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def listed_tickers() -> dict[str, str]:
    """Series -> ticker of its first share class, from data/tickers.csv (the SEC's list of fund
    tickers, stored by the update). Empty until that file exists."""
    path = Path(__file__).resolve().parent.parent / "data" / "tickers.csv"
    out: dict[str, str] = {}
    if path.exists():
        for row in sorted(csv.DictReader(path.open(encoding="utf-8")), key=lambda r: r["class_id"], reverse=True):
            out[row["series_id"]] = row["ticker"]
    return out


def file_name(fid: str, is_bench: bool) -> str:
    """Name of a fund's own file: its SEC series identifier, or its name in plain letters."""
    if is_bench:
        return "benchmark-" + fid.split(":")[-1] + ".json"
    return (fid if re.fullmatch(r"S\d+", fid) else re.sub(r"[^a-z0-9]+", "-", fid.lower()).strip("-")) + ".json"


def publish(cfg, by_fund, series, orders, data, cutoff, dirs: list[Path], stopped: dict | None = None) -> list[dict]:
    tick = listed_tickers()
    tick.update({d["series"]: d["ticker"] for d in cfg["detail"]})
    tick.update({"benchmark:" + b["ticker"]: b["ticker"] for b in cfg["benchmark"]})
    bench_of = {d["series"]: d["benchmark"] for d in cfg["detail"]}

    beside = {**(stopped or {}), **{f["id"]: f for f in data["funds"]}}   # each fund beside its index fund
    rnd = lambda d: d and {k: (r(v) if isinstance(v, float) else v) for k, v in d.items()}
    funds, monthly_rows, report_rows, own = [], [], [], {}
    for key in sorted(by_fund, key=lambda k: (by_fund[k][-1]["role"] != "category", by_fund[k][-1]["name"].lower())):
        reps = by_fund[key]
        last = reps[-1]
        ret, flow, odd = series[key]
        is_bench = key.startswith("benchmark:")
        fid = last["series_id"] or key
        end = last["report_date"][:7]
        ov, nt = overlay(last), notes(last)
        dist = distributions(reps, ret, flow)
        by_quarter = {q["to"]: q["rate"] for q in dist["quarters"]}
        span = lambda n: compound(ret, [month_back(end, k) for k in range(n - 1, -1, -1)])
        ann = lambda n: None if span(n) is None else ((1 + span(n) / 100) ** (12 / n) - 1) * 100
        funds.append({
            "id": fid, "name": last["name"], "ticker": tick.get(key),
            "file": "funds/" + file_name(key if is_bench else fid, is_bench),
            "role": "benchmark" if is_bench else "fund", "name_type": None if is_bench else type_of(last["name"]),
            "benchmark": (beside.get(fid) or {}).get("benchmark") or bench_of.get(key),
            "against_benchmark": None if not (beside.get(fid) or {}).get("benchmark") else {
                "last_12_months": rnd(beside[fid]["last12"]),
                "longest_common_period": rnd(beside[fid]["window"]),
                "risk": rnd(beside[fid]["risk"])},
            "still_reporting": last["report_date"][:7] >= cutoff,
            "first_report": reps[0]["report_date"], "latest_report": last["report_date"],
            "latest_filing": last["filing_date"], "reports": len(reps), "months": len(ret),
            "first_month": min(ret) if ret else None, "latest_month": max(ret) if ret else None,
            "net_assets_usd": last["net_assets"],
            "total_return_pct": {"to": end, "3_months": r(span(3)), "12_months": r(span(12)),
                                 "36_months_a_year": r(ann(36)), "60_months_a_year": r(ann(60))},
            "month_order": orders[key],
            "written_calls": {"positions": ov["written_calls"], "face_value_pct_net_assets": r(ov["notional_pct"], 2),
                              "strikes_taken_from_title": ov["strikes_repaired"],
                              "nearest_expiration": ov["nearest_expiration"]},
            "call_exposure_in_notes": (not is_bench) and ov["written_calls"] == 0 and nt["count"] > 0,
            "no_overlay_on_report_date": (not is_bench) and ov["written_calls"] == 0 and nt["count"] == 0,
            "structured_notes": {"count": nt["count"], "pct_net_assets": r(nt["pct"], 2),
                                 "issuers": [i["issuer"] for i in nt["issuers"]]},
            "distributions": {
                "last_12_months": dist["last_12_months"] and {"from": dist["last_12_months"]["from"], "to": dist["last_12_months"]["to"],
                                                              "pct_net_assets": r(dist["last_12_months"]["rate"], 2)},
                "quarters": [{"to": q["to"], "pct_net_assets": r(q["rate"], 2)} for q in dist["quarters"]]},
            "flow_months_not_used": odd})
        mine = {"monthly": [], "reports": []}
        own[funds[-1]["file"]] = (funds[-1], mine)
        for m in sorted(set(ret) | set(flow)):
            monthly_rows.append([fid, tick.get(key) or "", last["name"], m, "" if m not in ret else r(ret[m], 6),
                                 "" if flow.get(m) is None else round(flow[m], 2), orders[key]["order"]])
            mine["monthly"].append({"month": m, "total_return_pct": r(ret[m], 6) if m in ret else None,
                                    "net_flow_usd": None if flow.get(m) is None else round(flow[m], 2)})
        for rep in reps:
            e = rep["report_date"][:7]
            o, n = overlay(rep), notes(rep)
            m3 = [month_back(e, 2), month_back(e, 1), e]
            f3 = [flow.get(m) for m in m3]
            c3 = compound(ret, m3)
            report_rows.append([fid, tick.get(key) or "", rep["name"], rep["report_date"], rep["filing_date"],
                                rep["net_assets"], "" if c3 is None else r(c3, 4),
                                "" if any(f is None for f in f3) else round(sum(f3), 2), o["written_calls"],
                                "" if e not in by_quarter else r(by_quarter[e], 2),
                                "" if o["notional_pct"] is None else r(o["notional_pct"], 2), n["count"],
                                "" if n["pct"] is None else r(n["pct"], 2)])
            mine["reports"].append({"report_date": rep["report_date"], "filing_date": rep["filing_date"],
                                    "net_assets_usd": rep["net_assets"], "total_return_3m_pct": r(c3, 4),
                                    "net_flow_3m_usd": None if any(f is None for f in f3) else round(sum(f3), 2),
                                    "written_calls": o["written_calls"],
                                    "distributions_3m_pct_net_assets": r(by_quarter.get(e), 2),
                                    "calls_face_value_pct_net_assets": r(o["notional_pct"], 2),
                                    "notes": n["count"], "notes_pct_net_assets": r(n["pct"], 2)})

    meta = data["meta"]
    counts = {}
    for f in funds:
        if f["role"] == "fund":
            counts[f["month_order"]["order"]] = counts.get(f["month_order"]["order"], 0) + 1
    n_funds = sum(1 for f in funds if f["role"] == "fund")
    n_tick = sum(1 for f in funds if f["role"] == "fund" and f["ticker"])
    cite = (f"Papadogiannis, A. (2026). Covered-Call Monitor, data to {meta['reports_to']}. Zenodo. "
            f"https://doi.org/{DOI}")
    credit = {"licence": LICENCE, "cite_as": cite, "doi": f"https://doi.org/{DOI}", "site": SITE, "code": REPO,
              "describe_as": DESCRIBE_AS,
              "author": {"name": "Agisilaos Papadogiannis", "orcid": "https://orcid.org/0009-0002-7753-7052",
                         "url": "https://github.com/apapadogiannis"},
              "related_article": ARTICLE}
    data["meta"]["credit"] = credit
    package = {"name": "covered-call-monitor", "title": "Covered-Call Monitor", "description": DESCRIBE_AS,
               "homepage": SITE, "repository": REPO, "doi": f"https://doi.org/{DOI}", "version": meta["reports_to"],
               "licenses": [{"name": LICENCE["name"], "path": LICENCE["url"], "title": "Creative Commons Attribution 4.0"}],
               "contributors": [{"title": "Agisilaos Papadogiannis", "role": "author",
                                 "path": "https://orcid.org/0009-0002-7753-7052"}],
               "citation": cite, "related_article": ARTICLE,
               "sources": [{"title": "SEC Form N-PORT data sets (US government work, public domain)", "path": meta["source"]}],
               "resources": [
                   {"name": "monthly", "path": "monthly.csv", "format": "csv", "mediatype": "text/csv",
                    "schema": {"fields": [{"name": n, "type": t, "description": d} for n, t, d in MONTHLY_FIELDS],
                               "missingValues": [""]}},
                   {"name": "reports", "path": "reports.csv", "format": "csv", "mediatype": "text/csv",
                    "schema": {"fields": [{"name": n, "type": t, "description": d} for n, t, d in REPORT_FIELDS],
                               "missingValues": [""]}},
                   {"name": "funds", "path": "funds.json", "format": "json", "mediatype": "application/json",
                    "description": "One record per fund, under the key `funds`",
                    "fields": [{"name": n, "description": d} for n, d in FUND_FIELDS]}]}
    funds_doc = {"about": "Covered-Call Monitor. See llms.txt for what each file is and how the figures are made.",
                 **credit,
                 "reports_to": meta["reports_to"], "first_month": meta["first_month"],
                 "source": meta["source"], "funds": funds}
    guide = f"""# Covered-Call Monitor

> Total returns, written call positions, structured notes and net flows of US-registered
> covered-call, buy-write and premium-income funds, computed and corrected from the reports the
> funds file with the US Securities and Exchange Commission (Form N-PORT).

Maintained by Agisilaos Papadogiannis (https://github.com/apapadogiannis). Updated each quarter.
Page: {SITE}  Code: {REPO}  Archive: https://doi.org/{DOI}
This file is written for AI agents and other programs. People should start at the page.

## Coverage

- A fund is included when its name, as filed, says covered call, buy-write or premium income.
  Funds that sell calls under another name (option income, enhanced income, overwrite) are not
  included, and a few funds on bonds or other assets are. This is not every fund that writes calls.
- {sum(1 for f in funds if f['role'] == 'fund')} funds, of which {meta['funds_in_category']} still report; {sum(1 for f in funds if f['role'] == 'benchmark')} index funds as benchmarks.
- Monthly figures from {min(x[3] for x in monthly_rows)}; latest report on file {meta['reports_to']}.
- monthly.csv has {len(monthly_rows)} rows and reports.csv {len(report_rows)}, index funds included.
- Funds that stopped reporting are kept, marked `still_reporting: false`.

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
4. Months before a fund existed are filed as zero. Their returns are removed, with the part month
   the fund started in. A fund that started in the first month of its first report files no zero,
   so for every fund that enters the data after June 2020 the first month filed is removed too.
5. Redemptions are filed by some funds as negative numbers (QYLD from 2020 to early 2024, for one). They
   are read as outflows of that size. Only a month with negative sales or reinvestments is left out.
6. Amended reports replace the report they amend. A fund whose identifier changed keeps one series.
7. Distributions. The filings state none. They are implied from net assets, total returns and
   flows, quarter by quarter, and given as a rate on net assets. Checked on the three index funds,
   whose dividend yields are known: {", ".join(f"{f['ticker']} {f['distributions']['last_12_months']['pct_net_assets']:.1f}%" for f in funds if f['role'] == 'benchmark' and f['distributions']['last_12_months'])} over the last twelve months.
8. Market risk. Each fund with an index fund is also set beside a mix of that index fund and
   four-week Treasury bills with the fund's own beta, so that lower market exposure is not read as
   the cost of the options.
9. Checked against published figures: QYLD and JEPI total returns to 30 June 2026 over 1 month to
   5 years match those published for the funds.

## Files

- index.json: a short list of every fund (id, ticker, name, benchmark, whether it still reports) with
  the address of its own file. Start here for a question about one fund.
- funds/<file>.json: one fund: its record as in funds.json, every month and every report. Small
  enough to read whole.
- funds.json: one record per fund, about 150 KB. Use it for rankings and questions across funds.
  `month_order.order` tells you whether a fund's monthly figures can be trusted month by month.
  Every field is described in datapackage.json.
- monthly.csv: columns id, ticker, name, month, total_return_pct, net_flow_usd, month_order.
- reports.csv: one row per quarterly report: id, ticker, name, report_date, filing_date,
  net_assets_usd, total_return_3m_pct, net_flow_3m_usd, written_calls,
  distributions_3m_pct_net_assets, calls_face_value_pct_net_assets, notes, notes_pct_net_assets.
- data.json: what the page draws from, close to 1 MB: the monthly path of every fund beside its
  index fund (`funds[].months`), five funds in detail with their option positions (`detail`), and
  the totals by name type (`types`) and for the category (`meta`, `category`). Its keys are the
  page's own. You rarely need it: funds.json has each fund's comparison with its index fund.
- datapackage.json: the licence, the citation, and the meaning of every column of the two CSV
  files and every field of funds.json.
- A skill for an AI assistant: one skill covers this tool and the rest of the author's work, and
  sends the assistant to this guide. {SKILL_FOR_AGENTS}

All files are at {SITE} (for example {SITE}funds.json). In the repository the same
files are under api/. Every file of one build states the same latest report date; if two files
you fetched disagree on it, one is a cached copy, so fetch again.

## How to read the figures

- Every return is a total return on net asset value in per cent, with distributions reinvested, as
  the fund reports it. It is not the return on the market price. For a closed-end fund, which can
  trade well away from net asset value, it is not what a shareholder earned.
- A month is the calendar month, written YYYY-MM. Returns compound: multiply (1 + r/100).
- `id` is the SEC series identifier. A few funds have none and use the fund name. Fund names are
  as filed. {n_tick} of the {n_funds} funds carry a ticker; tickers come from the SEC's list of fund
  tickers, which has none for closed-end funds and for funds no longer listed. Find the others by
  name, and check a name in full:
  "JPMorgan Equity Premium Income ETF" and "JPMorgan Equity Premium Income Fund" are different
  funds. For a mutual fund the figures and the ticker are those of the first share class listed.
- Returns over whole reports (3, 12, 36, 60 months ending at a report date) do not depend on the
  month order. Use them for any fund. Use single months only where month_order is "as filed" or
  "reversed".
- One single month is safe even where the order is "not determined": the middle month of a report
  (the month before the report date's month), which is the same under either reading. The first
  and third months of such a report are the ones that may be swapped.
- Each fund is as of its own report date, and report dates differ between fund families. In
  funds.json `total_return_pct.to` gives the month each fund's returns end. A fund and an index
  fund whose `to` differ cover different months and cannot be set side by side. The category total
  of net assets adds funds at their own report dates.
- To set a fund beside its index fund, use `against_benchmark` in funds.json: it gives both over
  the same months, with the months stated. `gap` is in cumulative points over that fund's own
  period, so do not compare it between funds; `gap_a_year` is the yearly rate.
- The gap to the index fund is not the cost of the options alone. These funds carry about half the
  market risk of their index fund, so in a rising market they trail it for that reason as well.
  `against_benchmark.risk` gives the beta, the volatility and the largest fall of both, and
  `gap_to_matched_mix`: the fund against beta in the index fund and the rest in Treasury bills.
  Report that gap with the gap to the index fund. The beta is measured over the same months, so
  the mix is a reading in hindsight. No index fund is assigned to most funds: {meta['funds_with_index_fund']} of the
  {meta['funds_in_category']} that still report have one.
- `distributions` is an estimate implied by the filings, not a filed figure. Call it "the
  distribution rate implied by the fund's filings, on net asset value", give the twelve-month
  figure and not a single quarter, and say it is good to within a point or two a year. It is not a yield
  on the price an investor pays, and a high rate is not a high return: compare it with the total
  return over the same months, which already counts every distribution.
- Net flows: for a fund whose `month_order.order` is "reversed", single months of flow are in the
  order filed, which may be reversed too. Sums over the three months of a report are safe.
- A fund with `no_overlay_on_report_date: true` lists no written call and no note in its latest
  report. Do not say it has no option overlay: funds that write options expiring the same day
  hold none at a report date.
- A fund with `call_exposure_in_notes: true` shows zero written calls because its calls are inside
  structured notes. It does write calls. The size of the notes is not the share of the portfolio
  covered.
- Face value of written calls can exceed 100% of net assets. It is left empty above 200%, which
  happens with options on foreign indices struck in another currency.
- An empty cell means the figure was not filed or is not shown for a stated reason. It never means
  zero. A monthly return of exactly 0 is the figure as filed.

## Do not use this for

- Distributions per share, the split between income and return of capital, or a yield on the
  market price: not in these filings. The distribution rate here is implied, on net asset value.
- Anything after the latest report date, or daily prices.
- European (UCITS) funds.
- Strikes or coverage of funds that hold their options inside notes: the filing does not give them.
- Expense ratios, option premium earned, or the tax character of distributions: not in these files.
- Market-price returns, premiums and discounts.
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

## Related article

For how covered-call funds work and what to look at in one, the same author's peer-reviewed article:
{ARTICLE['citation']} {ARTICLE['doi']}

Cite the article for the explanation of the strategy and this data set for the figures. The figures
here are computed from SEC filings and are not taken from the article.
"""
    index_doc = {"about": "Covered-Call Monitor: every fund on file and the address of its own file. See llms.txt.",
                 "reports_to": meta["reports_to"], "licence": LICENCE, "cite_as": cite,
                 "funds": [{k: f[k] for k in ("id", "ticker", "name", "role", "still_reporting", "benchmark",
                                             "latest_report", "file")} for f in funds]}
    out = {"index.json": json.dumps(index_doc, indent=1) + "\n",
           **{name: json.dumps({"about": "Covered-Call Monitor: one fund. Fields as in funds.json, monthly.csv and "
                                         "reports.csv; see llms.txt and datapackage.json.",
                                "reports_to": meta["reports_to"], "licence": LICENCE, "cite_as": cite,
                                "fund": rec, **rows}, indent=1) + "\n" for name, (rec, rows) in own.items()},
           "funds.json": json.dumps(funds_doc, indent=1) + "\n",
           "monthly.csv": table(["id", "ticker", "name", "month", "total_return_pct", "net_flow_usd", "month_order"],
                                monthly_rows),
           "reports.csv": table(["id", "ticker", "name", "report_date", "filing_date", "net_assets_usd",
                                 "total_return_3m_pct", "net_flow_3m_usd", "written_calls",
                                 "distributions_3m_pct_net_assets", "calls_face_value_pct_net_assets", "notes", "notes_pct_net_assets"], report_rows),
           "datapackage.json": json.dumps(package, indent=1) + "\n",
           "llms.txt": guide}
    for d in dirs:
        (d / "funds").mkdir(parents=True, exist_ok=True)
        for name, text in out.items():
            (d / name).write_text(text, encoding="utf-8")
    return FILES
