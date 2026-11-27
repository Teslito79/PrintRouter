"""Handoff 2026-11-17_04: the walk-in print queue (customer batches per copier, drag to reorder, restart) and
dropping files onto orders. Temp copy of the folder layout, pretend copiers, pictures of ORCA's own windows only.
Drops are sent to ORCA's window as Windows' own WM_DROPFILES message (what Explorer sends)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import csv, ctypes, json, os, shutil, sys, time, tkinter as tk
from ctypes import wintypes
from pathlib import Path

ctypes.windll.shcore.SetProcessDpiAwareness(1)
APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); sys.path.insert(0, str(Path(__file__).parent)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
ADMIN = TMP / "ORCA" / "ADMIN"
SRC = TMP / "Desktop"  # where dropped files come from (Explorer, a USB stick)
ADMIN.mkdir(parents=True); SRC.mkdir(); OUT.mkdir(parents=True, exist_ok=True)
for f in ("prices.json", "icon.ico"):
    shutil.copyfile(APP / f, ADMIN / f)
import price_sheet  # the walk-in price list: the test prices typed into the empty template
price_sheet.website_sheet(helpers.PRICE_TEMPLATE, ADMIN / "Walk-in_Prices.xlsx")
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, cleanup, driverprint, jobs, mainmenu, toners, walkin_orders as wo, walkin_prices, walkin_queue
import walkin_pricing as P, walkin_screens as ws, filedrop
ws.ask_keep = lambda parent: True  # 17_07: the first-time question answered Keep details
ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order
from tkinter import messagebox
import pypdfium2 as pdfium
import window_shot

SENT = []  # (queue, document name, pages, paper, colour, duplex, paper type, tray, copies)
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
driverprint.build_devmode = lambda q, paper, color, duplex, copies, pt, tray, short_edge=False: (paper, color, duplex, pt, tray, copies)


def fake_print(pdf, q, devmode, name, **kw):
    d = pdfium.PdfDocument(str(pdf)); n = len(d); d.close()
    SENT.append((q, name, n) + tuple(devmode))


driverprint.print_pdf = fake_print
toners.TIMEOUT = 0.2
os.startfile = lambda p: None
RECYCLED = []
cleanup.recycle = lambda p: RECYCLED.append(Path(p).name) or os.remove(p)  # not Tesla's real Recycle Bin
asked, warned = [], []
messagebox.showwarning = lambda **k: warned.append(k["message"])
messagebox.askyesno = lambda *a, **k: asked.append(k.get("message") or a[1]) or True
CHOSEN = []
ws.ask_item = lambda parent, labels: CHOSEN.append(labels) or 0
results = []
Q4510, Q3000 = rules["printers"]["C4510"]["queue"], rules["printers"]["C3000"]["queue"]


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:400])


def pdf(path, w_mm=210, h_mm=297, pages=1, age=60):
    d = pdfium.PdfDocument.new()
    for _ in range(pages):
        d.new_page(w_mm / 25.4 * 72, h_mm / 25.4 * 72)
    d.save(str(path)); d.close()
    if age:
        t = time.time() - age
        os.utime(path, (t, t))
    return path


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2
run = menu.print_queue


def pump(secs=0.4, until=None):
    end = time.time() + secs
    while time.time() < end and not (until and until()):
        root.update(); time.sleep(0.03)
    for _ in range(3):
        root.update(); time.sleep(0.02)


pl = walkin_prices.current()
people = {"Maria": ("Maria Georgiou", "99 123 456"), "Nikos": ("Nikos P.", "99 222 333"), "Eleni": ("Eleni K.", "99 444 555")}
cust = {k: wo.Customers().resolve(n, ph, "", 0) for k, (n, ph) in people.items()}


def doc(pages=1, copies=1, sides="single"):
    return {"kind": "document", "size": "A4", "pages": pages, "copies": copies, "color": "bw", "color_pages": "",
            "sides": sides, "per_side": 1, "paper": "Normal 80 gsm", "finish": "none", "lam": False, "lam_sheets": 0}


FLYERS = {"kind": "product", "product": "flyer", "qty": 50, "picks": {"size": 1, "paper": 1, "sides": 0}}
CARDS_HAND = {"kind": "product", "product": "bcard", "qty": 100, "picks": {"size": 0, "paper": 2, "sides": 1}}


def place(who, items):
    name, phone = people[who]
    return wo.place(items, P.price_order(pl, items), dict(cust[who], entered_name=name, entered_phone=phone), "quote", None)


def fill(o, pages=None):
    """Put each item's print file in (documents: a PDF; products: the exported W…pdf, then Layout done)."""
    o = wo.load_order(o["_folder"])
    for k, item in enumerate(o["items"], start=1):
        folder = o["_folder"] / item["folder"]
        if item["kind"] == "document":
            pdf(folder / "file.pdf", pages=(pages or {}).get(k, item["pages"]))
        else:
            pdf(folder / f"W{o['number']}-{k}.pdf", pages=2 if P.product_of(item)["id"] == "bcard" else 1)
    o = wo.refresh(o)
    for item in o["items"]:
        if item["kind"] == "product":
            wo.layout_done(o, item, 10)
    return wo.refresh(wo.load_order(o["_folder"]))


