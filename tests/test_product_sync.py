"""Sync product items from a pretend website. Everything in a temp folder."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import datetime, hashlib, http.server, json, os, shutil, sys, threading, time, tkinter as tk
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
pdf(F / "doc.pdf", 210, 297, 2)
pdf(F / "front.pdf", 85, 55)
(F / "back.ai").write_bytes(b"%!PS-Adobe-3.0 fake illustrator file\n" + os.urandom(2000))
(F / "flyer.jpg").write_bytes(b"\xff\xd8\xff\xe0" + os.urandom(3000))
(F / "x.docx").write_bytes(b"PK fake")
URL = "http://127.0.0.1:8766"


def furl(name):
    return {"name": name, "url": f"{URL}/files/{name}"}


def order(number, items):
    return {"order": {"format": 1, "order": number, "paid_at": datetime.datetime.now().astimezone().isoformat(),
                      "delivery": "courier", "courier": "boxnow", "steps": ["PRINT", "CUTTING"],
                      "documents": [i["folder"] for i in items]}, "items": items}


doc_item = {"folder": "01", "job": {"format": 1, "file": "doc.pdf", "pages": 2, "copies": 1, "color": "bw",
                                    "sides": "single", "paper": "A4", "per_side": 1,
                                    "paper_type": "Plain & Recycled"}, "files": [furl("doc.pdf")]}


def product(folder, pid, name, cut, files, titles=None, dl=None, kind="product"):
    return {"folder": folder, "job": {"format": 1, "kind": kind, "product": pid, "name": name, "quantity": 250,
                                      "options": {"Size": "x", "Paper": "Silk 300 gsm", "Sides": "One side"},
                                      "cut_mm": cut, "files": files, "titles": titles if titles is not None else files,
                                      "note": ""},
            "files": [furl(n) for n in (dl if dl is not None else files)]}


feed = {"format": 1, "orders": [
    order("PH-10100", [doc_item,
                       product("02", "bcard", "Business cards", [85, 55], ["front.pdf", "back.ai"],
                               ["Logo front final.pdf", "back.ai"]),
                       product("03", "flyer", "Flyers", [148, 210], ["flyer.jpg"])]),
    order("PH-10101", [doc_item, product("02", "bcard", "Business cards", [85, 55], ["front.pdf", "back.ai"],
                                         dl=["front.pdf"])]),                                    # missing file
    order("PH-10102", [product("01", "bcard", "Business cards", [85, 55], ["x.docx"])]),         # bad suffix
    order("PH-10103", [product("01", "bcard", "Business cards", [85, 55], ["front.pdf", "back.ai"],
                               ["only one title"])]),                                            # length mismatch
    order("PH-10104", [product("01", "bcard", "Business cards", [85, 55], ["front.pdf"], kind="poster")]),
]}


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


server = http.server.ThreadingHTTPServer(("127.0.0.1", 8766), H)
threading.Thread(target=server.serve_forever, daemon=True).start()

rules = routing.load_json("rules.json")
rules.update(pending_folder=str(TMP / "pending"), orders_folder=str(TMP / "orders"),
             finished_folder=str(TMP / "finished"), templates_folder=str(real_app_dir() / "templates"),
             website={"url": URL, "check_seconds": 60})
web = sync.WebsiteSync(rules)
web.check()
server.shutdown(); server.server_close()

results = []


def check(name, ok, info=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name, info)


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


P = TMP / "pending"
check("only PH-10100 arrived; nothing else left in Pending Orders",
      sorted(p.name for p in P.iterdir()) == ["PH-10100"], sorted(p.name for p in P.iterdir()))
o = P / "PH-10100"
check("product files untouched (same bytes)",
      all(md5(o / f) == md5(F / n) for f, n in (("02/front.pdf", "front.pdf"), ("02/back.ai", "back.ai"),
                                                  ("03/flyer.jpg", "flyer.jpg"))))
check("no document.pdf in product items", not (o / "02" / "document.pdf").exists() and not (o / "03" / "document.pdf").exists())
sent = feed["orders"][0]["items"]
check("product job.json written unchanged",
      json.loads((o / "02" / "job.json").read_text(encoding="utf-8")) == sent[1]["job"]
      and json.loads((o / "03" / "job.json").read_text(encoding="utf-8")) == sent[2]["job"])
check("document as before (PDF kept, job.json file = doc.pdf)",
      json.loads((o / "01" / "job.json").read_text(encoding="utf-8"))["file"] == "doc.pdf" and md5(o / "01" / "doc.pdf") == md5(F / "doc.pdf"))
log = (TMP / sync.LOG_FILE).read_text(encoding="utf-8")
for number, words in (("PH-10101", "its file back.ai wasn't in the download"),
                      ("PH-10102", "x.docx isn't one of pdf, png, jpg, jpeg, ai, eps, psd"),
                      ("PH-10103", "files and titles don't match (2 files, 1 titles)"),
                      ("PH-10104", "unknown kind 'poster'")):
    check(f"{number} refused with a clear log line", f"{number}  failed (try 1): item " in log and words in log)
check("no hidden download folders left", not any(p.name.startswith(".") for p in P.iterdir()))

# PrintHub: Waiting for layout, the right template
root = tk.Tk(); root.withdraw()
view = printhub.PrintHubView(root, rules, jobs.Jobs(rules, routing.load_json("prices.json")))
view.win.withdraw()
end = time.time() + 20
while time.time() < end and not view.orders:
    root.update(); time.sleep(0.1)
for _ in range(10):
    root.update(); time.sleep(0.05)
order_ = view.orders[0]
check("order shows Waiting for layout (with how many products, when more than one)",
      view.order_text(order_) in ("Waiting for layout", f"Waiting for layout ({len(view.waiting_layout(order_))})"),
      view.order_text(order_))
d2, d3 = order_.documents[1], order_.documents[2]
check("items are products without problems", d2.product and d3.product and not d2.problems and not d3.problems,
      (d2.problems, d3.problems))
check("business card got 85x55.cdr", (d2.folder / "PH-10100-02.cdr").read_bytes() == (real_app_dir() / "templates" / "85x55.cdr").read_bytes())
check("flyer got 148x210.cdr", (d3.folder / "PH-10100-03.cdr").read_bytes() == (real_app_dir() / "templates" / "148x210.cdr").read_bytes())
check("Options.txt names the templates", "CorelDRAW template: 85x55.cdr" in (d2.folder / "Options.txt").read_text(encoding="utf-8-sig")
      and "CorelDRAW template: 148x210.cdr" in (d3.folder / "Options.txt").read_text(encoding="utf-8-sig"))
check("product files still untouched after PrintHub", md5(o / "02" / "back.ai") == md5(F / "back.ai"))
root.destroy()
print(log)
print("ALL OK" if all(results) else "SOME FAILED")
