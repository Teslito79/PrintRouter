"""Handoff 2026-11-18_01: the Copy counter reads the copier's counter page. Temp copy of the folder layout; the
copiers' pages are HTML fixtures built from Tesla's readings (page_fixtures.py), served by a small HTTP server on
127.0.0.1 or handed to the counter by a pretend copier; no real copier, the receipt printer faked; a picture of
ORCA's own window only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, http.server, json, os, shutil, sys, threading, time, tkinter as tk
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
import appicon, copier_queue, copy_counter as cc, counter_page as cp, driverprint, mainmenu, printing, toners
import walkin_orders as wo, walkin_prices as wp, walkin_screens as ws
import page_fixtures as F
from tkinter import messagebox, ttk
import window_shot

results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:600])


def reading(page):
    return cc.from_page(cp.parse(page))


def kinds(entries):
    return [(e["type"], e["sides"], e["copies"], e.get("sheets")) for e in entries]


# ------------------------------------------------------------------ the page server (HTTP on 127.0.0.1)
SERVE = {"page": F.c4510(1), "status": 200}


class Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != cp.PATH:
            self.send_response(404); self.end_headers(); return
        body = SERVE["page"].encode("utf-8")
        self.send_response(SERVE["status"]); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
real_url = cp.url
cp.url = lambda address: real_url(address).replace("http://127.0.0.1/", f"http://127.0.0.1:{PORT}/")
check("the page's address is the copier's host on the web port (a typed “:port” for SNMP is left out)",
      real_url("192.168.10.85") == "http://192.168.10.85/web/guest/en/websys/status/getUnificationCounter.cgi"
      and real_url("192.168.10.85:161") == "http://192.168.10.85/web/guest/en/websys/status/getUnificationCounter.cgi")

# ------------------------------------------------------------------ parsing Tesla's readings
r1, r2, r3 = (reading(F.c4510(n)) for n in (1, 2, 3))
check("IM C4510 reading 1: the Copier section's sheets by colour and size, and the Total Counter",
      r1["how"] == "sheets" and r1["total"] == 656415 and r1["copier"]["bw"]["s_other"] == 83021
      and r1["copier"]["color"]["s_a3"] == 1247 and set(r1["copier"]["bw"]) == {"s_a3", "s_other", "d_a3", "d_other"}, r1)
check("…the Copier rows are read, not the Total or Printer rows with the same labels",
      r1["copier"]["bw"]["d_other"] == 71500 and r1["copier"]["color"]["s_other"] == 6100, r1["copier"])
c3000 = reading(F.c3000())
check("IM C3000 (no Banner columns) parses like the IM C4510",
      c3000["how"] == "sheets" and c3000["copier"] == {"color": {"s_a3": 3308, "s_other": 23710, "d_a3": 388, "d_other": 6044},
                                                      "bw": {"s_a3": 15924, "s_other": 167246, "d_a3": 2330, "d_other": 145979}},
      c3000)
c3004 = reading(F.c3004())
check("MP C3004: its own layout, B&W / colour copier totals, the top Total, and Other Function(s) recorded",
      c3004["how"] == "pages" and c3004["total"] == 1207997
      and c3004["copier"] == {"color": {"pages": 49919}, "bw": {"pages": 318002}}
      and c3004["other"] == {"A3/DLT": 72281, "Duplex": 283975, "Banner": 1}, c3004)
squashed = F.c4510(1).replace("\n", " ").replace("<td>", "<td>  \n ").replace(" :", "\n:")
check("labels are matched with any spaces and line breaks between them", reading(squashed) == r1)
try:
    reading("<html><body>Login required</body></html>")
    garbled = False
except cp.PageError:
    garbled = True
check("a page ORCA doesn't know is refused (PageError), never half read", garbled)

# ------------------------------------------------------------------ the copier's own split, without the screen
M = cc.Manager(rules, read_func=lambda pid: READ[pid])
READ = {"C4510": r1, "C3000": c3000, "C3004": c3004}
cnt = M.start("C4510")
check("Start with the page readable: the sheets reading, and the copier is NOT held",
      cnt.how == "sheets" and not copier_queue.held("C4510"), (cnt.how, copier_queue.HELD))
check("reading 1 to 2: A4 B&W 2 prints on 2 sheets, nothing else", kinds(cnt.counted(r2)) == [("A4 B&W", "single", 2, 2)],
      cnt.counted(r2))
check("reading 2 to 3: A3 colour 1 copy on 1 A3 sheet", kinds(cnt.counted(r3, start=r2)) == [("A3 colour", "single", 1, 1)],
      cnt.counted(r3, start=r2))
cnt.data["current"]["type"] = "A3 colour"
cnt.data["how"] = "total"
check("…the total-counter fallback with copy_counter_a3_counts_as 2 gives 1 too (656417 to 656419)",
      cc.a3_counts_as(rules) == 2 and kinds(cnt.counted({"how": "total", "total": 656419}, start={"total": 656417}))
      == [("A3 colour", "single", 1, None)], cnt.counted({"how": "total", "total": 656419}, start={"total": 656417}))
cnt.data["how"], cnt.data["current"]["type"] = "sheets", "A4 B&W"
dup = reading(F.c4510_raw(656425, bw=(227385, (512, 83021), (306, 71505)), fc=(14063, (1247, 6100), (80, 3200))))
check("duplex: 5 both-sides A4 B&W sheets give 10 prints on 5 sheets", kinds(cnt.counted(dup)) == [("A4 B&W", "double", 10, 5)],
      cnt.counted(dup))
mixed = reading(F.c4510_raw(656430, bw=(227377, (514, 83021), (306, 71500)), fc=(14066, (1247, 6103), (80, 3200))))
seg = cnt.counted(mixed)
check("mixed: A4 colour and A3 B&W in one segment are both counted",
      kinds(seg) == [("A3 B&W", "single", 2, 2), ("A4 colour", "single", 3, 3)], seg)
for e in seg:
    e["paper"] = cc.FIRST_PAPER
p = cc.price(wp.current(), seg, [])
check("…each priced on its own line (19_02: by size and colour, then the paper by size)",
      p["lines"] == [("A4 colour: 3 prints", 0.9), ("A3 B&W: 2 prints", 0.4), ("Smooth white 80 gsm: 2 A3 sheets", 0.08),
                     ("Smooth white 80 gsm: 3 A4 sheets", 0.06)] and p["total"] == 1.44, p["lines"])
READ["C4510"] = dup
cnt.poll()
check("the segment line: “A4 B&W: 10 prints on 5 sheets (both sides)” (19_02: the paper is given at Finish)",
      cnt.lines() == ["A4 B&W: 10 prints on 5 sheets (both sides)"], cnt.lines())
both = reading(F.c4510_raw(656440, bw=(227400, (512, 83038), (306, 71508)), fc=(14063, (1247, 6100), (80, 3200))))
READ["C4510"] = both
cnt.poll()
check("…one side and both sides of one type: “A4 B&W: 33 prints on 25 sheets (17 one side, 8 both sides)”",
      cnt.lines() == ["A4 B&W: 33 prints on 25 sheets (17 one side, 8 both sides)"], cnt.lines())
M.cancel("C4510")

# ------------------------------------------------------------------ the real read(): the page over HTTP, the SNMP fallback
toners.save_settings({"community": "public", "addresses": {"C4510": "127.0.0.1", "C3000": "127.0.0.1", "C3004": "127.0.0.1"}})
SNMP = {"total": 656415, "asked": 0}


def fake_total(address, community="public", timeout=None):
    SNMP["asked"] += 1
    return SNMP["total"]


toners.read_total = fake_total
SERVE["page"] = F.c4510(1)
got = cc.read("C4510", rules)
check("read(): the counter page fetched over HTTP (GET, no login) and parsed; SNMP not needed",
      got == r1 and SNMP["asked"] == 0, got)
SERVE["page"] = "<html><body>Something else</body></html>"
got = cc.read("C4510", rules)
check("read(): a garbled page falls back to the SNMP total counter", got == {"how": "total", "total": 656415}
      and SNMP["asked"] == 1, got)
SERVE["status"] = 500
got = cc.read("C4510", rules)
check("read(): a page that fails (HTTP 500) falls back too", got == {"how": "total", "total": 656415}, got)
SERVE["status"] = 200
srv_closed = http.server.HTTPServer(("127.0.0.1", 0), Site); dead = srv_closed.server_address[1]; srv_closed.server_close()
cp.url = lambda address: f"http://127.0.0.1:{dead}{cp.PATH}"
t0 = time.time()
got = cc.read("C4510", rules)
check("read(): no web server at all: the SNMP total, quickly", got["how"] == "total" and time.time() - t0 < 6, time.time() - t0)
cp.url = lambda address: real_url(address).replace("http://127.0.0.1/", f"http://127.0.0.1:{PORT}/")

# ------------------------------------------------------------------ the screen
ws.ask_keep = lambda parent: True
ws.ask_add = lambda *a, **k: "new"  # 24_02: an open order of this customer -> New order
messagebox.askyesno = lambda *a, **k: True
messagebox.showwarning = lambda **k: None
RECEIPTS = []
printing.send = lambda pdf, queue, settings=None: RECEIPTS.append((str(pdf), queue))
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers in the test"))
toners.TIMEOUT = 0.2
root = tk.Tk(); root.withdraw(); appicon.apply(root)
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2
run = menu.print_queue
MM = menu.copy_counter
MM.read_func = lambda pid: READ[pid]
READ.update(C4510=r1, C3000=c3000, C3004=c3004)


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


def radios(w):
    return [x.cget("text") for x in widgets(w, "TRadiobutton")]


walkin = ws.WalkinScreen(menu, on_back=menu.show_menu)
pump(0.5)
walkin.open_copy_counter(); pump(0.6)
import gc
S = [x for x in gc.get_objects() if isinstance(x, ws.CopyCounterScreen)][-1]
S.win.geometry("1500x980+10+10"); pump(0.4)
S.start("C4510"); pump(0.2)
c = MM.counters["C4510"]
panel = S.panels["C4510"]
check("detailed mode: Start counting with the page readable, the copier not held, the walk-in queue not held",
      c.how == "sheets" and not copier_queue.held("C4510") and run.copier_text("C4510") != copier_queue.HELD_TEXT,
      (c.how, run.copier_text("C4510")))
check("…the copy type buttons and One side / Both sides are hidden; only the paper is picked",
      radios(panel) == [] and any(isinstance(x, ttk.Combobox) for x in widgets(panel))
      and S.HOW_HINTS["sheets"] in texts(panel) and cc.FALLBACK_TEXT not in texts(panel), radios(panel))
menu.open_printhub(); pump(0.8)
ph = menu.printhub
ph.refresh(); pump(0.2)
check("…PrintHub's IM C4510 block isn't held either", ph.panels["C4510"]["state"].cget("text") != copier_queue.HELD_TEXT,
      ph.panels["C4510"]["state"].cget("text"))
ph.win.withdraw()
check("…and the copier doesn't count as busy for routing", "C4510" not in menu.jobs.busy(), menu.jobs.busy())
READ["C4510"] = r2
S.tick(); pump(1.5, until=lambda: c.current_copies() == 2); pump(0.2)
check("the copier counts by itself: reading 1 to 2 shows “A4 B&W 2 prints, on 2 A4 sheets”",
      "A4 B&W 2 prints, on 2 A4 sheets" in texts(panel), texts(panel))
# 19_02: no paper while counting: one count from Start to Finish
READ["C4510"] = r3
c.poll(); S.refresh_live("C4510"); pump(0.2)
check("one count from Start to Finish: “A4 B&W 2, A3 colour 1 prints, on 2 A4 + 1 A3 sheets”",
      "A4 B&W 2, A3 colour 1 prints, on 2 A4 + 1 A3 sheets" in texts(panel) and not c.data["segments"], texts(panel))
window_shot.shot(S.win, OUT / "copy_counter_detailed.png")
# Finish: the Copier section must stand still, the total may move with ORCA's prints
READS = iter([r3, dict(r3, total=r3["total"] + 7), dict(r3, total=r3["total"] + 9)])
MM.read_func = lambda pid: next(READS)
slept = []
steady = c.finish(sleep=slept.append, clock=lambda: 0)
check("Finish: the Copier section standing still is enough, even while ORCA's prints move the total",
      steady and slept == [3] and c.data["finished"], slept)
priced = c.priced()
check("…priced from the copier's counts: A4 B&W 2 x 0.10 + 2 A4 sheets, A3 colour 1 x 0.60 + its paper",
      ("A4 B&W: 2 prints", 0.2) in priced["lines"] and ("A3 colour: 1 print", 0.6) in priced["lines"]
      and ("Smooth white 80 gsm: 2 A4 sheets", 0.04) in priced["lines"], priced)
S.build("C4510"); pump(0.2)
k = len(wo.read_sales())
MM.done("C4510"); S.build("C4510"); pump(0.2)
sale = wo.read_sales()[-1]
check("Done: the sale is written, the panel is Free", len(wo.read_sales()) == k + 1 and sale["items"].startswith(
    "A4 B&W x 2; A3 colour x 1") and "Free" in texts(panel), sale)

# ------------------------------------------------------------------ page down while counting: the fallback
MM.read_func = lambda pid: READ[pid]
READ["C4510"] = r1
S.start("C4510"); pump(0.2)
c = MM.counters["C4510"]
READ["C4510"] = r2
c.poll()
READ["C4510"] = {"how": "total", "total": 656418}  # the page stopped answering: read() gave the SNMP total
S.tick(); pump(1.5, until=lambda: c.how == "total"); pump(0.3)
check("page down while counting: the fallback, with its yellow line “Counting from the total counter: pick the copy type”",
      c.how == "total" and cc.FALLBACK_TEXT in texts(panel)
      and [x for x in widgets(panel, "TLabel") if x.cget("text") == cc.FALLBACK_TEXT][0].cget("style").__str__().endswith("Warn.TLabel")
      and ttk.Style(root).lookup([x for x in widgets(panel, "TLabel") if x.cget("text") == cc.FALLBACK_TEXT][0].cget("style"), "foreground") == ws.theme.WARN,
      texts(panel))
check("…the copy type buttons and the sides return", radios(panel)[:4] == list(cc.TYPES) and "Both sides" in radios(panel),
      radios(panel))
check("…the hold comes back (the walk-in queue shows it)", copier_queue.held("C4510")
      and run.copier_text("C4510") == copier_queue.HELD_TEXT, run.copier_text("C4510"))
check("…the 2 copies read from the page are kept, and the count goes on from the last page reading's Total Counter",
      kinds(c.data["segments"]) == [("A4 B&W", "single", 2, 2)] and c.data["start"]["total"] == 656417
      and c.current_copies() == 1, (c.data["segments"], c.data["start"], c.current_copies()))
MM.cancel("C4510"); S.build("C4510"); pump(0.2)
check("Cancel lets the held copier go", not copier_queue.held("C4510"))
READ["C4510"] = {"how": "total", "total": 656418}
S.start("C4510"); pump(0.2)
c = MM.counters["C4510"]
check("Start with the page down: 10's way, held, with the yellow line and the type buttons",
      c.how == "total" and copier_queue.held("C4510") and cc.FALLBACK_TEXT in texts(panel) and "A3 colour" in radios(panel))
MM.cancel("C4510"); S.build("C4510"); pump(0.2)

# ------------------------------------------------------------------ MP C3004 mode
S.start("C3004"); pump(0.2)
c = MM.counters["C3004"]
p3 = S.panels["C3004"]
check("MP C3004 mode: held, with A4 / A3 and the sides to pick, no copy type buttons",
      c.how == "pages" and copier_queue.held("C3004") and run.copier_text("C3004") == copier_queue.HELD_TEXT
      and radios(p3) == ["A4", "A3", "One side", "Both sides"] and S.HOW_HINTS["pages"] in texts(p3), radios(p3))
READ["C3004"] = reading(F.c3004(bw=318005, fc=49921, p_bw=700040, total=1208042, other=(72281, 284010, 1)))
c.poll(); S.refresh_live("C3004"); pump(0.2)
check("…3 B&W and 2 colour copier pages with A4 picked: B&W 3 and colour 2 counted by themselves (prints ignored)",
      kinds(c.segments_now()) == [("A4 B&W", "single", 3, None), ("A4 colour", "single", 2, None)], c.segments_now())
S.change("C3004", sides="double"); pump(0.2)
saved = json.loads((wo.open_dir() / cc.FILE).read_text(encoding="utf-8"))["C3004"]["segments"]
check("…Other Function(s) is recorded in each segment in copy_counter.json (at both ends), not counted",
      [s["other"] for s in saved] == [{"start": {"A3/DLT": 72281, "Duplex": 283975, "Banner": 1},
                                      "end": {"A3/DLT": 72281, "Duplex": 284010, "Banner": 1}}] * 2, saved)
MM.cancel("C3004"); S.build("C3004"); pump(0.2)

# ------------------------------------------------------------------ restart: a sheets count stays unheld
READ["C3000"] = c3000
MM.start("C3000")
M2 = cc.Manager(rules, read_func=lambda pid: READ[pid])
check("restart while counting (sheets): goes on, and the copier stays unheld", "C3000" in M2.counters
      and M2.counters["C3000"].how == "sheets" and not copier_queue.held("C3000"))
MM.cancel("C3000")

# ------------------------------------------------------------------ the Data screen
SERVE["page"] = F.c4510(1)
base = {"ok": True, "version": "v2c", "model": "IM C4510", "sysdescr": "RICOH IM C4510",
        "counters": {"total": 656415, "black": None, "colour": None},
        "toners": {"black": 5, "cyan": 50, "magenta": 50, "yellow": 50},
        "raw": {"supplies": [], "counters": [], "life": 656415}, "error": None, "address": "127.0.0.1", "where": "typed"}
first = json.loads(json.dumps(base))
toners.add_page_counts(first, "127.0.0.1")
black1, colour1 = cp.toner_counts(cp.parse(F.c4510(1)))
_rows = cp.page_totals(cp.parse(F.c4510(1)), ("Copier", "Printer"))
check("Data screen (27_01): the page's Copier + Printer row totals give the Black and Colour counts (pages, A3 = 2)",
      first["counters"]["black"] == black1 == _rows["bw"] and first["counters"]["colour"] == colour1 == _rows["color"],
      (first["counters"], _rows))
mp = cp.parse(F.c3004())
check("…on the MP C3004 the Copier + Printer B&W and Full Color totals", cp.toner_counts(mp) == (318002 + 700000, 49919 + 140076),
      cp.toner_counts(mp))
import datetime
watch = menu.toners
day = datetime.datetime(2026, 11, 1, 9, 0)
watch.record({"C4510": first}, now=day)
new = json.loads(json.dumps(base)); new["toners"]["black"] = 100
toners.add_page_counts(new, "127.0.0.1")
watch.record({"C4510": new}, now=day + datetime.timedelta(days=1))
low = json.loads(json.dumps(base)); low["toners"]["black"] = 4
watch.record({"C4510": low}, now=day + datetime.timedelta(days=30))
SERVE["page"] = F.c4510_raw(700000, bw=(260000, (512, 95021), (306, 80500)), fc=(14063, (1247, 6100), (80, 3200)))
again = json.loads(json.dumps(base)); again["toners"]["black"] = 100; again["counters"]["total"] = 700000
toners.add_page_counts(again, "127.0.0.1")
watch.record({"C4510": again}, now=day + datetime.timedelta(days=31))
hist = toners.history(toners.read_changes(), rules["printers"])["C4510"]["black"]
want = again["counters"]["black"] - new["counters"]["black"]
check("…History (copies per toner) uses the Black count, not the total counter",
      hist["average"] == want and want > 0 and want != again["counters"]["total"] - new["counters"]["total"]
      and hist["note"] == "", (hist["average"], want))  # 27_01: the Black count is now the row totals
data = toners.TonersScreen(root, rules, watch, on_back=lambda: None)
pump(0.5)
all_text = "\n".join(texts(data.win))
check("…the Data screen shows the Black and Colour counts (no “not given”) and the history line",
      f"{again['counters']['black']:,}" in all_text and f"{again['counters']['colour']:,}" in all_text
      and f"{want:,} copies by the toner taken out" in all_text, all_text[:900])
data.win.destroy()
check_lines = None
real_read_copier = toners.read_copier
toners.read_copier = lambda address, community="public", timeout=0.2, page=True: (
    lambda r: (toners.add_page_counts(r, address), r)[1])(json.loads(json.dumps(base)))
path = watch.check_file()
toners.read_copier = real_read_copier
text = path.read_text(encoding="utf-8-sig")
check("Copier check (copier_check.txt) lists what the page gave", "Counter page (/web/guest/en/websys/status/getUnificationCounter.cgi): read"
      in text and "Copier / bw: total" in text and "Total Counter: 700000" in text, text[:1500])

srv.shutdown()
print(f"{sum(results)}/{len(results)} passed")
