"""Handoff 2026-11-19_11: categories filled by name, and low stock warnings. Temp copy of the folder layout; the real
Shopify export only read (copied to the temp folder); the receipt printer faked; pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import collections, csv, ctypes, gc, json, os, shutil, sys, time, tkinter as tk
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
import appicon, categories as C, driverprint, inventory as inv, inventory_screens as iscr, mainmenu, printing
import shopify_stock as shop, toners
from tkinter import messagebox, ttk
import window_shot

driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
RECEIPTS = []
printing.send = lambda pdf, queue, settings=None: RECEIPTS.append((str(pdf), queue))
toners.TIMEOUT = 0.2
messagebox.askyesno = lambda *a, **k: True
messagebox.showwarning = lambda *a, **k: None
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:600])


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2


def pump(secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.02)


def widgets(w, cls=None):
    out = [w] if cls is None or w.winfo_class() == cls else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


def close(*titles):
    for w in widgets(root):
        if isinstance(w, tk.Toplevel) and w.winfo_exists() and w.title() in titles:
            w.destroy()
    pump(0.2)


# ------------------------------------------------------------------ the real export with the starting rules
REAL = Path(str(helpers.REAL_SHOPIFY_EXPORT))
if not REAL.exists():  # Tesla's real export is read (a temp copy) only where it is; never part of the repo
    print("SKIPPED: the real Shopify export isn't on this PC (Downloads\inventory_export_1.csv)")
    root.destroy()
    sys.exit(0)
real = TMP / "inventory_export_1.csv"
shutil.copyfile(REAL, real)
I = inv.Inventory()
paper = I.add({"name": "Copy paper A4", "stock": 500, "link": {"kind": "paper", "name": "Smooth white 80 gsm", "size": "A4"}})
I.add({"name": "My own stapler", "category": "Office", "category_hand": True, "stock": 2})
menu.open_inventory(); pump(0.8)
S = [x for x in gc.get_objects() if isinstance(x, iscr.InventoryScreen) and x.win.winfo_exists()][-1]
S.win.geometry("1300x880+10+10"); pump(0.3)
I = S.inventory
S.load_shopify(str(real)); pump(1.0)
close("End of day: Shopify stock", "Restock", "Low stock")
by_title = {}
for it in I.items:
    if it.get("shopify_key"):
        by_title.setdefault(it["shopify_key"].split("|")[0], it.get("category") or "")
counts = collections.Counter(by_title.values())
check("the real export with the starting rules: 61 / 132 / 204 / 173 / 133 products, 1235 empty",
      (counts["Inks and toners"], counts["Diaries and calendars"], counts["School bags"], counts["Notebooks"],
       counts["Art supplies"], counts[""]) == (61, 132, 204, 173, 133, 1235), dict(counts))
spots = {"Pen Pastel Blue Ink BIC": "", "Ink 560 Black CANON": "Inks and toners", 'HP Notebook 250 G9 15.6"': "",
         "Gift Bag Pen Ballpoint with Notebook WELLINGTON": "", "To Imerologio Enos Spasikla #11 PSIXOGIOS": "",
         "Pencil Case Barell Puff STREET": "School bags", "Acrylic Sign Holder A4 Landscape KEJEA": ""}
got = {t: C.match(t, C.DEFAULT_RULES) for t in spots}
check("…the spot cases", got == spots, got)
check("…every Shopify item of a product has its product's category, from its title",
      all((it.get("category") or "") == C.match(it["shopify_title"], C.DEFAULT_RULES)
          for it in I.items if it.get("shopify_key")))
check("…ORCA's own linked item and a category set by hand are left alone",
      not I.get(paper["id"]).get("category") and I.by_name("My own stapler")["category"] == "Office")
check("…the rules are kept in inventory.json (the starting rules)", [r["name"] for r in I.data["category_rules"]]
      == ["Inks and toners", "Diaries and calendars", "School bags", "Notebooks", "Art supplies"])
S.category.set("Inks and toners"); S.fill(); pump(0.3)
window_shot.shot(S.win, OUT / "inventory_with_categories.png")
S.category.set("All"); S.fill()

# ------------------------------------------------------------------ set by hand
ink = next(it for it in I.items if it.get("category") == "Inks and toners")  # any ink or toner item
S.fill(select=ink["id"]); S.edit(); pump(0.2)
d = [x for x in gc.get_objects() if isinstance(x, iscr.ItemDialog) and x.dlg.winfo_exists()][-1]
d.vars["category"].set("Printer supplies"); d.done(); pump(0.2)
C.apply(I)
check("a category set by hand (Edit) survives Apply now", I.get(ink["id"])["category"] == "Printer supplies"
      and I.get(ink["id"])["category_hand"])
copy2 = FILES / "export_2.csv"
shutil.copyfile(real, copy2)
os.utime(copy2, (time.time() + 60, time.time() + 60))
S.load_shopify(str(copy2)); pump(1.0)
close("End of day: Shopify stock", "Restock", "Low stock")
check("…and the next load", I.get(ink["id"])["category"] == "Printer supplies")

# ------------------------------------------------------------------ the Categories… window
S.categories(); pump(0.4)
W = [x for x in gc.get_objects() if isinstance(x, iscr.CategoriesWindow) and x.dlg.winfo_exists()][-1]
check("Categories…: each rule with its name and how many items it gives; the empty count line",
      [W.list.item(i, "values")[0] for i in W.list.get_children()][:5] == [r["name"] for r in C.DEFAULT_RULES]
      and W.empty_line.cget("text").endswith("items have no category (click to see them)"), W.empty_line.cget("text"))
before_empty = len(W.empty)
W.add(); pump(0.2)
W.name_var.set("Pens"); W.words_var.set("pen, ballpoint"); pump(0.3)
preview = [W.preview.item(i, "values")[0] for i in W.preview.get_children()]
check("…a new rule “Pens: pen, ballpoint” shows its items live in the preview (and fewer have no category)",
      preview and all("pen" in C.tokens(n) or "ballpoint" in C.tokens(n) for n in preview[:20])
      and len(W.empty) < before_empty, (len(preview), preview[:3]))
W.dlg.geometry("+20+20"); pump(0.3)
window_shot.shot(W.dlg, OUT / "categories_window.png")
W.show_empty(); pump(0.2)
check("…clicking the count line shows the items with no category",
      len(W.preview.get_children()) == min(500, len(W.empty)))
W.apply(); pump(0.3)
pens = [it for it in I.items if it.get("category") == "Pens"]
check("…Apply now fills it", len(pens) > 50 and all(not it.get("category_hand") for it in pens), len(pens))
S.categories(); pump(0.3)
W = [x for x in gc.get_objects() if isinstance(x, iscr.CategoriesWindow) and x.dlg.winfo_exists()][-1]
W.list.selection_set("5"); W.picked(); W.name_var.set("Pens and markers"); W.apply(); pump(0.3)
check("a renamed category carries over to its items", len([it for it in I.items if it.get("category") == "Pens and markers"])
      == len(pens) and not [it for it in I.items if it.get("category") == "Pens"])
S.categories(); pump(0.3)
W = [x for x in gc.get_objects() if isinstance(x, iscr.CategoriesWindow) and x.dlg.winfo_exists()][-1]
W.list.selection_set("0"); W.picked(); W.remove(); W.apply(); pump(0.3)
check("removing a rule (Inks and toners) empties its items, except those set by hand",
      not [it for it in I.items if it.get("category") == "Inks and toners"]
      and I.get(ink["id"])["category"] == "Printer supplies")
before = json.dumps(I.data, sort_keys=True)
S.categories(); pump(0.3)
W = [x for x in gc.get_objects() if isinstance(x, iscr.CategoriesWindow) and x.dlg.winfo_exists()][-1]
W.add(); W.name_var.set("Junk"); W.words_var.set("a"); W.dlg.destroy(); pump(0.2)
check("Cancel changes nothing", json.dumps(I.data, sort_keys=True) == before)

# ------------------------------------------------------------------ low stock
pen = next(it for it in I.items if it.get("shopify_title") == "Pen Pastel Blue Ink BIC")
I.get(pen["id"])["stock"] = 16
I.save()
shop.set_display(I, pen["id"], 10)
S.reload()
menu.show_sync(); pump(0.2)
check("on display 10 with 6 in storage: “Low: 6 in storage” (yellow) and the menu dot",
      iscr.InventoryScreen.status(I.get(pen["id"])) == "Low: 6 in storage"
      and "lowish" in S.tree.item(pen["id"], "tags") and bool(menu.inventory_dot.place_info()))
I.get(pen["id"])["stock"] = 20; I.save(); S.reload()
check("…10 in storage clears it", iscr.InventoryScreen.status(I.get(pen["id"])) == ""
      and pen["id"] not in [it["id"] for it in I.low_stock()])
I.get(pen["id"])["stock"] = 16; I.save(); S.reload()
S.category.set("School bags"); S.tree.selection_set(()); S.minimum(); pump(0.2)
md = [x for x in gc.get_objects() if isinstance(x, iscr.MinimumDialog) and x.dlg.winfo_exists()][-1]
md.var.set("3"); md.done(); pump(0.2)
bags = [it for it in I.items if it.get("category") == "School bags"]
check("Minimum… on a category (the filter): every item in it gets 3, logged",
      bags and all(it.get("minimum") == 3 for it in bags)
      and inv.read_log(bags[0]["id"])[-1]["reason"] == "minimum - -> 3", len(bags))
S.category.set("All"); S.fill()
sel = [it["id"] for it in I.items if it.get("category") == "Notebooks"][:2]
S.tree.selection_set(sel); S.minimum(); pump(0.2)
md = [x for x in gc.get_objects() if isinstance(x, iscr.MinimumDialog) and x.dlg.winfo_exists()][-1]
md.var.set("5"); md.done(); pump(0.2)
check("…and on selected rows", all(I.get(i)["minimum"] == 5 for i in sel))
S.low_stock(); pump(0.4)
L = [x for x in gc.get_objects() if isinstance(x, iscr.LowStockWindow) and x.dlg.winfo_exists()][-1]
whys = [L.tree.item(i, "values")[-1] for i in L.tree.get_children()]
check("the Low stock list: “Order more” and “Low” items, by category then name",
      "Order more" in whys and "Low: 6 in storage" in whys and S.low_btn.cget("text") == f"Low stock ({len(whys)})",
      (len(whys), S.low_btn.cget("text")))
L.dlg.geometry("+30+30"); pump(0.3)
window_shot.shot(L.dlg, OUT / "low_stock_list.png")
RECEIPTS.clear()
L.print_receipt(TMP / "low.pdf")
pdf = L.save_pdf(str(TMP / "low_a4.pdf"))
check("…printed to the XP-80C and saved as a PDF, with no money", RECEIPTS and RECEIPTS[-1][1] == "XP-80C"
      and Path(pdf).is_file() and not any("EUR" in line for line in L.lines()))
L.dlg.destroy()
copy3 = FILES / "export_3.csv"
shutil.copyfile(real, copy3)
os.utime(copy3, (time.time() + 120, time.time() + 120))
S.load_shopify(str(copy3)); pump(1.2)
check("…it opens by itself after a load when something is low",
      [x for x in gc.get_objects() if isinstance(x, iscr.LowStockWindow) and x.dlg.winfo_exists()])
print(f"{sum(results)}/{len(results)} passed")
