"""Test templates by size with temporary orders in a temp folder."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import datetime, filecmp, json, os, shutil, sys, tkinter as tk
from pathlib import Path

APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
helpers.temp_admin(OUT / "admin")  # ORCA reads its files from a temp ADMIN, never the real one
sys.path.insert(0, str(APP)); os.chdir(APP)
import orders, printhub, routing, jobs

if TMP.exists():
    shutil.rmtree(TMP)
for d in ("pending", "orders", "finished"):
    (TMP / d).mkdir(parents=True)
tpl = TMP / "templates"
shutil.copytree(APP / "templates", tpl)
shutil.copyfile(tpl / "210x210.cdr", tpl / "TestProd.cdr")  # a product's own template (temporary)

cases = {"PH-99011": ("bcard", [85, 55], "85x55.cdr"),
         "PH-99012": ("bcard", [55, 85], "85x55.cdr"),
         "PH-99013": ("flyer", [148, 210], "148x210.cdr"),
         "PH-99014": ("envelope", [165, 165], "blank.cdr"),
         "PH-99015": ("testprod", [85, 55], "TestProd.cdr"),
         "PH-99016": ("bcard", [84.6, 55.4], "85x55.cdr"),
         "PH-99017": ("bcard", [85, 55], None)}  # already has its .cdr
for number, (product, cut, _) in cases.items():
    item = TMP / "pending" / number / "01"
    item.mkdir(parents=True)
    (item.parent / "order.json").write_text(json.dumps({
        "format": 1, "order": number, "paid_at": datetime.datetime.now().astimezone().isoformat(),
        "delivery": "pickup", "steps": ["PRINT"], "documents": ["01"]}), encoding="utf-8")
    (item / "job.json").write_text(json.dumps({
        "format": 1, "kind": "product", "product": product, "name": "Test", "quantity": 10,
        "options": {}, "cut_mm": cut, "files": ["c.png"]}), encoding="utf-8")
    (item / "c.png").write_bytes(b"")
(TMP / "pending" / "PH-99017" / "01" / "PH-99017.cdr").write_bytes(b"MY LAYOUT")

rules = routing.load_json("rules.json")
rules.update(pending_folder=str(TMP / "pending"), orders_folder=str(TMP / "orders"),
             finished_folder=str(TMP / "finished"), templates_folder=str(tpl))
root = tk.Tk(); root.withdraw()
view = printhub.PrintHubView(root, rules, jobs.Jobs(rules, routing.load_json("prices.json")))
view.win.withdraw()
ok = True


def check():
    global ok
    if not view.orders:
        root.after(300, check); return
    for order in view.orders:
        doc = order.documents[0]
        _, cut, want = cases[order.number]
        cdr = doc.folder / f"{order.number}.cdr"
        opts = (doc.folder / "Options.txt").read_text(encoding="utf-8-sig")
        line = [l for l in opts.splitlines() if l.startswith("CorelDRAW template")]
        details = [l.strip() for l in view.product_lines(order, doc) if "CorelDRAW template" in l]
        if want is None:
            good = cdr.read_bytes() == b"MY LAYOUT"
        else:
            good = filecmp.cmp(cdr, tpl / want, shallow=False) and line and want in line[0] and details == line
        ok &= bool(good)
        print(order.number, cut, "->", line, "| details:", details, "| OK" if good else "| FAIL")
    root.destroy()


root.after(500, check)
root.mainloop()
print("ALL OK" if ok else "SOME FAILED")
