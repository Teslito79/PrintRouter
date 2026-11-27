"""Handoff 2026-11-19_03: Inventory management. Temp copy of the folder layout; the scanner is simulated as fast
key presses + Enter; the receipt printer faked; pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import csv, ctypes, json, os, shutil, sys, time, tkinter as tk, zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape

ctypes.windll.shcore.SetProcessDpiAwareness(1)
APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); sys.path.insert(0, str(Path(__file__).parent)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
ADMIN = TMP / "ORCA" / "ADMIN"
ADMIN.mkdir(parents=True); OUT.mkdir(parents=True, exist_ok=True)
for f in ("prices.json", "icon.ico"):
    shutil.copyfile(APP / f, ADMIN / f)
import price_sheet as ps
ps.test_sheet(helpers.PRICE_TEMPLATE, ADMIN / "Walk-in_Prices.xlsx")
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, copy_counter as cc, driverprint, inventory as inv, inventory_screens as iscr, mainmenu, printing
import toners, walkin_orders as wo, walkin_prices as wp, walkin_pricing as P, walkin_screens as ws
from tkinter import messagebox, ttk
import window_shot

driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
RECEIPTS = []
printing.send = lambda pdf, queue, settings=None: RECEIPTS.append((str(pdf), queue))
toners.TIMEOUT = 0.2
asked, warned = [], []
ANSWER = {"yes": True}
messagebox.askyesno = lambda *a, **k: asked.append(k.get("message")) or ANSWER["yes"]
messagebox.showwarning = lambda *a, **k: warned.append(k.get("message"))
PASSWORD = {"ok": False}
iscr.ask_password = lambda parent: PASSWORD["ok"]
ws.ask_keep = lambda parent: True
ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:600])


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2


def pump(secs=0.3, until=None):
    end = time.time() + secs
    while time.time() < end and not (until and until()):
        root.update(); time.sleep(0.02)


def widgets(w, cls=None):
    out = [w] if cls is None or w.winfo_class() == cls else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


def scan(catcher, code, widget):
    """A USB scanner: the code's keys a few milliseconds apart, then Enter."""
    for ch in code:
        catcher.key(SimpleNamespace(widget=widget, char=ch, keysym=ch))
        time.sleep(0.005)
    return catcher.key(SimpleNamespace(widget=widget, char="\r", keysym="Return"))


buttons = [b.cget("text") for b in widgets(menu.win, "TButton")]
check("menu (19_08 order): “Inventory management” second, Data third, Settings last",
      buttons[:7] == ["Walk-in", "Inventory management", "Data", "PrintHub", "Counter", "Prices", "Settings"],
      buttons)

# ------------------------------------------------------------------ items
menu.open_inventory(); pump(0.6)
import gc
S = [x for x in gc.get_objects() if isinstance(x, iscr.InventoryScreen) and x.win.winfo_exists()][-1]
S.win.geometry("1300x900+10+10"); pump(0.3)
I = S.inventory


def add(**kw):
    S.add(); pump(0.1)
    d = [x for x in gc.get_objects() if isinstance(x, iscr.ItemDialog) and x.dlg.winfo_exists()][-1]
    for k, v in kw.items():
        d.vars[k].set(v)
    d.done(); pump(0.1)
    return d


d = add(name="Pen blue", category="Pens", barcodes="5201234000011", stock="40", minimum="10")
pen = I.by_name("Pen blue")
check("Add item: kept with its barcode, stock and minimum", pen and pen["barcodes"] == ["5201234000011"]
      and pen["stock"] == 40 and pen["minimum"] == 10 and not d.dlg.winfo_exists(), pen)
d = add(name="Pen red", barcodes="5201234000011")
check("a barcode can't belong to two items", I.by_name("Pen red") is None and "belongs to “Pen blue”" in d.error.cget("text"),
      d.error.cget("text"))
d.dlg.destroy()
d = add(name="Pen red", barcodes="5201234000028", price="1.20")
check("a sale price is refused without the Prices password",
      I.by_name("Pen red") is None and "Prices password" in d.error.cget("text"), d.error.cget("text"))
