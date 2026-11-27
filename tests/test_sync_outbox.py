"""Ready for courier -> website, against a pretend local server. Everything in a temp folder."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import datetime, http.server, json, os, shutil, sys, threading, time, tkinter as tk
from pathlib import Path

APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True)
for _f in ("rules.json", "prices.json"):  # the shipped files ORCA reads, copied into the temp folder
    shutil.copyfile(APP / _f, TMP / _f)
routing_app_dir = routing.app_dir
routing.app_dir = lambda: TMP  # token, log and outbox go to the temp folder
import jobs, printhub, sync

TOKEN = "test-token-not-real-123"
(TMP / sync.TOKEN_FILE).write_text(TOKEN, encoding="utf-8")
for d in ("pending", "orders", "finished"):
    (TMP / d).mkdir()

calls, answer = [], {"code": 200}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self._send(200, {"format": 1, "orders": []})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/api/printrouter/orders/status":
            calls.append((self.path, self.headers.get("Authorization"), self.headers.get("Content-Type"),
                          json.loads(body)))
            c = answer["code"]
            self._send(c, {200: {"ok": True}, 409: {"error": "cancelled"}, 404: {"error": "unknown order"},
                           500: {"error": "boom"}}[c])
        else:
            self._send(200, {"ok": True})

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


server = None


def start_server():
    global server
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def stop_server():
    server.shutdown(); server.server_close()


def make_order(number):
    folder = TMP / "orders" / number
    (folder / "01").mkdir(parents=True)
    (folder / "order.json").write_text(json.dumps({
        "format": 1, "order": number, "paid_at": datetime.datetime.now().astimezone().isoformat(),
        "delivery": "courier", "courier": "acs", "steps": ["PRINT", "CUTTING"], "documents": ["01"]}),
        encoding="utf-8")
    (folder / "01" / "job.json").write_text(json.dumps({
        "format": 1, "file": "a.pdf", "pages": 1, "copies": 1, "color": "bw", "sides": "single",
        "paper": "A4", "per_side": 1, "paper_type": "Plain & Recycled"}), encoding="utf-8")
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument.new(); pdf.new_page(595, 842); pdf.save(str(folder / "01" / "a.pdf"))
    (folder / "status.json").write_text(json.dumps({"step": 1, "parts": {}, "layout": {}, "history": []}),
                                        encoding="utf-8")


numbers = [f"PH-990{n}" for n in range(31, 37)]
for n in numbers:
    make_order(n)

rules = routing.load_json("rules.json")
rules.update(pending_folder=str(TMP / "pending"), orders_folder=str(TMP / "orders"),
             finished_folder=str(TMP / "finished"), website={"url": "http://127.0.0.1:8765", "check_seconds": 60})
root = tk.Tk(); root.withdraw()
web = sync.WebsiteSync(rules)  # not started: checks are run by hand below
view = printhub.PrintHubView(root, rules, jobs.Jobs(rules, routing.load_json("prices.json")), web)
view.win.withdraw()


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        root.update(); time.sleep(0.05)


def wait_sends(limit=20):
    """Let every background send (report_ready starts one) finish before the next step."""
    end = time.time() + limit
    while time.time() < end and any(t.is_alive() and getattr(getattr(t, "_target", None), "__name__", "") == "send_outbox"
                                    for t in threading.enumerate()):
        pump(0.2)


def wait_orders():
    end = time.time() + 20
    while time.time() < end and not view.orders:
        pump(0.2)


results = []


def check(name, ok, info=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name, info)


def outbox():
    p = TMP / sync.OUTBOX_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def ready(number):
    wait_orders()
    order = next(o for o in view.orders if o.number == number)
    check(f"{number} button is Ready for courier", view.next_step(order)[0] == "Ready for courier")
    view.do_next_step(number)
    pump(1.5)
    view.reload(); pump(1.5)


start_server()
wait_orders()

# 1. 200
ready("PH-99031")
check("200: exactly one request, as in the contract",
      calls == [("/api/printrouter/orders/status", f"Bearer {TOKEN}", "application/json",
                 {"order": "PH-99031", "status": "ready"})], calls)
check("200: outbox empty", outbox() == [])
check("200: order moved to Finished Orders", (TMP / "finished" / "PH-99031").is_dir())

# 2. 409 and 3. 404
for code, number, text in ((409, "PH-99032", "website says cancelled"), (404, "PH-99033", "website says unknown order")):
    calls.clear(); answer["code"] = code
    ready(number)
    check(f"{code}: one request", len(calls) == 1)
    check(f"{code}: dropped from outbox", outbox() == [])
    t, red, stuck = web.status()
    check(f"{code}: shown in red in the top bar", f"{number}: {text}" in stuck, stuck)
    web.send_outbox(); pump(0.2)
    check(f"{code}: not sent again", len(calls) == 1)
    check(f"{code}: shown once (one line)", sum(f"{number}:" in s for s in web.status()[2]) == 1)
view.press_reload(); pump(0.5)
check("Reload clears the red notices", web.status()[2] == [], web.status()[2])

# 4. 500: kept, retried at the next check, survives a restart
calls.clear(); answer["code"] = 500
ready("PH-99034")
box = outbox()
check("500: kept with tries 1", len(box) == 1 and box[0]["order"] == "PH-99034" and box[0]["tries"] == 1, box)
check("500: the status line stays on / can't connect only (2026-11-15: the count is in sync_log.txt)",
      web.status()[0] in ("Website sync: on", "Website sync: can't connect"), web.status()[0])
web.check()
check("500: retried at the next check, tries 2", len(calls) == 2 and outbox()[0]["tries"] == 2)

# 5. no server
stop_server()
ready("PH-99035")
box = outbox()
check("no server: both kept", [m["order"] for m in box] == ["PH-99034", "PH-99035"], box)
check("no server: the status line says on or can't connect", web.status()[0] in ("Website sync: on", "Website sync: can't connect"),
      web.status()[0])

# restart: a new WebsiteSync reads the outbox and sends it at its check
wait_sends()
start_server(); answer["code"] = 200; calls.clear()
web2 = sync.WebsiteSync(rules)
check("restart: outbox read back", [m["order"] for m in web2.outbox] == ["PH-99034", "PH-99035"])
web2.check()
check("restart: both sent once", sorted(c[3]["order"] for c in calls) == ["PH-99034", "PH-99035"], calls)
check("restart: outbox empty", outbox() == [] and web2.status()[0].find("waiting") < 0)
web = view.website = web2  # from here on the restarted ORCA's sync (ORCA has only one)

# 6. no token file
wait_sends()
(TMP / sync.TOKEN_FILE).unlink()
web = view.website = sync.WebsiteSync(rules)  # ORCA started without the token file: the sync is off
calls.clear()
ready("PH-99036")
log = (TMP / sync.LOG_FILE).read_text(encoding="utf-8")
check("no token: nothing sent", calls == [] and outbox() == [], (calls, outbox()))
check("no token: log line", "PH-99036  ready: not reported, website sync is off" in log)

# token nowhere
texts = [log, (TMP / sync.OUTBOX_FILE).read_text(encoding="utf-8")] + [web.status()[0]] + web.status()[2]
check("token in no log, outbox or window text", not any(TOKEN in t for t in texts))

stop_server()
root.destroy()
print(log)
print("ALL OK" if all(results) else "SOME FAILED")
