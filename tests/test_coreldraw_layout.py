"""Walk-in product items: CorelDRAW template, Options.txt, W100-2.pdf as the only print sheet, Layout done.
Temp copy of the folders, the real templates folder (and temp copies for the missing-template cases), pretend copiers."""
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
for f in ("prices.json",):
    shutil.copyfile(APP / f, ADMIN / f)
import price_sheet  # the walk-in price list: the test prices typed into the empty template
price_sheet.website_sheet(helpers.PRICE_TEMPLATE, ADMIN / "Walk-in_Prices.xlsx")
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
TEMPLATES = APP / "templates"
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(TEMPLATES))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import driverprint, jobs, orders, printhub, product_files, walkin_orders as wo, walkin_prices, walkin_pricing as P
import walkin_screens as ws, mainmenu, toners
ws.ask_keep = lambda parent: True
ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order
from tkinter import messagebox
import pypdfium2 as pdfium

SENT = []
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
driverprint.build_devmode = lambda *a, **k: None
driverprint.print_pdf = lambda pdf, q, dm, name, **k: SENT.append((Path(pdf).name, name))
toners.TIMEOUT = 0.2
os.startfile = lambda p: None
messagebox.showwarning = lambda **k: None
messagebox.askokcancel = lambda **k: True
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:400])


def pdf(path, w_mm, h_mm, pages=1, age=60):
    d = pdfium.PdfDocument.new()
    for _ in range(pages):
        d.new_page(w_mm / 25.4 * 72, h_mm / 25.4 * 72)
    d.save(str(path)); d.close()
    if age:
        t = time.time() - age
        os.utime(path, (t, t))


root = tk.Tk(); root.withdraw()
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2


def pump(secs=0.4, until=None):
    end = time.time() + secs
    while time.time() < end and not (until and until()):
        root.update(); time.sleep(0.03)
    for _ in range(3):
        root.update(); time.sleep(0.02)


pl = walkin_prices.current()
cards = {"kind": "product", "product": "bcard", "qty": 250, "picks": {"size": 0, "paper": 2, "sides": 0}}
flyers = {"kind": "product", "product": "flyer", "qty": 50, "picks": {"size": 1, "paper": 1, "sides": 0}}
doc = {"kind": "document", "size": "A4", "pages": 2, "copies": 1, "color": "bw", "color_pages": "", "sides": "single",
       "per_side": 1, "paper": "Normal 80 gsm", "finish": "none", "lam": False, "lam_sheets": 0}
customer = wo.Customers().resolve("Maria Georgiou", "99 123 456", "maria@example.com", 0)


def place(items, source="quote"):
    return wo.place(items, P.price_order(pl, items), dict(customer, entered_name="Maria Georgiou",
                                                           entered_phone="99 123 456", entered_email="maria@example.com"),
                    source, None)


o = place([cards, flyers, doc])
f2 = o["_folder"] / "2 Flyers A5"
opts = (f2 / "Options.txt").read_text(encoding="utf-8-sig")
check("#100 item 2: W100-2.cdr is a copy of 148x210.cdr", (f2 / "W100-2.cdr").read_bytes() == (TEMPLATES / "148x210.cdr").read_bytes())
check("Options.txt: order, customer, product lines, template, pieces, the closing instruction",
      all(x in opts for x in ("Order #100   item 2   quote   placed ", "Customer: Maria Georgiou · 99 123 456 · maria@example.com",
                              "Flyers   quantity 50", "  Size: A5", "  Paper: Silk 170 gsm", "  Sides: One side",
                              "  Cut size: 148 x 210 mm", "Tray: Bypass Tray (the paper isn't plain paper)",
                              "CorelDRAW template: 148x210.cdr", "Pieces per sheet: 2 on A4, 4 on A3",
                              "Put the customer's design in this folder. Lay it out in W100-2.cdr, export W100-2.pdf "
                              "into this folder, then press Layout done in Walk-in.")), opts)
