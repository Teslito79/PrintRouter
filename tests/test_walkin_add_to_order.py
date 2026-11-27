"""Handoff 2026-11-24_02: add new items to a customer's open order. Temp copy of the folder layout, the test price
sheet (Tier 2 from 50, Loyalty 1 = 10%), pretend copiers, pictures of ORCA's own windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import csv, ctypes, gc, json, os, shutil, sys, time, tkinter as tk
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
SRC_SHEET = helpers.PRICE_TEMPLATE
ROWS = ps.settings_rows(SRC_SHEET)
EXTRA = {"Settings": {f"C{ROWS['tier 2 from']}": 50, f"C{ROWS['tier 3 from']}": 1000, f"C{ROWS['loyalty 1']}": 10}}
ps.test_sheet(SRC_SHEET, ADMIN / "Walk-in_Prices.xlsx", EXTRA)
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, cleanup, driverprint, inventory as inv, jobs, mainmenu, toners, walkin_orders as wo, walkin_prices
import walkin_pricing as P, walkin_print, walkin_queue, walkin_screens as ws
from tkinter import messagebox
import pypdfium2 as pdfium
import window_shot

ws.ask_keep = lambda parent: True
SENT = []
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
driverprint.build_devmode = lambda q, paper, color, duplex, copies, pt, tray, short_edge=False: (paper, color, duplex, pt, tray, copies)


def fake_print(pdf, q, devmode, name, **kw):
    SENT.append((q, name))


driverprint.print_pdf = fake_print
toners.TIMEOUT = 0.2
STARTED = []
os.startfile = lambda p: STARTED.append(str(p))
cleanup.recycle = lambda p: os.remove(p)
warned = []
messagebox.showwarning = lambda **k: warned.append(k["message"])
messagebox.askyesno = lambda *a, **k: True
results = []
Q4510 = rules["printers"]["C4510"]["queue"]


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:500])


def pdf(path, pages=1):
    d = pdfium.PdfDocument.new()
    for _ in range(pages):
        d.new_page(595, 842)
    d.save(str(path)); d.close()
    t = time.time() - 60
    os.utime(path, (t, t))


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2
run = menu.print_queue


def pump(secs=0.4, until=None):
    end = time.time() + secs
    while time.time() < end and not (until and until()):
        root.update(); time.sleep(0.03)


def idle_wait():
    pump(10, until=lambda: not run.busy() and run.to_send.empty())
    pump(0.3)


def doc(pages, copies=1):
    return {"kind": "document", "size": "A4", "pages": pages, "copies": copies, "color": "bw", "color_pages": "",
            "sides": "single", "per_side": 1, "paper": "Normal 80 gsm", "finish": "none", "lam": False,
            "lam_sheets": 0}


def get(n):
    return wo.load_order(wo.open_dir() / f"#{n}")


def fill(n):
    o = get(n)
    for item in o["items"]:
        folder = o["_folder"] / item["folder"]
        if item["kind"] == "document" and wo.item_file(o, item) is None:
            pdf(folder / "file.pdf", pages=item["pages"])
    return wo.refresh(get(n))


def sent_names(k):
    return [s[1] for s in SENT[k:]]


def print_order(n):
    def ready():
        run.update([wo.refresh(o) for o in wo.list_open()])
        return isinstance(run.plans.get(n), tuple)
    pump(15, until=ready)
    k = len(SENT)
    msg = run.print_now(n)
    idle_wait()
    return msg, sent_names(k)


def texts(w):
    out = []
    for x in [w] + list(all_children(w)):
        try:
            out.append(x.cget("text"))
        except tk.TclError:
            pass
    return [t for t in out if t]


def all_children(w):
    for c in w.winfo_children():
        yield c
        yield from all_children(c)


pl = walkin_prices.current()
# A linked paper item: Inventory takes the sheets at Pages collected
inv.Inventory().add({"name": "Copy paper A4", "category": "Paper", "unit": "sheet", "stock": 1000, "minimum": None,
                     "price": None, "link": {"kind": "paper", "name": "Smooth white 80 gsm", "size": "A4"},
                     "notes": ""})


def paper_stock():
    return next(i for i in inv.Inventory().items if i["name"] == "Copy paper A4")["stock"]


# ------------------------------------------------------------------ #100: placed, printed, ready for pickup
maria = wo.Customers().resolve("Maria Georgiou", "99 123 456", "maria@example.com", 1)
first_items = [doc(30), doc(2), doc(1)]
o = wo.place(first_items, P.price_order(pl, first_items, loyalty=1),
             dict(maria, entered_name="Maria Georgiou", entered_phone="99 123 456", entered_email="maria@example.com"),
             "quote", P.price_order(pl, first_items, loyalty=1)["loyalty"])
fill(100)
msg, names = print_order(100)
check("#100 (3 items, 33 A4 B&W copies at Tier 1) prints: the cover sheet and items 1-3",
      msg is None and len(names) == 4 and "cover" in names[0].lower(), names)
stock_before = paper_stock()
run.collected("C4510"); pump(0.5)
o = get(100)
check("…Pages collected: Printed, the paper taken (33 sheets)", o["status"] == "printed"
      and stock_before - paper_stock() == 33, (o["status"], stock_before - paper_stock()))
wo.set_status(o, "ready_for_pickup")
old_total = wo.price_due(get(100))
check("…Ready for pickup; total 33 x 0.10 + 33 x 0.02 = 3.96, less 10% loyalty = 3.56",
      abs(old_total - 3.56) < 0.005, old_total)

# ------------------------------------------------------------------ Add Email with 2 items for the same customer
walkin = ws.WalkinScreen(menu, on_back=menu.show_menu)
walkin.open_quote("email"); pump()
E = [x for x in gc.get_objects() if isinstance(x, ws.QuoteScreen) and x.mode == "email" and x.win.winfo_exists()][-1]
E.items = [doc(30), doc(1)]
E.reprice()
E.cust_vars["phone"].set("99 123 456"); pump(0.2)
ASKED = []
ANSWER = []


def fake_ask(parent, candidates, items, rounding, name=""):
    q = ws.AddQuestion(parent, candidates, items, rounding, name)
    pump(0.4)
    ASKED.append((candidates, texts(q.dlg), q))
    if len(ASKED) == 1:
        window_shot.shot(q.dlg, OUT / "question.png")
    answer = ANSWER.pop(0)
    if answer == "add":
        answer = q.options[0][0] if len(candidates) == 1 else q.options[int(ANSWER.pop(0))][0]
    q.choose(answer)
    return answer


ws.ask_add = fake_ask
ANSWER[:] = [None]
k_orders = sorted(wo.used_numbers())
E.place(); pump(0.3)
t = " ".join(ASKED[0][1])
check("the question names #100, its status, 3 items and its total",
      "Maria Georgiou already has order #100 (Ready for pickup, 3 items, EUR 3.56)." in t, t)
new = wo.price_with(get(100), E.items)
check("…“Add these 2 items to #100? New total: …” (the whole order priced again)",
      f"Add these 2 items to #100? New total: {P.euro(new['due'])}." in t and "Add to #100" in t
      and "New order" in t and "Cancel" in t, t)
check("Cancel: nothing is placed or added, the screen keeps its items",
      sorted(wo.used_numbers()) == k_orders and len(get(100)["items"]) == 3 and len(E.items) == 2)

# Add to #100, with Up to 1 chosen on the screen
E.set_rounding("up1")
ANSWER[:] = ["add"]
E.place(); pump(0.5)
o = get(100)
dlg = [w for w in E.win.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "ORCA - added to order"]
check("Add to #100: items 4-5 appended with their own folders, still #100, no new order",
      [i["folder"] for i in o["items"]][3:] == ["4 Document A4", "5 Document A4"]
      and (o["_folder"] / "4 Document A4").is_dir() and sorted(wo.used_numbers()) == k_orders,
      [i["folder"] for i in o["items"]])
check("…the number window says “Added to” #100 with the new total, and lists only items 4-5",
      dlg and "Added to" in texts(dlg[0]) and "#100" in texts(dlg[0])
      and sum(1 for x in texts(dlg[0]) if x.startswith(("4. ", "5. "))) == 2
      and not any(x.startswith(("1. ", "2. ", "3. ")) for x in texts(dlg[0])), texts(dlg[0]) if dlg else None)
check("…no Explorer window opened (24_01)", not STARTED, STARTED)
if dlg:
    window_shot.shot(dlg[0], OUT / "added_to_100.png")
    dlg[0].destroy()
# re-pricing
w1 = o["items"][0]["working"]
check("re-priced as one: 30 + 30 now with Tier 2 from 50: item 1's line changes to tier 2 (0.08)",
      any("tier 2" in x and "0.08" in x for x in w1) and o["items"][3]["working"][1].endswith("(tier 2) = 2.40"), w1)
check("…loyalty kept: level 1, 10%", o["loyalty"]["level"] == 1 and o["loyalty"]["pct"] == 10, o["loyalty"])
subtotal = round(64 * 0.08 + 64 * 0.02, 2)
total = round(subtotal - round(subtotal * 0.10, 2), 2)
check("…the total 64 x 0.08 + 64 x 0.02 less 10% = 5.76, the screen's Up to 1 applied: 6.00",
      abs(o["total"] - total) < 0.005 and abs(total - 5.76) < 0.005 and o["rounding"] == "up1"
      and o["changed_total"] == 6.0,
      (o["total"], o["rounding"], o["changed_total"]))
a = o["added"][-1]
check("…the “added” record: the time, items 4-5, totals before and after",
      a["items"] == [4, 5] and abs(a["total_before"] - 3.56) < 0.005 and a["total_after"] == 6.0 and a["time"], a)
check("…Details: “Items 4-5 added …”", wo.added_lines(o)[0].startswith("Items 4-5 added "), wo.added_lines(o))
check("…Waiting for PDF until items 4-5 have their files", o["status"] == "waiting" and len(wo.missing(o)) == 2,
      (o["status"], wo.missing(o)))
fill(100)
o = get(100)
check("status: “Ready to print (items 4-5 added; 1-3 printed)”",
      ws.status_of(o) == "Ready to print (items 4-5 added; 1-3 printed)", ws.status_of(o))

# Orders line
orders = ws.OrdersScreen(menu, on_back=menu.show_menu); orders.win.geometry("1300x700+10+10"); pump(1.0)
check("the Orders line shows it", any("items 4-5 added; 1-3 printed" in x for x in texts(orders.win)),
      [x for x in texts(orders.win) if "added" in x])
window_shot.shot(orders.win, OUT / "orders_line.png")
orders.win.destroy()

# ------------------------------------------------------------------ printing only the new items
msg, names = print_order(100)
check("only items 4-5 are sent, after a cover sheet; items 1-3 not again",
      msg is None and len(names) == 3 and "cover" in names[0].lower() and "4 Document" in names[1]
      and "5 Document" in names[2], names)
cover = walkin_print.WORK_DIR / "cover_100.pdf"
d = pdfium.PdfDocument(str(cover)); text = d[0].get_textpage().get_text_range().replace(' ', ' '); d.close()
check("the cover sheet says “#100 (added)” and counts only the new items (A4 B&W: 31)",
      "#100 (added)" in text and "A4 B&W: 31" in text and "A4 B&W: 64" not in text, text.replace("\r\n", " | "))
log = list(csv.DictReader(open(ADMIN / "print_log.csv", encoding="utf-8-sig")))
check("print_log.csv logs the new prints as order #100", [r["order"] for r in log[-3:]] == ["#100"] * 3,
      [r.get("order") for r in log[-3:]])
stock_before = paper_stock()
run.collected("C4510"); pump(0.5)
o = get(100)
check("Pages collected: Printed again, and only items 4-5's 31 sheets taken (1-3 not taken again)",
      o["status"] == "printed" and stock_before - paper_stock() == 31, (o["status"], stock_before - paper_stock()))
wo.set_status(o, "ready_for_pickup")
check("…Ready for pickup by hand", get(100)["status"] == "ready_for_pickup")

# ------------------------------------------------------------------ restart: everything comes back
o_before = {k: v for k, v in get(100).items() if k != "_folder"}
menu2 = None
wo.clear_cache()
o_after = {k: v for k, v in wo.load_order(wo.open_dir() / "#100").items() if k != "_folder"}
check("restart: the order reads back the same (items, rounds, parts, added, total)", o_before == o_after
      and o_after["round"] == 1 and len(o_after["earlier_parts"]) == 1)

# ------------------------------------------------------------------ matching
nikos = wo.Customers().resolve("Nikos P.", "99 222 333", "", 0)
o101 = wo.place([doc(1)], P.price_order(pl, [doc(1)]), dict(nikos, entered_name="Nikos P.", entered_phone="99 222 333"),
                "quote", None)
check("matching by email only finds #100", [x["number"] for x in wo.open_orders_for("", "MARIA@example.com")] == [100])
check("…by phone only (+357, no spaces) finds #100",
      [x["number"] for x in wo.open_orders_for("+35799123456", "")] == [100])
check("…a name alone never matches", wo.open_orders_for("", "") == [])
dk = {"id": "x123", "name": "Eleni K."}
o102 = wo.place([doc(1)], P.price_order(pl, [doc(1)]), dict(dk, entered_name="Eleni K.", entered_phone="99 444 555"),
                "email", None, keep_data=False)
check("…a Don't keep order matches by its typed phone", [x["number"] for x in wo.open_orders_for("99444555", "")] == [102])
# two open orders: pick from the list
o103 = wo.place([doc(2)], P.price_order(pl, [doc(2)]), dict(nikos, entered_name="Nikos P.", entered_phone="99 222 333"),
                "quote", None)
E.items = [doc(1)]; E.reprice(); E.rounding = None
E.cust_vars["phone"].set("99 222 333"); E.cust_vars["email"].set(""); E.cust_vars["name"].set("Nikos P."); pump(0.2)
ANSWER[:] = ["add", "1"]
E.place(); pump(0.4)
q = ASKED[-1][2]
check("two open orders: a list of both (number, status, date, total), and the one picked gets the item",
      len(ASKED[-1][0]) == 2 and len(get(103)["items"]) == 2 and len(get(101)["items"]) == 1,
      ASKED[-1][1])
window_shot.shot(E.win, OUT / "_unused.png") if False else None
for w in E.win.winfo_children():
    if isinstance(w, tk.Toplevel):
        w.destroy()
# New order
E.items = [doc(1)]; E.reprice()
E.cust_vars["phone"].set("99 222 333"); pump(0.2)
ANSWER[:] = ["new"]
E.place(); pump(0.4)
check("New order: placed as today with the next free number (#104)", 104 in wo.used_numbers()
      and get(104)["customer"]["id"] == nikos["id"], sorted(wo.used_numbers()))
for w in E.win.winfo_children():
    if isinstance(w, tk.Toplevel):
        w.destroy()

# ------------------------------------------------------------------ an empty price cell blocks Add with its name
ps.COPIES["A3 colour"] = [None, None, None]
ps.test_sheet(SRC_SHEET, ADMIN / "Walk-in_Prices.xlsx", EXTRA)
t2 = time.time() + 5; os.utime(ADMIN / "Walk-in_Prices.xlsx", (t2, t2))
a3 = dict(doc(1), size="A3", color="color")
cands = wo.open_orders_for("99 123 456", "")
q = ws.AddQuestion(E.win, cands, [a3], None); pump(0.3)
tt = texts(q.dlg)
check("an empty price cell: the question names it and offers only New order or Cancel",
      any("can't be added to" in x and "A3 colour" in x for x in tt) and not any(x.startswith("Add to #") for x in tt)
      and "New order" in tt and "Cancel" in tt, tt)
q.choose(None)
try:
    wo.add_items(get(100), [a3])
    blocked = False
except ValueError as e:
    blocked = "A3 colour" in str(e)
check("…and add_items refuses it, naming the cell", blocked)
ps.COPIES["A3 colour"] = [0.60, 0.50, 0.40]
ps.test_sheet(SRC_SHEET, ADMIN / "Walk-in_Prices.xlsx", EXTRA)
t3 = time.time() + 10; os.utime(ADMIN / "Walk-in_Prices.xlsx", (t3, t3))

# ------------------------------------------------------------------ mid-print: adding while #101 is on the IM C4510
fill(101)
print_order(101)
o = wo.add_items(get(101), [doc(3)])
check("adding while #101's part is on the IM C4510 is allowed; that part is left alone (still printing)",
      o["parts"]["C4510"]["state"] == "printing" and o["items"][1]["round"] == 1 and o["status"] == "ready_to_print",
      (o["parts"], o["status"]))
pdf(o["_folder"] / o["items"][1]["folder"] / "file.pdf", pages=3)
o = wo.refresh(get(101))
check("…status while waiting: “items 2 added; they print after 1”… the new item waits",
      "item 2 added; they print after 1" in ws.status_of(o), ws.status_of(o))
run.update([wo.refresh(x) for x in wo.list_open()])
check("…not in the queue while the first part prints", 101 not in [n for b in run.batches("C4510") for n in b])
run.collected("C4510"); pump(0.5)
o = get(101)
check("…Pages collected: the new item's round starts (Ready to print), not Printed",
      o["status"] == "ready_to_print" and o["round"] == 1 and not o.get("parts"), (o["status"], o.get("round")))
msg, names = print_order(101)
check("…then only the new item prints, with its own cover sheet",
      msg is None and len(names) == 2 and "cover" in names[0].lower() and "2 Document" in names[1], names)
run.collected("C4510"); pump(0.3)

# ------------------------------------------------------------------ Collected: one sales line, spending once
o = get(100)
due = wo.price_due(o)
wo.finish(o)
sales = [r for r in wo.read_sales() if r["order"] == "#100"]
check("Collected: one sales line for #100 with the whole new total", len(sales) == 1 and sales[0]["paid"] == f"{due:.2f}",
      sales)
spent = wo.spending(maria["id"])
check("…spending counts the order once, with its final total", abs(spent['all_time'] - due) < 0.005 and spent['orders'] == 1, spent)

root.destroy()
print(f"{sum(results)} of {len(results)} passed")
