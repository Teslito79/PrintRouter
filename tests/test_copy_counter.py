"""Handoff 2026-11-17_10: the walk-in Copy counter and the rounding buttons (Up above Down). Temp copy of the folder
layout, pretend copiers (a fake copy_counter.read with counts the test sets, no network), the receipt printer faked,
pictures of ORCA's own windows and of the rendered receipts only."""
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
import price_sheet as ps
EMPTY = helpers.PRICE_TEMPLATE
SHEET = ADMIN / "Walk-in_Prices.xlsx"
ps.test_sheet(EMPTY, SHEET)  # A4 B&W 0.10 / colour 0.30, A3 B&W 0.20 / colour 0.60, Smooth white 80 A4 0.02, A3 0.04
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
rules.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
             finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: ADMIN
import appicon, copier_queue, copy_counter as cc, counter, driverprint, jobs, mainmenu, printing, toners
import walkin_orders as wo, walkin_prices as wp, walkin_pricing as P, walkin_print, walkin_screens as ws, receipt
from tkinter import messagebox, ttk
import pypdfium2 as pdfium
import window_shot

READ = {"C4510": 1000, "C3000": 5000, "C3004": 200}
DOWN = set()
READS = []


def fake_read(copier, rules=None, **kw):
    READS.append(copier)
    if copier in DOWN:
        raise cc.CounterError("no answer from 192.168.10.99")
    return {"total": READ[copier]}


cc.read = fake_read
SENT = []
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
driverprint.build_devmode = lambda q, paper, color, duplex, copies, pt, tray, short_edge=False: (paper, color, duplex, pt, tray, copies)


def fake_print(pdf, q, devmode, name, **kw):
    SENT.append((q, name))


driverprint.print_pdf = fake_print
RECEIPTS = []
printing.send = lambda pdf, queue, settings=None: RECEIPTS.append((str(pdf), queue))
toners.TIMEOUT = 0.2
os.startfile = lambda p: None
asked, warned = [], []
messagebox.showwarning = lambda **k: warned.append(k["message"])
ANSWER = {"yes": True}
messagebox.askyesno = lambda *a, **k: asked.append(k.get("message")) or ANSWER["yes"]
ws.ask_keep = lambda parent: True
ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order
results = []
Q4510 = rules["printers"]["C4510"]["queue"]


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:500])


root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2
run = menu.print_queue
M = menu.copy_counter


def pump(secs=0.4, until=None):
    end = time.time() + secs
    while time.time() < end and not (until and until()):
        root.update(); time.sleep(0.03)


def widgets(w, cls=None):
    out = [w] if cls is None or w.winfo_class() == cls else []
    for c in w.winfo_children():
        out += widgets(c, cls)
    return out


def texts(w):
    return [x.cget("text") for x in widgets(w) if x.winfo_class() in ("TLabel", "TButton", "TLabelframe", "TRadiobutton")]


def sales():
    return wo.read_sales()


def log_lines():
    return [e for e in counter.read_log() if e["order"] == "copy counter"]


# ------------------------------------------------------------------ the Walk-in screen: Copy counter button
walkin = ws.WalkinScreen(menu, on_back=menu.show_menu)
walkin.win.geometry("1160x720+10+10"); pump(0.8)
row = [b for b in widgets(walkin.win, "TButton") if b.cget("text") in ("Get Quote", "Add Email")]
btn = walkin.counter_btn
check("Walk-in (19_08): Copy counter is a big button on the first row after Add Email, same size and style, with its hint",
      btn.cget("style") == "Walkin.TButton" and abs(btn.winfo_rooty() - row[0].winfo_rooty()) < 3
      and btn.winfo_rootx() > row[1].winfo_rootx() and btn.winfo_width() == row[0].winfo_width()
      and btn.winfo_height() == row[0].winfo_height()
      and any("Copy counter: count copies made at the copier" in t for t in texts(walkin.win)),
      (btn.winfo_rootx(), btn.winfo_rooty()))
window_shot.shot(walkin.win, OUT / "walkin_with_copy_counter.png")

