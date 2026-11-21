"""Cuts one quarterly SEC Form N-PORT data set down to the funds the monitor follows.

    python3 -I monitor/extract.py NPORT_ZIP CONFIG_TOML OUT_DIR

Reads the SEC's zip as published and writes five small CSV files to OUT_DIR:

    funds.csv        one row per report: fund, report date, net assets, monthly flows
    returns.csv      monthly total returns of the three months each report covers
    composition.csv  share of net assets by kind of holding
    options.csv      every option position, with the strike as filed and as named in the title
    notes.csv        every structured note (the equity-linked notes of some funds)

Nothing is computed here beyond selecting rows and naming columns. The zip is not stored.
"""
from __future__ import annotations

import csv
import io
import re
import sys
import tomllib
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

csv.field_size_limit(1 << 30)


def iso(d: str) -> str:
    """'31-JUL-2026' -> '2026-07-31'. Empty stays empty."""
    return datetime.strptime(d.title(), "%d-%b-%Y").date().isoformat() if d else ""


def table(z: zipfile.ZipFile, name: str):
    """Rows of one tab-delimited table of the data set, as dictionaries."""
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8", newline=""), delimiter="\t",
                                  quoting=csv.QUOTE_NONE)


def write(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def role_of(name: str, series: str, cfg: dict) -> str:
    """'benchmark:QQQ', 'category' or ''."""
    for b in cfg["benchmark"]:
        if series in b["series"] or re.search(b["name"], name):
            return "benchmark:" + b["ticker"]
    c = cfg["category"]
    if re.search(c["include"], name) and not re.search(c["exclude"], name):
        return "category"
    return ""


def extract(zip_path: Path, cfg: dict, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        sub = {r["ACCESSION_NUMBER"]: r for r in table(z, "SUBMISSION.tsv")}

        chosen: dict[str, str] = {}
        funds = []
        for r in table(z, "FUND_REPORTED_INFO.tsv"):
            role = role_of(r["SERIES_NAME"], r["SERIES_ID"], cfg)
            if not role:
                continue
            a = r["ACCESSION_NUMBER"]
            chosen[a] = role
            s = sub[a]
            funds.append([a, r["SERIES_ID"], r["SERIES_NAME"], role, iso(s["REPORT_DATE"]), iso(s["FILING_DATE"]),
                          s["SUB_TYPE"], r["NET_ASSETS"], r["TOTAL_ASSETS"]]
                         + [r[f"{k}_FLOW_MON{m}"] for m in (1, 2, 3) for k in ("SALES", "REINVESTMENT", "REDEMPTION")])
        funds.sort(key=lambda x: (x[2], x[4], x[5], x[0]))
        write(out / "funds.csv",
              ["accession", "series_id", "series_name", "role", "report_date", "filing_date", "form", "net_assets",
               "total_assets"] + [f"{k}_m{m}" for m in (1, 2, 3) for k in ("sales", "reinvested", "redeemed")], funds)

        rets = [[r["ACCESSION_NUMBER"], r["CLASS_ID"], r["MONTHLY_TOTAL_RETURN1"], r["MONTHLY_TOTAL_RETURN2"],
                 r["MONTHLY_TOTAL_RETURN3"]] for r in table(z, "MONTHLY_TOTAL_RETURN.tsv")
                if r["ACCESSION_NUMBER"] in chosen]
        rets.sort()
        write(out / "returns.csv", ["accession", "class_id", "return_m1", "return_m2", "return_m3"], rets)

        # Holdings: one pass over the largest table, keeping only the chosen reports.
        comp: dict[tuple, list] = defaultdict(lambda: [0, 0.0, 0.0])
        deriv: dict[str, dict] = {}
        notes = []
        with z.open("FUND_REPORTED_HOLDING.tsv") as f:
            text = io.TextIOWrapper(f, encoding="utf-8", newline="")
            header = text.readline().rstrip("\n").split("\t")
            ix = {h: i for i, h in enumerate(header)}
            for line in text:
                a = line[:line.find("\t")]
                if a not in chosen:
                    continue
                c = line.rstrip("\n").split("\t")
                g = lambda k: c[ix[k]]
                key = (a, g("ASSET_CAT"), g("DERIVATIVE_CAT"))
                comp[key][0] += 1
                comp[key][1] += float(g("PERCENTAGE") or 0)
                comp[key][2] += float(g("CURRENCY_VALUE") or 0)
                if g("DERIVATIVE_CAT"):
                    deriv[g("HOLDING_ID")] = {k: g(k) for k in
                                              ("ACCESSION_NUMBER", "ISSUER_NAME", "ISSUER_TITLE", "BALANCE", "UNIT",
                                               "CURRENCY_VALUE", "PERCENTAGE", "DERIVATIVE_CAT")}
                if g("ASSET_CAT") == "SN":
                    notes.append([a, g("ISSUER_NAME"), g("ISSUER_TITLE"), g("CURRENCY_VALUE"), g("PERCENTAGE")])
        write(out / "composition.csv", ["accession", "asset_cat", "derivative_cat", "holdings", "pct_net_assets", "value"],
              sorted([k[0], k[1], k[2], v[0], round(v[1], 6), round(v[2], 2)] for k, v in comp.items()))
        notes.sort()
        write(out / "notes.csv", ["accession", "issuer", "title", "value", "pct_net_assets"], notes)

        ref: dict[str, list[str]] = {}
        for r in table(z, "DESC_REF_INDEX_BASKET.tsv"):
            if r["HOLDING_ID"] in deriv:
                ref[r["HOLDING_ID"]] = [r["INDEX_NAME"], r["INDEX_IDENTIFIER"]]
        for r in table(z, "DESC_REF_OTHER.tsv"):
            if r["HOLDING_ID"] in deriv and r["HOLDING_ID"] not in ref:
                ref[r["HOLDING_ID"]] = [(r["ISSUER_NAME"] + " " + r["ISSUE_TITLE"]).strip(), r["TICKER"]]

        opts = []
        for r in table(z, "SWAPTION_OPTION_WARNT_DERIV.tsv"):
            h = deriv.get(r["HOLDING_ID"])
            if not h:
                continue
            rn, rt = ref.get(r["HOLDING_ID"], ["", ""])
            opts.append([h["ACCESSION_NUMBER"], r["HOLDING_ID"], h["ISSUER_TITLE"], h["BALANCE"], h["UNIT"],
                         h["CURRENCY_VALUE"], h["PERCENTAGE"], r["PUT_OR_CALL"], r["WRITTEN_OR_PURCHASED"],
                         r["SHARES_CNT"], r["EXERCISE_PRICE"], iso(r["EXPIRATION_DATE"]),
                         r["UNREALIZED_APPRECIATION"], rn, rt])
        opts.sort(key=lambda x: (x[0], x[2], x[1]))
        write(out / "options.csv",
              ["accession", "holding_id", "title", "balance", "unit", "value", "pct_net_assets", "put_or_call",
               "written_or_purchased", "shares", "strike_as_filed", "expiration", "unrealized", "reference",
               "reference_id"], opts)

    return {"reports": len(funds), "category": sum(1 for f in funds if f[3] == "category"),
            "benchmark": sum(1 for f in funds if f[3] != "category"), "return_rows": len(rets),
            "options": len(opts), "notes": len(notes)}


if __name__ == "__main__":
    zip_path, cfg_path, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    print(extract(zip_path, tomllib.loads(cfg_path.read_text(encoding="utf-8")), out))