def get(n):
    return wo.load_order(wo.open_dir() / f"#{n}")


def ready_all(numbers):
    return all(isinstance(run.plans.get(n), tuple) for n in numbers)


def names_since(k):
    return [(("C4510" if s[0] == Q4510 else "C3000" if s[0] == Q3000 else s[0]), s[1]) for s in SENT[k:]]


def idle_wait():
    pump(10, until=lambda: not run.busy() and run.to_send.empty())
    pump(0.5)


# ------------------------------------------------------------------ the five orders
o100 = fill(place("Maria", [doc()]))
o101 = fill(place("Nikos", [doc(10, 100, "double")]))
o102 = fill(place("Maria", [doc()]))
o103 = fill(place("Maria", [FLYERS]))
o104 = fill(place("Eleni", [doc(2, 20, "double")]))
check("five ready orders #100-#104", [o["number"] for o in (o100, o101, o102, o103, o104)] == [100, 101, 102, 103, 104]
      and all(o["status"] == "ready_to_print" for o in (o100, o101, o102, o103, o104)))

pj = ws.PrintJobsScreen(menu, on_back=menu.show_menu)
pj.win.geometry("1320x980+10+10")
pump(15, until=lambda: ready_all([100, 101, 102, 103, 104]))
pump(2)
check("nothing is sent before Start", SENT == [] and not run.running, SENT)
check("default queue: IM C4510 Maria #100+#102, Nikos #101, Eleni #104; IM C3000 Maria #103",
      run.batches("C4510") == [[100, 102], [101], [104]] and run.batches("C3000") == [[103]],
      (run.batches("C4510"), run.batches("C3000")))
check("queue lines show customer, orders and sheets", run.batch_text("C4510", [101]) == "Nikos P.: #101 (500 sheets, B&W, both sides)",
      run.batch_text("C4510", [101]))
check("run line OFF", pj.run_label.cget("text") == "Printing orders: OFF. Nothing is sent until you press Start printing orders.",
      pj.run_label.cget("text"))

# ------------------------------------------------------------------ rearranging before Start
tree = pj.panels["C4510"]["tree"]


def row_y(iid, part=0.5):
    x, y, w, h = tree.bbox(iid)
    return int(y + h * part)


def drag(t, iid, y_to):
    y0 = row_y(iid)
    t.event_generate("<ButtonPress-1>", x=20, y=y0)
    for y in range(y0, y_to, 6 if y_to > y0 else -6):
        t.event_generate("<B1-Motion>", x=20, y=y, state=0x100)
    t.event_generate("<B1-Motion>", x=20, y=y_to, state=0x100)
    t.event_generate("<ButtonRelease-1>", x=20, y=y_to)
    pump(0.2)