PASSWORD["ok"] = True
d.unlock(); d.done(); pump(0.1)
check("…and works with it", I.by_name("Pen red") and I.by_name("Pen red")["price"] == 1.2)
S.fill(select=pen["id"]); S.edit(); pump(0.1)
d = [x for x in gc.get_objects() if isinstance(x, iscr.ItemDialog) and x.dlg.winfo_exists()][-1]
d.vars["price"].set("0.90"); d.vars["category"].set("Writing"); d.done(); pump(0.1)
pen = I.get(pen["id"])
check("Edit: changes kept (the price with the password given on this screen)", pen["price"] == 0.9 and pen["category"] == "Writing")
add(name="Notebook A5", barcodes="5201234000035", stock="12", price="2.50")
add(name="Folder", barcodes="5201234000042", stock="3", minimum="5", price="0.60")
silk = add(name="Silk 250 A4 ream", category="Paper", unit="ream", per_unit="125", stock="500",
           link=inv.link_text({"kind": "paper", "name": "Silk 250 gsm", "size": "A4"}))
lam = add(name="Pouches A4", category="Finishing", unit="box", per_unit="100", stock="300",
          link=inv.link_text({"kind": "lamination", "size": "A4"}))
smooth = add(name="Copy paper A4", category="Paper", unit="ream", per_unit="500", stock="2620",
             link=inv.link_text({"kind": "paper", "name": "Smooth white 80 gsm", "size": "A4"}))
check("“500 per ream” shows as reams + sheets (2620 sheets: “5 reams + 120 sheets”)",
      inv.qty_text(I.by_name("Copy paper A4")) == "5 reams + 120 sheets", inv.qty_text(I.by_name("Copy paper A4")))
PASSWORD["ok"] = False
S.prices_open = False
S.fill(select=I.by_name("Pen red")["id"])
S.remove(); pump(0.1)
check("Remove needs the Prices password", I.by_name("Pen red") is not None)
PASSWORD["ok"] = True
asked.clear()
n_log = len(inv.read_log())
S.remove(); pump(0.1)
check("…with it, asks once and removes; the log lines stay", I.by_name("Pen red") is None and len(asked) == 1
      and len(inv.read_log()) == n_log, (asked, I.by_name("Pen red") is None))  # nothing taken out of the log

# ------------------------------------------------------------------ scanning on the Inventory screen
S.fill(select=I.by_name("Folder")["id"])
scan(S.scan, "5201234000011", S.tree); pump(0.2)
check("a scan anywhere on the screen selects the item", S.tree.selection() == (I.by_name("Pen blue")["id"],),
      S.tree.selection())
asked.clear()
scan(S.scan, "5209999999999", S.tree); pump(0.2)
d = [x for x in gc.get_objects() if isinstance(x, iscr.ItemDialog) and x.dlg.winfo_exists()]
check("an unknown code asks “No item with barcode 5209999999999. Add a new item with it?” and offers it",
      asked == ["No item with barcode 5209999999999. Add a new item with it?"] and d
      and d[-1].vars["barcodes"].get() == "5209999999999", asked)
d[-1].dlg.destroy()
slow = []
S.scan.on_scan = lambda c: slow.append(c)
for ch in "1234":
    S.scan.key(SimpleNamespace(widget=S.tree, char=ch, keysym=ch)); time.sleep(0.15)
S.scan.key(SimpleNamespace(widget=S.tree, char="\r", keysym="Return"))
check("a person typing slowly isn't a scan", not slow)
S.scan.on_scan = S.scanned

# ------------------------------------------------------------------ Delivery / Used / Count, minimum
nb = I.by_name("Notebook A5")
S.fill(select=nb["id"]); S.delivery(); pump(0.1)
q = [x for x in gc.get_objects() if isinstance(x, iscr.QtyDialog) and x.dlg.winfo_exists()][-1]
q.units.set("8"); scan(q.scan, "5201234000035", q.dlg); q.done(); pump(0.1)
check("Delivery: 8 typed + 1 scanned = 9 more (12 -> 21)", I.by_name("Notebook A5")["stock"] == 21)
S.used(); pump(0.1)
q = [x for x in gc.get_objects() if isinstance(x, iscr.QtyDialog) and x.dlg.winfo_exists()][-1]
q.units.set("2"); q.reason.set("broken"); q.done(); pump(0.1)
S.count(); pump(0.1)
q = [x for x in gc.get_objects() if isinstance(x, iscr.QtyDialog) and x.dlg.winfo_exists()][-1]
q.units.set("17"); q.done(); pump(0.1)
lines = [(r["change"], r["stock"], r["reason"]) for r in inv.read_log(nb["id"])]
check("Used / broken and Count: the stock is right and the log has the lines (Count logs the difference)",
      I.by_name("Notebook A5")["stock"] == 17 and lines == [("+12", "12", "added"), ("+9", "21", "delivery"),
                                                           ("-2", "19", "broken"), ("-2", "17", "count")], lines)