# ------------------------------------------------------------------ rounding buttons: Up above Down
Q = ws.QuoteScreen(menu, "quote", on_back=menu.show_menu)
Q.win.geometry("1360x1000+10+10"); pump(0.6)
Q.what.set("Document"); Q.build_options(); Q.option_vars["pages"].set("117"); Q.add_item(); pump(0.2)  # 14.04
rows = {m: int(b.grid_info()["row"]) for m, b in Q.round_buttons.items()}
cols = {m: int(b.grid_info()["column"]) for m, b in Q.round_buttons.items()}
check("rounding: Up to 1 | 5 | 10 on the top row, Down to 1 | 5 | 10 under them, No rounding on the right",
      rows == {"up1": 0, "up5": 0, "up10": 0, "down1": 1, "down5": 1, "down10": 1}
      and cols == {"up1": 0, "up5": 1, "up10": 2, "down1": 0, "down5": 1, "down10": 2}, (rows, cols))
ok = True
for mode, b in Q.round_buttons.items():
    Q.rounding = None
    b.invoke(); pump(0.05)
    ok = ok and Q.rounding == mode and Q.priced["due"] == P.rounded(14.04, mode)
check("…each button still applies its own rounding (14.04: 15 / 20 / 20 up, 14 / 10 / 10 down)", ok)
Q.rounding = None; Q.reprice(); pump(0.2)
window_shot.shot(Q.win, OUT / "rounding_up_above_down.png")
Q.back(); pump(0.2)

# ------------------------------------------------------------------ a ready walk-in order for the IM C4510 (held test)
c = wo.Customers().resolve("Held Test", "99 111 222", "", "auto")
item = {"kind": "document", "size": "A4", "pages": 2, "copies": 1, "color": "bw", "color_pages": "", "sides": "single",
        "per_side": 1, "paper": "Normal 80 gsm", "finish": "none", "lam": False, "lam_sheets": 0}
o = wo.place([item], P.price_order(wp.current(), [item]), dict(c, entered_name="Held Test", entered_phone="99 111 222"),
             "quote", None)
d = pdfium.PdfDocument.new(); d.new_page(595, 842); d.new_page(595, 842)
pdfp = o["_folder"] / o["items"][0]["folder"] / "file.pdf"; d.save(str(pdfp)); d.close()
t = time.time() - 60; os.utime(pdfp, (t, t))

# ------------------------------------------------------------------ the Copy counter window
walkin.open_copy_counter(); pump(0.6)
import gc
S = [x for x in gc.get_objects() if isinstance(x, ws.CopyCounterScreen)][-1]
S.win.geometry("1500x980+10+10"); pump(0.4)
check("one panel per copier, each Free with Start counting",
      [S.panels[p].cget("text") for p in S.panels] == ["IM C4510", "IM C3000", "MP C3004"]
      and texts(S.win).count("Start counting") == 3 and texts(S.win).count("Free") == 3)
# Start refused on a copier ORCA is printing on
run.copiers["C4510"] = {"state": "sent", "orders": [102], "customer": "Someone"}
S.start("C4510"); pump(0.1)
check("Start on a copier ORCA is printing on is refused: “IM C4510 is busy printing #102: press Pages collected first.”",
      "C4510" not in M.counters and "IM C4510 is busy printing #102: press Pages collected first." in texts(S.panels["C4510"]),
      texts(S.panels["C4510"]))
run.copiers["C4510"] = {"state": "idle"}
# Start: the copier is held
S.start("C4510"); pump(0.2)
check("Start counting reads the start count and holds the copier", "C4510" in M.counters
      and M.counters["C4510"].data["start"] == {"total": 1000} and copier_queue.held("C4510"))
check("…the walk-in queue shows “Held: copy counter running”", run.copier_text("C4510") == "Held: copy counter running")
menu.open_printhub(); pump(0.8)
ph = menu.printhub
ph.refresh(); pump(0.2)
check("…PrintHub's IM C4510 block shows it too", ph.panels["C4510"]["state"].cget("text") == "Held: copy counter running",
      ph.panels["C4510"]["state"].cget("text"))
ph.win.withdraw()
for _ in range(60):
    run.update([wo.refresh(x) for x in wo.list_open()]); pump(0.3)
    if isinstance(run.plans.get(o["number"]), tuple):
        break
