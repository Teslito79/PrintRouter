"""Handoff 2026-11-17_09: no prices on the cover sheet (behind rules.json walkin_paper_prices), the trial price list.
Temp copy of the folder layout, pictures of ORCA's own window and of the rendered cover sheet PDF only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, json, os, re, shutil, sys, time, tkinter as tk
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
for f in ("prices.json", "icon.ico", "Walk-in_Prices.xlsx"):  # ADMIN's own sheet: the trial price list
    shutil.copyfile(APP / f, ADMIN / f)
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, driverprint, jobs, mainmenu, toners, walkin_orders as wo, walkin_prices as wp, walkin_print
import walkin_pricing as P, walkin_screens as ws, walkin_catalogue as cat
import price_sheet as ps
from tkinter import messagebox
import pypdfium2 as pdfium
import window_shot

driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
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


def doc(pages, **more):
    return dict({"kind": "document", "size": "A4", "pages": pages, "copies": 2, "color": "mixed", "color_pages": "1-3",
                 "sides": "double", "per_side": 1, "paper": "Normal 80 gsm", "finish": "staple", "lam": True,
                 "lam_sheets": 2, "cuts": 3}, **more)


def pages_of(path):
    """[(text, PIL image)] per page."""
    with jobs.PDF_LOCK:
        d = pdfium.PdfDocument(str(path))
        out = [(d[i].get_textpage().get_text_range().replace("\xa0", " ").replace("\r", ""),
                d[i].render(scale=2).to_pil().convert("L")) for i in range(len(d))]
        d.close()
    return out


def balance(img):
    """|left space - right space| in mm for every text line, and (top, bottom) margins of the ink in mm."""
    px = img.load(); w, h = img.size
    bands, inside, start = [], False, 0
    for y in range(h):
        ink = any(px[x, y] < 128 for x in range(0, w, 2))
        if ink and not inside:
            inside, start = True, y
        elif not ink and inside:
            inside = False
            bands.append((start, y))
    out = []
    for a, b in bands:
        xs = [x for x in range(w) if any(px[x, y] < 128 for y in range(a, b))]
        out.append(abs(xs[0] - (w - 1 - xs[-1])) * 210 / w)
    mm = 210 / w
    return out, bands[0][0] * mm, (h - bands[-1][1]) * mm


MONEY = re.compile(r"\d+[.,]\d{2}\b")


def no_money(text):
    return "EUR" not in text and "€" not in text and "%" not in text and not MONEY.search(text) \
        and "Loyalty" not in text and "rounded" not in text.lower() and "Total" not in text and "price" not in text.lower()


# ------------------------------------------------------------------ the switch
check("rules.json has walkin_paper_prices false, with its help line",
      json.loads((APP / "rules.json").read_text(encoding="utf-8"))["walkin_paper_prices"] is False
      and any("walkin_paper_prices: Prices on walk-in cover sheets. false while testing (Tesla, 2026-11-17); set to true "
              "when going live." == h for h in json.loads((APP / "rules.json").read_text(encoding="utf-8"))["_help"]))
check("…false, true and missing read as no / yes / no", (walkin_print.paper_prices({"walkin_paper_prices": False}),
                                                         walkin_print.paper_prices({"walkin_paper_prices": True}),
                                                         walkin_print.paper_prices({})) == (False, True, False))

# ------------------------------------------------------------------ a 3-item order with loyalty and rounding (test prices)
priced_sheet = TMP / "priced.xlsx"
ps.test_sheet(helpers.PRICE_TEMPLATE, priced_sheet,
              {"Settings": {ps.cell(helpers.PRICE_TEMPLATE, "Settings", "Loyalty 1", col=2): 10}})
pl = wp.load(priced_sheet)
items = [dict(prod("bcard", 250, size="85 x 55 mm", paper="Silk 300 gsm", sides="Both sides"), services={"Filing": True}),
         dict(doc(30), services={"Stapling": 2}), prod("labels", 20)]
priced = P.price_order(pl, items, loyalty=1, rounding="up5")
c = wo.Customers().resolve("Maria Georgiou", "99 123 456", "maria@example.com", 1)
order = wo.place(items, priced, dict(c, entered_name="Maria Georgiou", entered_phone="99 123 456",
                                      entered_email="maria@example.com"), "quote", priced["loyalty"])
check("the test order: 3 items, loyalty 10%, rounded up to 5, prices and working kept in order.json",
      order["loyalty"]["pct"] == 10 and order["rounding"] == "up5" and order["changed_total"] == priced["due"]
      and all(i["price"] > 0 and i["working"] for i in order["items"]), (priced["total"], priced["due"]))
check("no item line (walkin_pricing.describe) carries money",
      all(no_money(i["description"]) for i in order["items"]), [i["description"] for i in order["items"]])
cover = OUT / "cover_three_items.pdf"
walkin_print.cover_pdf(order, cover)  # rules.json of the temp ADMIN: false
pages = pages_of(cover)
text = pages[0][0]
check("cover sheet (setting false): no EUR, no €, no %, no amounts, no total, loyalty or rounding", len(pages) == 1
      and no_money(text) and f"{priced['due']:.2f}" not in text and f"{priced['total']:.2f}" not in text, text)
counted = walkin_print.counter_lines(order)  # 2026-11-19_01: the Counter replaced the item lines
check("…the rest is kept: number, name, phone, email, printed / placed, the Counter",
      f"#{order['number']}" in text and "Maria Georgiou" in text and "99 123 456" in text and "maria@example.com" in text
      and "Printed " in text and "placed " in text and "Counter" in text
      and all(line in text for line in counted[0] + counted[1]), text)
bal, top, bottom = balance(pages[0][1])
check("…still centred: every line left to right within 1 mm, the block top to bottom within 3 mm",
      max(bal) < 1.0 and abs(top - bottom) < 3, ([round(b, 2) for b in bal], round(top, 1), round(bottom, 1)))
pages[0][1].save(OUT / "cover_three_items.png")
with_total = OUT / "cover_with_prices.pdf"
walkin_print.cover_pdf(order, with_total, rules={"walkin_paper_prices": True})
t2 = pages_of(with_total)[0][0]
check("setting true: the total line is back, exactly as before (the rounded amount only)",
      f"Total: EUR {priced['due']:,.2f}" in t2 and "rounded" not in t2, [l for l in t2.splitlines() if "Total" in l])
missing_rules = {k: v for k, v in rules.items() if k != "walkin_paper_prices"}
walkin_print.cover_pdf(order, OUT / "cover_missing.pdf", rules=missing_rules)
check("setting missing: counts as false (no total)", no_money(pages_of(OUT / "cover_missing.pdf")[0][0]))
# ------------------------------------------------------------------ a long order onto a second page
# 2026-11-19_01: the Counter adds items up, so a long one needs many different papers (A4 and A3 each)
long_papers = [x for x in pl.papers if x not in walkin_print.PLAIN_PAPERS and x != wp.LABEL_SHEET]
long_items = [doc(1, paper=x, size=z, finish="none", lam=False, cuts=0) for x in long_papers for z in ("A4", "A3")]
priced_long = P.price_order(pl, long_items, loyalty=1, rounding="down10")
long_order = wo.place(long_items, priced_long, dict(c, entered_name="Maria Georgiou", entered_phone="99 123 456"),
                      "quote", priced_long["loyalty"])
walkin_print.cover_pdf(long_order, OUT / "cover_long.pdf")
lp = pages_of(OUT / "cover_long.pdf")
all_text = "".join(t for t, _ in lp)
long_lines = walkin_print.counter_lines(long_order)
check("long order: two pages, every Counter line there, no money on any page", len(lp) >= 2
      and all(line in all_text for line in long_lines[0] + long_lines[1]) and no_money(all_text), f"{len(lp)} pages")
check("…wrapped lines centred on both pages (page number left out)",
      max(balance(lp[0][1])[0][:-1] + balance(lp[-1][1])[0][:-1]) < 1.0)
lp[0][1].save(OUT / "cover_long_page1.png")

# ------------------------------------------------------------------ the trial price list
trial = wp.current()
check("ADMIN's sheet is the trial list: reads with no warnings except the trial line",
      trial.trial and trial.warnings == [wp.TRIAL], trial.warnings)
blocked = []
for p in cat.PRODUCTS:
    for size in next(o for o in p["options"] if o["key"] == "size")["choices"]:
        for o in p["options"]:
            if o["key"] == "size":
                continue
            for k in range(len(o["choices"])):
                it = prod(p["id"], p["qty"][0], size=size)
                it["picks"][o["key"]] = k
                r = P.price_order(trial, [it])
                if r["problems"]:
                    blocked.append((p["id"], size))
                elif r["total"] != 0:
                    blocked.append((p["id"], size, "not 0", r["total"]))
docs_ok = all(P.price_order(trial, [doc(n, **v)])["total"] == 0 and not P.price_order(trial, [doc(n, **v)])["problems"]
              for n in (1, 30, 120) for v in ({}, {"finish": "spiral"}, {"size": "A3", "lam": False},
                                              {"paper": "Glossy 100 gsm"}, {"color": "bw", "sides": "single"}))
check("every product option and document variant prices at 0.00; only the two known blocks remain",
      set(b[:2] for b in blocked) == {("wire", "A4"), ("wire", "A5"), ("wire", "A6"), ("stapled", "Square 148 x 148 mm")}
      and all(len(b) == 2 for b in blocked) and docs_ok, sorted(set(blocked)))

root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2


def pump(secs=0.4):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.03)


Q = ws.QuoteScreen(menu, "quote", on_back=menu.show_menu)
Q.win.geometry("1360x1000+10+10"); pump(0.8)
check("Get Quote shows the yellow line “Trial price list: every price is 0”", Q.warn.cget("text") == wp.TRIAL, Q.warn.cget("text"))
Q.what.set("Document"); Q.build_options(); Q.option_vars["pages"].set("10"); Q.add_item()
Q.what.set("Business cards"); Q.build_options(); Q.option_vars["qty"].set("250"); Q.add_item(); pump(0.3)
check("a document and a business card item are added at 0.00, the screen still shows the total",
      len(Q.items) == 2 and [Q.tree.item(i)["values"][2] for i in Q.tree.get_children()] == ["EUR 0.00", "EUR 0.00"]
      and Q.total_label.cget("text") == "Total: EUR 0.00", (Q.editor_error.cget("text"), Q.total_label.cget("text")))
window_shot.shot(Q.win, OUT / "get_quote_trial.png")
Q.cust_vars["name"].set("Trial Test"); Q.cust_vars["phone"].set("99 000 111"); pump(0.2)
before = set(wo.used_numbers())
Q.place(); pump(0.5)
new = set(wo.used_numbers()) - before
check("…and the order can be placed", len(new) == 1 and not warned, (new, warned))
for w in Q.win.winfo_children():
    if isinstance(w, tk.Toplevel):
        w.destroy()
os_ = ws.OrdersScreen(menu, on_back=menu.show_menu); pump(1.5)
titles = []
def walk(w):
    if w.winfo_class() == "TLabelframe":
        titles.append(w.cget("text"))
    for ch in w.winfo_children():
        walk(ch)
det = ws.OrderDetailsScreen(menu, wo.list_open()[0]["number"], on_back=lambda: None); pump(1.5)
walk(det.win)  # 2026-11-19_04: the list shows no prices; the order's total is in Details…
check("Orders still shows each order's total on screen (in Details…)", any("EUR " in t for t in titles), titles[:3])
det.win.destroy()
os_.back(); Q.back(); pump(0.2)
print(f"\n{sum(results)}/{len(results)} passed")
root.destroy()
