# Covered-call monitor

**What does the yield cost?** Covered-call, buy-write and premium-income funds measured each quarter
from public SEC filings: each fund's total return beside the index fund that holds the same shares,
the options it had actually written on its last report date, and the money moving in and out.

Status: first version, private until reviewed.

## For AI agents and programs

Read [`api/llms.txt`](api/llms.txt) first. It says what this data set is, what it adds over the raw
SEC files, which file to use for what, and what not to use it for. The data are in `api/`:

| File | Content |
|---|---|
| `api/funds.json` | one record per fund: identity, status, latest figures, and whether its monthly figures can be trusted month by month |
| `api/monthly.csv` | monthly total return and net flow for every fund and benchmark, from 2019 |
| `api/reports.csv` | one row per quarterly report: net assets, 3-month return, written calls, notes |
| `api/datapackage.json` | the licence, the citation and the meaning of every column of the CSV files |
| `api/llms.txt` | the guide |

These files are rebuilt from `data/` by `build.py` and checked by the tests. Do not edit them by hand.

## What it shows

- **Every fund of the category, one at a time:** cumulative total return since 2019 or its start, the
  written calls or structured notes on its last report date, and monthly net flows. A fund whose name
  names the Nasdaq-100, the S&P 500 or the Russell 2000 is set beside an index fund on that index
  (QQQ, IVV, IWM).
- **Five large funds on the front page** (QYLD, XYLD, RYLD, JEPI, JEPQ), compared with their index
  funds over a chosen period.
- **The whole category**: every US-registered fund whose name says covered call, buy-write or premium
  income, with net assets, returns, flows and the face value of its written calls.

It reports what the funds filed. It does not forecast and it shows no distribution yield.

## How it works

```
config/funds.toml     which funds are followed, the benchmarks, the first quarter kept
monitor/update.py     the only code that uses the network: downloads the SEC's quarterly data set
monitor/extract.py    cuts one quarterly data set down to the followed funds
monitor/build.py      joins the quarters and computes everything the page shows
monitor/publish.py    writes the files for programs and AI agents (api/)
api/                  those files: funds.json, monthly.csv, reports.csv, datapackage.json, llms.txt
site/template.html    the page; the numbers are embedded at build time
data/nport/<quarter>/ the stored extracts (five small CSV files per quarter)
data/sources.json     what was downloaded, when, its size and checksum
tests/test_monitor.py checks of the rules the page depends on
```

```bash
python3 -I tests/test_monitor.py     # checks
python3 -I build.py                  # writes _site/index.html and _site/data.json
python3 update.py                    # downloads any quarter not yet stored (needs SEC_CONTACT)
```

Python 3.11 or later, standard library only.

A GitHub Actions workflow runs the update on the sixth of each month. It does nothing unless the SEC
has posted a new quarter. The SEC asks automated clients to declare a contact; the workflow reads it
from the repository variable `SEC_CONTACT`, and it is never written to a file.

## Data and licensing

Source: US Securities and Exchange Commission, Form N-PORT data sets
(https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets), a work of the US
government in the public domain. `data/README.md` describes the stored files and the known quirks of
the source. Figures are as filed by the funds and are not audited or corrected here.

Code: MIT. Extracted tables in `data/`: public domain, as their source. The computed figures in
`api/` and on the page: CC BY 4.0, which allows any reuse with credit. Cite as given in
`CITATION.cff` and in `api/llms.txt`.

## Related article

For how covered-call funds work and what to look at in one: A. Papadogiannis (2026), "High Yield,
Capped Gains: Mechanics, Trade-Offs, and Practical Diagnostics for Covered-Call ETFs", *The Journal of
Beta Investment Strategies* 17(2), 110-123, [doi:10.3905/jbis.2026.001](https://doi.org/10.3905/jbis.2026.001).
The figures of this monitor are computed from SEC filings and are not taken from the article.

## Disclaimer

Independent work, without funding. For information only. Not investment advice and not a
recommendation to buy or sell any fund.