check("(the order is ready to print)", isinstance(run.plans.get(o["number"]), tuple), run.plans.get(o["number"]))
k = len(SENT)
run.start_printing(); pump(1.5)
check("…and the walk-in queue sends nothing to it (the ready order waits)", not any(s[0] == Q4510 for s in SENT[k:])
      and run.copiers["C4510"]["state"] == "idle", SENT[k:])
msg = run.print_now(o["number"])
check("…Print now says it is held", msg == "IM C4510 is held: the copy counter is running on it.", msg)
check("…a held copier counts as busy for routing (a colour job goes to the if_busy copier)", "C4510" in menu.jobs.busy())
# Counting: 37 A4 B&W, a switch to A4 colour, 5 copies
cnt = M.counters["C4510"]
READ["C4510"] = 1037
S.tick(); pump(1, until=lambda: cnt.current_copies() == 37); pump(0.2)
check("the counter is read again while counting: 37 copies so far, “Last read” shown",
      cnt.current_copies() == 37 and any("A4 B&W 37 prints, on 37 A4 sheets" in x for x in texts(S.panels["C4510"]))
      and any(x.startswith("Last read ") for x in texts(S.panels["C4510"])), texts(S.panels["C4510"]))
S.change("C4510", type="A4 colour"); pump(0.1)
READ["C4510"] = 1042
cnt.poll()
check("37 A4 B&W, switch to A4 colour, 5 copies: two segments with the right counts",
      [{k: v for k, v in x.items() if k != "group"} for x in cnt.segments_now()] == [{"type": "A4 B&W", "sides": "single", "copies": 37},
                             {"type": "A4 colour", "sides": "single", "copies": 5}],  # 19_02: no paper while counting
      cnt.segments_now())
check("…the running total on screen: 37 x 0.10 + 37 x 0.02 + 5 x 0.30 + 5 x 0.02 = 6.04",
      cnt.priced()["total"] == 6.04, cnt.priced()["lines"])
# extras: 2 staples and 4 cuts
S.add_extra("C4510", "Staple", "2", ""); S.add_extra("C4510", "Cutting", "4", ""); pump(0.1)
p = cnt.priced()
check("extras: 2 staples and 4 cuts are added (as counts), priced 2 x 0.05 and 4 x 0.10",
      ("Staple x 2", 0.1) in p["lines"] and ("Cutting x 4", 0.4) in p["lines"] and p["total"] == 6.54, p["lines"])
S.add_extra("C4510", "Staple", "2.50", ""); pump(0.1)
check("…a count is a whole number, never money", "whole number" in S.messages.get("C4510", "")
      and len(cnt.data["extras"]) == 2, S.messages.get("C4510"))
S.messages.pop("C4510", None); S.build("C4510"); pump(0.2)
window_shot.shot(S.win, OUT / "copy_counter_counting.png")
# restart while counting: a new Manager from the saved file
M2 = cc.Manager(rules, read_func=fake_read)
check("a restart while counting resumes the panel with the same segments, the copier still held",
      "C4510" in M2.counters and M2.counters["C4510"].data["segments"] == cnt.data["segments"]
      and M2.counters["C4510"].data["start"] == cnt.data["start"] and copier_queue.held("C4510")
      and (wo.open_dir() / "copy_counter.json").is_file())
# Finish: waits for a stable count
fake_clock = {"t": 0.0}
seq = iter([1042, 1043, 1043])


def stepping_read(copier):
    return {"total": next(seq)}


def fake_sleep(s):
    fake_clock["t"] += s


M.read_func = stepping_read
steady = cnt.finish(sleep=fake_sleep, clock=lambda: fake_clock["t"])
M.read_func = None
check("Finish waits for two reads 3 s apart that agree (1042, 1043, 1043): the last copy counted",
      steady and fake_clock["t"] == 6 and cnt.data["segments"][-1]["copies"] == 6 and cnt.data["finished"], cnt.data["segments"])
# a counter that keeps changing stops after 30 s (on another copier)
READ["C3004"] = 200
S.start("C3004"); c3 = M.counters["C3004"]
moving = {"n": 200}


def moving_read(copier):
    moving["n"] += 1
    return {"total": moving["n"]}


fake_clock["t"] = 0.0
M.read_func = moving_read
steady = c3.finish(sleep=fake_sleep, clock=lambda: fake_clock["t"])
M.read_func = None
check("a count that keeps changing stops after 30 s and uses the last read", steady is False and fake_clock["t"] == 30
      and c3.data["finished"], fake_clock["t"])
