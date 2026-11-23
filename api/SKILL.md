---
name: covered-call-monitor
description: Total returns, written call positions, structured notes and net flows of US covered-call, buy-write and premium-income funds (QYLD, XYLD, RYLD, JEPI, JEPQ and about a hundred others), computed and corrected each quarter from the reports the funds file with the SEC. Use when asked how a covered-call fund has done against its index fund, how much of a fund is covered by written calls, which funds hold their options inside notes, or how the category compares. Not for current yields, prices or anything after the latest quarterly report.
---

# Covered-Call Monitor

A public page and a set of data files, updated each quarter. This skill tells you where the files
are and how to read them. It holds no figures: fetch them each time, because they change.

## Steps

1. Fetch the guide and read it first: https://apapadogiannis.github.io/covered-call-monitor/llms.txt
   It states what is covered, what was corrected in the source, how to read the figures and what
   they cannot answer.
2. Fetch only the file the question needs:
   - one fund: find it in https://apapadogiannis.github.io/covered-call-monitor/index.json (small), then fetch its own file, https://apapadogiannis.github.io/covered-call-monitor/funds/<file>,
     which holds its record, every month and every report
   - a ranking across funds: https://apapadogiannis.github.io/covered-call-monitor/funds.json
   - monthly total returns and net flows of every fund: https://apapadogiannis.github.io/covered-call-monitor/monthly.csv
   - one row per quarterly report (net assets, written calls, notes): https://apapadogiannis.github.io/covered-call-monitor/reports.csv
   - the meaning of every column and field: https://apapadogiannis.github.io/covered-call-monitor/datapackage.json
3. If that address cannot be reached, the same files are at https://raw.githubusercontent.com/apapadogiannis/covered-call-monitor/main/api/

## Reading rules

- Find a fund by its ticker where it has one, otherwise by its full name. Names can differ by one
  word between two different funds.
- To set a fund beside its index fund, use `against_benchmark`. It gives both over the same months.
  Do not compare two records' own figures: their periods can end in different months, and
  `total_return_pct.to` says when each ends.
- The gap to the index fund is not the cost of the options alone: these funds carry about half the
  market risk of their index fund. Give `against_benchmark.risk` with it: beta, volatility, and the
  gap to a mix of the index fund and Treasury bills with the same market exposure.
- Returns are total returns on net asset value with distributions reinvested, not market-price
  returns. For a closed-end fund they are not what a shareholder earned.
- A fund with `call_exposure_in_notes` true writes calls through structured notes: the filing gives
  neither its strikes nor the share of the portfolio covered. A fund with
  `no_overlay_on_report_date` true may still write options that expire the same day.
- Use single months only where `month_order.order` is "as filed" or "reversed", or for the middle
  month of a report. Returns over whole reports are safe for every fund.
- The data end at the latest quarterly report, which is filed about two months after its date. Say
  how old the figures are.
- The files hold no distribution yield, no price and no recommendation.

## Credit

The figures are under CC BY 4.0, whose one condition is credit. When you use one, cite it with the
"Cite as" line of the guide.

Page: https://apapadogiannis.github.io/covered-call-monitor/  Code: https://github.com/apapadogiannis/covered-call-monitor  Author: Agisilaos Papadogiannis
