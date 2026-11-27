"""Walk-in rebuild: pricing, placing, folders, printing, pickup, customers, price-file problems.
Temp copy of the folder layout (ORCA\\ADMIN + ORCA\\Walk-in), pretend copiers, pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, datetime, json, os, re, shutil, sys, time, tkinter as tk, zipfile
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
import price_sheet  # 17_07: a test copy of Walk-in_Prices.xlsx filled with the old website numbers
price_sheet.website_sheet(helpers.PRICE_TEMPLATE, ADMIN / "Walk-in_Prices.xlsx")
A4C = price_sheet.cell(helpers.PRICE_TEMPLATE, "Copies", "A4 colour", col=1)  # 18_04: on the Prices sheet
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, driverprint, jobs, counter, walkin_orders as wo, walkin_prices, walkin_pricing as P, walkin_print
import walkin_screens as ws, mainmenu, toners
ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order (as before)
import walkin_screens as _ws17
_ws17.ask_keep = lambda parent: True  # 17_07: the first-time question answered Keep details

from tkinter import messagebox
import pypdfium2 as pdfium
import window_shot

SENT = []  # what reached the pretend copiers: (queue, document name, pages, paper, colour, duplex, paper type, tray, copies)
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
_dm = {}
driverprint.build_devmode = lambda q, paper, color, duplex, copies, pt, tray, short_edge=False: (paper, color, duplex, pt, tray, copies)


def fake_print(pdf, q, devmode, name, **kw):
    d = pdfium.PdfDocument(str(pdf)); n = len(d); d.close()
    SENT.append((q, name, n) + tuple(devmode))


driverprint.print_pdf = fake_print
toners.TIMEOUT = 0.2
os_startfile = []
os.startfile = lambda p: os_startfile.append(str(p))
asked, warned = [], []
messagebox.showwarning = lambda **k: warned.append(k["message"])
ANSWER = {"yesno": True}
messagebox.askyesno = lambda **k: asked.append(k["message"]) or ANSWER["yesno"]
messagebox.askokcancel = lambda **k: True

results = []


def check(name, ok, info=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:300])


def pdf(path, w_mm, h_mm, pages=1):
    d = pdfium.PdfDocument.new()
    for _ in range(pages):
        d.new_page(w_mm / 25.4 * 72, h_mm / 25.4 * 72)
    d.save(str(path)); d.close()


def set_cell(sheet_no, ref, value):
    """Change one cell of the TEST copy of the price sheet (number, text or None)."""
    path = ADMIN / walkin_prices.FILE
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == f"xl/worksheets/sheet{sheet_no}.xml":
                xml = data.decode("utf-8")
                cell = (f'<c r="{ref}"/>' if value is None else
                        f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>' if isinstance(value, str) else
                        f'<c r="{ref}"><v>{value}</v></c>')
                xml, n = re.subn(rf'<c r="{ref}"[^>]*?(/>|>.*?</c>)', cell, xml, count=1)
                assert n == 1, ref
                data = xml.encode("utf-8")
            zout.writestr(info, data)
    os.replace(tmp, path)
    time.sleep(0.05)


# ------------------------------------------------------------------ the menu
appicon.set_app_id()
root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2


def pump(secs=0.4, until=None):
    end = time.time() + secs
    while time.time() < end and not (until and until()):
        root.update(); time.sleep(0.03)
    for _ in range(3):
        root.update(); time.sleep(0.02)


def buttons(w):
    out = [w.cget("text")] if w.winfo_class() == "TButton" else []
    for c in w.winfo_children():
        out += buttons(c)
    return out


def texts(w):
    out = [w.cget("text")] if w.winfo_class() in ("TLabel", "TButton", "TLabelframe") else []
    for c in w.winfo_children():
        out += texts(c)
    return out




def settle(pj):
    """Wait for the sends; press Print backs while a copier waits for it; then Pages collected everywhere."""
    q = pj.run
    for _ in range(10):
        pump(10, until=lambda: not q.busy() and q.to_send.empty()); pump(0.6)
        turns = [p for p, c in q.copiers.items() if c["state"] == "turn"]
        if not turns:
            break
        for p in turns:
            pj.send_backs(p)
    for p, c in list(q.copiers.items()):
        if c["state"] == "sent":
            pj.collected(p)
    pump(0.5)

pump(1)
check("menu: Walk-in, Orders, PrintHub, Counter, Prices, Data in that order",
      buttons(menu.win) == ["Walk-in", "Inventory management", "Data", "PrintHub", "Counter", "Prices", "Settings"], buttons(menu.win))
check("the website sync line still runs without the old screen", menu.sync_label.cget("text").startswith("Website sync:"),
      menu.sync_label.cget("text"))
window_shot.shot(menu.win, OUT / "1_menu.png")

# ------------------------------------------------------------------ pricing
pl = walkin_prices.current()
bc = {"kind": "product", "product": "bcard", "qty": 100, "picks": {"size": 0, "paper": 2, "sides": 0}}
check("100 business cards 85 x 55 one side = 13 copies 3.90 + 13 sheets 2.60 + 8 cuts 0.80 = EUR 7.30",
      P.price_order(pl, [bc])["total"] == 7.3, P.price_order(pl, [bc])["lines"][0]["working"])
set_cell(1, A4C, 0.4)
check("A4 colour copy 0.40: EUR 8.60 after the file changed, no restart",
      P.price_order(walkin_prices.current(), [bc])["total"] == 8.6)
set_cell(1, A4C, 0.3)
bc2 = dict(bc, picks={"size": 0, "paper": 2, "sides": 1})
check("both sides: 2 copies per sheet (26 copies 7.80 + 2.60 + 0.80 = EUR 11.20)",
      P.price_order(walkin_prices.current(), [bc2])["total"] == 11.2)
pl = walkin_prices.current()
doc = {"kind": "document", "size": "A4", "pages": 10, "copies": 2, "color": "bw", "color_pages": "", "sides": "single",
       "per_side": 1, "paper": "Normal 80 gsm", "finish": "none", "lam": False, "lam_sheets": 0}
check("A4 B&W 10 pages x 2 copies = 20 copies x 0.10 + 20 sheets x 0.02 = EUR 2.40", P.price_order(pl, [doc])["total"] == 2.4)
set_cell(2, "C8", 10)  # Settings: Loyalty 1
bc250 = dict(bc, qty=250)
r = P.price_order(walkin_prices.current(), [bc250], loyalty=1)
check("Loyalty 1 at 10% on EUR 16.80: -EUR 1.68 line, total EUR 15.12", r["subtotal"] == 16.8
      and r["loyalty"]["amount"] == -1.68 and r["total"] == 15.12, r["loyalty"])
r2 = P.price_order(walkin_prices.current(), [bc250], loyalty=2)
check("a level with no % set takes nothing off and says so", r2["total"] == 16.8 and r2["loyalty"]["text"] == "Loyalty 2 (no discount set yet)")

# ------------------------------------------------------------------ the Walk-in screen and Get Quote
walkin = ws.WalkinScreen(menu, on_back=menu.show_menu)
pump()
check("Walk-in screen: Get Quote, Add Email, Print Jobs, Customers, Back", buttons(walkin.win) == ["← Back", "Get Quote", "Add Email", "Copy counter", "Print Jobs", "Orders", "Customers"],
      buttons(walkin.win))
check("the price sheet reads fine: no yellow line", walkin.warn.cget("text") == "")
window_shot.shot(walkin.win, OUT / "2_walkin.png")
walkin.open_quote("quote"); pump()
quote = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "ORCA - Get Quote")
import gc
Q = next(o for o in gc.get_objects() if isinstance(o, ws.QuoteScreen))


def add_product(name, picks, qty):
    Q.what.set(name); Q.build_options()
    for k, v in picks.items():
        Q.option_vars[k].set(v)
    Q.option_vars["qty"].set(str(qty)); Q.add_item()


def add_document(**v):
    Q.what.set("Document"); Q.build_options()
    for k, val in v.items():
        Q.option_vars[k].set(val)
    Q.add_item()


add_product("Business cards", {"size": "85 x 55 mm", "paper": "Silk 300 gsm", "sides": "Both sides"}, 250)
add_product("Flyers", {"size": "A5", "paper": "Silk 170 gsm", "sides": "One side"}, 100)
add_document(size="A4", pages="10", copies="2", color="B&W")
Q.loyalty.set("1"); Q.reprice(); pump()
check("Get Quote: three items listed with their prices", len(Q.tree.get_children()) == 3
      and [Q.tree.item(i)["values"][2] for i in Q.tree.get_children()] == ["EUR 26.40", "EUR 25.50", "EUR 2.40"])
check("loyalty line and total on screen", "Loyalty 1 (10% off): -EUR 5.43" in Q.total_lines.cget("text")
      and Q.total_label.cget("text") == "Total: EUR 48.87", (Q.total_lines.cget("text"), Q.total_label.cget("text")))
Q.cust_vars["name"].set("Maria Georgiou"); Q.cust_vars["phone"].set("99 123 456")
window_shot.shot(quote, OUT / "3_get_quote.png")
Q.set_rounding("down10"); pump(0.2)
check("Down to 10: the rounded total and the calculated one shown",
      Q.total_label.cget("text") == "Total: EUR 40.00 (rounded down from 48.87)", Q.total_label.cget("text"))
Q.set_rounding(None)
# Required details
Q.cust_vars["name"].set(""); warned.clear(); Q.place()
check("placing without a name is refused", warned == ["Name and phone are both needed."] and not wo.used_numbers())
Q.cust_vars["name"].set("Maria Georgiou"); Q.cust_vars["phone"].set(""); warned.clear(); Q.place()
check("placing without a phone is refused", warned == ["Name and phone are both needed."] and not wo.used_numbers())
Q.cust_vars["phone"].set("99 123 456"); Q.cust_vars["email"].set("Maria@Example.com")
os_startfile.clear()
Q.place(); pump(0.5)
o100 = next(o for o in wo.list_open() if o["number"] == 100)
check("first order gets #100 with its item subfolders, NO folder opened (24_01), number shown",
      sorted(p.name for p in (wo.open_dir() / "#100").iterdir()) == ["1 Business cards 85 x 55", "2 Flyers A5", "3 Document A4", "order.json"]
      and not os_startfile and any(isinstance(w, tk.Toplevel) and w.title() == "ORCA - order placed"
                                                   for w in quote.winfo_children()),
      sorted(p.name for p in (wo.open_dir() / "#100").iterdir()))
check("order.json: source, customer, loyalty, items with prices, totals, status",
      o100["source"] == "quote" and o100["customer"]["phone"] == "99 123 456" and o100["loyalty"]["pct"] == 10
      and [i["price"] for i in o100["items"]] == [26.4, 25.5, 2.4] and o100["total"] == 48.87
      and o100["items"][0]["working"][1] == "64 A4 colour copies x 0.30 (tier 1) = 19.20"
      and o100["status"] == "waiting" and o100["changed_total"] is None, o100["items"][0])
for w in quote.winfo_children():
    if isinstance(w, tk.Toplevel):
        w.destroy()

# Known customer fills in, second order #101 (same customer by email only)
Q.cust_vars["email"].set("maria@example.com"); pump(0.2)
check("typing a known email fills in the name and loyalty level", Q.cust_vars["name"].get() == "Maria Georgiou"
      and Q.loyalty.get() == "1")
Q.cust_vars["email"].set(""); Q.cust_vars["name"].set(""); Q.loyalty.set("None")
Q.cust_vars["phone"].set("+357 99123456"); pump(0.2)
check("typing a known phone (+357 and no spaces) fills in the name and loyalty", Q.cust_vars["name"].get() == "Maria Georgiou"
      and Q.loyalty.get() == "1")
add_product("Business cards", {"size": "85 x 55 mm", "paper": "Silk 300 gsm", "sides": "One side"}, 100)
Q.cust_vars["phone"].set(""); Q.cust_vars["email"].set("MARIA@example.com")
Q.mode = "email"; Q.place(); Q.mode = "quote"; pump(0.3)
o101 = next(o for o in wo.list_open() if o["number"] == 101)
check("a second order gets #101; only the email: the same customer", o101["customer"]["id"] == o100["customer"]["id"])
quote.destroy()

# ------------------------------------------------------------------ Add Email, number pool
walkin.open_quote("email"); pump()
E = [o for o in gc.get_objects() if isinstance(o, ws.QuoteScreen) and o.mode == "email" and o.win.winfo_exists()][-1]
E.what.set("Document"); E.build_options(); E.add_item()
warned.clear(); E.place()
check("Add Email with nothing is refused", warned == ["Give a name, a phone or an email."])
E.cust_vars["email"].set("someone@else.cy"); E.place(); pump(0.3)
o102 = next(o for o in wo.list_open() if o["number"] == 102)
check("Add Email with only an email places the order from the same number pool (#102)", o102["source"] == "email")
check("24_01: neither Get Quote nor Add Email opened Explorer (os.startfile never called)", not os_startfile, os_startfile)
E.win.destroy()

# ------------------------------------------------------------------ waiting -> ready to print
order = wo.refresh(o100)
check("#100 shows Waiting for PDF", order["status"] == "waiting" and len(wo.missing(order)) == 3)
def aged(path):
    """A print sheet saved a minute ago (not 'still being saved')."""
    t = time.time() - 60
    os.utime(path, (t, t))


pdf(order["_folder"] / "1 Business cards 85 x 55" / "W100-1.pdf", 210, 297, 2); aged(order["_folder"] / "1 Business cards 85 x 55" / "W100-1.pdf")
pdf(order["_folder"] / "2 Flyers A5" / "W100-2.pdf", 210, 297, 1); aged(order["_folder"] / "2 Flyers A5" / "W100-2.pdf")
pdf(order["_folder"] / "3 Document A4" / "report.pdf", 210, 297, 10)
order = wo.refresh(order)
check("print sheets in, Layout done not pressed: still waiting", order["status"] == "waiting"
      and wo.missing(order) == ["item 1: waiting for layout", "item 2: waiting for layout"], wo.missing(order))
orders_screen = ws.OrdersScreen(menu, on_back=menu.show_menu); pump(1)
os_startfile.clear(); orders_screen.open_folder(wo.load_order(wo.open_dir() / "#100"))
check("24_01: Open folder in Orders still opens the order's folder", os_startfile == [str(wo.open_dir() / "#100")],
      os_startfile)
d1 = ws.SheetsDialog(orders_screen, order, 0)
check("sheet count suggested from pieces per sheet (250 cards, 8 per A4 = 32)", d1.var.get() == "32", d1.var.get())
d1.save()
order = next(o for o in wo.list_open() if o["number"] == 100)
d2 = ws.SheetsDialog(orders_screen, order, 1); d2.var.set("50"); d2.save()
order = wo.refresh(next(o for o in wo.list_open() if o["number"] == 100))
check("all files and sheet counts in: moves to Ready to print by itself", order["status"] == "ready_to_print")

# ------------------------------------------------------------------ printing
SENT.clear()
pj = ws.PrintJobsScreen(menu, on_back=menu.show_menu)
pump(3, until=lambda: all(menu.preparer.get(order, i) for i in order["items"]))
pump(2)
check("nothing is sent before Print now / Start is pressed", SENT == [])
P100 = next(o for o in wo.list_open() if o["number"] == 100)
pump(6, until=lambda: isinstance(pj.run.plans.get(100), tuple))
pj.print_now(P100)
settle(pj)
names = [s[1] for s in SENT]
check("the cover sheet first, the straight-through items, then the hand-turned cards (fronts, Print backs)",
      names == ["#100 Cover sheet", "#100 2 Flyers A5", "#100 1 Business cards 85 x 55 fronts", "#100 3 Document A4",
                "#100 1 Business cards 85 x 55 backs"]
      and [s[2] for s in SENT if "Business cards" in s[1]] == [1, 1], names)  # Silk 300 both sides: turned by hand
cover = SENT[0]
check("cover sheet: one A4 page, B&W, one side, plain paper, normal tray, on the copier of the first part",
      cover[2:] == (1, "A4", False, False, "Plain & Recycled", "Auto Tray Select", 1) and cover[0] == SENT[1][0], cover)
doc_job = next(s for s in SENT if s[1] == "#100 3 Document A4")
check("document printed with its settings (10 pages, A4, B&W, plain, x 2)", doc_job[2:] == (10, "A4", False, False,
                                                                                         "Plain & Recycled", "Auto Tray Select", 2), doc_job)
flyer = next(s for s in SENT if s[1] == "#100 2 Flyers A5")
check("product printed as laid out: colour, its paper type from the website mapping, x the sheet count",
      flyer[3:] == ("A4", True, False, "Thick 3(221 to 256 g/m2)", "Bypass Tray", 50), flyer)
P100 = next(o for o in wo.list_open() if o["number"] == 100)
check("after printing: Printed", P100["status"] == "printed" and P100["times"]["printed"])
entries = [e for e in counter.read_log() if e["order"] == "#100"]
check("print_log.csv has #100 lines (source walk-in, products named, cover sheet logged)",
      len(entries) == 4 and all(e["source"] == "walk-in" for e in entries)
      and sorted(e["product"] for e in entries) == ["Business cards", "Cover sheet", "Document", "Flyers"],
      [(e["product"], e["color"], e["bw"], e["sheets"]) for e in entries])
today = datetime.date.today()
walk = counter.sections(counter.read_log(), today, today, __import__("costs").Costs(__import__("costs").load(rules)))[1][1]
check("the Counter counts them under Walk-in", walk["count"] == 4 and walk["sizes"]["A4"]["bw"] == 20 + 1, walk["sizes"])

# ------------------------------------------------------------------ Print Jobs grouped by customer (picture)
for o in wo.list_open():
    if o["number"] in (101, 102):
        for k, item in enumerate(o["items"], start=1):
            name = f"W{o['number']}-{k}.pdf" if item["kind"] == "product" else "file.pdf"
            pdf(o["_folder"] / item["folder"] / name, 210, 297, 2 if item["kind"] == "product" else 1)
            aged(o["_folder"] / item["folder"] / name)
        o = wo.refresh(o)
        for item in o["items"]:
            if item["kind"] == "product":
                wo.layout_done(o, item, 13)
        wo.refresh(o)
pj.signature = None
pump(4, until=lambda: all(menu.preparer.get(o, i) for o in wo.list_open() for i in o["items"]))
pj.signature = None; pump(2)
t = texts(pj.win)
check("Print Jobs groups orders by customer (Maria's #100 and #101 under one heading)",
      sum(1 for x in t if x.startswith("Maria Georgiou")) == 1 and any(x.startswith("someone@else.cy") for x in t), [x for x in t if "Maria" in x or "someone" in x])
pj.win.geometry("1200x980+20+20"); pump(0.5)
window_shot.shot(pj.win, OUT / "4_print_jobs.png")

# ------------------------------------------------------------------ pickup
pj.ready_for_pickup(next(o for o in wo.list_open() if o["number"] == 100)); pump(0.3)
check("Ready for pickup moves the order to that list", next(o for o in wo.list_open() if o["number"] == 100)["status"] == "ready_for_pickup")
orders_screen.signature = None; pump(2)
orders_screen.win.geometry("1200x980+20+20"); pump(0.5)
window_shot.shot(orders_screen.win, OUT / "5_orders.png")
check("Orders shows the three lists with counts", orders_screen.status.cget("text") == "Waiting for PDF: 0   ·   Ready to print: 2   ·   Ready for pickup: 1",
      orders_screen.status.cget("text"))
asked.clear()
orders_screen.collected(next(o for o in wo.list_open() if o["number"] == 100))
cust = wo.Customers().all[o100["customer"]["id"]]
dest = wo.customers_dir() / cust["folder"] / f"{o100['created'][:10]} #100"
check("Collected asks first, then moves the folder to Customers\\<name - phone>\\<date> #100",
      asked == ["Order #100, EUR 48.87: the customer has picked it up and paid?"] and dest.is_dir()
      and cust["folder"] == "Maria Georgiou - +35799123456" and not (wo.open_dir() / "#100").exists(), (asked, cust["folder"]))
check("the collected record: time and price paid", json.loads((dest / "order.json").read_text(encoding="utf-8"))["paid"] == 48.87)
orders_screen.search.set("#100"); orders_screen.signature = None; pump(2)
check("the search still finds it, read-only (Open folder only)", any("Collected" in x for x in texts(orders_screen.win))
      and "Collected" not in buttons(orders_screen.win), [x for x in texts(orders_screen.win) if "#100" in x][:3])
orders_screen.search.set("")
# freed number
o = wo.place([doc], P.price_order(pl, [doc]), dict(cust, entered_name="Maria Georgiou", entered_phone="99123456"), "quote", None)
check("collecting #100 freed it: the next order gets #100 again", o["number"] == 100)
asked.clear(); orders_screen.cancel(o)
check("Cancel asks, then names the folder '... cancelled'", asked and (wo.customers_dir() / cust["folder"] / f"{o['created'][:10]} #100 cancelled").is_dir())

# ------------------------------------------------------------------ customers
c = wo.Customers()
same_name = c.resolve("Maria Georgiou", "99 777 888", "", 0)
check("same name with a different phone is a separate customer", same_name["id"] != cust["id"])
b = c.resolve("Andreas K", "", "andreas@mail.cy", 0)
wo.place([doc], P.price_order(pl, [doc]), dict(b, entered_name="Andreas K", entered_email="andreas@mail.cy"), "email", None)
ANSWER["yesno"] = True
assert c.conflict("99123456", "andreas@mail.cy")
merged = c.resolve("Maria Georgiou", "99123456", "andreas@mail.cy", 1, join=True)
c = wo.Customers()
check("phone of A with email of B: joined (older record and folder kept, the other's open orders point to it)",
      merged["id"] == cust["id"] and "andreas@mail.cy" in c.all[cust["id"]]["emails"] and b["id"] not in c.all
      and all(o["customer"]["id"] == cust["id"] for o in wo.list_open() if o["customer"].get("email") == "andreas@mail.cy"))
for text in ("99 123 456", "+357 99123456", "35799123456", "MARIA@EXAMPLE.COM", "maria geo", "#101", "101"):
    hit = [o["number"] for o in wo.list_open() if wo.matches(o, text)]
    check(f"search finds Maria's order by “{text}”", 101 in hit, hit)

# ------------------------------------------------------------------ the number pool
for n in range(200):
    if wo.next_number() is None:
        break
    (wo.open_dir() / f"#{wo.next_number()}").mkdir()
try:
    wo.place([doc], P.price_order(pl, [doc]), dict(cust, entered_name="x"), "quote", None)
    check("with 200 open orders a new one is refused", False)
except ValueError as e:
    check("with 200 open orders a new one is refused with the message",
          str(e) == "All order numbers #100-#299 are in use. Collect or cancel an order first.", e)

# ------------------------------------------------------------------ price file problems
set_cell(1, A4C, "twenty")
pl = walkin_prices.current()
walkin.poll(); pump(0.2)
check("a text cell: yellow warning naming the sheet and row, and that item has no price",
      P.price_order(pl, [bc])["problems"] == ["Item 1: No price for A4 colour copies, Tier 1: fill it in in "
                                              "Walk-in_Prices.xlsx"]
      and f"Prices row {A4C[1:]}" in walkin.warn.cget("text"), (walkin.warn.cget("text"), P.price_order(pl, [bc])["problems"]))
(ADMIN / walkin_prices.FILE).unlink()
pl = walkin_prices.current()
walkin.poll(); pump(0.2)
check("a missing file: no price for anything, with the warning", P.price_order(pl, [bc])["problems"]
      and "Walk-in_Prices.xlsx is missing from ADMIN" in walkin.warn.cget("text"), walkin.warn.cget("text"))

# ------------------------------------------------------------------ the cover sheet as a picture
with jobs.PDF_LOCK:
    walkin_print.cover_pdf(json.loads((dest / "order.json").read_text(encoding="utf-8")) | {"_folder": dest}, OUT / "cover.pdf")
    d = pdfium.PdfDocument(str(OUT / "cover.pdf")); d[0].render(scale=1.2).to_pil().save(OUT / "6_cover_sheet.png"); d.close()
root.destroy()
print("ALL OK" if all(results) else "SOME FAILED", f"{sum(map(bool, results))}/{len(results)}")