S.history(); pump(0.2)
for w in root.winfo_children():
    for x in widgets(w):
        if isinstance(x, tk.Toplevel) and x.title().startswith("History"):
            x.destroy()
menu.show_sync(); pump(0.1)
folder = I.by_name("Folder")
S.fill()
check("below its minimum: “Order more” in the table (first), and the menu's red dot",
      S.tree.get_children()[0] == folder["id"] and S.tree.item(folder["id"], "values")[-1] == "Order more"
      and bool(menu.inventory_dot.place_info()), S.tree.item(folder["id"], "values"))  # status: the last column (19_09)
window_shot.shot(S.win, OUT / "inventory_order_more.png")
S.fill(select=folder["id"]); S.delivery(); pump(0.1)
q = [x for x in gc.get_objects() if isinstance(x, iscr.QtyDialog) and x.dlg.winfo_exists()][-1]
q.units.set("10"); q.done(); pump(0.1)
menu.show_sync(); pump(0.1)
check("…above it again: both go away", S.tree.item(folder["id"], "values")[6] == "" and not menu.inventory_dot.winfo_ismapped())

# ------------------------------------------------------------------ Sell
S.sell(); pump(0.6)
L = [x for x in gc.get_objects() if isinstance(x, iscr.SellScreen) and x.win.winfo_exists()][-1]
L.win.geometry("1100x860+10+10"); pump(0.2)
scan(L.scan, "5201234000011", L.entry); scan(L.scan, "5201234000011", L.entry); pump(0.1)
check("Sell: a scan adds the item; twice gives quantity 2", L.basket == [{"id": I.by_name("Pen blue")["id"], "qty": 2}])
L.entry_var.set("Notebook"); L.add_typed(); L.entry_var.set("Folder"); L.add_typed(); pump(0.1)
L.entry_var.set("Silk 250 A4 ream"); L.add_typed(); pump(0.1)
check("…search by name adds; an item with no sale price can't be added",
      len(L.basket) == 3 and "no sale price" in L.message.cget("text"), L.message.cget("text"))
rows, total, due = L.priced()
check("…the total from each item's sale price: 2 x 0.90 + 2.50 + 0.60 = 4.90", total == 4.9, total)
L.set_rounding("up5"); pump(0.1)
window_shot.shot(L.win, OUT / "sell_basket.png")
pdf = L.print_receipt(TMP / "sale.pdf")
header, rws, tot = L.receipt_rows(False)
check("Print receipt: the lines, no money with walkin_paper_prices false (XP-80C)",
      RECEIPTS and RECEIPTS[-1][1] == "XP-80C" and Path(pdf).is_file()
      and [r[0] for r in rws] == ["Pen blue x 2", "Notebook A5 x 1", "Folder x 1"] and all(r[1] == "" for r in rws)
      and tot is None, rws)
before = {n: I.by_name(n)["stock"] for n in ("Pen blue", "Notebook A5", "Folder")}
k = len(wo.read_sales())
L.done(); pump(0.1)
after = {n: inv.Inventory().by_name(n)["stock"] for n in before}
sale = wo.read_sales()[-1]
check("Done: stock goes down, a sales_log line with source shop and the rounded total, the basket cleared",
      after == {"Pen blue": before["Pen blue"] - 2, "Notebook A5": before["Notebook A5"] - 1, "Folder": before["Folder"] - 1}
      and sale["source"] == "shop" and sale["paid"] == "5.00" and sale["items"] == "Pen blue x 2; Notebook A5 x 1; Folder x 1"
      and len(wo.read_sales()) == k + 1 and L.basket == [], (after, sale))
check("…the log says sold, with the sale number",
      any(r["reason"] == "sold" and r["sale"] == sale["order"] for r in inv.read_log()), sale["order"])
L.entry_var.set("Folder"); L.add_typed(); asked.clear()
s1 = inv.Inventory().by_name("Folder")["stock"]
L.cancel(); pump(0.1)
check("Cancel asks, empties the basket and changes nothing", asked == ["Empty the basket?"] and not L.basket
      and inv.Inventory().by_name("Folder")["stock"] == s1)
