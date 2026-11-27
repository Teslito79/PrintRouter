"""Main menu, Counter, Prices. Everything in a temp folder; simulated copiers and a pretend website."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import csv, ctypes, datetime, http.server, json, os, shutil, sys, threading, time, tkinter as tk
from pathlib import Path

ctypes.windll.shcore.SetProcessDpiAwareness(1)
APP = helpers.APP
TMP, SHOTS = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True); SHOTS.mkdir(parents=True, exist_ok=True)
for f in ("prices.json",):
    shutil.copyfile(APP / f, TMP / f)
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (TMP / d).mkdir()
URL = "http://127.0.0.1:8768"
rules.update(pending_folder=str(TMP / "pending"), orders_folder=str(TMP / "orders"),
             finished_folder=str(TMP / "finished"), templates_folder=str(APP / "templates"),
             website={"url": URL, "check_seconds": 60})
(TMP / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: TMP
import jobs, orders, printhub, driverprint, sync, costs, counter, mainmenu
from tkinter import messagebox
import pypdfium2 as pdfium
from PIL import ImageGrab

driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
driverprint.build_devmode = lambda *a, **k: None
SENT = []
driverprint.print_pdf = lambda pdf, q, dm, name, **k: SENT.append((q, name))
printhub.WORK_DIR = TMP / "phwork"
(TMP / sync.TOKEN_FILE).write_text("test-token-not-real", encoding="utf-8")

results = []


def check(name, ok, info=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name, "|", info)


def pdf(path, w_mm, h_mm, pages=1):
    d = pdfium.PdfDocument.new()
    for _ in range(pages):
        d.new_page(w_mm / 25.4 * 72, h_mm / 25.4 * 72)
    d.save(str(path)); d.close()


# ---------------------------------------------------------------- pretend website: one order
(TMP / "files").mkdir()
pdf(TMP / "files" / "doc.pdf", 210, 297, 2)
feed = {"format": 1, "orders": [{"order": {"format": 1, "order": "PH-30000",
                                           "paid_at": datetime.datetime.now().astimezone().isoformat(),
                                           "delivery": "pickup", "steps": ["PRINT"], "documents": ["01"]},
                                 "items": [{"folder": "01", "job": {"format": 1, "file": "doc.pdf", "pages": 2, "copies": 1,
                                                                    "color": "bw", "sides": "single", "paper": "A4",
                                                                    "per_side": 1, "paper_type": "Plain & Recycled"},
                                            "files": [{"name": "doc.pdf", "url": f"{URL}/files/doc.pdf"}]}]}]}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        raw = json.dumps(feed).encode() if self.path == "/api/printrouter/orders" else \
            (TMP / "files" / self.path[7:]).read_bytes() if self.path.startswith("/files/") else None
        if raw is None:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")


server = http.server.ThreadingHTTPServer(("127.0.0.1", 8768), H)
threading.Thread(target=server.serve_forever, daemon=True).start()

# ---------------------------------------------------------------- an order waiting at Print backs
o = TMP / "orders" / "PH-30001"
(o / "01").mkdir(parents=True)
pdf(o / "01" / "doc.pdf", 210, 297, 4)
(o / "01" / "job.json").write_text(json.dumps({"format": 1, "file": "doc.pdf", "pages": 4, "copies": 2, "color": "color",
                                               "sides": "long", "paper": "A4", "per_side": 1,
                                               "paper_type": "Thick 4(257 to 300 g/m2)"}), encoding="utf-8")
(o / "order.json").write_text(json.dumps({"format": 1, "order": "PH-30001", "paid_at": "2026-11-15T09:00:00+02:00",
                                          "delivery": "pickup", "steps": ["PRINT"], "documents": ["01"]}),
                              encoding="utf-8")

root = tk.Tk(); root.withdraw()


def pump(cond=lambda: False, secs=3):
    end = time.time() + secs
    while time.time() < end and not cond():
        root.update(); time.sleep(0.03)
    for _ in range(5):
        root.update(); time.sleep(0.02)


def all_widgets(w):
    return [w] + [c for ch in w.winfo_children() for c in all_widgets(ch)]


def shown(w):
    return w.winfo_exists() and w.state() != "withdrawn"


def shot(window, name):
    import window_shot  # ORCA's own window only (PrintWindow), never the screen
    window.lift(); pump(secs=1.2)
    window_shot.shot(window, SHOTS / name)


def walkin_win():
    return next((w for w in reversed(root.winfo_children()) if isinstance(w, tk.Toplevel) and w.winfo_exists()
                 and w.title().startswith("ORCA - Walk-in")), None)


# ---------------------------------------------------------------- the test log (written first: every print
# below, the PrintHub hand-turned one too, is added to it, as it happened before)
log = TMP / jobs.LOG_FILE
# Start from an old-format log (14 columns): it must keep its lines and get the new header.
old = [["time", "file", "pages", "copies", "color", "sides", "paper", "paper type", "tray", "content", "printer",
        "reason", "sheets", "price"],
       ["2025-12-30 10:00:00", "PH-10011 01 menu.pdf", "2", "3", "color", "single", "A4", "Plain & Recycled",
        "Auto Tray Select", "document", "MP C3004", "Color document", "6", "1.20"],
       ["2026-11-15 09:00:00", "flyer.pdf", "1", "4", "bw", "single", "A3", "Plain & Recycled",
        "Auto Tray Select", "document", "IM C4510", "Black & white", "4", "0.80"],
       ["broken line"], ["2026-11-15 09:30:00", "half", "x"]]
with open(log, "w", newline="", encoding="utf-8-sig") as f:
    csv.writer(f).writerows(old)
start = time.time()
menu = mainmenu.MainMenu(root)
pump(secs=1)
check("start: only the menu shows", shown(menu.win) and walkin_win() is None, menu.win.state())
pump(lambda: (TMP / "pending" / "PH-30000").exists(), 60)
check("with the menu showing, the website order downloads within a minute",
      (TMP / "pending" / "PH-30000").exists(), f"{time.time() - start:.0f} s; {menu.sync_label.cget('text')}")
pump(secs=3)
check("menu shows the sync line", menu.sync_label.cget("text") == "Website sync: on", menu.sync_label.cget("text"))
shot(menu.win, "menu.png")

# Walk-in (the walk-in orders menu since 2026-11-17): open, Back, X
menu.open_walkin(); pump()
W = walkin_win()
check("Walk-in opens and hides the menu", W is not None and shown(W) and not shown(menu.win))
check("Walk-in has no PrintHub button", not any(w.winfo_class() == "TButton" and w.cget("text") == "PrintHub"
                                                for w in all_widgets(W)))
next(w for w in all_widgets(W) if w.winfo_class() == "TButton" and w.cget("text").endswith("Back")).invoke(); pump()
check("Back returns to the menu", shown(menu.win) and not (W.winfo_exists() and shown(W)))
menu.open_walkin(); pump()
W = walkin_win()
W.tk.eval(W.protocol("WM_DELETE_WINDOW"))  # the X
pump()
check("Walk-in: X returns to the menu", shown(menu.win) and not (W.winfo_exists() and shown(W)))

# PrintHub: order to Print backs, back, reopen
menu.open_printhub(); ph = menu.printhub
pump(lambda: any(x.number == "PH-30001" and x.documents and x.documents[0].pdf for x in ph.orders), 10)
check("PrintHub opens and hides the menu", shown(ph.win) and not shown(menu.win))
ph.start_printing()
order = next(x for x in ph.orders if x.number == "PH-30001")
pump(lambda: ph.part_state(order, "C3000") == "turn", 10)
check("order waiting at Print backs", ph.part_state(order, "C3000") == "turn", ph.part_state(order, "C3000"))
ph.win.protocol("WM_DELETE_WINDOW")  # the X
ph.back(); pump()
check("PrintHub X/Back returns to the menu", shown(menu.win) and not shown(ph.win))
menu.open_printhub(); pump()
check("same PrintHub, still at Print backs after reopening", menu.printhub is ph and ph.part_state(order, "C3000") == "turn"
      and "Print backs" in [b.cget("text") for b in ph.panels["C3000"]["buttons"].winfo_children()])
log_before = len(counter.read_log())
ph.send_backs("C3000")
pump(lambda: ph.part_state(order, "C3000") == "sent", 10)
lines = [e for e in counter.read_log() if e["order"] == "PH-30001"]
check("hand-turned job: one log line with both sides", len(lines) == 1 and lines[0]["color"] == 8 and lines[0]["sheets"] == 4
      and lines[0]["source"] == "printhub" and lines[0]["product"] == "Document", lines)
ph.collected("C3000"); pump()
ph.back(); pump()

# Counter opens and backs
c = None
menu.open_counter(); pump()
cw = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "ORCA - Counter"]
check("Counter opens and hides the menu", cw and shown(cw[0]) and not shown(menu.win))
cw[0].destroy(); menu.show_menu(); pump()

J = menu.jobs


def walk(name, s, pages, colors):
    job = J.job_for(name, s, pages, 20.0, colors, busy=set())
    J.log(job, "x")


base = {"color": "bw", "printer": "auto", "sides": "single", "paper": "A4", "per_side": "1",
        "paper_type": "Plain & Recycled", "tray": "Auto Tray Select", "copies": "2", "rotate": "0"}
walk("a_bw.pdf", base, 3, [False] * 3)                                                   # 6 bw, 6 sheets
walk("b_colour.pdf", dict(base, color="color", sides="long", copies="5"), 2, [True, True])  # 10 colour, 5 sheets
walk("c_mixed.pdf", dict(base, color="auto", copies="3"), 4, [True, False, True, False])    # 6 colour 6 bw, 12 sheets
d = orders.Document("01", TMP); d.kind, d.print_paper, d.pages = "product", "A3", 1
d.job = {"name": "Flyers", "quantity": 200, "options": {"Paper": "Silk 300 gsm", "Sides": "One side"}, "cut_mm": [297, 420]}
s = d.product_settings(20, d.default_paper_type(rules), "single", rules)
job = J.job_for("PH-40000 01 Flyers", s, 1, 20.0, [True], printhub.PRODUCT_MAX_SHEETS, busy=set())
job["log_info"] = {"source": "printhub", "order": "PH-40000", "product": "Flyers", "quantity": 200, "paper_name": "Silk 300 gsm"}
J.log(job, "x")                                                                            # A3 20 colour, 20 sheets
d2 = orders.Document("01", TMP); d2.kind, d2.print_paper, d2.pages = "product", "A4", 2
d2.job = {"name": "Business cards", "quantity": 100, "options": {"Paper": "Silk 300 gsm", "Sides": "Both sides"}, "cut_mm": [85, 55]}
s2 = d2.product_settings(13, d2.default_paper_type(rules), orders.HAND, rules)
job2 = J.job_for("PH-40001 01 Cards", s2, 2, 20.0, [True, True], printhub.PRODUCT_MAX_SHEETS, busy=set())
printhub.hand_job(job2)
job2["log_info"] = {"source": "printhub", "order": "PH-40001", "product": "Business cards", "quantity": 100,
                    "paper_name": "Silk 300 gsm", "file": "PH-40001 01 Cards"}
J.log(job2, "x")                                                                           # A4 26 colour, 13 sheets

with open(log, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.reader(f))
check("old log kept its lines and got the new header", rows[0] == jobs.LOG_COLUMNS and rows[1][1] == "PH-10011 01 menu.pdf"
      and rows[2][1] == "flyer.pdf" and len(rows) == 1 + 4 + 2 + 5, len(rows))
# Spread the new lines (rows 5..) over the dates; the PH-30001 line from the PrintHub test stays first. PH-30000
# (the downloaded website order, printed by Start printing too) isn't part of the Counter's sums below.
rows = [r for r in rows if not (len(r) >= 22 and r[1].startswith("PH-30000"))]
new_rows = [r for r in rows[1:] if len(r) >= 22]
dates = {"a_bw.pdf": "2026-11-15", "b_colour.pdf": "2026-11-14", "c_mixed.pdf": "2026-11-10",
         "PH-40000 01 Flyers": "2026-11-05", "PH-40001 01 Cards": "2026-10-20", "PH-30001 01 01": "2026-11-13"}
for r in new_rows:
    r[0] = dates[r[1]] + " 12:00:00"
with open(log, "w", newline="", encoding="utf-8-sig") as f:
    csv.writer(f).writerows(rows)

entries = counter.read_log()
check("broken lines skipped, every other line read", len(entries) == 8, len(entries))
by = {e["order"] or e["paper"] + str(e["sheets"]): e for e in entries}
mixed = next(e for e in entries if e["sheets"] == 12)
check("mixed job split by page colour", (mixed["color"], mixed["bw"]) == (6, 6), mixed)
cards = [e for e in entries if e["order"] == "PH-40001"]
check("hand-turned product counts once, both sides", len(cards) == 1 and (cards[0]["color"], cards[0]["sheets"]) == (26, 13), cards)
old_ph = next(e for e in entries if e["order"] == "PH-10011")
old_walk = next(e for e in entries if e["sheets"] == 4 and e["size"] == "A3" and e["source"] == "walk-in")
check("old lines: PH- is PrintHub, sides = pages x copies", old_ph["source"] == "printhub" and old_ph["color"] == 6
      and old_walk["bw"] == 4)

# Expected totals per period, worked out by hand from the lines above
E = {  # name: (date, source, size, colour, bw, sheets)
    "old_ph": ("2025-12-30", "printhub", "A4", 6, 0, 6), "old_walk": ("2026-11-15", "walk-in", "A3", 0, 4, 4),
    "a": ("2026-11-15", "walk-in", "A4", 0, 6, 6), "b": ("2026-11-14", "walk-in", "A4", 10, 0, 5),
    "c": ("2026-11-10", "walk-in", "A4", 6, 6, 12), "flyers": ("2026-11-05", "printhub", "A3", 20, 0, 20),
    "cards": ("2026-10-20", "printhub", "A4", 26, 0, 13), "ph30001": ("2026-11-13", "printhub", "A4", 8, 0, 4)}


def expect(start, end, source=None):
    out = {}
    for date, src, size, cs, bs, sh in E.values():
        if start <= date <= end and (source is None or src == source):
            cell = out.setdefault(size, [0, 0, 0])
            cell[0] += cs; cell[1] += bs; cell[2] += sh
    return out


def got(summary):
    return {size: [v["color"], v["bw"], v["color_sheets"] + v["bw_sheets"]] for size, v in summary["sizes"].items()}


screen = counter.CounterScreen(root, rules, on_back=menu.show_menu, today=datetime.date(2026, 11, 15))
ranges = {"Today": ("2026-11-15", "2026-11-15"), "Yesterday": ("2026-11-14", "2026-11-14"),
          "This week": ("2026-11-09", "2026-11-15"), "This month": ("2026-11-01", "2026-11-30"),
          "This year": ("2026-01-01", "2026-12-31")}
check("Counter opens on This week", screen.chosen == "This week" and screen.range_label.cget("text") == "9 Nov - 15 Nov 2026",
      screen.range_label.cget("text"))
for name, (a, b) in list(ranges.items()) + [("custom", ("2025-12-01", "2026-10-31"))]:
    if name == "custom":
        screen.from_var.set("1/12/2025"); screen.to_var.set("31/10/2026"); screen.custom()
    else:
        screen.choose(name)
    pump(secs=0.2)
    (_, total), (_, walk), (_, hub) = screen.result
    ok = got(total) == expect(a, b) and got(walk) == expect(a, b, "walk-in") and got(hub) == expect(a, b, "printhub")
    summed = all(got(total).get(sz, [0, 0, 0])[i] == got(walk).get(sz, [0, 0, 0])[i] + got(hub).get(sz, [0, 0, 0])[i]
                 for sz in ("A3", "A4") for i in range(3))
    papers_ok = all(sum(p["sheets"] for p in sec["papers"]) == sum(v[2] for v in got(sec).values())
                    and sum(p["color"] for p in sec["papers"]) == sum(v[0] for v in got(sec).values())
                    and sum(p["bw"] for p in sec["papers"]) == sum(v[1] for v in got(sec).values())
                    for _, sec in screen.result)
    check(f"Counter {name} ({screen.range_label.cget('text')}): right sides and sheets; Walk-in + PrintHub = Total; By paper adds up",
          ok and summed and papers_ok, (got(total), expect(a, b)))
screen.choose("This year")
hub = screen.result[2][1]
check("PrintHub: orders printed and By product", hub["orders"] == 3
      and {p["product"]: (len(p["orders"]), p["pieces"], p["sheets"]) for p in hub["products"]}
      == {"Flyers": (1, 200, 20), "Business cards": (1, 100, 13), "Document": (1, 0, 4)}, hub["products"])

# ---------------------------------------------------------------- costs
data = costs.empty(rules)
data["copy"]["A3"]["color"] = 0.20
next(p for p in data["papers"] if p["name"] == "Silk 300 gsm")["A3"] = 0.05
table = costs.Costs(data)
one = table.job_cost("A3", 1, 0, 1, "Silk 300 gsm")
two = table.job_cost("A3", 2, 0, 1, "Silk 300 gsm")
check("one one-sided A3 colour sheet on Silk 300 costs 0.25", abs(one[0] - 0.25) < 1e-9 and not one[1], one)
check("the same sheet two-sided costs 0.45", abs(two[0] - 0.45) < 1e-9 and not two[1], two)
check("a paper with no cost is flagged", table.job_cost("A3", 1, 0, 1, "Gloss 300 gsm")[1] is True)
check("amounts: comma or point, 4 decimals", costs.parse_amount("0,20") == 0.2 and costs.parse_amount(" 0.0525 ") == 0.0525
      and costs.parse_amount("") is None)
for bad in ("abc", "-1", "0.12345"):
    try:
        costs.parse_amount(bad); check(f"'{bad}' refused", False)
    except ValueError:
        check(f"'{bad}' refused", True)

# ---------------------------------------------------------------- Prices: password and saving
asked = []
messagebox.askyesnocancel = lambda **k: asked.append(k["message"]) or False


def dialog(mode, *values):
    dlg = costs.PasswordDialog(menu.win, mode)
    for var, v in zip(dlg.vars, values):
        var.set(v)
    dlg.done()
    error = dlg.error.cget("text") if dlg.dlg.winfo_exists() else ""
    if dlg.dlg.winfo_exists():
        dlg.dlg.destroy()
    return dlg.ok, error


check("first open: no password yet, so Prices asks for a new one", not costs.has_password())
check("two different passwords refused", dialog("new", "kitten1", "kitten2") == (False, "The two passwords are not the same."))
check("new password set", dialog("new", "kitten1", "kitten1")[0] and costs.has_password())
stored = (TMP / costs.PASSWORD_FILE).read_text(encoding="utf-8")
check("only a salted hash is stored", "kitten1" not in stored and "salt" in stored)
check("a wrong password doesn't open Prices", dialog("ask", "dog") == (False, "Wrong password."))
check("the right password opens Prices", dialog("ask", "kitten1")[0])
check("Change password: a wrong old one is refused", dialog("change", "nope", "new2", "new2") == (False, "The old password is wrong."))
check("Change password works", dialog("change", "kitten1", "new2", "new2")[0] and dialog("ask", "new2")[0]
      and not dialog("ask", "kitten1")[0])

papers = sorted({e["paper"] for e in counter.read_log() if e["paper"]})
prices = costs.PricesScreen(root, rules, on_back=menu.show_menu, papers_in_log=papers + ["Odd paper from the log"])
check("papers from the log added to the list", any(r["vars"][0].get() == "Odd paper from the log" for r in prices.paper_rows))
prices.copy_vars[("A3", "color")].set("0,20")
prices.copy_vars[("A4", "color")].set("0.10")
prices.copy_vars[("A4", "bw")].set("0.03")
row = next(r for r in prices.paper_rows if r["vars"][0].get() == "Silk 300 gsm")
row["vars"][2].set("0.05"); row["vars"][1].set("0.03")
prices.add_paper_row("Kraft card", "0.12", "", True)
prices.add_cons_row("Laminating pouch A4", "piece", "0,15", True)
check("unsaved changes noticed", prices.changed())
prices.back()
check("Back with unsaved changes asks first", asked == ["Save the changes before going back?"])
prices = costs.PricesScreen(root, rules, on_back=menu.show_menu)
check("'No' at the question saves nothing", not (TMP / costs.COSTS_FILE).exists())
prices.copy_vars[("A3", "color")].set("0,20")
prices.copy_vars[("A4", "color")].set("0.10")
prices.copy_vars[("A4", "bw")].set("0.03")
row = next(r for r in prices.paper_rows if r["vars"][0].get() == "Silk 300 gsm")
row["vars"][2].set("0.05"); row["vars"][1].set("0.03")
prices.add_paper_row("Kraft card", "0.12", "", True)
prices.add_cons_row("Laminating pouch A4", "piece", "0,15", True)
check("Save", prices.save() and not prices.changed())
prices.win.destroy()
prices = costs.PricesScreen(root, rules, on_back=menu.show_menu)  # as after a restart
saved = costs.load(rules)
check("costs survive a restart", prices.copy_vars[("A3", "color")].get() == "0.20"
      and next(p for p in saved["papers"] if p["name"] == "Silk 300 gsm")["A3"] == 0.05
      and any(p["name"] == "Kraft card" for p in saved["papers"])
      and saved["consumables"] == [{"name": "Laminating pouch A4", "unit": "piece", "cost": 0.15}])
prices.win.geometry("900x860+40+40"); pump(secs=0.5)
shot(prices.win, "prices.png")
prices.win.destroy()

screen.choose("This year")
total = screen.result[0][1]
check("Counter cost uses the Prices", total["missing"] is True and total["cost"] > 0, (total["cost"], total["missing"]))
screen.win.geometry("1000x1000+40+20"); pump(secs=0.5)
shot(screen.win, "counter.png")
screen.scroll.canvas.yview_moveto(0.55); pump(secs=0.3)
shot(screen.win, "counter_printhub.png")
screen.win.destroy()

server.shutdown()
check("nothing reached a real copier (sending was simulated)", all(q.startswith("RICOH") for q, _ in SENT), len(SENT))
root.destroy()
print("ALL OK" if all(results) else "SOME FAILED", f"{sum(results)}/{len(results)}")
