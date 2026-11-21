# Reference figures

`published_returns.csv` holds total returns of two funds as published by a third party, read on the
date in the `retrieved` column. They are not an input: nothing on the page is computed from them.
They are the yardstick of `tests/test_published.py`, which recomputes the same returns from the SEC
filings in `data/` and fails if any differs from the published figure by more than its rounding
(0.05 of a percentage point, plus a small allowance for the difference between funds' own and the
publisher's compounding).

One fund is from a family that files its monthly returns newest first (QYLD) and one from a family
that files them as the form asks (JEPI), so the test covers both readings.

The file is frozen. A later date is added as new rows, never by editing these.
