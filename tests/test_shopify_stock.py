"""Handoff 2026-11-19_09: Shopify stock at the end of the day, On display and the restock list. Temp copy of the folder
layout; the real export is only read (copied to the temp folder); test CSVs in Shopify's exact format; the receipt
printer faked; pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import csv, ctypes, datetime, gc, json, os, shutil, sys, time, tkinter as tk
from pathlib import Path

ctypes.windll.shcore.SetProcessDpiAwareness(1)
APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); sys.path.insert(0, str(Path(__file__).parent)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
ADMIN = TMP / "ORCA" / "ADMIN"
FILES = TMP / "Downloads"
ADMIN.mkdir(parents=True); FILES.mkdir(); OUT.mkdir(parents=True, exist_ok=True)
for f in ("prices.json", "icon.ico", "Walk-in_Prices.xlsx"):
    shutil.copyfile(APP / f, ADMIN / f)
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, driverprint, inventory as inv, inventory_screens as iscr, mainmenu, printing, shopify_stock as shop, toners
from tkinter import messagebox, ttk
import window_shot

driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
RECEIPTS = []
printing.send = lambda pdf, queue, settings=None: RECEIPTS.append((str(pdf), queue))
toners.TIMEOUT = 0.2
asked = []
ANSWER = {"yes": True}
messagebox.askyesno = lambda *a, **k: asked.append(k.get("message")) or ANSWER["yes"]
messagebox.showwarning = lambda *a, **k: None
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:600])


HEADER = ["Handle", "Title", "Option1 Name", "Option1 Value", "Option2 Name", "Option2 Value", "Option3 Name",
          "Option3 Value", "SKU", "HS Code", "COO", "Location", "Bin name", "Incoming (not editable)",
          "Unavailable (not editable)", "Committed (not editable)", "Available (not editable)", "On hand (current)",
          "On hand (new)", "Variant Packed Length", "Variant Packed Width", "Variant Packed Height",
          "Variant Packed Dimension Unit"]
STAMP = {"t": time.time() - 10 * 86400}


def export(name, stock):
    """A CSV in Shopify's exact format (UTF-8 with BOM). stock: {short name: on hand}; a missing name = not in it."""
    products = {
        "pen": ("pen-blue", "Pen blue", "Title", "Default Title", "", "", "5201234000011"),
        "yarn_red": ("handcraft-yarn", "Handcraft Yarn 25g KEYROAD", "Χρώμα", "Red", "Μέγεθος", "25g", "5209000000101"),
        "yarn_blue": ("handcraft-yarn", "Handcraft Yarn 25g KEYROAD", "Χρώμα", "Blue", "Μέγεθος", "25g", "5209000000118"),
        "pencil": ("molyvi-hb", "Μολύβι HB ΣΧΟΛΙΚΟ", "Title", "Default Title", "", "", ""),
        "dup1": ("glue-a", "Glue stick A", "Title", "Default Title", "", "", "777"),
        "dup2": ("glue-b", "Glue stick B", "Title", "Default Title", "", "", "777"),
        "neg": ("tape", "Tape 19mm", "Title", "Default Title", "", "", "5201234000999"),
        "gone": ("old-thing", "Old thing", "Title", "Default Title", "", "", "5201234000888"),
        "notebook": ("notebook-new", "Notebook new", "Title", "Default Title", "", "", "5201234000777"),
    }
    path = FILES / name
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for short, n in stock.items():
            h, title, o1n, o1v, o2n, o2v, sku = products[short]
            w.writerow([h, title, o1n, o1v, o2n, o2v, "", "", sku, "", "", "Shop", "", 0, 0, 0, n, n, "", "", "", "", ""])
    STAMP["t"] += 86400
    os.utime(path, (STAMP["t"], STAMP["t"]))
    return path


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2


def pump(secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.02)


