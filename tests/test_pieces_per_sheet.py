"""Pieces per sheet at Layout done. Everything in a temp folder."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import datetime, http.server, json, os, shutil, sys, threading, time, tkinter as tk
from tkinter import ttk
from pathlib import Path

APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
(TMP / "files").mkdir(parents=True)
for f in ("rules.json", "prices.json"):
    shutil.copyfile(APP / f, TMP / f)
real_app_dir = routing.app_dir
routing.app_dir = lambda: TMP
import jobs, orders, printhub, sync
import pypdfium2 as pdfium

(TMP / sync.TOKEN_FILE).write_text("test-token-not-real", encoding="utf-8")
for d in ("pending", "orders", "finished"):
    (TMP / d).mkdir()


def pdf(path, w_mm, h_mm, pages=1):
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(w_mm / 25.4 * 72, h_mm / 25.4 * 72)
    doc.save(str(path)); doc.close()


F = TMP / "files"
pdf(F / "art.pdf", 85, 55)
URL = "http://127.0.0.1:8767"

CASES = {  # number: (cut_mm, quantity, sheet of the laid-out PDF)
    "PH-10200": ([85, 55], 100, "A4"),
    "PH-10201": ([55, 55], 100, "A4"),
    "PH-10202": ([55, 55], 100, "A3"),
    "PH-10203": ([74, 210], 10, "A4"),
    "PH-10204": ([297, 420], 10, "A4"),
    "PH-10205": ([123, 45], 10, "A4"),
    "PH-10206": ([85, 55], 100, "A4"),
}


def order(number, cut, qty):
    item = {"folder": "01", "job": {"format": 1, "kind": "product", "product": "test", "name": "Cards",
                                    "quantity": qty, "options": {"Paper": "Smooth white 80 gsm", "Sides": "One side"},
                                    "cut_mm": cut, "files": ["art.pdf"], "titles": ["art.pdf"], "note": ""},
            "files": [{"name": "art.pdf", "url": f"{URL}/files/art.pdf"}]}
    return {"order": {"format": 1, "order": number, "paid_at": datetime.datetime.now().astimezone().isoformat(),
                      "delivery": "courier", "courier": "boxnow", "steps": ["PRINT", "CUTTING"],
                      "documents": ["01"]}, "items": [item]}


feed = {"format": 1, "orders": [order(n, c, q) for n, (c, q, _) in CASES.items()]}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/api/printrouter/orders":
            return self._send(json.dumps(feed).encode())
        if self.path.startswith("/files/"):
            return self._send((F / self.path[7:]).read_bytes())
        self.send_response(404); self.end_headers()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._send(b'{"ok": true}')

    def _send(self, raw):
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


server = http.server.ThreadingHTTPServer(("127.0.0.1", 8767), H)
threading.Thread(target=server.serve_forever, daemon=True).start()
rules = routing.load_json("rules.json")
rules.update(pending_folder=str(TMP / "pending"), orders_folder=str(TMP / "orders"),
             finished_folder=str(TMP / "finished"), templates_folder=str(real_app_dir() / "templates"),
             website={"url": URL, "check_seconds": 60})
sync.WebsiteSync(rules).check()
server.shutdown(); server.server_close()
print(sorted(p.name for p in (TMP / "pending").iterdir()))

results = []


def check(name, ok, info=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name, info)


root = tk.Tk(); root.withdraw()


def pump(view, until, secs=20):
    end = time.time() + secs
    while time.time() < end and not until():
        root.update(); time.sleep(0.1)
    for _ in range(5):
        root.update(); time.sleep(0.05)


def find(view, number):
    return next(o for o in view.orders if o.number == number)


def open_view():
    v = printhub.PrintHubView(root, rules, jobs.Jobs(rules, routing.load_json("prices.json")))
    v.win.withdraw()
    pump(v, lambda: len(v.orders) == len(CASES))
    return v


view = open_view()
for number, (_, _, sheet) in CASES.items():
    doc = find(view, number).documents[0]
    w, h = orders.SHEET_MM[sheet]
    pdf(doc.folder / doc.pdf_name, w, h)
view.refresh()
pump(view, lambda: all(find(view, n).documents[0].print_state == "ok" for n in CASES))


def dialog(view, number):
    o = find(view, number)
    doc = o.documents[0]
    before = set(root.winfo_children()) | set(view.win.winfo_children())
    view.layout_dialog(o, doc)
    root.update()
    dlg = next(w for w in view.win.winfo_children() if isinstance(w, tk.Toplevel) and w not in before)
    frame = dlg.winfo_children()[0]
    entries = [w for w in frame.winfo_children() if isinstance(w, ttk.Entry)]
    hints = [w.cget("text") for w in frame.winfo_children()
             if isinstance(w, ttk.Label) and str(w.cget("style")) == "Hint.TLabel"]
    return dlg, entries, hints, doc


expect = {"PH-10200": ("8", "13", "from the size table (85 x 55 on A4: 8)"),
          "PH-10201": ("12", "9", "from the size table (55 x 55 on A4: 12)"),
          "PH-10202": ("24", "5", "from the size table (55 x 55 on A3: 24)"),
          "PH-10203": ("2", "5", "from the size table (210 x 74 on A4: 2)"),
          "PH-10204": ("", "", None),
          "PH-10205": ("", "", None)}
for number, (per, sheets, hint) in expect.items():
    dlg, entries, hints, doc = dialog(view, number)
    got = (entries[0].get(), entries[1].get(), hints[0] if hints and hint else None)
    check(f"{number} {CASES[number]}", got == (per, sheets, hint) and (hint or not hints), (got, hints))
    dlg.destroy()

# Options.txt
opt = (find(view, "PH-10200").documents[0].folder / orders.OPTIONS_TXT).read_text(encoding="utf-8-sig")
check("Options.txt 85x55 line", "Pieces per sheet: 8 on A4, 18 on A3" in opt)
opt = (find(view, "PH-10204").documents[0].folder / orders.OPTIONS_TXT).read_text(encoding="utf-8-sig")
check("Options.txt 297x420 line", "Pieces per sheet: 1 on A3" in opt)
opt = (find(view, "PH-10205").documents[0].folder / orders.OPTIONS_TXT).read_text(encoding="utf-8-sig")
check("Options.txt no line for an unknown size", "Pieces per sheet" not in opt)
print(open(find(view, "PH-10200").documents[0].folder / orders.OPTIONS_TXT, encoding="utf-8-sig").read())

# Typed value, then restart
dlg, entries, hints, doc = dialog(view, "PH-10206")
entries[0].delete(0, "end"); entries[0].insert(0, "10")
root.update()
check("typing 10 gives 10 sheets and hides the hint", entries[1].get() == "10", (entries[1].get(), hints))
ok = next(w for w in dlg.winfo_children()[0].winfo_children()[-1].winfo_children() if w.cget("text") == "Ready to print")
check("Ready to print enabled", str(ok.cget("state")) == "normal", ok.cget("state"))
ok.invoke()
pump(view, lambda: False, 2)
view.win.destroy()

view = open_view()
dlg, entries, hints, doc = dialog(view, "PH-10206")
check("after restart: typed 10 kept, not replaced", (entries[0].get(), entries[1].get(), hints) == ("10", "10", []),
      (entries[0].get(), entries[1].get(), hints))
dlg.destroy()
view.win.destroy()
root.destroy()
print("ALL OK" if all(results) else "SOME FAILED")
