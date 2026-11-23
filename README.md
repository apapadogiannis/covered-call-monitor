# Covered-call monitor

[![check](https://github.com/apapadogiannis/covered-call-monitor/actions/workflows/check.yml/badge.svg)](https://github.com/apapadogiannis/covered-call-monitor/actions/workflows/check.yml)
[![Zenodo](https://img.shields.io/badge/Zenodo-10.5281%2Fzenodo.24418592-007ec6)](https://doi.org/10.5281/zenodo.24418592)

Live at https://apapadogiannis.github.io/covered-call-monitor/

**What does the yield cost?** Covered-call, buy-write and premium-income funds measured each quarter
from public SEC filings: each fund's total return beside an index fund on the same market and beside
a mix of that index fund and Treasury bills with the same market risk, the options it had actually
written on its last report date, what it paid out, and the money moving in and out.

## Use it from your own AI assistant

One skill covers this tool and the rest of the research: a short file that tells an assistant when to
use the work, where the files are and how to read them. It holds no figures, so it does not go stale.
For Claude Code:

```bash
mkdir -p ~/.claude/skills/papadogiannis-finance-research
curl -o ~/.claude/skills/papadogiannis-finance-research/SKILL.md https://raw.githubusercontent.com/apapadogiannis/apapadogiannis/main/skill/SKILL.md
```

Then ask, for example, "how has QYLD done against the Nasdaq-100 index fund?". Other assistants that
read `SKILL.md` files take the same file in their own skills folder. This tool no longer publishes a
skill of its own: a copy added earlier keeps working, since it only points to the files below.

## For AI agents and programs

Read [`api/llms.txt`](api/llms.txt) first. It says what this data set is, what it adds over the raw
SEC files, which file to use for what, and what not to use it for. The data are in `api/`:

| File | Content |
|---|---|
| `api/index.json` | a short list of every fund with the address of its own file |
| `api/funds/` | one small file per fund: its record, every month and every report |
| `api/funds.json` | one record per fund: identity, status, latest figures, its market risk beside its index fund, and whether its monthly figures can be trusted month by month |
| `api/monthly.csv` | monthly total return and net flow for every fund and benchmark, from 2019 |
| `api/reports.csv` | one row per quarterly report: net assets, 3-month return, written calls, notes |
| `api/data.json` | what the page draws from; the same file the page serves |
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
- **The category by name**: every US-registered fund whose name says covered call, buy-write or premium
  income, with net assets, returns, flows and the face value of its written calls. Funds that sell
  calls under another name (option income, enhanced income, overwrite) are not in it.
- **What each fund paid out**: the filings state no distribution, so it is implied from them, quarter
  by quarter, from net assets, total returns and flows, and given as a rate on net asset value with its
  history. It is an estimate, good to within a point or two a year, and not a yield on the market price.
- **Market risk**: a covered-call fund carries about half the market risk of its index fund, so its
  gap to the index fund is not the cost of the options alone. Each fund with an index fund is also
  set beside a mix of that index fund and four-week Treasury bills with the fund's own beta, with
  the volatility and the largest fall of both.

It reports what the funds filed. It does not forecast, and it shows no yield on the market price.

## How it works

```
config/funds.toml     which funds are followed, the benchmarks, the first quarter kept
monitor/update.py     the only code that uses the network: downloads the SEC's quarterly data set
                      and the US Treasury's daily bill rate
monitor/extract.py    cuts one quarterly data set down to the followed funds
monitor/build.py      joins the quarters and computes everything the page shows
monitor/publish.py    writes the files for programs and AI agents (api/)
api/                  those files: funds.json, monthly.csv, reports.csv, datapackage.json, llms.txt
site/template.html    the page; the numbers are embedded at build time
data/nport/<quarter>/ the stored extracts (five small CSV files per quarter)
data/sources.json     what was downloaded, when, its size and checksum
data/rates/           the US Treasury's daily four-week bill rate, the cash of the equal-risk mix
tests/test_monitor.py checks of the rules the page depends on
tests/test_published.py recomputes published fund returns from the stored filings
reference/            the published returns used as the yardstick
```

```bash
python3 -I tests/test_monitor.py     # the rules
python3 -I tests/test_published.py   # published returns reproduced from the filings
python3 -I build.py                  # writes _site/index.html and _site/data.json
python3 update.py                    # downloads any quarter not yet stored (needs SEC_CONTACT)
```

Python 3.11 or later, standard library only.

A GitHub Actions workflow runs the update on the sixth of each month. It does nothing unless the SEC
has posted a new quarter. The SEC asks automated clients to declare a contact; the workflow reads it
from the repository variable `SEC_CONTACT`, and it is never written to a file.

## How the check works

The badge at the top is green when all of the following pass, at every change and after every
quarterly update. The page is published only if they do.

1. **The rules.** `tests/test_monitor.py` tests each rule the figures depend on with small made-up
   cases: joining reports into monthly series, reading a fund that files its months newest first,
   dropping months before a fund existed, repairing a strike that was cut short, leaving out a month
   with a negative flow.
2. **Published returns.** `tests/test_published.py` recomputes, from the SEC filings stored in
   `data/`, twelve total returns that a third party has published for two funds (one month to five
   years, to 30 June 2026) and fails if any differs by more than the published rounding. The figures
   are in `reference/published_returns.csv`. One of the two funds files its months newest first and
   the other does not, so both readings are covered.
3. **The build.** The page and the data files are built, and the files in `api/` must be exactly the
   ones the build produces.

What the check does not show: that the funds' own filings are right, or that funds other than the two
in the reference match their published returns.

## Data and licensing

Source: US Securities and Exchange Commission, Form N-PORT data sets
(https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets), a work of the US
government in the public domain. `data/README.md` describes the stored files and the known quirks of
the source. Figures are as filed by the funds and are not audited or corrected here.

Code: MIT. Extracted tables in `data/`: public domain, as their source. The computed figures in
`api/` and on the page: CC BY 4.0, which allows any reuse with credit. Cite as given in
`CITATION.cff` and in `api/llms.txt`.

## Citation

Papadogiannis, A. (2026). *Covered-Call Monitor*. Zenodo. [doi:10.5281/zenodo.24418592](https://doi.org/10.5281/zenodo.24418592)

That DOI covers all versions and always resolves to the latest release. The citation with the date
of the data is in `api/llms.txt` and inside the JSON data files.

## Related article

For how covered-call funds work and what to look at in one: A. Papadogiannis (2026), "High Yield,
Capped Gains: Mechanics, Trade-Offs, and Practical Diagnostics for Covered-Call ETFs", *The Journal of
Beta Investment Strategies* 17(2), 110-123, [doi:10.3905/jbis.2026.001](https://doi.org/10.3905/jbis.2026.001).
The figures of this monitor are computed from SEC filings and are not taken from the article.

## Disclaimer

Independent work, without funding. For information only. Not investment advice and not a
recommendation to buy or sell any fund.