S.build("C4510"); pump(0.2)
check("after Finish: the summary with Print receipt and Done", "Print receipt" in texts(S.panels["C4510"])
      and "Done" in texts(S.panels["C4510"]))
# prices as in 08 (test sheet) and the receipt
p = cnt.priced()
check("prices from the test sheet: copies by type (tier by this receipt), paper by sheets, extras",
      p["lines"] == [("A4 B&W: 37 prints", 3.7), ("A4 colour: 6 prints", 1.8), ("Smooth white 80 gsm: 43 A4 sheets", 0.86),
                     ("Staple x 2", 0.1), ("Cutting x 4", 0.4)] and p["total"] == 6.86, p["lines"])  # 19_02
cnt.set_rounding("up1")
off_rules, on_rules = dict(rules, walkin_paper_prices=False), dict(rules, walkin_paper_prices=True)
h, rws, tot = cc.receipt_rows(cnt, cnt.priced(), False)
check("receipt with walkin_paper_prices false: the date, the copier, one line per segment, paper, extras; no money, no total",
      h[1] == "IM C4510" and [r[0] for r in rws] == ["A4 B&W: 37 prints", "A4 colour: 6 prints", "Staple x 2", "Cutting x 4"]
      and all(r[1] == "" for r in rws) and tot is None, (h, rws, tot))
h2, rws2, tot2 = cc.receipt_rows(cnt, cnt.priced(), True)
check("…true: the prices and the total (the rounded one)", [r[1] for r in rws2] == ["3.70", "1.80", "0.86", "0.10", "0.40"]
      and tot2 == "EUR 7.00", (rws2, tot2))
shop = json.loads((APP / "prices.json").read_text(encoding="utf-8")).get("shop_name", "COPY CENTER")
every = " ".join(h + [a + " " + b for a, b in rws] + h2 + [a + " " + b for a, b in rws2] + [tot2])
check("…in both: no shop name, no ORCA, no PrintHub", shop not in every and "ORCA" not in every and "PrintHub" not in every)
for name, rr, tt in (("receipt_no_prices", rws, tot), ("receipt_with_prices", rws2, tot2)):
    path = OUT / f"{name}.pdf"
    receipt.lines_pdf(path, h, rr, tt)
    with jobs.PDF_LOCK:
        dd = pdfium.PdfDocument(str(path)); dd[0].render(scale=1).to_pil().save(OUT / f"{name}.png"); dd.close()
RECEIPTS.clear()
S.print_receipt("C4510"); pump(2, until=lambda: RECEIPTS)
check("Print receipt sends it to the receipt printer (rules.json receipt_printer) through the receipt path",
      RECEIPTS and RECEIPTS[0][1] == rules["receipt_printer"], RECEIPTS)
# Done
n_sales, k = len(sales()), len(SENT)
S.done("C4510"); pump(1.5)
line = sales()[-1]
check("Done writes sales_log.csv: source copy counter, the date, the copier, the segments in short, the rounded total",
      line["source"] == "copy counter" and line["copier"] == "IM C4510" and line["date"] == datetime.date.today().isoformat()
      and line["items"] == "A4 B&W x 37; A4 colour x 6; Staple x 2; Cutting x 4" and line["paid"] == "7.00"
      and len(sales()) == n_sales + 1, line)
logs = log_lines()
check("…and print_log.csv one line per segment (source walk-in, order copy counter, size, colour / B&W sides, paper)",
      len(logs) == 2 and all(e["source"] == "walk-in" for e in logs)
      and [(e["size"], e["color"], e["bw"], e["paper"]) for e in logs] == [("A4", 0, 37, "Smooth white 80 gsm"),
                                                                         ("A4", 6, 0, "Smooth white 80 gsm")],
      [(e["size"], e["color"], e["bw"], e["paper"]) for e in logs])
today = datetime.date.today()
import costs
walk = counter.sections(counter.read_log(), today, today, costs.Costs(costs.load(rules)))[1][1]
check("…the Counter counts these copies as Walk-in (37 B&W + 6 colour A4 sides added)",
      walk["sizes"]["A4"]["bw"] >= 37 and walk["sizes"]["A4"]["color"] >= 6, walk["sizes"])
