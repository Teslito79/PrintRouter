"""Handoff 2026-11-18_04: the walk-in price list in two sheets. Reads only; temp files in the temp folder."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import os, shutil, subprocess, sys
from pathlib import Path

APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); sys.path.insert(0, str(Path(__file__).parent)); os.chdir(APP)
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True)
helpers.temp_admin(OUT / "admin")  # ORCA reads its files from a temp ADMIN
import walkin_prices as wp
import price_sheet as ps

results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:600])


OLD = TMP / "old_trial.xlsx"
OLD.write_bytes(subprocess.run(["git", "show", "eb0b427:Walk-in_Prices.xlsx"], capture_output=True, check=True).stdout)
NEW = APP / "Walk-in_Prices.xlsx"
EMPTY = Path(str(helpers.PRICE_TEMPLATE))
FIELDS = ("copies", "papers", "envelopes", "cut_price", "stacks", "lamination", "spiral", "staple", "extras", "services",
          "tier2", "tier3", "loyalty", "spend", "trial", "filled")
check("the old trial list (from git) has six sheets, the new one two", list(wp.read_xlsx(OLD)) ==
      ["Read me", "Copies", "Paper", "Cutting", "Extras", "Settings"] and list(wp.read_xlsx(NEW)) == ["Prices", "Settings"],
      (list(wp.read_xlsx(OLD)), list(wp.read_xlsx(NEW))))
check("ADMIN's Walk-in_Prices.xlsx is the trial list (its title says TEST, every price 0)",
      "TEST" in wp.read_xlsx(NEW)["Prices"][0][1][0] and wp.load(NEW).trial, wp.read_xlsx(NEW)["Prices"][0])
a, b = wp.load(OLD), wp.load(NEW)
diff = {f: (getattr(a, f), getattr(b, f)) for f in FIELDS if getattr(a, f) != getattr(b, f)}
check("same price list from both trial files: " + ", ".join(FIELDS), not diff, diff)
check("…in the same order (papers, extras, services)", list(a.papers) == list(b.papers) and list(a.extras) == list(b.extras)
      and list(a.services) == list(b.services))
check("…both give the trial line and nothing else", a.warnings == b.warnings == [wp.TRIAL], (a.warnings, b.warnings))
e = wp.load(EMPTY)
check("Tesla's empty two-sheet file: no prices, the one “no prices” yellow line, no other warnings",
      e.filled == 0 and e.warnings == [wp.NO_PRICES] and not e.trial, e.warnings)
filled = ps.test_sheet(EMPTY, TMP / "filled.xlsx")
f = wp.load(filled)
check("the empty file with test prices typed into its yellow cells reads every price with no warnings",
      f.warnings == [] and f.copies[("A4", "color")] == [0.3, 0.25, 0.2] and f.papers["Silk 300 gsm"] == {"A4": 0.2, "A3": 0.4}
      and f.cut_price == 0.1 and f.services["Folding"][:2] == (0.05, "sheet") and f.tier2 == 200, f.warnings)
row = int(ps.cell(EMPTY, "Paper", "Silk 300 gsm", col=1)[1:])
bad = ps.test_sheet(EMPTY, TMP / "bad.xlsx", {"Prices": {f"B{row}": "abc"}})
w = wp.load(bad).warnings
check(f"text in a price cell on Prices gives a warning naming Prices and its row ({row})",
      w == [f"Prices row {row}: “abc” isn't a number: Silk 300 gsm, A4 sheet counts as empty."], w)
bad2 = ps.test_sheet(EMPTY, TMP / "bad2.xlsx", {"Settings": {ps.cell(EMPTY, "Settings", "Tier 2 from", col=2): "lots"}})
w2 = wp.load(bad2).warnings
check("…and on Settings it names Settings", len(w2) == 1 and w2[0].startswith("Settings row 4:"), w2)
# a missing table: today's warning for that table, not "this sheet is missing"
import xml.etree.ElementTree as ET
sheets = wp.read_xlsx(filled)
real = wp.read_xlsx
wp.read_xlsx = lambda p: {"Prices": [(r, v) for r, v in sheets["Prices"] if not (v and v[0] in ("Envelope",))],
                          "Settings": sheets["Settings"]}
w3 = wp.load(filled).warnings
wp.read_xlsx = real
check("a missing table gives that table's warning, naming Prices",
      "Prices row -: the “Envelope / Per envelope” heading row wasn't found: envelopes have no prices." in w3
      and not any("this sheet is missing" in x for x in w3), w3)
title = sheets["Prices"][0][1][0]
check("the trial title is A1 of Prices", wp.read_xlsx(NEW)["Prices"][0] == (1, ["Walk-in prices - TEST, every price 0"])
      and b.trial and title == "Walk-in prices", (wp.read_xlsx(NEW)["Prices"][0], title))
print(f"{sum(results)}/{len(results)} passed")
