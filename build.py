"""Builds the page and its data file. See monitor/build.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from monitor.build import ROOT, build  # noqa: E402

if __name__ == "__main__":
    d = build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_site")
    print(f"{d['meta']['funds_in_category']} funds, reports {d['meta']['reports_from']} to {d['meta']['reports_to']}")
