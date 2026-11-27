"""PrintHub: a website document on Thick 4, both sides -> fronts, turn, Print backs. Simulated copiers, temp folder."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import datetime, json, os, shutil, sys, time, tkinter as tk
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
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers"))
driverprint.build_devmode = lambda q, paper, color, duplex, copies, pt, tray, short_edge=False: (duplex, tray, copies)


def fake_print(pdf, q, devmode, name, **kw):
    d = pdfium.PdfDocument(str(pdf)); n = len(d); d.close()
    SENT.append((q, name, n, devmode))


driverprint.print_pdf = fake_print
for d in ("pending", "orders", "finished"):
    (TMP / d).mkdir()
o = TMP / "orders" / "PH-20000"
(o / "01").mkdir(parents=True)
p = pdfium.PdfDocument.new()
for _ in range(4):
    p.new_page(595, 842)
p.save(str(o / "01" / "doc.pdf")); p.close()
(o / "01" / "job.json").write_text(json.dumps({"format": 1, "file": "doc.pdf", "pages": 4, "copies": 3, "color": "color",
                                               "sides": "long", "paper": "A4", "per_side": 1,
                                               "paper_type": "Thick 4(257 to 300 g/m2)"}), encoding="utf-8")
(o / "order.json").write_text(json.dumps({"format": 1, "order": "PH-20000", "paid_at": datetime.datetime.now().astimezone().isoformat(),
                                          "delivery": "pickup", "steps": ["PRINT"], "documents": ["01"]}), encoding="utf-8")
rules = routing.load_json("rules.json")
rules.update(pending_folder=str(TMP / "pending"), orders_folder=str(TMP / "orders"),
             finished_folder=str(TMP / "finished"), templates_folder=str(real_app_dir() / "templates"))
root = tk.Tk(); root.withdraw()
J = jobs.Jobs(rules, routing.load_json("prices.json"))
view = printhub.PrintHubView(root, rules, J)
view.win.withdraw()


def pump(cond, secs=15):
    end = time.time() + secs
    while time.time() < end and not cond():
        root.update(); time.sleep(0.05)
    for _ in range(5):
        root.update(); time.sleep(0.05)


pump(lambda: view.orders and view.orders[0].documents[0].pdf)
order = view.orders[0]
print("problems:", view.problems_of(order), "parts:", view.parts_of(order))
view.start_printing()
pump(lambda: view.part_state(order, "C3000") == "turn")
part = view.status_of(order)["parts"].get("C3000", {})
print("after start:", part.get("state"), SENT)
print("panel:", view.panels["C3000"]["state"].cget("text"))
ok1 = part.get("state") == "turn" and [s[2] for s in SENT] == [2] and SENT[0][3] == (False, "Bypass Tray", 3)
view.send_backs("C3000")
pump(lambda: view.part_state(order, "C3000") == "sent")
print("after Print backs:", view.part_state(order, "C3000"), SENT)
ok2 = view.part_state(order, "C3000") == "sent" and len(SENT) == 2 and "backs" in SENT[1][1]
opt = printhub.options_text(order, order.documents[0], rules=rules)
print(opt)
ok3 = "Tray: Bypass Tray" in opt and "turned by hand" in opt
view.win.destroy(); root.destroy()
print("ALL OK" if ok1 and ok2 and ok3 else "SOME FAILED", ok1, ok2, ok3)