pj.win.update()
# Move up / Move down on the selected line
tree.selection_set("b1"); pj.move("C4510", -1)
up = run.batches("C4510")
pj.move("C4510", 1)
check("Move up / Move down move the selected batch one place (and back)",
      up == [[101], [100, 102], [104]] and run.batches("C4510") == [[100, 102], [101], [104]], (up, run.batches("C4510")))
check("reordering IM C4510 leaves IM C3000's queue as it was", run.batches("C3000") == [[103]] and "C3000" not in run.custom,
      (run.batches("C3000"), run.custom))
# Drag #102 out of Maria's batch, to the end
pj.refresh_panels(); pj.win.update()
last = tree.get_children("")[-1]
drag(tree, "o102", row_y(last, 0.9))
out = run.batches("C4510")
check("dragging #102 out of Maria's waiting batch makes it its own line (at the end)", out == [[100], [101], [104], [102]], out)
pj.refresh_panels(); pj.win.update()
drag(tree, "b3", row_y("b0", 0.5))
back = run.batches("C4510")
check("dragging it back onto Maria's batch joins it again", back == [[100, 102], [101], [104]], back)

# ------------------------------------------------------------------ Start
SENT.clear(); asked.clear()
pj.start(); idle_wait()
sent = names_since(0)
check("Start: Maria's #100 + #102 to IM C4510 (each with its cover sheet), #103 to IM C3000",
      [n for n in sent if n[0] == "C4510"] == [("C4510", "#100 Cover sheet"), ("C4510", "#100 1 Document A4"),
                                               ("C4510", "#102 Cover sheet"), ("C4510", "#102 1 Document A4")]
      and [n for n in sent if n[0] == "C3000"] == [("C3000", "#103 Cover sheet"), ("C3000", "#103 1 Flyers A5")], sent)
check("run line ON", pj.run_label.cget("text") == "Printing orders: ON. “Pages collected” starts that copier's next customer.",
      pj.run_label.cget("text"))
pump(2)
check("IM C4510's queue then reads Nikos #101, then Eleni #104", run.batches("C4510") == [[101], [104]]
      and [tree.item(i, "text") for i in tree.get_children("")] == ["Nikos P.: #101 (500 sheets, B&W, both sides)",
                                                                    "Eleni K.: #104 (20 sheets, B&W, both sides)"],
      [tree.item(i, "text") for i in tree.get_children("")])
panel_text = pj.panels["C4510"]["state"].cget("text")
check("the panel shows “Maria Georgiou: #100, #102 (2 orders)”", panel_text.startswith("Maria Georgiou: #100, #102 (2 orders)"), panel_text)
check("Pages collected waits on both busy copiers", [b.cget("text") for b in pj.panels["C4510"]["buttons"].winfo_children()] == ["Pages collected"]
      and [b.cget("text") for b in pj.panels["C3000"]["buttons"].winfo_children()] == ["Pages collected"])
check("the orders show Printing on IM C4510", run.order_state(get(100)) == "Printing on IM C4510"
      and run.order_state(get(103)) == "Printing on IM C3000", run.order_state(get(100)))

# New ready orders while printing is ON
o105 = fill(place("Maria", [doc()]))
pump(4, until=lambda: ready_all([105])); pump(1)
check("a new order of Maria's while her batch is printing: a new batch at the end", run.batches("C4510") == [[101], [104], [105]],
      run.batches("C4510"))
o106 = fill(place("Maria", [doc()]))
pump(4, until=lambda: ready_all([106])); pump(1)
check("another while that batch waits: joins it", run.batches("C4510") == [[101], [104], [105, 106]], run.batches("C4510"))
check("nothing new was sent meanwhile (IM C4510 still holds Maria)", len(SENT) == 6, names_since(6))
pj.signature = None; pj.refresh_panels(); pump(1.5)
window_shot.shot(pj.win, OUT / "1_print_jobs_printing_on.png")