(OUT / "Options_W100-2.txt").write_text(opts, encoding="utf-8")
ph_doc = orders.Document("01", o["_folder"]); ph_doc.kind = "product"; ph_doc.job = {"product": "bcard", "cut_mm": [85, 55]}
ph_template = product_files.choose_template(ph_doc, TEMPLATES)[0]
check("business cards 85 x 55 get the template PrintHub would choose", (o["_folder"] / "1 Business cards 85 x 55" / "W100-1.cdr").read_bytes()
      == ph_template.read_bytes() and ph_template.name == "85x55.cdr", ph_template.name)
check("the document item gets no .cdr and no Options.txt", sorted(p.name for p in (o["_folder"] / "3 Document A4").iterdir()) == [])

# A size with no template: blank.cdr; and with blank.cdr missing too
no148 = TMP / "templates_no148"; shutil.copytree(TEMPLATES, no148); (no148 / "148x148.cdr").unlink()
rules["templates_folder"] = str(no148); (ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8"); wo._RULES.clear()
sq = {"kind": "product", "product": "flyer", "qty": 50, "picks": {"size": 4, "paper": 1, "sides": 0}}
o2 = place([sq])
f = o2["_folder"] / "1 Flyers Square 148 x 148"
t2 = (f / "Options.txt").read_text(encoding="utf-8-sig")
check("a size with no template gets blank.cdr, with the line naming it", (f / f"W{o2['number']}-1.cdr").read_bytes()
      == (TEMPLATES / "blank.cdr").read_bytes() and "CorelDRAW template: blank.cdr (no template for 148 x 148 mm)" in t2,
      [l for l in t2.splitlines() if "template" in l])
(no148 / "blank.cdr").unlink(); wo._RULES.clear()
o3 = place([sq])
f = o3["_folder"] / "1 Flyers Square 148 x 148"
check("no template and no blank.cdr: the order is placed, Options.txt says 'blank.cdr (missing!)'",
      not list(f.glob("*.cdr")) and "CorelDRAW template: blank.cdr (missing!) (no template for 148 x 148 mm)"
      in (f / "Options.txt").read_text(encoding="utf-8-sig"))
for x in (o2, o3):
    wo.finish(x, cancelled=True)
rules["templates_folder"] = str(TEMPLATES); (ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8"); wo._RULES.clear()

# Before the layout
orders_screen = ws.OrdersScreen(menu, on_back=menu.show_menu); pump(1)
o = wo.refresh(next(x for x in wo.list_open() if x["number"] == 100))
state = orders_screen.item_state(o, o["items"][1])
check("nothing but W100-2.cdr and Options.txt: 'Waiting for the customer's file'", state[0].startswith("Waiting for the customer's file")
      and state[1] == "Warn.TLabel", state)
pdf(f2 / "flyer design.pdf", 216, 279, 3)  # the customer's Letter-size file
o = wo.refresh(o)
state = orders_screen.item_state(o, o["items"][1])
check("a Letter-size customer PDF is a customer file: no red error, 'Waiting for layout'",
      state[0].startswith("Waiting for layout") and "customer files: flyer design.pdf" in state[0] and state[1] == "Warn.TLabel"
      and wo.item_file(o, o["items"][1]) is None and o["status"] == "waiting", state)
check("no Layout done button before W100-2.pdf is there", not any(b[0].startswith("Layout done (item 2)") for b in ws.OrderDetailsScreen.buttons(orders_screen, o)))

# Layout done
pdf(f2 / "W100-2.pdf", 210, 297, 1)
pdf(o["_folder"] / "1 Business cards 85 x 55" / "W100-1.pdf", 210, 297, 1)
pdf(o["_folder"] / "3 Document A4" / "notes.pdf", 210, 297, 2)
o = wo.refresh(o)
check("W100-2.pdf (A4) exported: Layout done is offered (in Details…)", any(b[0] == "Layout done (item 2)…" for b in ws.OrderDetailsScreen.buttons(orders_screen, o))
      and orders_screen.item_state(o, o["items"][1])[0].startswith("W100-2.pdf found: press Layout done"))
d = ws.SheetsDialog(orders_screen, o, 1)
check("Layout done suggests 25 sheets (50 A5 at 2 per A4)", d.var.get() == "25", d.var.get())
d.save()
o = next(x for x in wo.list_open() if x["number"] == 100)
ws.SheetsDialog(orders_screen, o, 0).save()
o = wo.refresh(next(x for x in wo.list_open() if x["number"] == 100))
check("all items laid out (and the document's file in): ready to print", o["status"] == "ready_to_print", wo.missing(o))
SENT.clear()
pj = ws.PrintJobsScreen(menu, on_back=menu.show_menu)
pump(4, until=lambda: all(menu.preparer.get(o, i) for i in o["items"]))
menu.print_queue.update([wo.refresh(x) for x in wo.list_open()])  # the walk-in queue (2026-11-17_04): Print now
pj.print_now(o); pump(10, until=lambda: not menu.print_queue.busy() and menu.print_queue.to_send.empty()); pump(1)
sent_files = [n for n, _ in SENT]
check("printing sends W100-2.pdf, never the customer's file", "W100-2.pdf" in sent_files and "flyer design.pdf" not in sent_files
      and "W100-1.pdf" in sent_files, SENT)
check("the document item prints its dropped file", any(n == "#100 3 Document A4" for _, n in SENT), SENT)
pj.win.destroy()

# A changed print sheet goes back to waiting for Layout done
o = next(x for x in wo.list_open() if x["number"] == 100)
wo.set_status(o, "ready_to_print")
pdf(f2 / "W100-2.pdf", 210, 297, 2, age=30)
o = wo.refresh(o)
state = orders_screen.item_state(o, o["items"][1])
check("W100-2.pdf saved again after Layout done: back to waiting for Layout done", o["status"] == "waiting"
      and state[0].startswith("W100-2.pdf changed: press Layout done again"), (o["status"], state))
pdf(f2 / "W100-2.pdf", 210, 297, 1, age=0)
check("while it is still being saved, it isn't checked", wo.sheet_state(o, o["items"][1])[0] == "saving")
for w_mm, h_mm, what in ((148, 210, "A5"), (216, 279, "Letter")):
    pdf(f2 / "W100-2.pdf", w_mm, h_mm, 1)
    st, text, _ = wo.sheet_state(o, o["items"][1])
    check(f"an {what}-size W100-2.pdf is refused with the A4/A3 message", st == "bad" and "export it as A4 or A3" in text
          and orders_screen.item_state(o, o["items"][1])[1] == "Bad.TLabel", text)

# Older orders: an open order with empty product folders gets its files at start; a second start overwrites nothing
older = place([flyers])
f = older["_folder"] / "1 Flyers A5"
for p in f.iterdir():
    p.unlink()
wo.prepare_all(rules)
name = f"W{older['number']}-1"
check("an older order's empty product folder gets its .cdr and Options.txt at start",
      (f / f"{name}.cdr").is_file() and (f / "Options.txt").is_file())
(f / "Options.txt").write_text("Tesla's own note", encoding="utf-8")
(f / f"{name}.cdr").write_bytes(b"laid out")
wo.prepare_all(rules)
check("a second start overwrites nothing", (f / "Options.txt").read_text(encoding="utf-8") == "Tesla's own note"
      and (f / f"{name}.cdr").read_bytes() == b"laid out")

# A picture of one walk-in product folder in Explorer: that window only
import subprocess, win32gui, window_shot
f2_shot = o["_folder"] / "2 Flyers A5"
subprocess.Popen(["explorer.exe", str(f2_shot)])
hwnd = None
end = time.time() + 15
while time.time() < end and not hwnd:
    def look(h, _):
        global hwnd
        if win32gui.GetClassName(h) == "CabinetWClass" and win32gui.GetWindowText(h).startswith("2 Flyers A5"):
            hwnd = h
    win32gui.EnumWindows(look, None)
    time.sleep(0.3)
if hwnd:
    time.sleep(1.5)

    class W:  # what window_shot.shot needs
        def update(self): pass
        def winfo_id(self): return hwnd
    window_shot.shot(W(), OUT / "explorer_W100-2_folder.png")
    win32gui.PostMessage(hwnd, 0x0010, 0, 0)  # WM_CLOSE: close the Explorer window again
check("Explorer picture of the folder taken (that window only)", hwnd is not None)
root.destroy()
print("ALL OK" if all(results) else "SOME FAILED", f"{sum(results)}/{len(results)}")