for _ in range(20):
    L.entry_var.set("Folder"); L.add_typed()
L.show_basket(); pump(0.1)
check("selling more than is in stock is allowed; the item turns red, “count it”",
      any("count it" in x.cget("text") for x in widgets(L.lines.inner, "TLabel")))
L.done(); pump(0.1)
check("…and goes below 0 (shown “Count it” in Inventory)", inv.Inventory().by_name("Folder")["stock"] < 0
      and iscr.InventoryScreen.status(inv.Inventory().by_name("Folder")) == "Count it")
L.back(); pump(0.4)

# ------------------------------------------------------------------ linked paper
I = inv.Inventory()
doc = {"kind": "document", "size": "A4", "pages": 32, "copies": 1, "color": "color", "color_pages": "", "sides": "single",
       "per_side": 1, "paper": "Silk 250 gsm", "finish": "none", "lam": True, "lam_sheets": 4, "cuts": 0}
c = wo.Customers().resolve("Stock Test", "99 000 111", "", 0)
o = wo.place([doc], P.price_order(wp.current(), [doc]), dict(c, entered_name="Stock Test", entered_phone="99 000 111"),
             "quote", None)
o = wo.load_order(o["_folder"])
o["parts"] = {"C4510": {"items": [0], "cover": True, "state": "printing", "sent": [], "fronts": []}}
wo.save_order(o)
run = menu.print_queue
run.copiers["C4510"] = {"state": "sent", "orders": [o["number"]]}
silk0, lam0 = I.by_name("Silk 250 A4 ream")["stock"], I.by_name("Pouches A4")["stock"]
run.collected("C4510"); pump(0.2)
I = inv.Inventory()
check("a walk-in order with 32 Silk 250 A4 sheets takes 32 at Pages collected",
      I.by_name("Silk 250 A4 ream")["stock"] == silk0 - 32, (silk0, I.by_name("Silk 250 A4 ream")["stock"]))
o2 = wo.load_order(o["_folder"])
again = inv.take_for_part(o2, "C4510", o2["parts"]["C4510"])
check("…once, even after a restart (the order remembers it)", again == []
      and inv.Inventory().by_name("Silk 250 A4 ream")["stock"] == silk0 - 32, o2.get("stock_taken"))
check("…the lamination isn't taken yet", inv.Inventory().by_name("Pouches A4")["stock"] == lam0)
OS = ws.OrdersScreen(menu, on_back=lambda: None); pump(1)
OS.finish(wo.load_order(o["_folder"]), False); pump(0.3)
check("lamination is taken at Collected (4 sheets)", inv.Inventory().by_name("Pouches A4")["stock"] == lam0 - 4)
OS.win.destroy()
CM = menu.copy_counter
CM.read_func = lambda pid: {"how": "total", "total": 100}
cnt = CM.start("C3000")
CM.read_func = lambda pid: {"how": "total", "total": 112}
cnt.poll()
cc.STABLE_SECONDS = 0
cnt.finish(sleep=lambda s: None, clock=lambda: 0)
cnt.set_split("A4", True, "Silk 250 gsm"); cnt.set_row("A4", 1, sheets=5)
smooth0 = inv.Inventory().by_name("Copy paper A4")["stock"]
silk1 = inv.Inventory().by_name("Silk 250 A4 ream")["stock"]
CM.done("C3000")
I = inv.Inventory()
check("the copy counter's Done takes the papers given at Finish (7 Smooth white 80, 5 Silk 250)",
      I.by_name("Copy paper A4")["stock"] == smooth0 - 7 and I.by_name("Silk 250 A4 ream")["stock"] == silk1 - 5)
check("a paper with no linked item changes nothing (Gloss 130 used nowhere in Inventory)",
      inv.Inventory().take([(("paper", "Gloss 130 gsm", "A4"), 10)], "order #999") == [])