# Reorder: Eleni above Nikos
pj.refresh_panels(); pj.win.update()
drag(tree, "b1", row_y("b0", 0.2))
check("dragging Eleni #104 above Nikos #101", run.batches("C4510") == [[104], [101], [105, 106]], run.batches("C4510"))
check("IM C3000's queue unchanged by it", run.batches("C3000") == [] and "C3000" not in run.custom, run.custom)
saved = json.loads((wo.open_dir() / "print_queue.json").read_text(encoding="utf-8"))
check("print_queue.json is in Walk-in\\Open, with the custom order and what each copier holds",
      saved["custom"]["C4510"][:2] == [[104], [101]] and saved["copiers"]["C4510"]["orders"] == [100, 102], saved)
# A restart: a second queue read from the file
again = walkin_queue.Run(menu.jobs, rules, menu.preparer)
again.update([wo.refresh(o) for o in wo.list_open()])
check("after a restart the custom order is still there (and what the copiers hold)",
      again.batches("C4510") == [[104], [101], [105, 106]] and again.copiers["C4510"]["orders"] == [100, 102]
      and again.copiers["C4510"]["state"] == "sent", (again.batches("C4510"), again.copiers["C4510"]))
menu.jobs.busy_sources.pop()  # the test's second queue: forget it
k = len(SENT)
pj.collected("C4510"); idle_wait()
check("Pages collected on IM C4510 sends #104 next", names_since(k) == [("C4510", "#104 Cover sheet"), ("C4510", "#104 1 Document A4")],
      names_since(k))
check("Maria's #100 and #102 are Printed", get(100)["status"] == "printed" and get(102)["status"] == "printed")

# Stop, then Pages collected: nothing new
pj.stop()
k = len(SENT)
pj.collected("C4510"); pump(2)
check("Stop, then Pages collected: nothing new is sent", names_since(k) == [] and run.copiers["C4510"]["state"] == "idle"
      and run.batches("C4510") == [[101], [105, 106]], (names_since(k), run.batches("C4510")))

# Print now
asked.clear()
pj.print_now(get(101)); idle_wait()
check("Print now on a free copier sends the order at once (asks first: 500 sheets)",
      names_since(k) == [("C4510", "#101 Cover sheet"), ("C4510", "#101 1 Document A4")]
      and asked and "500 sheets" in asked[0], (names_since(k), asked))  # the cover sheet isn't counted (17_04)
k = len(SENT); warned.clear()
pj.print_now(get(105)); pump(1)
check("Print now on a busy copier: the message, nothing sent",
      warned == ["IM C4510 is busy with Nikos P. Press Pages collected first, or move the order up the queue."]
      and names_since(k) == [], warned)
pj.collected("C4510"); pj.collected("C3000"); pump(1)
check("#103 Printed after its copier's Pages collected", get(103)["status"] == "printed")
# print the rest of Maria's so the copiers are free
pj.start(); idle_wait(); pj.collected("C4510"); pj.stop(); pump(1)

# ------------------------------------------------------------------ hand-turned alongside plain (IM C3000)
o107 = fill(place("Maria", [CARDS_HAND]))
o108 = fill(place("Maria", [FLYERS]))
pump(6, until=lambda: ready_all([107, 108])); pump(1)
check("Maria's hand-turned cards and flyers wait on IM C3000 as one batch", run.batches("C3000") == [[107, 108]], run.batches("C3000"))
k = len(SENT)
pj.start(); idle_wait()
first = names_since(k)
check("the plain one first, then the fronts; then it waits for Print backs",
      first == [("C3000", "#107 Cover sheet"), ("C3000", "#108 Cover sheet"), ("C3000", "#108 1 Flyers A5"),
                ("C3000", "#107 1 Business cards 85 x 55 fronts")] and run.copiers["C3000"]["state"] == "turn"
      and [b.cget("text") for b in pj.panels["C3000"]["buttons"].winfo_children()] == ["Print backs"], first)
