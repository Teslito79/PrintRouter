"""Handoff 2026-11-17_07: customers list, automatic loyalty, asking before keeping data, the walk-in-only price sheet,
rounding instead of typed prices. Temp copy of the folder layout, pretend copiers, pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import csv, ctypes, datetime, json, os, shutil, sys, time, tkinter as tk
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
import price_sheet
SHEET = ADMIN / "Walk-in_Prices.xlsx"
S_ROWS = price_sheet.settings_rows(helpers.PRICE_TEMPLATE)
LOYAL = {f"C{S_ROWS['loyalty 1']}": 5, f"C{S_ROWS['loyalty 2']}": 10, f"C{S_ROWS['loyalty 3']}": 15}
SPEND = {f"C{S_ROWS['level 1 from']}": 100, f"C{S_ROWS['level 2 from']}": 300, f"C{S_ROWS['level 3 from']}": 600}
price_sheet.website_sheet(helpers.PRICE_TEMPLATE, SHEET, {"Settings": LOYAL | SPEND})
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
# A customer from before this handoff (old format): counts as Keep details, automatic loyalty.
(ADMIN / "walkin_customers.json").write_text(json.dumps({"customers": {"old1": {
    "id": "old1", "name": "Old Customer", "phones": ["+35799000111"], "emails": [], "loyalty": 2,
    "folder": "Old Customer - +35799000111", "created": "2026-11-17T09:00:00"}}}), encoding="utf-8")
import appicon, cleanup, counter, driverprint, jobs, mainmenu, toners, walkin_orders as wo, walkin_prices, walkin_print
import walkin_pricing as P, walkin_screens as ws
ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order (as before)
from tkinter import messagebox, ttk
import pypdfium2 as pdfium
import window_shot

SENT = []
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
driverprint.build_devmode = lambda q, paper, color, duplex, copies, pt, tray, short_edge=False: (paper, color, duplex, pt, tray, copies)


def fake_print(pdf, q, devmode, name, **kw):
    d = pdfium.PdfDocument(str(pdf)); n = len(d); d.close()
    SENT.append((q, name, n) + tuple(devmode))


driverprint.print_pdf = fake_print
toners.TIMEOUT = 0.2
STARTED = []
os.startfile = lambda p: STARTED.append(str(p))
RECYCLED = []
cleanup.recycle = lambda p: RECYCLED.append(Path(p).name) or os.remove(p)  # never Tesla's real Recycle Bin
asked, warned, infos = [], [], []
messagebox.showwarning = lambda **k: warned.append(k["message"])
messagebox.showinfo = lambda **k: infos.append(k["message"])
messagebox.askyesno = lambda *a, **k: asked.append(k.get("message") or a[1]) or True
KEEP = {"answer": True, "asked": 0}
real_ask_keep = ws.ask_keep


def fake_ask_keep(parent):
    KEEP["asked"] += 1
    return KEEP["answer"]


ws.ask_keep = fake_ask_keep
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:400])


def pdf(path, pages=1, age=60):
    d = pdfium.PdfDocument.new()
    for _ in range(pages):
        d.new_page(595, 842)
    d.save(str(path)); d.close()
    t = time.time() - age
    os.utime(path, (t, t))
    return path


def pdf_text(path):
    with jobs.PDF_LOCK:
        d = pdfium.PdfDocument(str(path))
        text = "\n".join(d[i].get_textpage().get_text_range() for i in range(len(d)))
        d.close()
    return text


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2


def pump(secs=0.4, until=None):
    end = time.time() + secs
    while time.time() < end and not (until and until()):
        root.update(); time.sleep(0.03)
    for _ in range(3):
        root.update(); time.sleep(0.02)


def widgets(w, cls=None):
    out = [w] if cls is None or w.winfo_class() == cls else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


def texts(w):
    return [x.cget("text") for x in widgets(w) if x.winfo_class() in ("TLabel", "TButton", "TLabelframe", "Label")]


def doc(pages=1, copies=1):
    return {"kind": "document", "size": "A4", "pages": pages, "copies": copies, "color": "bw", "color_pages": "",
            "sides": "single", "per_side": 1, "paper": "Normal 80 gsm", "finish": "none", "lam": False, "lam_sheets": 0}


def priced(total, rounding=None):
    return {"lines": [{"price": total, "note": ""}], "volume": 0.0, "total": total, "rounding": rounding,
            "due": P.rounded(total, rounding), "problems": []}


def order_for(c, total, rounding=None, keep=True, phone=None):
    return wo.place([doc()], priced(total, rounding), dict(c, entered_name=c["name"], entered_phone=phone or (c.get("phones") or [""])[0]),
                    "quote", None, keep_data=keep)


TODAY = datetime.date.today()

# ================================================================== 1. the price sheet
real = walkin_prices.load(helpers.PRICE_TEMPLATE)
check("the real ADMIN sheet reads with only the one 'no prices yet' line (no per-cell warnings)",
      real.warnings == [walkin_prices.NO_PRICES] and real.filled == 0, real.warnings)
check("…its spending rows are read and empty: everyone None in automatic", real.spend == {1: None, 2: None, 3: None}
      and real.level_for(5000) == 0, real.spend)
check("…the Services table is read into pl.services (prices empty for now)",
      list(real.services) == ["Stapling", "Folding", "Filing"]
      and all(v[:2] == (None, None) for v in real.services.values()), real.services)
check("the sheet says nothing about the website, PrintHub or ORCA",
      not any(w in json.dumps(walkin_prices.read_xlsx(helpers.PRICE_TEMPLATE)).lower() for w in ("website", "printhub", "orca")))
bc = {"kind": "product", "product": "bcard", "qty": 100, "picks": {"size": 0, "paper": 2, "sides": 0}}
env = {"kind": "product", "product": "envelope", "qty": 100, "picks": {"size": 0, "paper": 0}}
items = [bc, env, doc(10, 2), dict(doc(), finish="spiral"), dict(doc(), lam=True)]
probs = P.price_order(real, items)["problems"]
check("with the empty sheet every item names an empty cell (“No price for …: fill it in in Walk-in_Prices.xlsx”)",
      {p.split(":")[0] for p in probs} == {"Item 1", "Item 2", "Item 3", "Item 4", "Item 5"}
      and all((": No price for " in p or ": No number for " in p) and p.endswith("fill it in in Walk-in_Prices.xlsx")
              for p in probs), probs)
missing = walkin_prices.load(ADMIN / "gone.xlsx")
check("with the file renamed away: no item has a price, the yellow line says so",
      P.price_order(missing, [bc])["problems"] and missing.warnings == ["Walk-in_Prices.xlsx is missing from ADMIN: no item "
                                                                       "can be priced until it is back."], missing.warnings)
pl = walkin_prices.current()
check("the test sheet with prices reads with no warnings", pl.warnings == [], pl.warnings)
check("…and the quote uses its prices (100 cards EUR 7.30, A4 B&W 10 x 2 = EUR 2.40)",
      P.price_order(pl, [bc])["total"] == 7.3 and P.price_order(pl, [doc(10, 2)])["total"] == 2.4)
check("loyalty % and spending amounts read", pl.loyalty == {1: 5, 2: 10, 3: 15} and pl.spend == {1: 100, 2: 300, 3: 600})
odd = TMP / "odd.xlsx"
STAPLING = price_sheet.cell(helpers.PRICE_TEMPLATE, "Extras", "Stapling", col=1)  # the Stapling service row
price_sheet.fill(helpers.PRICE_TEMPLATE, odd, {"Settings": {f"C{S_ROWS['level 1 from']}": 300,
                                                                 f"C{S_ROWS['level 2 from']}": 100,
                                                                 f"C{S_ROWS['level 3 from']}": "lots"},
                                                    "Extras": {STAPLING.replace("B", "C"): 0.5, STAPLING.replace("B", "D"): "per piece"}})
o = walkin_prices.load(odd)
check("level amounts that don't rise: warned, still used (highest level reached)",
      any("Level amounts should rise from 1 to 3" in w for w in o.warnings) and o.level_for(150) == 2 and o.level_for(350) == 2,
      o.warnings)
check("a spending value that isn't a number: the usual warning, None", o.spend[3] is None
      and any("“lots” isn't an amount" in w for w in o.warnings), o.warnings)
check("a service price filled in: read with how it is charged",
      o.services["Stapling"] == (0.5, "piece", "Stapling a set of pages together"), o.services)

# ================================================================== 2. rounding
want = {"down1": 23.0, "up1": 24.0, "down5": 20.0, "up5": 25.0, "down10": 20.0, "up10": 30.0}
check("23.40 gives 23 / 24 / 20 / 25 / 20 / 30", {m: P.rounded(23.40, m) for m in want} == want)
check("26.00 gives 25 / 30 with the 5s", (P.rounded(26, "down5"), P.rounded(26, "up5")) == (25.0, 30.0))
check("23 gives 20 or 25 with the 5s (Tesla's example)", (P.rounded(23, "down5"), P.rounded(23, "up5")) == (20.0, 25.0))
check("a total of 30.00 stays 30.00 with Up to 10", P.rounded(30, "up10") == 30.0)
check("never below 0 (Down to 10 from 4.00 gives 0, allowed)", P.rounded(4, "down10") == 0.0)
check("No rounding gives the calculated total back", P.rounded(23.40, None) == 23.40)

# ================================================================== 3. Get Quote: rounding buttons, no typed price
Q = ws.QuoteScreen(menu, "quote", on_back=menu.show_menu)
Q.win.geometry("1320x940+10+10"); pump(0.8)
check("Get Quote still marks name and phone as required", "* required. Email optional." in texts(Q.win)
      and "Name *" in texts(Q.win) and "Phone *" in texts(Q.win))
entries_in_totals = [w for w in widgets(Q.total_label.master) if w.winfo_class() == "TEntry"]
check("no box next to the total accepts a typed price; six rounding buttons and No rounding",
      not entries_in_totals and [b.cget("text") for b in Q.round_buttons.values()] ==
      ["Down to 1", "Up to 1", "Down to 5", "Up to 5", "Down to 10", "Up to 10"]
      and "No rounding" in texts(Q.win) and not any("Change price" in t for t in texts(Q.win)), texts(Q.total_label.master))
Q.what.set("Document"); Q.build_options()
Q.option_vars["pages"].set("117"); Q.add_item(); pump(0.2)  # 117 copies x 0.10 + 117 sheets x 0.02 = 14.04
base = Q.priced["total"]
Q.set_rounding("up10"); pump(0.2)
check("Up to 10: “Total: EUR 20.00 (rounded up from 14.04)”", base == 14.04
      and Q.total_label.cget("text") == "Total: EUR 20.00 (rounded up from 14.04)", (base, Q.total_label.cget("text")))
Q.set_rounding("down1"); pump(0.2)
check("another button replaces the rounding (Down to 1: 14.00)", Q.priced["due"] == 14.0 and Q.rounding == "down1")
Q.set_rounding("down1"); pump(0.2)
check("pressing the same button again goes back to the calculated total", Q.rounding is None
      and Q.total_label.cget("text") == "Total: EUR 14.04")
Q.set_rounding("up10")
Q.option_vars["pages"].set("200"); Q.add_item(); pump(0.2)  # 317 B&W copies: tier 2 (0.08) = 25.36 + 6.34 paper
check("round, then change the items: worked out again from the new total, same button",
      Q.rounding == "up10" and Q.priced["total"] == 31.7 and Q.priced["due"] == 40.0, (Q.priced["total"], Q.priced["due"]))
# ---------------------------------------------- the first-time question
Q.cust_vars["name"].set("Nina New"); Q.cust_vars["phone"].set("99 555 001"); pump(0.2)
KEEP.update(answer=None, asked=0)
before = set(wo.used_numbers())
Q.place(); pump(0.3)
check("a new phone at Place order asks the question; closing it places nothing",
      KEEP["asked"] == 1 and set(wo.used_numbers()) == before and len(Q.items) == 2)
KEEP.update(answer=True, asked=0)
Q.place(); pump(0.5)
nina = wo.Customers().by_phone("99 555 001")
o_n = max(wo.list_open(), key=lambda o: o["number"])
check("Keep details: placed, the customer saved with consent (today's date), automatic loyalty",
      KEEP["asked"] == 1 and nina and nina["consent"] == TODAY.isoformat() and nina["loyalty_mode"] == "auto"
      and o_n["keep_data"] is True, nina)
check("order.json keeps the rounded amount and the button: changed_total 40, rounding up10",
      o_n["changed_total"] == 40.0 and o_n["rounding"] == "up10" and o_n["total"] == 31.7, (o_n["changed_total"], o_n["rounding"]))
cover = TMP / "cover.pdf"
with jobs.PDF_LOCK:
    walkin_print.cover_pdf(o_n, cover)
text = pdf_text(cover).replace(" ", " ")
check("the cover sheet (17_09: walkin_paper_prices false) shows no total at all", "EUR" not in text and "40.00" not in text
      and "31.70" not in text and "Total" not in text, text)
with jobs.PDF_LOCK:
    walkin_print.cover_pdf(o_n, cover, rules={"walkin_paper_prices": True})
text = pdf_text(cover).replace(" ", " ")
check("…with walkin_paper_prices true: only the rounded total", "Total: EUR 40.00" in text and "31.70" not in text
      and "changed price" not in text and "rounded" not in text, [l for l in text.splitlines() if "Total" in l])
for w in Q.win.winfo_children():
    if isinstance(w, tk.Toplevel):
        w.destroy()
# known phone: no question; a new email for a known customer: no question
Q.what.set("Document"); Q.build_options(); Q.add_item()
KEEP.update(answer=True, asked=0)
Q.cust_vars["phone"].set("+357 99555001"); Q.cust_vars["email"].set("nina@new.cy"); pump(0.2)
Q.place(); pump(0.4)
check("a known phone with a new email: no question, the email is linked", KEEP["asked"] == 0
      and "nina@new.cy" in wo.Customers().all[nina["id"]]["emails"])
for w in Q.win.winfo_children():
    if isinstance(w, tk.Toplevel):
        w.destroy()
# ---------------------------------------------- the empty sheet: items can't be added
saved = SHEET.read_bytes()
shutil.copyfile(helpers.PRICE_TEMPLATE, SHEET); pump(0.1)
Q.cancel_edit(); n_items = len(Q.items)
Q.what.set("Business cards"); Q.build_options(); Q.add_item(); pump(0.2)
check("with the empty sheet an item can't be added: the exact empty cell (“No price for Silk 300 gsm, A4 sheet: …”)",
      len(Q.items) == n_items and Q.editor_error.cget("text").startswith("No price for Silk 300 gsm, A4 sheet: fill it in in Walk-in_Prices.xlsx")
      and Q.warn.cget("text") == walkin_prices.NO_PRICES, (Q.editor_error.cget("text"), Q.warn.cget("text")))
SHEET.unlink(); pump(0.1)
Q.what.set("Document"); Q.build_options(); Q.add_item(); pump(0.2)
check("with the file renamed away an item can't be added either", len(Q.items) == n_items
      and "No price for" in Q.editor_error.cget("text") and "is missing" in Q.warn.cget("text"),
      Q.editor_error.cget("text"))
SHEET.write_bytes(saved); time.sleep(0.05); walkin_prices.current(); pump(0.1)
Q.back(); pump(0.3)

# ================================================================== 4. spending and automatic loyalty
c = wo.Customers()
maria = c.resolve("Maria Georgiou", "99 123 456", "", "auto")
o1 = order_for(maria, 50.0); wo.finish(o1)
check("EUR 50 collected: None", wo.level_of(wo.Customers().all[maria["id"]])[:2] == (0, "auto")
      and wo.spent_12_months(maria["id"]) == 50.0)
o2 = order_for(maria, 80.0); wo.finish(o2)
check("another EUR 80 collected: level 1 automatically (stored at Collected)", wo.level_of(wo.Customers().all[maria["id"]])[:2] == (1, "auto")
      and wo.Customers().all[maria["id"]]["loyalty"] == 1)
Q = ws.QuoteScreen(menu, "quote", on_back=menu.show_menu); pump(0.5)
Q.what.set("Document"); Q.build_options(); Q.option_vars["pages"].set("100"); Q.add_item()
Q.cust_vars["phone"].set("99123456"); pump(0.3)
check("the next quote shows “Automatic (Level 1, EUR 130…)” with 5% off at once",
      Q.loyalty.get().startswith("Automatic (Level 1, EUR 130") and Q.priced["loyalty"]["pct"] == 5
      and "Loyalty 1 (5% off)" in Q.total_lines.cget("text"), (Q.loyalty.get(), Q.total_lines.cget("text")))
window_shot.shot(Q.win, OUT / "get_quote_automatic_loyalty.png")
old = order_for(maria, 400.0); dest = wo.finish(old)
data = json.loads((dest / "order.json").read_text(encoding="utf-8"))
data["times"]["collected"] = (datetime.datetime.now() - datetime.timedelta(days=396)).replace(microsecond=0).isoformat()
(dest / "order.json").write_text(json.dumps(data), encoding="utf-8"); wo.clear_cache()
check("an order of EUR 400 collected 13 months ago doesn't count (all time it does)",
      wo.spent_12_months(maria["id"]) == 130.0 and wo.spending(maria["id"])["all_time"] == 530.0, wo.spending(maria["id"])["spent_12"])
oc = order_for(maria, 500.0); wo.finish(oc, cancelled=True)
op = order_for(maria, 600.0)
check("a cancelled order doesn't count, and neither does an open one", wo.spent_12_months(maria["id"]) == 130.0)
orr = order_for(maria, 23.40, rounding="up5"); wo.finish(orr)
check("a changed (rounded) price counts as changed: 23.40 rounded up to 25 adds 25", wo.spent_12_months(maria["id"]) == 155.0)
legacy = order_for(maria, 10.0); legacy["changed_total"] = 12.0; wo.save_order(legacy); wo.finish(legacy)
check("an old typed changed_total keeps counting as typed (EUR 12)", wo.spent_12_months(maria["id"]) == 167.0)
c = wo.Customers(); c.set_loyalty(maria["id"], 3)
check("manual level 3 stays at 3 even with low spending", wo.level_of(wo.Customers().all[maria["id"]])[:2] == (3, "manual"))
c = wo.Customers(); c.set_loyalty(maria["id"], "auto")
check("set back to Automatic: the worked-out level again", wo.level_of(wo.Customers().all[maria["id"]])[:2] == (1, "auto"))
# picking a level by hand in the quote makes the customer manual at Place order; Automatic puts them back
Q.loyalty.set("3"); Q.reprice(); KEEP.update(asked=0); Q.place(); pump(0.4)
check("picking 3 in the quote: the customer is set to manual 3 when the order is placed", KEEP["asked"] == 0
      and wo.Customers().all[maria["id"]]["loyalty_mode"] == "manual" and wo.Customers().all[maria["id"]]["loyalty"] == 3)
for w in Q.win.winfo_children():
    if isinstance(w, tk.Toplevel):
        w.destroy()
Q.what.set("Document"); Q.build_options(); Q.add_item()
Q.cust_vars["phone"].set("99123456"); pump(0.3)
check("…the next quote shows 3 (set by hand)", Q.loyalty.get() == "3" and Q.priced["loyalty"]["pct"] == 15, Q.loyalty.get())
Q.loyalty.set(Q.loyalty_box.cget("values")[0]); Q.reprice(); Q.place(); pump(0.4)
check("…picking Automatic again puts them back on auto", wo.Customers().all[maria["id"]]["loyalty_mode"] == "auto")
for w in Q.win.winfo_children():
    if isinstance(w, tk.Toplevel):
        w.destroy()
Q.back(); pump(0.2)
empty_pl = walkin_prices.load(helpers.PRICE_TEMPLATE)
check("with the spending rows empty: everyone None in auto, no errors",
      wo.level_of(wo.Customers().all[maria["id"]], empty_pl)[0] == 0)
old1 = wo.Customers().all["old1"]
check("a customer from before: consent “before 2026-11-17”, automatic loyalty",
      old1["consent"] == "before 2026-11-17" and old1["loyalty_mode"] == "auto"
      and json.loads((ADMIN / "walkin_customers.json").read_text(encoding="utf-8"))["customers"]["old1"]["loyalty_mode"] == "auto")

# ================================================================== 5. Don't keep
pj = ws.PrintJobsScreen(menu, on_back=menu.show_menu); pump(0.5)
run = menu.print_queue
Q = ws.QuoteScreen(menu, "quote", on_back=menu.show_menu); pump(0.5)
Q.what.set("Document"); Q.build_options(); Q.option_vars["pages"].set("3"); Q.add_item()
Q.cust_vars["name"].set("Petros Private"); Q.cust_vars["phone"].set("99 777 000"); pump(0.2)
KEEP.update(answer=False, asked=0)
Q.place(); pump(0.4)
priv = max(wo.list_open(), key=lambda o: o["number"])
check("Don't keep: the order is placed normally (number, folder, keep_data false)", KEEP["asked"] == 1
      and priv["keep_data"] is False and priv["_folder"].is_dir() and priv["customer"]["name"] == "Petros Private")
check("…the customer is not in walkin_customers.json", "99 777 000" not in (ADMIN / "walkin_customers.json").read_text(encoding="utf-8")
      and "Petros" not in (ADMIN / "walkin_customers.json").read_text(encoding="utf-8")
      and wo.Customers().by_phone("99 777 000") is None)
for w in Q.win.winfo_children():
    if isinstance(w, tk.Toplevel):
        w.destroy()
pdf(priv["_folder"] / priv["items"][0]["folder"] / "file.pdf", pages=3)
priv = wo.refresh(wo.load_order(priv["_folder"])); pump(2)
pump(12, until=lambda: isinstance(run.plans.get(priv["number"]), tuple))
k = len(SENT)
pj.print_now(priv); pump(10, until=lambda: not run.busy() and run.to_send.empty()); pump(1)
for p, cp in list(run.copiers.items()):
    if cp["state"] == "sent":
        pj.collected(p)
pump(2)
names = [s[1] for s in SENT[k:]]
check("…it prints: cover sheet and the document", names == [f"#{priv['number']} Cover sheet", f"#{priv['number']} 1 Document A4"], names)
with jobs.PDF_LOCK:
    walkin_print.cover_pdf(priv, cover)
text = pdf_text(cover).replace(" ", " ")
check("…the cover sheet has name and phone so staff can call them", "Petros Private" in text and "99 777 000" in text)
priv = wo.load_order(priv["_folder"])
wo.set_status(priv, "ready_for_pickup")
os_ = ws.OrdersScreen(menu, on_back=menu.show_menu); pump(1.5)
asked.clear(); RECYCLED.clear()
folder = priv["_folder"]
os_.collected(priv); pump(0.5)
check("Collected asks, saying the folder is deleted for good", asked and "deleted for good" in asked[0], asked)
check("…at Collected the folder is gone for good (not in the Recycle Bin), the number free",
      not folder.exists() and not RECYCLED and priv["number"] not in wo.used_numbers()
      and not any(p.name.endswith(f"#{priv['number']}") for p in wo.customers_dir().rglob("*")))
sales = wo.read_sales()
line = next(r for r in sales if r["order"] == f"#{priv['number']}")
raw = wo.sales_path().read_text(encoding="utf-8-sig")
check("…sales_log.csv has a line with no name: date, #, collected, items, amount",
      line == {"date": TODAY.isoformat(), "order": f"#{priv['number']}", "status": "collected",
               "items": "Document A4 3 pages x 1", "paid": f"{priv['total']:.2f}", "source": "walk-in order", "copier": ""} and "Petros" not in raw and "777" not in raw, line)
entries = [e for e in counter.read_log() if e["order"] == f"#{priv['number']}"]
check("…the Counter counts it as Walk-in", entries and all(e["source"] == "walk-in" for e in entries), entries)
os_.back(); pump(0.2)
Q.what.set("Document"); Q.build_options(); Q.add_item()
Q.cust_vars["name"].set("Petros Private"); Q.cust_vars["phone"].set("99 777 000"); pump(0.2)
KEEP.update(answer=None, asked=0); Q.place(); pump(0.2)
check("…the same phone next time is asked again", KEEP["asked"] == 1)
# cancelling a Don't keep order also deletes it for good
KEEP.update(answer=False); Q.place(); pump(0.3)
priv2 = max(wo.list_open(), key=lambda o: o["number"])
for w in Q.win.winfo_children():
    if isinstance(w, tk.Toplevel):
        w.destroy()
f2 = priv2["_folder"]; wo.finish(priv2, cancelled=True)
check("a Don't keep order cancelled: its folder is gone for good too, the sales line says cancelled, EUR 0.00",
      not f2.exists() and any(r["order"] == f"#{priv2['number']}" and r["status"] == "cancelled" and r["paid"] == "0.00"
                              for r in wo.read_sales()))
check("sales_log.csv has a line for kept customers too (one list of all walk-in sales), with the rounded amount",
      any(r["order"] == f"#{orr['number']}" and r["paid"] == "25.00" for r in wo.read_sales()))
Q.back(); pump(0.2)

# ================================================================== 6. the real first-time dialog
win = tk.Toplevel(root); win.geometry("300x200+40+40"); pump(0.3)
def press(what):
    def go():
        d = next((w for w in win.winfo_children() if isinstance(w, tk.Toplevel)), None)
        if d is None:
            return
        if what == "esc":
            d.focus_force(); d.update()
            d.event_generate("<Escape>")
        else:
            getattr(d, what).invoke()
    def stuck():  # never hang the test: a dialog still open after 4 s is closed (and the check fails)
        d = next((w for w in win.winfo_children() if isinstance(w, tk.Toplevel)), None)
        if d is not None:
            print("dialog still open after 4 s")
            d.destroy()
    win.after(4000, stuck)
    return go
win.after(400, press("keep_btn")); r1 = real_ask_keep(win)
win.after(400, press("dont_btn")); r2 = real_ask_keep(win)
win.after(400, press("esc")); r3 = real_ask_keep(win)
check("the dialog: Keep details / Don't keep / Esc give True / False / None (Esc cancels Place order)",
      (r1, r2, r3) == (True, False, None), (r1, r2, r3))
check("its wording", ws.KEEP_QUESTION == "First order from this customer. Keep their details for loyalty and their own folder?")
win.destroy()

# ================================================================== 7. the Customers list
walkin = ws.WalkinScreen(menu, on_back=menu.show_menu); pump(0.4)
check("Walk-in screen has a Customers button next to Get Quote, Add Email and Print Jobs",
      [w.cget("text") for w in widgets(walkin.win, "TButton")][1:7] == ["Get Quote", "Add Email", "Copy counter", "Print Jobs", "Orders", "Customers"])
walkin.open_customers(); pump(0.6)
import gc
C = [o for o in gc.get_objects() if isinstance(o, ws.CustomersScreen)][-1]
C.win.geometry("1240x860+10+10"); pump(0.5)
rows = {C.tree.item(i)["values"][0]: C.tree.item(i)["values"] for i in C.tree.get_children()}
m = rows["Maria Georgiou"]
check("Maria's line: orders, 12 months, all time, loyalty (auto)",
      str(m[3]) == "5" and m[5] == "167.00" and m[6] == "567.00" and m[7] == "1 (auto)", m)
first = C.tree.item(C.tree.get_children()[0])["values"][0]
check("sorted by spent in 12 months, highest first (default)", first == "Maria Georgiou", first)
total12 = sum(wo.spent_12_months(cid) for cid in wo.Customers().all)
check("totals line: number of customers and total spent in 12 months",
      C.totals.cget("text") == f"{len(wo.Customers().all)} customers   ·   spent in the last 12 months: EUR {total12:,.2f}",
      C.totals.cget("text"))
C.sort("name"); pump(0.1)
names_sorted = [C.tree.item(i)["values"][0] for i in C.tree.get_children()]
check("sorts by another column (name A to Z)", names_sorted == sorted(names_sorted, key=str.lower), names_sorted)
C.sort("spent"); pump(0.1)
C.search.set("99555"); pump(0.1)
check("search by phone finds Nina", [C.tree.item(i)["values"][0] for i in C.tree.get_children()] == ["Nina New"])
C.search.set("maria geo"); pump(0.1)
check("search by name", [C.tree.item(i)["values"][0] for i in C.tree.get_children()] == ["Maria Georgiou"])
C.tree.selection_set(maria["id"]); pump(0.2)
lines = [C.orders.item(i)["values"] for i in C.orders.get_children()]
check("selecting a customer lists their orders: open ones with “open”, collected and cancelled with date, #, items, amount",
      any(l[4] == "open" for l in lines) and any(l[4] == "cancelled" and l[3] == "-" for l in lines)
      and any(l[4] == "collected" and l[3] == "EUR 400.00" for l in lines) and lines[0][4] == "open", lines[:4])
window_shot.shot(C.win, OUT / "customers_list.png")
STARTED.clear(); C.open_folder()
check("Open folder opens their Customers folder in Explorer", STARTED == [str(wo.customers_dir() / wo.Customers().all[maria["id"]]["folder"])], STARTED)
C.search.set(""); pump(0.1)
C.tree.selection_set(nina["id"]); C.edit(); pump(0.3)
D = [o for o in gc.get_objects() if isinstance(o, ws.DetailsDialog)][-1]
D.vars["email"].set("nina.second@new.cy"); D.save(); pump(0.2)
check("Edit details adds an email", "nina.second@new.cy" in wo.Customers().all[nina["id"]]["emails"])
C.tree.selection_set(nina["id"]); C.edit(); pump(0.3)
D = [o for o in gc.get_objects() if isinstance(o, ws.DetailsDialog)][-1]
D.vars["phone"].set("99 123 456"); D.save(); pump(0.2)
check("…another customer's phone is refused (matching is never by name)", "already Maria Georgiou's phone" in D.error.cget("text"),
      D.error.cget("text"))
D.dlg.destroy()
Q = ws.QuoteScreen(menu, "quote", on_back=menu.show_menu); pump(0.4)
Q.cust_vars["email"].set("Nina.Second@new.cy"); pump(0.3)
check("…and that email then finds the customer in Get Quote", Q.cust_vars["name"].get() == "Nina New"
      and Q.known.cget("text").startswith("Known customer: Nina New"))
Q.back(); pump(0.2)
C.tree.selection_set(nina["id"]); C.loyalty(); pump(0.3)
L = [o for o in gc.get_objects() if isinstance(o, ws.LoyaltyDialog)][-1]
L.var.set("2"); L.save(); pump(0.2)
check("Loyalty… sets a level by hand: shown as “2 (set by hand)”",
      C.tree.item(nina["id"])["values"][7] == "2 (set by hand)", C.tree.item(nina["id"])["values"])
# Forget customer
asked.clear(); warned.clear()
C.tree.selection_set(maria["id"]); C.forget(); pump(0.2)
check("Forget customer with open orders: refused", asked == ["Delete Maria Georgiou's details and folder for good? Their "
                                                            "sales stay without a name."]
      and warned and warned[0].startswith("Maria Georgiou still has open orders #") and maria["id"] in wo.Customers().all, warned)
for o in wo.list_open():
    if o["customer"]["id"] == maria["id"]:
        wo.finish(o, cancelled=True)
mfolder = wo.customers_dir() / wo.Customers().all[maria["id"]]["folder"]
sales_before = len(wo.read_sales())
RECYCLED.clear(); C.refresh(); C.tree.selection_set(maria["id"]); C.forget(); pump(0.2)
check("Forget customer: the folder and the record are gone for good, the sales lines stay",
      not mfolder.exists() and maria["id"] not in wo.Customers().all and not RECYCLED
      and len(wo.read_sales()) == sales_before and not C.tree.exists(maria["id"]))
check("nothing in the Customers list changes prices or orders (only these four buttons)",
      [w.cget("text") for w in widgets(C.win, "TButton")] == ["← Back", "Open folder", "Loyalty…", "Edit details…", "Forget customer…"])
check("Orders has no Change price", "PriceDialog" not in dir(ws) and not hasattr(wo, "change_price"))
C.back(); pump(0.2)
print(f"\n{sum(results)}/{len(results)} passed")
root.destroy()