# ------------------------------------------------------------------ the real export (read only, a temp copy)
REAL = Path(str(helpers.REAL_SHOPIFY_EXPORT))
if REAL.exists():
    real_copy = TMP / "real_export.csv"
    shutil.copyfile(REAL, real_copy)
    rows, locations = shop.read_export(real_copy)
    names = [r["name"] for r in rows.values()]
    codes = [r["barcode"] for r in rows.values() if r["barcode"]]
    t0 = time.time()
    I0 = inv.Inventory.__new__(inv.Inventory)
    I0.data = {"items": [], "next_sale": 1}
    I0.save = lambda: None
    res = shop.load(I0, real_copy)
    check("the real Shopify export: 3180 items, 3180 unique keys, names from Title + options, barcodes only where "
          "unique, no errors", len(rows) == 3180 and len(I0.items) == 3180
          and len({it["shopify_key"] for it in I0.items}) == 3180 and len(codes) == len(set(codes))
          and not any(n.endswith("Default Title") for n in names) and res["first"] and locations == 1,
          (len(rows), len(codes), round(time.time() - t0, 1)))
    check("…below 0 kept as it is (340 rows)", sum(1 for it in I0.items if it["stock"] < 0) == 340)
    shutil.rmtree(ADMIN / shop.LOADS, ignore_errors=True)
    (ADMIN / inv.LOG_FILE).unlink(missing_ok=True)
else:
    check("the real Shopify export is on this PC", False, REAL)

# ------------------------------------------------------------------ before the first load: ORCA's own items
I = inv.Inventory()
paper = I.add({"name": "Copy paper A4", "stock": 2500, "per_unit": 500, "unit": "ream",
               "link": {"kind": "paper", "name": "Smooth white 80 gsm", "size": "A4"}})
mine = I.add({"name": "Pen blue (mine)", "barcodes": ["5201234000011"], "stock": 3, "category": "Pens", "price": 0.9})
menu.open_inventory(); pump(0.6)
S = [x for x in gc.get_objects() if isinstance(x, iscr.InventoryScreen) and x.win.winfo_exists()][-1]
S.win.geometry("1400x900+10+10"); pump(0.3)
I = S.inventory

# ------------------------------------------------------------------ the first load
day1 = export("day1.csv", {"pen": 20, "yarn_red": 5, "yarn_blue": 7, "pencil": 3, "dup1": 4, "dup2": 6, "neg": -2,
                            "gone": 4})
asked.clear()
r = S.load_shopify(str(day1)); pump(0.5)
pen = I.by_barcode("5201234000011")
check("first load: asks once to join ORCA items that match (barcode or name), then they follow Shopify",
      len(asked) == 1 and "1 items already in Inventory match" in asked[0] and pen["id"] == mine["id"]
      and pen["shopify_key"] == "pen-blue|Default Title||" and pen["stock"] == 20 and pen["category"] == "Pens"
      and pen["price"] == 0.9, (asked, pen))
check("…no Sold or Came in, and the line “First load: from tomorrow ORCA shows what sold”",
      r["first"] and r["sold"] == [] and r["came"] == [] and shop.since_text(r) == "First load: from tomorrow ORCA shows what sold")
names = sorted(it["name"] for it in I.items if it.get("shopify_key"))
check("…names from Title + options (Greek kept), keys from Handle + options",
      "Handcraft Yarn 25g KEYROAD - Red / 25g" in names and "Μολύβι HB ΣΧΟΛΙΚΟ" in names, names)
check("…a repeated SKU and an empty SKU give no barcode; stock below 0 is kept",
      I.by_name("Glue stick A")["barcodes"] == [] and I.by_name("Glue stick B")["barcodes"] == []
      and I.by_name("Μολύβι HB ΣΧΟΛΙΚΟ")["barcodes"] == [] and I.by_name("Tape 19mm")["stock"] == -2)
check("…ORCA's own linked paper item is untouched", I.get(paper["id"])["stock"] == 2500 and not I.get(paper["id"]).get("shopify_key"))
check("…the load is kept (a copy of the file and its time) and the changes are logged as shopify",
      len(list((ADMIN / shop.LOADS).iterdir())) == 1 and I.data["shopify_load"]["file"] == "day1.csv"
      and sum(1 for row in inv.read_log() if row["reason"] == "shopify") >= 7)
for w in root.winfo_children():
    for x in [w] + list(w.winfo_children()):
        if isinstance(x, tk.Toplevel) and x.title() in ("End of day: Shopify stock", "Restock"):
            x.destroy()

