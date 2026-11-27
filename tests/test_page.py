"""The built page: what a visitor and the page's own script depend on.

    python3 -I build.py && python3 -I tests/test_page.py

Reads _site/index.html as built and checks that every element the script looks up by a fixed name
exists, that every card of the page has a name for the row under the header, that the summary shown
without scripts sits outside the sections the script reveals, and that the icons and the share card
were written.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_site"
page = (out / "index.html").read_text(encoding="utf-8")
script = max(re.findall(r"<script>(.*?)</script>", page, flags=re.S), key=len)
markup = page.replace(script, "")

ids = set(re.findall(r'\bid="([^"]+)"', markup))
looked_up = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', script)) | set(re.findall(r'getElementById\("([A-Za-z0-9_-]+)"\)', script))
missing = sorted(looked_up - ids)
assert not missing, f"the script looks up elements the page does not have: {missing}"

cards = re.findall(r'<div class="card"([^>]*)>\s*<h2', markup)
unnamed = [c for c in cards if "data-nav" not in c]
assert len(cards) >= 12 and len(unnamed) <= 1, f"cards without a name for the row under the header: {unnamed}"   # the fallback summary has none

assert markup.index("<noscript>") < markup.index('id="view-funds"') and '<main id="main">' in markup
assert 'id="sec-about"' in markup and 'id="sec-glossary"' in markup and "about:" in script and "glossary:" in script
assert "\\u003c" in page or "<" not in re.search(r"const D = (.*?);\nconst", script, flags=re.S).group(1)
for name in ("favicon.svg", "apple-touch-icon.png", "social-card.png"):
    assert (out / name).stat().st_size > 0, name
assert 'rel="icon" href="favicon.svg"' in page and "social-card.png" in page
print(f"page checks pass: {len(looked_up)} elements looked up, {len(cards)} cards")