k = len(SENT)
pj.send_backs("C3000"); idle_wait()
check("Print backs sends the backs, then Pages collected", names_since(k) == [("C3000", "#107 1 Business cards 85 x 55 backs")]
      and run.copiers["C3000"]["state"] == "sent"
      and [b.cget("text") for b in pj.panels["C3000"]["buttons"].winfo_children()] == ["Pages collected"], names_since(k))
pj.collected("C3000"); pj.stop(); pump(1)
check("both Printed", get(107)["status"] == "printed" and get(108)["status"] == "printed")

# ------------------------------------------------------------------ an order across both copiers
o109 = fill(place("Eleni", [doc(), FLYERS]))
pump(6, until=lambda: ready_all([109])); pump(1)
k = len(SENT)
pj.print_now(get(109)); idle_wait()
check("split order: one cover sheet, on the copier of its first part",
      sorted(names_since(k)) == sorted([("C4510", "#109 Cover sheet"), ("C4510", "#109 1 Document A4"), ("C3000", "#109 2 Flyers A5")]),
      names_since(k))
c3000 = pj.panels["C3000"]["state"].cget("text")
check("the other copier says no cover sheet", "no cover sheet for #109" in c3000, c3000)
pj.collected("C4510"); pump(1)
check("Printed only after both parts are collected", get(109)["status"] == "ready_to_print"
      and run.order_state(get(109)) == "Printing on IM C3000", run.order_state(get(109)))
pj.collected("C3000"); pump(1)
check("…then Printed", get(109)["status"] == "printed")
pj.back(); pump(0.5)

# ------------------------------------------------------------------ dropping files
WM_DROPFILES = 0x0233
k32 = ctypes.windll.kernel32
k32.GlobalAlloc.restype = ctypes.c_void_p; k32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
k32.GlobalLock.restype = ctypes.c_void_p; k32.GlobalLock.argtypes = (ctypes.c_void_p,)
k32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
u32 = ctypes.windll.user32
u32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
u32.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))


def explorer_drop(widget, paths, dx=8, dy=6):
    """What Explorer sends: WM_DROPFILES with the files and the point, here over `widget`."""
    win = widget.winfo_toplevel()
    win.lift(); win.update()
    hwnd = int(win.wm_frame(), 16)
    pt = wintypes.POINT(widget.winfo_rootx() + dx, widget.winfo_rooty() + dy)
    u32.ScreenToClient(hwnd, ctypes.byref(pt))
    data = ("\0".join(str(p) for p in paths) + "\0\0").encode("utf-16-le")
    h = k32.GlobalAlloc(0x0042, 20 + len(data))  # GHND
    ptr = k32.GlobalLock(h)
    header = (ctypes.c_uint32 * 5)(20, pt.x & 0xFFFFFFFF, pt.y & 0xFFFFFFFF, 0, 1)  # pFiles, pt, fNC, fWide
    ctypes.memmove(ptr, header, 20)
    ctypes.memmove(ptr + 20, data, len(data))
    k32.GlobalUnlock(h)
    u32.PostMessageW(hwnd, WM_DROPFILES, h, 0)
    pump(1.5)


def find(w, cls, text_start):
    if w.winfo_class() == cls and str(w.cget("text")).startswith(text_start):
        return w
    for c in w.winfo_children():
        r = find(c, cls, text_start)
        if r is not None:
            return r
    return None



_DETAILS = {}


def details(number):
    """2026-11-19_04: an order's items, files and drop zones are in Details… (OrderDetailsScreen)."""
    d = _DETAILS.get(number)
    if d is None or not d.win.winfo_exists():
        d = _DETAILS[number] = ws.OrderDetailsScreen(menu, number, on_back=lambda: None)
        d.win.geometry("1240x980+10+10")
    d.signature = None
    pump(2)
    return d


_DETAILS = {}


def details(number):
    """2026-11-19_04: an order's items, files and drop zones are in Details… (OrderDetailsScreen)."""
    d = _DETAILS.get(number)
    if d is None or not d.win.winfo_exists():
        d = _DETAILS[number] = ws.OrderDetailsScreen(menu, number, on_back=lambda: None)
        d.win.geometry("1240x980+10+10")
    d.signature = None
    pump(2)
    return d