# ------------------------------------------------------------------ On display: Edit, On display…, Import
S.fill(select=pen["id"]); S.edit(); pump(0.2)
d = [x for x in gc.get_objects() if isinstance(x, iscr.ItemDialog) and x.dlg.winfo_exists()][-1]
d.vars["display"].set("10"); d.done(); pump(0.2)
pen = I.get(pen["id"])
check("On display set by Edit: 10, the shelf counts as full (10), logged",
      pen["display"] == 10 and pen["shelf"] == 10 and inv.read_log(pen["id"])[-1]["reason"] == "on display - -> 10")
yarn = I.by_name("Handcraft Yarn 25g KEYROAD - Red / 25g")
S.fill(select=yarn["id"]); S.on_display(); pump(0.2)
dd = [x for x in gc.get_objects() if isinstance(x, iscr.DisplayDialog) and x.dlg.winfo_exists()][-1]
dd.var.set("4"); dd.done(); pump(0.2)
check("…by On display… (logged)", I.get(yarn["id"])["display"] == 4 and inv.read_log(yarn["id"])[-1]["reason"] == "on display - -> 4")
imp = FILES / "display.csv"
imp.write_text("Barcode;Name;On display\n5209000000118;Handcraft Yarn 25g KEYROAD - Blue / 25g;3\n", encoding="utf-8-sig")
dlg = iscr.ImportDialog(S, imp); pump(0.2)
cols = dlg.columns()
dlg.do(); pump(0.2)
blue = I.by_name("Handcraft Yarn 25g KEYROAD - Blue / 25g")
check("…and by Import list (its column picker has On display; logged)", cols["display"] == 2 and blue["display"] == 3
      and blue["shelf"] == 3 and any(row["reason"] == "on display - -> 3" for row in inv.read_log(blue["id"])), cols)

# ------------------------------------------------------------------ the second load: Sold, Came in, new, gone
day2 = export("day2.csv", {"pen": 14, "yarn_red": 15, "yarn_blue": 7, "pencil": 3, "dup1": 4, "dup2": 6, "neg": -2,
                            "notebook": 5})
r = S.load_shopify(str(day2)); pump(0.6)
check("second load: Sold (Pen 6) and Came in (Yarn Red 10), since the first load",
      r["sold"] == [("Pen blue", 6)] and r["came"] == [("Handcraft Yarn 25g KEYROAD - Red / 25g", 10)]
      and shop.since_text(r).startswith("Since "), (r["sold"], r["came"]))
check("…the new item is added, the removed one kept and marked “Not in Shopify any more” (grey)",
      r["new"] == ["Notebook new"] and r["gone"] == ["Old thing"] and I.by_name("Old thing")["gone"]
      and iscr.InventoryScreen.status(I.by_name("Old thing")) == "Not in Shopify any more"
      and "gone" in S.tree.item(I.by_name("Old thing")["id"], "tags"))
rep = [x for x in gc.get_objects() if isinstance(x, iscr.LoadReport) and x.dlg.winfo_exists()][-1]
rep.dlg.geometry("+20+20"); pump(0.3)
window_shot.shot(rep.dlg, OUT / "load_report.png")
lines = shop.restock_lines(I)
check("On display 10, 6 sold: “Pen blue: bring 6 (on display 10, on the shelf 4)”",
      [t for _, _, _, t in lines] == ["Pen blue: bring 6 (on display 10, on the shelf 4)"], [t for _, _, _, t in lines])
check("…came in doesn't change the shelf (Yarn Red: shelf 4 of 4, storage 11)", I.get(yarn["id"])["shelf"] == 4
      and shop.storage(I.get(yarn["id"])) == 11)
check("…the Inventory screen says “Restock: 1 item”", S.restock_line.cget("text") == "Restock: 1 item")

# several days without restocking
day3 = export("day3.csv", {"pen": 11, "yarn_red": 15, "yarn_blue": 7, "pencil": 3, "dup1": 4, "dup2": 6, "neg": -2,
                            "notebook": 5})
S.load_shopify(str(day3)); pump(0.4)
check("two loads with no restock between: the shelf goes down twice, the list asks for the sum (bring 9)",
      [t for _, _, _, t in shop.restock_lines(I)] == ["Pen blue: bring 9 (on display 10, on the shelf 1)"],
      [t for _, _, _, t in shop.restock_lines(I)])
day4 = export("day4.csv", {"pen": 3, "yarn_red": 15, "yarn_blue": 7, "pencil": 3, "dup1": 4, "dup2": 6, "neg": -2,
                            "notebook": 5})