# ------------------------------------------------------------------ import
def make_xlsx(path, sheets):
    """A small .xlsx with inline strings (as Excel and LibreOffice save them, read by walkin_prices.read_xlsx)."""
    def col(i):
        return chr(65 + i)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/></Types>')
        rels = "".join(f'<Relationship Id="r{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                       f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + rels + "</Relationships>")
        names = "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="r{i}"/>' for i, n in enumerate(sheets, start=1))
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + names + "</sheets></workbook>")
        for i, rows in enumerate(sheets.values(), start=1):
            data = ""
            for r, row in enumerate(rows, start=1):
                cells = ""
                for c, v in enumerate(row):
                    if v is None or v == "":
                        continue
                    ref = f"{col(c)}{r}"
                    cells += (f'<c r="{ref}"><v>{v}</v></c>' if isinstance(v, (int, float))
                              else f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>')
                data += f'<row r="{r}">{cells}</row>'
            z.writestr(f"xl/worksheets/sheet{i}.xml", '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
                       'spreadsheetml/2006/main"><sheetData>' + data + "</sheetData></worksheet>")


xlsx = TMP / "stock.xlsx"
make_xlsx(xlsx, {"Notes": [["nothing here"]],
                 "Items": [["Barcode", "Τιμή", "Name", "In stock", "Category", "Min"],
                           [5201234000011, 0.95, "Pen blue", 60, "Writing", 10],
                           [5201234000059, 3.5, "Stapler", 4, "Office", 2],
                           ["", "", "", "", "", ""],
                           [5201234000066, "abc", "Glue stick", 10, "Office", ""],
                           [5201234000073, 1.0, "", 5, "", ""],
                           [5201234000080, 2.0, "Tape", 7, "Office", ""],
                           [5201234000080, 2.0, "Tape wide", 7, "Office", ""]]})
S2 = [x for x in gc.get_objects() if isinstance(x, iscr.InventoryScreen) and x.win.winfo_exists()][-1]
S2.reload()
PASSWORD["ok"] = True
S2.prices_open = False
asked.clear()
dlg = iscr.ImportDialog(S2, xlsx); pump(0.2)
dlg.sheet.set("Items"); dlg.sheet_changed(); pump(0.2)
cols = dlg.columns()
check("Import xlsx: the sheet picked, the columns guessed from the headings (one in Greek: Τιμή = price)",
      cols == {"name": 2, "barcode": 0, "category": 4, "unit": None, "stock": 3, "minimum": 5, "price": 1, "display": None}, cols)  # On display (19_09)
dlg.dlg.update(); dlg.dlg.geometry("+20+20"); pump(0.2)
window_shot.shot(dlg.dlg, OUT / "import_column_picker.png")
new, upd, bad = dlg.plan
check("…preview: 2 new, 1 already there, bad rows listed (text price, no name, a barcode used twice)",
      [n["name"] for n in new] == ["Stapler", "Tape"] and [u[1]["name"] for u in upd] == ["Pen blue"]
      and len(bad) == 3 and any("Sale price" in b for b in bad) and any("no name" in b for b in bad)
      and any("used twice" in b for b in bad), (new, upd, bad))
dlg.do(); pump(0.2)
I = inv.Inventory()
check("…asks once to update, then adds the new and updates the one there (stock and price; logged as import)",
      asked == ["1 items are already in Inventory: update them?"] and I.by_name("Stapler")["price"] == 3.5
      and I.by_name("Pen blue")["price"] == 0.95 and I.by_name("Pen blue")["stock"] == 60
      and any(r["reason"] == "import" and r["name"] == "Pen blue" for r in inv.read_log()), asked)
csvf = TMP / "stock.csv"
csvf.write_text("Κωδικός;Όνομα;Ποσότητα;Price\n5201234000097;Eraser;30;0,40\n5201234000059;Stapler;6;3,50\n;;;\n",
                encoding="utf-8-sig")
PASSWORD["ok"] = False
S2.prices_open = False
dlg = iscr.ImportDialog(S2, csvf); pump(0.2)
check("Import csv (semicolons, Greek headings): columns guessed",
      dlg.columns() == {"name": 1, "barcode": 0, "category": None, "unit": None, "stock": 2, "minimum": None, "price": 3, "display": None},
      dlg.columns())
dlg.do(); pump(0.2)
I = inv.Inventory()
check("…without the Prices password the prices are left out, the rest is imported",
      I.by_name("Eraser") and I.by_name("Eraser").get("price") is None and I.by_name("Stapler")["stock"] == 6
      and "sale prices left out" in S2.message.cget("text"), S2.message.cget("text"))
export = TMP / "export.csv"
iscr.export_csv(I, export)
check("Export list: a CSV of the table", "Eraser" in export.read_text(encoding="utf-8-sig"))
print(f"{sum(results)}/{len(results)} passed")
