# Data

Everything the page shows is computed from the files in `nport/`. Nothing is fetched at build time.

## Source

US Securities and Exchange Commission, Form N-PORT data sets, one zip per calendar quarter:
https://www.sec.gov/data-research/sec-markets-data/form-n-port-data-sets

A work of the US government, in the public domain. Each quarterly set holds the reports made public
in that quarter. Funds report monthly, but only the report for the last month of each fiscal quarter
is made public, about two months after its date. `sources.json` records, for each quarter, the
address, the size and SHA-256 of the zip, when it was retrieved, and how many rows were kept.

## Files, per quarter

| File | Content | From the SEC tables |
|---|---|---|
| `funds.csv` | one row per report: fund, role (category or benchmark), report and filing date, net assets, sales, reinvestments and redemptions for each of the three months | SUBMISSION, FUND_REPORTED_INFO |
| `returns.csv` | monthly total return (%) of each share class for the three months ending at the report date | MONTHLY_TOTAL_RETURN |
| `composition.csv` | number of holdings and share of net assets by kind of holding | FUND_REPORTED_HOLDING |
| `options.csv` | every option position: title, balance in contracts, value, put or call, written or purchased, strike as filed, expiration, reference | FUND_REPORTED_HOLDING, SWAPTION_OPTION_WARNT_DERIV, DESC_REF_INDEX_BASKET, DESC_REF_OTHER |
| `notes.csv` | every structured note: issuer, title, value, share of net assets | FUND_REPORTED_HOLDING (asset category SN) |

Rows are selected by the rules in `config/funds.toml` and copied as filed. The zip itself is not
stored: it is about 450 MB per quarter and can be downloaded again from the SEC.

## Known quirks of the source, and how they are handled

- **Strikes cut short.** For some index options the strike field holds only the last digits (550 for
  an option struck at 28,550). The full strike is in the holding's title. `build.py` uses the titled
  strike only when the filed number is the tail of the titled one, and the page marks it.
- **The "shares" field of an option** is filled in three different ways (shares per contract, total
  shares, or the number of contracts). It is stored but not used. Face value is computed as
  contracts (the balance) x 100 x strike.
- **Options on foreign indices** are struck in other currencies. A face value above 200% of net
  assets is not shown.
- **Negative sales or redemptions** appear in a few reports. Such a month's net flow is not used and
  the page says so.
- **Monthly returns filed newest first.** The form asks for the three months oldest first. The
  Global X funds file them the other way round. For the funds shown in detail, `build.py` compares
  both readings with the fund's index fund over all reports and uses the one that fits (see
  `filed_newest_first`). With the correction, QYLD's 1-month, 3-month, 1-year, 3-year and 5-year
  returns to 30 June 2026 match those published for the fund.
- **Months before a fund existed** are filed as zero in its first report. They are dropped, with the
  part month in which the fund started.
- **Funds that stop reporting.** A fund whose latest report is more than six months older than the
  newest report on file is no longer listed in the category.
- **Several reports for one date.** An amended report replaces the earlier one for the same fund and
  report date.
- **Share classes.** Where a report lists several classes, the first class identifier is used.
- **A fund's identity can change.** The Invesco QQQ Trust has no series identifier before it was
  reorganised and a new one after. Benchmarks are therefore matched by name as well.

## Tickers

`tickers.csv` (series, share class, ticker) is cut from the SEC's list of mutual fund and ETF
tickers, `https://www.sec.gov/files/company_tickers_mf.json`, at each update, for the funds on file.
It is a convenience for finding a fund: no figure depends on it. The list has no entry for
closed-end funds or for funds that are no longer listed.
