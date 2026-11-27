"""Website sync line: on / off / can't connect. Temp folder, pretend website."""
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
shutil.copyfile(APP / "prices.json", TMP / "prices.json")
rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (TMP / d).mkdir()
URL = "http://127.0.0.1:8769"
rules.update(pending_folder=str(TMP / "pending"), orders_folder=str(TMP / "orders"),
             finished_folder=str(TMP / "finished"), templates_folder=str(APP / "templates"),
             website={"url": URL, "check_seconds": 60})
(TMP / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
routing.app_dir = lambda: TMP
import sync, theme, mainmenu, driverprint
from tkinter import ttk
driverprint.option_names = lambda *a: (_ for _ in ()).throw(RuntimeError("no drivers"))

results = []


def check(name, ok, info=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name, "|", info)


(TMP / "doc.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
good = {"order": {"format": 1, "order": "PH-50000", "paid_at": datetime.datetime.now().astimezone().isoformat(),
                  "delivery": "pickup", "steps": ["PRINT"], "documents": ["01"]},
        "items": [{"folder": "01", "job": {"format": 1, "file": "doc.pdf", "pages": 1, "copies": 1, "color": "bw",
                                           "sides": "single", "paper": "A4", "per_side": 1,
                                           "paper_type": "Plain & Recycled"},
                   "files": [{"name": "doc.pdf", "url": f"{URL}/files/doc.pdf"}]}]}
bad = json.loads(json.dumps(good))
bad["order"]["order"] = "PH-50001"
bad["items"][0]["files"][0]["url"] = f"{URL}/files/missing.pdf"
state = {"up": True, "orders": [good]}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if not state["up"]:
            self.send_response(500); self.end_headers(); return
        if self.path == "/api/printrouter/orders":
            raw = json.dumps({"format": 1, "orders": state["orders"]}).encode()
        elif self.path == "/files/doc.pdf":
            raw = (TMP / "doc.pdf").read_bytes()
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers()
        self.wfile.write(raw)


server = http.server.ThreadingHTTPServer(("127.0.0.1", 8769), H)
threading.Thread(target=server.serve_forever, daemon=True).start()

# 1. No token file: off, in the sync itself
s = sync.WebsiteSync(rules)
check("no token file: 'Website sync: off'", s.status() == ("Website sync: off", False, []), s.status())

# 2. Token file: on right away (first check not done yet), after a download, red when down, on again
(TMP / sync.TOKEN_FILE).write_text("test-token-not-real", encoding="utf-8")
s = sync.WebsiteSync(rules)
check("right after start: 'Website sync: on'", s.status() == ("Website sync: on", False, []), s.status())
s.check()
check("after an order is downloaded: 'Website sync: on'", (TMP / "pending" / "PH-50000").exists()
      and s.status() == ("Website sync: on", False, []), s.status())
state["up"] = False
s.check()
check("website down: 'Website sync: can't connect' in red", s.status() == ("Website sync: can't connect", True, []), s.status())
state["up"] = True
s.check()
check("website back: 'Website sync: on'", s.status() == ("Website sync: on", False, []), s.status())
state["orders"] = [bad]
for _ in range(sync.RED_AFTER):
    s.check()
text, red, stuck = s.status()
check("an order that keeps failing still has its red line", text == "Website sync: on" and len(stuck) == 1
      and stuck[0].startswith("PH-50001 can't be downloaded:"), (text, stuck))

# 3. The same text in the menu and the PrintHub top bar, with no token and with one
root = tk.Tk(); root.withdraw()
for token in (False, True):
    if not token:
        (TMP / sync.TOKEN_FILE).unlink()
    else:
        (TMP / sync.TOKEN_FILE).write_text("test-token-not-real", encoding="utf-8")
        state["orders"] = [good]
    menu = mainmenu.MainMenu(root)
    menu.open_printhub()
    end = time.time() + 8
    while time.time() < end:
        root.update(); time.sleep(0.05)
    a, b = menu.sync_label.cget("text"), menu.printhub.sync_label.cget("text")
    want = "Website sync: on" if token else "Website sync: off"
    check(f"menu and PrintHub both show '{want}'", a == b == want, (a, b))
    menu.sync.stop() if hasattr(menu.sync, "stop") else None
    menu.printhub.win.destroy(); menu.win.destroy()
server.shutdown()
root.destroy()
print("ALL OK" if all(results) else "SOME FAILED", f"{sum(results)}/{len(results)}")
