# Changes

## 1.5.0 (27 November 2026)

New on the site

- A mark, a tab icon and a card shown when the page is shared.
- A row under the header that lists the cards of the page in view, stays in place while scrolling and
  marks the one being read.
- "Words used on this site", a glossary (address `#glossary`), and an "About" card for the monitor and
  its author (address `#about`), both linked beside the author line.

Robustness and access

- The summary shown without scripts sits outside the sections the script reveals, so it is seen.
- A card that cannot be drawn no longer stops the others.
- A "<" in a fund's name can no longer end the script that carries the data.
- Muted text and links meet the contrast standard in light mode; there is a link to skip to the content.
- A test of the built page (`tests/test_page.py`): every element the script looks up exists, and the
  script parses.

Effect on figures

- None. The data files are unchanged.

## 1.4.0

What each fund paid out, implied from its filings; one skill for the whole account.