def card_of(screen, number):
    for w in screen.scroll.inner.winfo_children():
        if w.winfo_class() == "TLabelframe" and w.cget("text").startswith(f"#{number} "):
            return w
    return None


o110 = place("Nikos", [doc(3)])
o111 = place("Eleni", [FLYERS, doc()])
orders_screen = ws.OrdersScreen(menu, on_back=menu.show_menu)
orders_screen.win.geometry("1240x980+10+10")
pump(3)
orders_screen.search.set("Nikos"); pump(2)
card = card_of(details(110), 110)
area = find(card, "Label", "⤓  Drop the file to print here")
check("a document item shows “Drop the file to print here”", area is not None)
report = pdf(SRC / "report.pdf", pages=3)
explorer_drop(area, [report]); pump(2, until=lambda: wo.item_file(get(110), get(110)["items"][0]) is not None); pump(2)
o110 = wo.refresh(get(110))
check("a PDF dropped on the document item is copied (the original is still there) and the order is ready",
      (o110["_folder"] / "1 Document A4" / "report.pdf").is_file() and report.is_file() and o110["status"] == "ready_to_print",
      (o110["status"], sorted(p.name for p in (o110["_folder"] / "1 Document A4").iterdir())))
asked.clear()
card = card_of(details(110), 110)
other = pdf(SRC / "report v2.pdf", pages=4)
explorer_drop(find(card, "Label", "⤓"), [other]); pump(2)
names = sorted(p.name for p in (o110["_folder"] / "1 Document A4").iterdir())
check("a second file on a document item asks before replacing (the old one goes to the Recycle Bin)",
      asked and "already has report.pdf" in asked[0] and names == ["report v2.pdf"] and RECYCLED == ["report.pdf"], (asked, names))

orders_screen.search.set("Eleni K"); pump(2)
card = card_of(details(111), 111)
area = find(card, "Label", "⤓  Drop the customer's file here")
check("a product item shows “Drop the customer's file here”", area is not None)
designs = [pdf(SRC / f"design {i}.pdf", 100, 100) for i in (1, 2, 3)]
explorer_drop(area, designs); pump(3, until=lambda: len(wo.customer_files(get(111), get(111)["items"][0])) == 3); pump(2)
o111 = get(111)
check("three files dropped onto a product item all become customer files",
      [p.name for p in wo.customer_files(o111, o111["items"][0])] == ["design 1.pdf", "design 2.pdf", "design 3.pdf"],
      [p.name for p in wo.customer_files(o111, o111["items"][0])])
card = card_of(details(111), 111)
sheet = pdf(SRC / "W111-1.pdf")
explorer_drop(find(card, "Label", "⤓  Drop the customer's file here"), [sheet]); pump(2)
orders_screen.signature = None; pump(2)
check("W111-1.pdf dropped onto it: Layout done is offered (in Details…)",
      "Layout done (item 1)…" in [t for t, _, _ in details(111).buttons(get(111))],
      [t for t, _, _ in details(111).buttons(get(111))])
CHOSEN.clear()
card = card_of(details(111), 111)
explorer_drop(card, [pdf(SRC / "brief.pdf")], dx=200, dy=4)  # the card's title line: the order, not an item
check("a drop onto a two-item order asks which item", CHOSEN and CHOSEN[0] == ["1. " + o111["items"][0]["description"],
                                                                                "2. " + o111["items"][1]["description"]], CHOSEN)
pump(2)
check("…and goes to the item picked", (o111["_folder"] / o111["items"][0]["folder"] / "brief.pdf").is_file())
window_shot.shot(orders_screen.win, OUT / "2_drop_areas_orders.png")

# files ORCA can't take
folder = SRC / "a folder"; folder.mkdir()
empty = SRC / "empty.pdf"; empty.write_bytes(b"")
big = SRC / "big.pdf"
with open(big, "wb") as f:
    f.truncate(201 * 1024 * 1024)
