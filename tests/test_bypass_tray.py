"""Copier rules 2026-11-13: simulated copiers only (sending replaced by a recorder), temp folders only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import os, shutil, sys, threading, time, tkinter as tk
from pathlib import Path

APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True)
for f in ("rules.json", "prices.json"):
    shutil.copyfile(APP / f, TMP / f)
real_app_dir = routing.app_dir
routing.app_dir = lambda: TMP
import jobs, orders, printhub, driverprint
import pypdfium2 as pdfium

SENT = []


def fake_print_pdf(pdf, queue_name, devmode, doc_name, **kw):
    with jobs.PDF_LOCK:
        d = pdfium.PdfDocument(str(pdf)); n = len(d); d.close()
    SENT.append((queue_name, doc_name, n))


def fake_devmode(queue_name, paper, color, duplex, copies, paper_type, tray, short_edge=False):
    SENT.append(("devmode", queue_name, duplex, tray, copies))
    return None


driverprint.print_pdf = fake_print_pdf
driverprint.build_devmode = fake_devmode
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))

rules = routing.load_json("rules.json")
print("rules check:", routing.check_rules(rules) or "fine")
J = jobs.Jobs(rules, routing.load_json("prices.json"))
results = []


def check(name, ok, info=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name, "|", info)


def product(paper, sides_choice, cut=(85, 55)):
    d = orders.Document("01", TMP)
    d.kind, d.print_paper, d.pages = "product", "A4", 2
    d.job = {"options": {"Paper": paper, "Sides": sides_choice}, "cut_mm": list(cut), "quantity": 100}
    return d


def product_job(doc, busy=frozenset(), sides=None):
    sides = sides or doc.default_sides(rules)
    s = doc.product_settings(13, doc.default_paper_type(rules), sides, rules)
    job = J.job_for("p", s, 2, 2.0, [True, True], printhub.PRODUCT_MAX_SHEETS, busy=busy)
    if sides == orders.HAND:
        printhub.hand_job(job)
    return job


def show(job):
    return (f"{rules['printers'][job['printer']]['label']}, {job['tray']}, "
            + ("hand-turned" if job.get("hand") else "duplex" if job["duplex"] else "one side")
            + f" ({job['reason']}){'; problem: ' + job['problem'] if job['problem'] else ''}")


j = product_job(product("Silk 300 gsm", "Both sides"))
check("product Silk 300, Both sides -> C3000, Bypass, hand", (j["printer"], j["tray"], j.get("hand")) == ("C3000", "Bypass Tray", True), show(j))
j = product_job(product("Silk 300 gsm", "Both sides"), busy={"C3000"})
check("same, C3000 busy -> C4510, Bypass, hand", (j["printer"], j["tray"], j.get("hand")) == ("C4510", "Bypass Tray", True), show(j))
j = product_job(product("Silk 300 gsm", "Both sides"), sides="long")
check("Silk 300 with Both sides long edge picked by hand -> still hand-turned", j.get("hand") is True and not j["problem"], show(j))
j = product_job(product("Smooth white 350 gsm", "One side"))
check("product Smooth white 350, One side -> C4510 (C3000 free), Bypass", (j["printer"], j["tray"], j["problem"]) == ("C4510", "Bypass Tray", None), show(j))
d = product("Smooth white 350 gsm", "One side")
s = d.product_settings(13, d.default_paper_type(rules), "single", rules); s["printer"] = "C3000"
j = J.job_for("p", s, 2, 2.0, [True, True], printhub.PRODUCT_MAX_SHEETS, busy=set())
check("350 gsm picked by hand onto C3000 -> problem", bool(j["problem"]) and "300 gsm" in j["problem"], j["problem"])
j = product_job(product("Silk 170 gsm", "Both sides"))
check("product Silk 170, Both sides -> C3000, Bypass, normal duplex", (j["printer"], j["tray"], j["duplex"], j.get("hand")) == ("C3000", "Bypass Tray", True, None), show(j))
j = product_job(product("Smooth white 80 gsm", "One side"))
check("product Smooth white 80, One side -> normal tray, C3000", (j["printer"], j["tray"]) == ("C3000", "Auto Tray Select"), show(j))
j = product_job(product("Smooth white 80 gsm", "One side"), busy={"C3000"})
check("same, C3000 busy -> C4510", j["printer"] == "C4510", show(j))


def doc_job(color, paper_type, sides, coverage=2.0, busy=frozenset()):
    d = orders.Document("01", TMP)
    d.job = {"color": color, "sides": sides, "paper": "A4", "per_side": 1, "paper_type": paper_type, "copies": 2}
    return J.job_for("d", d.settings(), 4, coverage, [True] * 4 if color != "bw" else [False] * 4, busy=busy)


j = doc_job("color", "Plain & Recycled", "single")
check("website document colour 80 gsm -> C3004, normal tray", (j["printer"], j["tray"]) == ("C3004", "Auto Tray Select"), show(j))
j = doc_job("color", "Plain & Recycled", "single", busy={"C3000"})
check("same with C3000 busy -> still C3004", j["printer"] == "C3004", show(j))
j = doc_job("bw", "Plain & Recycled", "long")
check("website document B&W 80 gsm -> C4510, normal tray, duplex", (j["printer"], j["tray"], j["duplex"], j.get("hand")) == ("C4510", "Auto Tray Select", True, None), show(j))
j = doc_job("color", "Thick 4(257 to 300 g/m2)", "long")
check("website document Glossy 300 (Thick 4), both sides -> Bypass, hand-turned", (j["tray"], j.get("hand")) == ("Bypass Tray", True), show(j))
j = doc_job("color", "Thick 3(221 to 256 g/m2)", "long")
check("website document Glossy 200 (Thick 3), both sides -> Bypass, hand-turned", (j["tray"], j.get("hand")) == ("Bypass Tray", True), show(j))
s = {"color": "color", "printer": "auto", "sides": "long", "paper": "A4", "per_side": "1",
     "paper_type": "Thick 1(106 to 169 g/m2)", "tray": "Auto Tray Select", "copies": "1", "rotate": "0"}
j = J.job_for("m", s, 4, 20.0, [True] * 4, busy=set())
check("main window colour Thick 1, both sides -> C3000, Bypass, normal duplex", (j["printer"], j["tray"], j["duplex"], j.get("hand")) == ("C3000", "Bypass Tray", True, None), show(j))
s2 = dict(s, paper_type="Thick 2(170 to 220 g/m2)", tray="Tray 2")
j = J.job_for("m", s2, 4, 20.0, [True] * 4, busy=set())
check("main window Thick 2 both sides, Tray 2 picked -> Bypass, hand-turned", (j["tray"], j.get("hand")) == ("Bypass Tray", True), show(j))
s3 = dict(s, paper_type="Plain & Recycled", tray="Tray 2", color="bw")
j = J.job_for("m", s3, 4, 0, [False] * 4, busy=set())
check("main window plain paper, Tray 2 picked -> Tray 2 kept", j["tray"] == "Tray 2", show(j))
check("settings text says Both sides by hand + Bypass", "Both sides by hand" in J.settings_text(s2, J.job_for("m", s2, 4, 20.0, [True] * 4, busy=set())) and "Bypass Tray" in J.settings_text(s2, J.job_for("m", s2, 4, 20.0, [True] * 4, busy=set())),
      J.settings_text(s2, J.job_for("m", s2, 4, 20.0, [True] * 4, busy=set())))

# Fronts / backs of a 3-page document: odd sides, then even sides + a blank, each one-sided, Bypass.
pdf = TMP / "doc3.pdf"
with jobs.PDF_LOCK:
    p = pdfium.PdfDocument.new()
    for _ in range(3):
        p.new_page(595, 842)
    p.save(str(pdf)); p.close()
j = doc_job("color", "Thick 4(257 to 300 g/m2)", "long")
(TMP / "w").mkdir()
SENT.clear()
J.print_one(TMP / "w", j, pdf, pdf, "A4", None, side="fronts")
J.print_one(TMP / "w", j, pdf, pdf, "A4", None, side="backs")
dm = [s for s in SENT if s[0] == "devmode"]
pages = [s[2] for s in SENT if s[0] != "devmode"]
check("hand-turned 3 pages: fronts 2 pages, backs 2 pages (1 blank), both one-sided from the Bypass",
      pages == [2, 2] and all(d[2] is False and d[3] == "Bypass Tray" for d in dm), (pages, dm))

# PrintHub: a copier taken by an order counts as busy for the colour choice.
for d in ("pending", "orders", "finished"):
    (TMP / d).mkdir()
rules.update(pending_folder=str(TMP / "pending"), orders_folder=str(TMP / "orders"),
             finished_folder=str(TMP / "finished"), templates_folder=str(real_app_dir() / "templates"))
root = tk.Tk(); root.withdraw()
view = printhub.PrintHubView(root, rules, J)
view.win.withdraw()
for _ in range(10):
    root.update(); time.sleep(0.05)
check("PrintHub: nothing taken -> no busy copier", J.busy() == set(), J.busy())


class FakeOrder:
    number = "PH-TEST"
    documents = []
view.orders = [FakeOrder()]
view.status["PH-TEST"] = {"step": 0, "parts": {"C3000": {"documents": ["01"], "state": "sent", "sent": ["01"]}},
                          "layout": {}, "history": []}
check("PrintHub: an order sent to C3000 and not collected -> C3000 busy", J.busy() == {"C3000"}, J.busy())
j = product_job(product("Silk 300 gsm", "Both sides"), busy=None)
check("product Silk 300 routed while PrintHub's C3000 is busy -> C4510", j["printer"] == "C4510", show(j))
view.status["PH-TEST"]["parts"]["C3000"]["state"] = "collected"
check("pages collected -> C3000 free again", J.busy() == set(), J.busy())
view.orders = []
view.win.destroy()

# Options.txt lines
d = product("Silk 300 gsm", "Both sides")
check("Options.txt product: Bypass + hand-turned lines", printhub.tray_lines(d, rules) == [
    "Tray: Bypass Tray (the paper isn't plain paper)",
    "Both sides, turned by hand: fronts first, turn the stack over, then Print backs"], printhub.tray_lines(d, rules))
check("Options.txt product 80 gsm: no tray line", printhub.tray_lines(product("Smooth white 80 gsm", "Both sides"), rules) == [])
check("Options.txt product Silk 170 both sides: Bypass only", printhub.tray_lines(product("Silk 170 gsm", "Both sides"), rules) == ["Tray: Bypass Tray (the paper isn't plain paper)"])

# (The old Walk-in main window, with its own hand-turned sending, was replaced on 2026-11-17 by walk-in orders;
# their hand-turned parts are checked in test_hand_turned.py and test_print_queue.py.)
root.destroy()
print("ALL OK" if all(results) else "SOME FAILED", f"{sum(map(bool, results))}/{len(results)} passed")