S.load_shopify(str(day4)); pump(0.4)
k = shop.restock_lines(I)
check("storage short: “Pen blue: bring 3, only 3 in storage” (yellow)",
      [(t, kind) for _, _, kind, t in k] == [("Pen blue: bring 3, only 3 in storage", "short")], k)
win = [x for x in gc.get_objects() if isinstance(x, iscr.RestockWindow) and x.dlg.winfo_exists()][-1]
win.dlg.geometry("+40+40"); pump(0.3)
window_shot.shot(win.dlg, OUT / "restock_list.png")
day5 = export("day5.csv", {"pen": 0, "yarn_red": 15, "yarn_blue": 7, "pencil": 3, "dup1": 4, "dup2": 6, "neg": -2,
                            "notebook": 5})
S.load_shopify(str(day5)); pump(0.4)
check("none in storage: “Order more” (red)", [kind for _, _, kind, _ in shop.restock_lines(I)] == ["order"]
      and "Order more" in shop.restock_lines(I)[0][3])
day6 = export("day6.csv", {"pen": 30, "yarn_red": 15, "yarn_blue": 7, "pencil": 3, "dup1": 4, "dup2": 6, "neg": -2,
                            "notebook": 5})
r = S.load_shopify(str(day6)); pump(0.4)
check("30 came in: the shelf stays 0, In storage goes up to 30", r["came"] == [("Pen blue", 30)]
      and I.get(pen["id"])["shelf"] == 0 and shop.storage(I.get(pen["id"])) == 30)
for x in [x for x in gc.get_objects() if isinstance(x, iscr.RestockWindow) and x.dlg.winfo_exists()]:
    x.dlg.destroy()
S.restock(); pump(0.3)
win = [x for x in gc.get_objects() if isinstance(x, iscr.RestockWindow) and x.dlg.winfo_exists()][-1]
RECEIPTS.clear()
pdfp = win.print_receipt(TMP / "restock.pdf")
a4 = win.save_pdf(str(TMP / "restock_a4.pdf"))
check("Print: the restock list goes to the receipt printer; the A4 PDF is made; the lines have no money",
      RECEIPTS and RECEIPTS[-1][1] == "XP-80C" and Path(a4).is_file()
      and all("EUR" not in line for line in win.lines()), win.lines())
win.done(pen["id"]); pump(0.2)
check("Restocked: the shelf is back to 10 and the line goes (logged)", I.get(pen["id"])["shelf"] == 10
      and not shop.restock_lines(I) and inv.read_log(pen["id"])[-1]["reason"] == "restocked 10 to the shelf")
win.dlg.destroy()

# ------------------------------------------------------------------ changing On display
shop.set_display(I, pen["id"], 15)
check("raised from 10 to 15 with a full shelf: asks for 5",
      [t for _, _, _, t in shop.restock_lines(I)] == ["Pen blue: bring 5 (on display 15, on the shelf 10)"])
shop.set_display(I, pen["id"], 8)
check("lowered to 8 with 10 on the shelf: the shelf is 8, nothing to restock",
      I.get(pen["id"])["shelf"] == 8 and not shop.restock_lines(I))
shop.set_display(I, pen["id"], None)
check("emptied: off the restock list", I.get(pen["id"]).get("display") is None and I.get(pen["id"]).get("shelf") is None)
shop.set_display(I, pen["id"], 10)

# ------------------------------------------------------------------ the same or an older file
before = json.dumps(I.data["items"], sort_keys=True)
ANSWER["yes"] = False
asked.clear()
res = S.load_shopify(str(day3)); pump(0.2)
check("an older file asks first (“This file is older than the last one loaded (…). Load it anyway?”); No changes nothing",
      res is None and asked and asked[0].startswith("This file is older than the last one loaded (")
      and json.dumps(I.data["items"], sort_keys=True) == before, asked)
asked.clear()
res = S.load_shopify(str(day6)); pump(0.2)
check("…the same file again asks too", res is None and asked and "older than the last one" in asked[0])
ANSWER["yes"] = True
check("ORCA's own linked paper item is still untouched after all the loads", I.get(paper["id"])["stock"] == 2500)
S.fill(); pump(0.3)
window_shot.shot(S.win, OUT / "inventory_table.png")
print(f"{sum(results)}/{len(results)} passed")
