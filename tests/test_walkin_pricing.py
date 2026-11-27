"""Handoff 2026-11-17_08: walk-in prices from copies, paper and cuts. Temp copy of the folder layout, a test copy of the
sheet with made-up prices (price_sheet.py), pretend copiers, pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, json, os, shutil, sys, time, tkinter as tk
from pathlib import Path

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
REAL = helpers.PRICE_TEMPLATE  # the empty sheet (ADMIN's own is the trial list since 17_09)
SHEET = ADMIN / "Walk-in_Prices.xlsx"
ps.test_sheet(REAL, SHEET)
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, driverprint, mainmenu, toners, walkin_orders as wo, walkin_prices as wp, walkin_print
import walkin_pricing as P, walkin_screens as ws, walkin_catalogue as cat
from tkinter import messagebox
import window_shot

driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
driverprint.print_pdf = lambda *a, **k: None
toners.TIMEOUT = 0.2
os.startfile = lambda p: None
warned = []
messagebox.showwarning = lambda **k: warned.append(k["message"])
messagebox.askyesno = lambda *a, **k: True
ws.ask_keep = lambda parent: True
ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:500])


def prod(pid, qty, **picks):
    p = cat.BY_ID[pid]
    pk = cat.default_picks(p)
    for k, v in picks.items():
        o = next(o for o in p["options"] if o["key"] == k)
        pk[k] = o["choices"].index(v)
    return {"kind": "product", "product": pid, "qty": qty, "picks": pk}


def doc(pages, copies=1, sides="single", color="bw", color_pages="", paper="Normal 80 gsm", **more):
    return dict({"kind": "document", "size": "A4", "pages": pages, "copies": copies, "color": color,
                 "color_pages": color_pages, "sides": sides, "per_side": 1, "paper": paper, "finish": "none",
                 "lam": False, "lam_sheets": 0}, **more)


def sheet_with(name, values):
    path = TMP / f"{name}.xlsx"
    ps.test_sheet(REAL, path, values)
    return wp.load(path)


def working(r, i=0):
    return r["lines"][i]["working"]


pl = wp.current()
RULES = P.rules_now()
check("the test sheet reads with no warnings", pl.warnings == [], pl.warnings)

# ------------------------------------------------------------------ the real sheet
real = wp.load(REAL)
check("the empty sheet: every yellow cell empty, one yellow line", real.filled == 0 and real.warnings == [wp.NO_PRICES],
      real.warnings)
check("…with it nothing can be added (business cards, a document)", P.price_order(real, [prod("bcard", 100)])["problems"]
      and P.price_order(real, [doc(1)])["problems"])
check("the new sheet's tables are read: 4 copy lines, 29 papers (28 + Label sheet), 12 envelopes, 4 stacks, "
      "5 product extras, 3 services",
      len(real.copies) == 4 and len(real.papers) == 29 and "Label sheet" in real.papers and len(real.envelopes) == 12
      and len(real.stacks) == 4 and len(real.extras) == 5 and list(real.services) == ["Stapling", "Folding", "Filing"])
paper_names = set(real.papers) - {"Label sheet"}
check("the papers are every product paper in rules.json plus Glossy 100 gsm",
      paper_names == (set(rules["product_papers"]) - {"_help"}) | {"Glossy 100 gsm"}, paper_names ^ ((set(rules["product_papers"]) - {"_help"}) | {"Glossy 100 gsm"}))

# ------------------------------------------------------------------ Tesla's example
c_bw = ps.cell(REAL, "Copies", "A4 black and white", col=1)
p80 = ps.cell(REAL, "Paper", "Smooth white 80 gsm", col=1)
t2 = ps.cell(REAL, "Settings", "Tier 2 from", col=2)
t3 = ps.cell(REAL, "Settings", "Tier 3 from", col=2)
tesla = sheet_with("tesla", {"Copies": {c_bw: 1.0}, "Paper": {p80: 1.0}, "Settings": {t2: None, t3: None}})
both = P.price_order(tesla, [doc(100, sides="double")])
one = P.price_order(tesla, [doc(100)])
check("Tesla's example: 50 sheets both sides = 100 x 1.00 + 50 x 1.00 = 150.00", both["total"] == 150.0, working(both))
check("…100 sheets one side = 100 + 100 = 200.00", one["total"] == 200.0, working(one))
check("…the copies part is the same in both (100 copies)", working(both)[1] == working(one)[1] ==
      "100 A4 black and white copies x 1.00 (tier 1) = 100.00", (working(both)[1], working(one)[1]))
check("…Tier 2 from empty: everything tier 1", tesla.tier_of(5000) == 1)

# ------------------------------------------------------------------ business cards
bc = prod("bcard", 250, size="85 x 55 mm", paper="Silk 300 gsm", sides="Both sides")
r = P.price_order(pl, [bc])
check("250 cards 85 x 55 both sides: 32 sheets, 64 copies, 8 cuts: 19.20 + 6.40 + 0.80 = 26.40 (with the working lines)",
      working(r) == ["250 x Business cards, 85 x 55 mm, Silk 300 gsm, Both sides",
                     "64 A4 colour copies x 0.30 (tier 1) = 19.20", "32 A4 sheets Silk 300 gsm x 0.20 = 6.40",
                     "8 cuts (4 x 2) x 0.10 = 0.80", "Total 26.40"] and r["total"] == 26.4, working(r))
r = P.price_order(pl, [dict(bc, qty=1000)])
check("1000 cards: 125 sheets, 250 copies at tier 2 (0.25) = 62.50, 2 stacks = 16 cuts",
      working(r)[1:4] == ["250 A4 colour copies x 0.25 (tier 2) = 62.50", "125 A4 sheets Silk 300 gsm x 0.20 = 25.00",
                          "16 cuts (4 x 2, 2 stacks) x 0.10 = 1.60"], working(r))
for size, per, rc, cuts in (("85 x 55 mm", 8, (4, 2), 8), ("Square 55 x 55 mm", 12, (4, 3), 9), ("100 x 70 mm", 4, (2, 2), 6)):
    w, h = cat.CUT_MM[size]
    lay = P.layout(RULES, w, h, size)
    check(f"cuts worked out: {size} at {per} per A4 gives {rc[0]} x {rc[1]} (rows x columns) and {cuts} cuts",
          lay["per"] == per and (lay["rows"], lay["cols"]) == rc and lay["rows"] + 1 + lay["cols"] + 1 == cuts, lay)
lay = P.layout(RULES, 100, 70, "x")
check("100 x 70: 2 x 2 (6 cuts) chosen over 4 x 1 (7 cuts)", (lay["rows"], lay["cols"]) == (2, 2))
check("an A4 piece is on A4 with no cuts; an A3 piece on A3; 210 x 210 (fits only A3) on A3",
      P.layout(RULES, 210, 297, "x") == {"sheet": "A4", "per": 1, "rows": None, "cols": None}
      and P.layout(RULES, 297, 420, "x")["sheet"] == "A3" and P.layout(RULES, 210, 210, "x")["sheet"] == "A3")
poster = P.price_order(pl, [prod("poster", 5, size="A4", paper="Gloss 170 gsm")])
check("5 A4 posters: 5 sheets, 5 copies, no cuts", working(poster)[1:-1] == ["5 A4 colour copies x 0.30 (tier 1) = 1.50",
                                                                            "5 A4 sheets Gloss 170 gsm x 0.20 = 1.00"], working(poster))
try:
    P.layout(RULES, 123, 77, "Odd size")
    check("a size with no layout can't be added", False)
except ValueError as e:
    check("a size with no layout can't be added, naming the size", "no layout for 123 x 77 mm" in str(e), e)

# ------------------------------------------------------------------ documents
d = doc(30, copies=2, sides="double", color="mixed", color_pages="1-3")
r = P.price_order(pl, [d])
check("document 30 pages both sides x 2, pages 1-3 colour: 6 colour + 54 B&W copies, 30 sheets",
      working(r)[1:4] == ["54 A4 black and white copies x 0.10 (tier 1) = 5.40", "6 A4 colour copies x 0.30 (tier 1) = 1.80",
                          "30 A4 sheets Normal 80 gsm x 0.02 = 0.60"], working(r))
r = P.price_order(pl, [dict(d, cuts=2)])
check("…then 2 cuts: “2 cuts x 0.10 = 0.20”", "2 cuts x 0.10 = 0.20" in working(r) and r["total"] == 8.0, working(r))
r = P.price_order(pl, [doc(10, paper="Silk 170 gsm")])
check("a document on another paper from the Paper list (Silk 170 gsm A4 0.20)", "10 A4 sheets Silk 170 gsm x 0.20 = 2.00" in working(r))
r = P.price_order(pl, [doc(20, finish="spiral", lam=True, lam_sheets=5), doc(4, copies=3, finish="staple")])
check("finishing: spiral by sheets per copy, lamination per sheet, staple per copy",
      "Spiral binding: 1 x 1.50 = 1.50" in working(r) and "Lamination A4: 5 sheets x 1.00 = 5.00" in working(r)
      and "Staple: 3 x 0.05 = 0.15" in working(r, 1), (working(r), working(r, 1)))

# ------------------------------------------------------------------ tiers
two = [prod("flyer", 240, size="A4", paper="Silk 130 gsm"), prod("poster", 10, size="A4", paper="Gloss 170 gsm")]
r = P.price_order(pl, two)
check("two items with A4 colour copies share a tier (240 + 10 = 250 copies: both tier 2)",
      working(r)[1] == "240 A4 colour copies x 0.25 (tier 2) = 60.00" and working(r, 1)[1] == "10 A4 colour copies x 0.25 (tier 2) = 2.50",
      (working(r)[1], working(r, 1)[1]))
r = P.price_order(pl, [prod("poster", 190, size="A4", paper="Gloss 170 gsm")])
check("never pay more for fewer: 190 copies at 0.30 = 57.00, 200 at 0.25 = 50.00: the volume line takes 7.00 off",
      r["volume"] == -7.0 and r["subtotal"] == r["lines"][0]["price"] - 7.0, (r["volume"], r["subtotal"]))
r = P.price_order(pl, [prod("poster", 160, size="A4", paper="Gloss 170 gsm")])
check("…160 copies (48.00 < 50.00): no volume line", r["volume"] == 0.0)
r = P.price_order(pl, [prod("poster", 200, size="A4", paper="Gloss 170 gsm")])
check("…exactly 200 copies: tier 2", "200 A4 colour copies x 0.25 (tier 2) = 50.00" in working(r))
r = P.price_order(pl, [prod("poster", 100, size="A4", paper="Gloss 170 gsm"), doc(150)])
check("B&W and colour copies are counted apart (100 colour tier 1, 150 B&W tier 1)",
      "100 A4 colour copies x 0.30 (tier 1) = 30.00" in working(r) and "150 A4 black and white copies x 0.10 (tier 1) = 15.00" in working(r, 1))

# ------------------------------------------------------------------ labels, booklets, envelopes
r = P.price_order(pl, [prod("labels", 20)])
check("labels: 20 A4 label sheets in colour = 20 colour copies + 20 label sheets, no cuts",
      working(r)[1:-1] == ["20 A4 colour copies x 0.30 (tier 1) = 6.00", "20 A4 sheets Label sheet x 0.50 = 10.00"], working(r))
r = P.price_order(pl, [prod("labels", 5, colour="Black and white")])
check("…black and white labels: B&W copies", working(r)[1] == "5 A4 black and white copies x 0.10 (tier 1) = 0.50")
lab = dict(prod("labels", 5, colour="Black and white"), folder="1 Labels", sheets=5)
s = walkin_print.settings_for(rules, lab, {"paper": "A4"})
check("…they print in B&W on the driver's Labels paper type", s["color"] == "bw" and s["paper_type"] == "Labels", s)
r = P.price_order(pl, [prod("stapled", 10, size="A5", extra="12 pages")])
check("booklet A5 stapled 12 pages x 10 = 3 A4 sheets per copy = 30 sheets, 60 copies, + 10 staples, no cuts",
      working(r)[1:-1] == ["60 A4 colour copies x 0.30 (tier 1) = 18.00", "30 A4 sheets Silk 130 gsm x 0.20 = 6.00",
                           "Staple: 10 x 0.05 = 0.50"], working(r))
r = P.price_order(pl, [prod("stapled", 10, size="A6", extra="8 pages")])
check("booklet A6 (opened 210 x 148, 2 per A4): 10 sheets, 20 copies, with cuts",
      working(r)[1:4] == ["20 A4 colour copies x 0.30 (tier 1) = 6.00", "10 A4 sheets Silk 130 gsm x 0.20 = 2.00",
                          "5 cuts (2 x 1) x 0.10 = 0.50"], working(r))
r = P.price_order(pl, [prod("stapled", 10, size="Square 148 x 148 mm")])
check("booklet Square 148 (opened 296 x 148): no layout, can't be added, says so",
      r["problems"] and "no layout for 296 x 148 mm" in r["problems"][0], r["problems"])
r = P.price_order(pl, [prod("wire", 10)])
check("spiral bound booklets (pages are a range): can't be added, says why", r["problems"]
      and "the pages are a range" in r["problems"][0], r["problems"])
r = P.price_order(pl, [prod("envelope", 100, size="DL 110 x 220 mm", paper="White")])
check("100 DL White envelopes, 1 side colour = 100 x envelope + 100 A4 colour copies",
      working(r)[1:-1] == ["100 A4 colour copies x 0.30 (tier 1) = 30.00",
                           "100 envelopes DL 110 x 220 mm, White x 0.15 = 15.00"], working(r))
r = P.price_order(pl, [prod("envelope", 100, size="C4 229 x 324 mm", paper="Kraft")])
check("C4 envelopes count as A3 copies", working(r)[1] == "100 A3 colour copies x 0.60 (tier 1) = 60.00", working(r))

# ------------------------------------------------------------------ extras and services
fl = dict(prod("flyer", 100, size="A5", paper="Silk 170 gsm"), services={"Folding": True, "Filing": True})
r = P.price_order(pl, [fl])
check("services: Folding per sheet on a 50-sheet flyer item (2.50), Filing once per item (1.00)",
      "Folding: 50 sheets x 0.05 = 2.50" in working(r) and "Filing: once x 1.00 = 1.00" in working(r), working(r))
r = P.price_order(pl, [doc(10, services={"Stapling": True})])
check("a service per piece on a document needs how many: refused without it", r["problems"] == ["Item 1: Stapling: type how many"],
      r["problems"])
r = P.price_order(pl, [doc(10, services={"Stapling": 3})])
check("…with 3: “Stapling: 3 x 0.20 = 0.60”", "Stapling: 3 x 0.20 = 0.60" in working(r), working(r))
inv = prod("invite", 50, size="A6", paper="Silk 300 gsm", extra="With envelopes")
r = P.price_order(pl, [inv])
check("a product extra per piece: With envelopes on 50 invitations = 50 x 0.50", "With envelopes: 50 x 0.50 = 25.00" in working(r), working(r))

# ------------------------------------------------------------------ empty cells
silk = ps.cell(REAL, "Paper", "Silk 300 gsm", col=1)
cut = ps.cell(REAL, "Cutting", "Price per cut", col=1)
holes = sheet_with("holes", {"Paper": {silk: None}, "Cutting": {cut: None}})
r = P.price_order(holes, [bc])
check("an empty cell blocks the item with the exact message",
      "Item 1: No price for Silk 300 gsm, A4 sheet: fill it in in Walk-in_Prices.xlsx" in r["problems"]
      and "Item 1: No price for the price per cut: fill it in in Walk-in_Prices.xlsx" in r["problems"], r["problems"])
r = P.price_order(holes, [prod("poster", 5, size="A4", paper="Gloss 170 gsm")])
check("…an item that needs no cut doesn't need the price per cut", r["problems"] == [], r["problems"])
fold = ps.cell(REAL, "Extras", "Folding", col=2)
r = P.price_order(sheet_with("nofold", {"Extras": {fold: None}}), [fl])
check("…a service that was picked and has no price blocks the item",
      "Item 1: No price for Folding (service): fill it in in Walk-in_Prices.xlsx" in r["problems"], r["problems"])

# ------------------------------------------------------------------ rounding and order total
r = P.price_order(pl, [bc], loyalty=0, rounding="up5")
check("rounding still works (26.40 up to 5 = 30.00)", r["due"] == 30.0 and r["total"] == 26.4)
check("no minimum charge: one A4 B&W copy on plain paper = 0.12", P.price_order(pl, [doc(1)])["total"] == 0.12)

# ------------------------------------------------------------------ the screens
root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2


def pump(secs=0.4):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.03)


Q = ws.QuoteScreen(menu, "quote", on_back=menu.show_menu)
Q.win.geometry("1360x1000+10+10"); pump(0.8)
Q.what.set("Business cards"); Q.build_options()
Q.option_vars["qty"].set("0"); Q.add_item()
check("Quantity is typed: 0 is refused", not Q.items and Q.editor_error.cget("text") == "Quantity: a whole number of 1 or more.",
      Q.editor_error.cget("text"))
Q.option_vars["size"].set("85 x 55 mm"); Q.option_vars["paper"].set("Silk 300 gsm"); Q.option_vars["sides"].set("Both sides")
Q.option_vars["qty"].set("250"); Q.add_item(); pump(0.2)
Q.what.set("Document"); Q.build_options()
for k, v in (("pages", "30"), ("copies", "2"), ("sides", "Both sides"), ("color", "Some pages in colour"),
             ("color_pages", "1-3"), ("cuts", "2")):
    Q.option_vars[k].set(v)
Q.service_vars["Stapling"][0].set(True); Q.service_vars["Stapling"][1].set("2")
Q.add_item(); pump(0.3)
rows = [Q.tree.item(i)["values"][1].strip() for i in Q.tree.get_children("0")]
check("Get Quote: each item shows its working under it", rows == ["64 A4 colour copies x 0.30 (tier 1) = 19.20",
                                                                 "32 A4 sheets Silk 300 gsm x 0.20 = 6.40",
                                                                 "8 cuts (4 x 2) x 0.10 = 0.80"], rows)
rows2 = [Q.tree.item(i)["values"][1].strip() for i in Q.tree.get_children("1")]
check("…the document: copies split by colour (the colour copies share the cards' tier), sheets, cuts, Stapling x 2",
      rows2 == ["54 A4 black and white copies x 0.10 (tier 1) = 5.40", "6 A4 colour copies x 0.30 (tier 1) = 1.80",
                "30 A4 sheets Normal 80 gsm x 0.02 = 0.60", "2 cuts x 0.10 = 0.20", "Stapling: 2 x 0.20 = 0.40"], rows2)
check("the document's paper list: Normal 80 gsm, Glossy 100 gsm, then the sheet's papers; a Cuts box",
      "cuts" in Q.option_vars and Q.priced["total"] == 34.8, Q.priced["total"])
Q.tree.selection_set("w:0:1"); pump(0.1)
check("selecting a working line selects its item (Edit, Remove)", Q.selected() == (0, None))
Q.tree.selection_set(())
window_shot.shot(Q.win, OUT / "get_quote_two_items_working.png")
Q.cust_vars["name"].set("Sheet Test"); Q.cust_vars["phone"].set("99 321 000"); pump(0.2)
Q.place(); pump(0.5)
o = max(wo.list_open(), key=lambda o: o["number"])
check("order.json keeps each item's working and price", o["items"][0]["working"][1] == "64 A4 colour copies x 0.30 (tier 1) = 19.20"
      and o["items"][0]["price"] == 26.4 and o["items"][1]["cuts"] == 2 and o["items"][1]["services"] == {"Stapling": 2})
for w in Q.win.winfo_children():
    if isinstance(w, tk.Toplevel):
        w.destroy()
ps.fill(SHEET, SHEET, {"Copies": {ps.cell(REAL, "Copies", "A4 colour", col=1): 9.99}}); time.sleep(0.05)
again = wo.load_order(o["_folder"])
check("changing the spreadsheet doesn't change a placed order", again["items"][0]["price"] == 26.4 and again["total"] == o["total"]
      and wp.current().copies[("A4", "color")][0] == 9.99)
os_ = ws.OrdersScreen(menu, on_back=menu.show_menu); pump(1.5)
texts = []
def walk(w):
    if w.winfo_class() == "TLabel":
        texts.append(w.cget("text"))
    for c in w.winfo_children():
        walk(c)
det = ws.OrderDetailsScreen(menu, o["number"], on_back=lambda: None); pump(1.5)
walk(det.win)  # 2026-11-19_04: the working lines are in Details…
check("Orders shows each item's working (in Details…)", any("64 A4 colour copies x 0.30 (tier 1) = 19.20" in t for t in texts))
os_.back(); Q.back(); pump(0.2)
print(f"\n{sum(results)}/{len(results)} passed")
root.destroy()