o112 = place("Nikos", [doc()])
orders_screen.search.set("Nikos"); pump(2)
before = sorted(p.name for p in (o112["_folder"] / "1 Document A4").iterdir())
results_bad = []
for bad, words in ((folder, "is a folder"), (empty, "is empty"), (big, "ORCA takes files up to 200 MB")):
    warned.clear()
    explorer_drop(find(card_of(details(112), 112), "Label", "⤓"), [bad]); pump(1)
    results_bad.append(bool(warned) and words in warned[0] and "Nothing was copied." in warned[0])
check("a folder, an empty file or a file over 200 MB: a message, nothing copied", all(results_bad)
      and sorted(p.name for p in (o112["_folder"] / "1 Document A4").iterdir()) == before, results_bad)
big.unlink()
orders_screen.back(); pump(0.5)

# ------------------------------------------------------------------ Get Quote: files kept until Place order
q = ws.QuoteScreen(menu, "quote", on_back=menu.show_menu)
q.win.geometry("1320x940+10+10"); pump(1)
q.items = [dict(FLYERS), doc()]; q.drops = [[], []]; q.reprice(); pump(0.5)
art = pdf(SRC / "flyer art.pdf", 148, 210)
memo = pdf(SRC / "memo.pdf")
q.win.update()
x, y, w, h = q.tree.bbox("0")
explorer_drop(q.tree, [art], dx=60, dy=y + h // 2)
x, y, w, h = q.tree.bbox("1")
explorer_drop(q.tree, [memo], dx=60, dy=y + h // 2)
check("files dropped on the quote's items are listed under them", q.drops == [[str(art)], [str(memo)]]
      and q.tree.exists("f:0:0") and "flyer art.pdf" in q.tree.item("f:0:0", "values")[1], q.drops)
window_shot.shot(q.win, OUT / "3_quote_with_dropped_files.png")
q.cust_vars["name"].set("Andreas K"); q.cust_vars["phone"].set("99 888 777"); pump(0.3)
q.place(); pump(3)
o = max(wo.list_open(), key=lambda o: o["number"])
check("Place order copies them into the right subfolders (the originals stay)",
      (o["_folder"] / o["items"][0]["folder"] / "flyer art.pdf").is_file()
      and (o["_folder"] / o["items"][1]["folder"] / "memo.pdf").is_file() and art.is_file() and memo.is_file(),
      [sorted(p.name for p in (o["_folder"] / i["folder"]).iterdir()) for i in o["items"]])
dlg = next(w for w in q.win.winfo_children() if isinstance(w, tk.Toplevel))
window_shot.shot(dlg, OUT / "4_order_placed_drop_areas.png")
dlg.destroy()
count = len(wo.list_open())
q.items = [doc()]; q.drops = [[]]; q.reprice(); pump(0.3)
x, y, w, h = q.tree.bbox("0")
explorer_drop(q.tree, [pdf(SRC / "never.pdf")], dx=60, dy=y + h // 2)
q.discard(); pump(0.5)
copies = [p for p in wo.base_dir().rglob("never.pdf")]
check("Discard leaves no copies", copies == [] and len(wo.list_open()) == count and (SRC / "never.pdf").is_file(), copies)

# ------------------------------------------------------------------ other checks
path = ADMIN / jobs.LOG_FILE
rows = list(csv.reader(open(path, encoding="utf-8-sig")))
check("print_log.csv format unchanged (same columns, every line full)", rows[0] == jobs.LOG_COLUMNS
      and all(len(r) == len(jobs.LOG_COLUMNS) for r in rows[1:]) and len(rows) > 15, (rows[0][:4], len(rows)))
hand = [r for r in rows if r[15] == "#107" and r[16] == "Business cards"]
check("the hand-turned cards are logged once (with the backs)", len(hand) == 1, len(hand))

print(f"\n{sum(results)}/{len(results)} passed")
root.destroy()