check("…the copier is Free again and the queues send again (the waiting order went to the IM C4510)",
      not copier_queue.held("C4510") and "C4510" not in M.counters and any(s[0] == Q4510 for s in SENT[k:]),
      SENT[k:])
# Cancel writes nothing
READ["C3000"] = 5000
S.start("C3000"); READ["C3000"] = 5010; M.counters["C3000"].poll()
n_sales, n_logs = len(sales()), len(counter.read_log())
asked.clear(); S.cancel("C3000"); pump(0.2)
check("Cancel asks “Stop counting and throw these copies away?”, writes nothing, frees the copier",
      asked == ["Stop counting and throw these copies away?"] and len(sales()) == n_sales
      and len(counter.read_log()) == n_logs and not copier_queue.held("C3000") and "C3000" not in M.counters)
# A3 colour with a3 counts as 2
M.rules = dict(rules, copy_counter_a3_counts_as=2)
S.start("C3000"); c2 = M.counters["C3000"]
S.change("C3000", type="A3 colour"); READ["C3000"] = 5016; c2.poll()
check("A3 colour with copy_counter_a3_counts_as 2 and a counter difference of 6 gives 3 copies", c2.current_copies() == 3,
      c2.current_copies())
S.change("C3000", type="A4 B&W"); S.change("C3000", sides="double")
READ["C3000"] = 5026; c2.poll()
seg = c2.segments_now()[-1]
p2 = c2.priced()
check("Both sides with 10 copies gives 5 sheets of paper", seg["copies"] == 10 and seg["sides"] == "double"
      and ("Smooth white 80 gsm: 5 A4 sheets", 0.1) in p2["lines"], p2["lines"])
M.rules = rules
S.cancel("C3000"); pump(0.1)
# a copier that doesn't answer
DOWN.add("C3000")
S.start("C3000"); pump(0.1)
check("a copier that doesn't answer: says so and offers Type the copies instead", "C3000" not in M.counters
      and any("doesn't answer" in x for x in texts(S.panels["C3000"])) and "Type the copies instead" in texts(S.panels["C3000"]),
      texts(S.panels["C3000"]))
S.start("C3000", typed=True); pump(0.1)
S.add_typed("C3000", "12"); pump(0.1)
check("…typed counts: a segment of 12, the copier held", M.counters["C3000"].data["segments"][0]["copies"] == 12
      and copier_queue.held("C3000"))
S.add_typed("C3000", "1.5"); pump(0.1)
check("…a typed count must be a whole number", "whole number" in S.messages.get("C3000", ""))
S.cancel("C3000"); DOWN.clear(); pump(0.1)
# the trial sheet: everything 0.00
shutil.copyfile(APP / "Walk-in_Prices.xlsx", SHEET); time.sleep(0.05)
pl = wp.current()
pt = cc.price(pl, [{"type": t, "paper": "Smooth white 80 gsm", "sides": s, "copies": 7} for t in cc.TYPES for s in ("single", "double")],
              [{"name": n, "count": 3, "per_copy": 10 if n == "Spiral binding" else None} for n, _ in cc.extra_rows(pl)])
check("with the trial sheet everything is 0.00 (no problems)", pl.trial and pt["total"] == 0 and not pt["problems"], pt["problems"])
# an empty needed cell blocks the receipt
holes = TMP / "holes.xlsx"
ps.test_sheet(EMPTY, holes, {"Copies": {ps.cell(EMPTY, "Copies", "A4 colour", col=1): None}})
ph_ = cc.price(wp.load(holes), [{"type": "A4 colour", "paper": "Smooth white 80 gsm", "sides": "single", "copies": 3}], [])
check("an empty needed cell is named, as in 08 (and Print receipt / Done wait for it)",
      ph_["problems"] == ["No price for A4 colour copies, Tier 1: fill it in in Walk-in_Prices.xlsx"], ph_["problems"])
check("copy_counter.json holds no finished counter after Done / Cancel", json.loads((wo.open_dir() / "copy_counter.json").read_text(encoding="utf-8")).keys() <= {"C3004"})
S.cancel("C3004"); pump(0.1)
S.back(); pump(0.2)
print(f"\n{sum(results)}/{len(results)} passed")
root.destroy()
