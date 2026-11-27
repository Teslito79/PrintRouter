"""Toner tracking against pretend copiers (small SNMP responders on 127.0.0.1). Temp folder only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, datetime, http.server, json, os, shutil, socket, sys, threading, time, tkinter as tk
from pathlib import Path

ctypes.windll.shcore.SetProcessDpiAwareness(1)
APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True); OUT.mkdir(parents=True, exist_ok=True)
routing.app_dir = lambda: TMP
import toners, theme
from tkinter import messagebox, ttk
from PIL import ImageGrab

rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
results = []


def check(name, ok, info=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name, "|", info)


# ------------------------------------------------------------ BER check against known bytes
known = bytes.fromhex("302602010104067075626c6963a019020101020100020100300e300c06082b060102010101000500")
check("SNMP GET request matches the standard bytes", toners.request("public", toners.GET, ["1.3.6.1.2.1.1.1.0"], 1, 1) == known)

# ------------------------------------------------------------ a pretend copier (written apart from toners.py)


def tlv(tag, body):
    n = len(body)
    ln = bytes([n]) if n < 128 else bytes([0x80 | ((n.bit_length() + 7) // 8)]) + n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([tag]) + ln + body


def enc_int(n, tag=0x02):
    return tlv(tag, n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True))


def enc_oid(text):
    p = [int(x) for x in text.split(".")]
    body = bytes([40 * p[0] + p[1]])
    for v in p[2:]:
        chunk = [v & 0x7F]; v >>= 7
        while v:
            chunk.insert(0, 0x80 | (v & 0x7F)); v >>= 7
        body += bytes(chunk)
    return tlv(0x06, body)


def take(data, i):
    tag, n = data[i], data[i + 1]; i += 2
    if n & 0x80:
        k = n & 0x7F; n = int.from_bytes(data[i:i + k], "big"); i += k
    return tag, data[i:i + n], i + n


def dec_oid(b):
    out, n = [b[0] // 40, b[0] % 40], 0
    for x in b[1:]:
        n = (n << 7) | (x & 0x7F)
        if not x & 0x80:
            out.append(n); n = 0
    return ".".join(map(str, out))


def key(oid):
    return tuple(int(x) for x in oid.split("."))


class PretendCopier:
    def __init__(self, port):
        self.values = {}  # oid -> ("int"/"str"/"counter", value)
        self.on = True
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("127.0.0.1", port))
        threading.Thread(target=self.serve, daemon=True).start()

    def encode(self, kind, v):
        return {"int": lambda: enc_int(v), "counter": lambda: enc_int(v, 0x41), "str": lambda: tlv(0x04, v.encode())}[kind]()

    def serve(self):
        while True:
            data, addr = self.s.recvfrom(65535)
            if not self.on:
                continue
            _, msg, _ = take(data, 0)
            _, ver, i = take(msg, 0); _, comm, i = take(msg, i); ptype, pdu, _ = take(msg, i)
            _, rid, j = take(pdu, 0); _, _, j = take(pdu, j); _, _, j = take(pdu, j); _, binds, _ = take(pdu, j)
            out, k = b"", 0
            while k < len(binds):
                _, bind, k = take(binds, k); _, oidb, _ = take(bind, 0)
                oid = dec_oid(oidb)
                if ptype == 0xA0:
                    val = self.values.get(oid)
                    out_oid, vb = oid, (self.encode(*val) if val else b"\x80\x00")
                else:
                    nxt = sorted((o for o in self.values if key(o) > key(oid)), key=key)
                    out_oid, vb = (nxt[0], self.encode(*self.values[nxt[0]])) if nxt else (oid, b"\x82\x00")
                out += tlv(0x30, enc_oid(out_oid) + vb)
            body = tlv(0x30, out)
            resp = tlv(0xA2, tlv(0x02, rid) + enc_int(0) + enc_int(0) + body)
            self.s.sendto(tlv(0x30, tlv(0x02, ver) + tlv(0x04, comm) + resp), addr)

    def set(self, total=None, bw=None, colour=None, levels=None, ricoh_names=True, ok_only=False):
        v = self.values
        v["1.3.6.1.2.1.1.1.0"] = ("str", "RICOH pretend copier")
        v["1.3.6.1.2.1.25.3.2.1.3.1"] = ("str", "RICOH IM Pretend")
        if total is not None:
            v["1.3.6.1.2.1.43.10.2.1.4.1.1"] = ("counter", total)
        base = "1.3.6.1.4.1.367.3.2.1.2.19.5.1"
        if bw is not None:
            v[f"{base}.5.1"] = ("str", "Total: Black & White"); v[f"{base}.9.1"] = ("int", bw)
        if colour is not None:
            v[f"{base}.5.2"] = ("str", "Total: Full Color"); v[f"{base}.9.2"] = ("int", colour)
        sup = "1.3.6.1.2.1.43.11.1.1"
        for i, c in enumerate(toners.COLOURS, start=1):
            v[f"{sup}.5.1.{i}"] = ("int", 3)
            v[f"{sup}.6.1.{i}"] = ("str", f"{c.title()} Toner")
            v[f"{sup}.8.1.{i}"] = ("int", -2 if ok_only else 100)
            v[f"{sup}.9.1.{i}"] = ("int", -3 if ok_only else levels[c])
        v[f"{sup}.5.1.5"] = ("int", 4); v[f"{sup}.6.1.5"] = ("str", "Waste Toner")
        v[f"{sup}.8.1.5"] = ("int", 100); v[f"{sup}.9.1.5"] = ("int", 60)


A, B, C = PretendCopier(16101), PretendCopier(16102), PretendCopier(16103)
lv = lambda k=50, c=60, m=70, y=80: {"black": k, "cyan": c, "magenta": m, "yellow": y}
A.set(total=100000, bw=70000, colour=30000, levels=lv(4))
B.set(total=50000, levels=lv(50, 3))           # no black / colour counters
C.set(ok_only=True)                              # levels "OK" only, no counters
ids = list(rules["printers"])  # C4510, C3000, C3004
toners.save_settings({"community": "public", "addresses": {ids[0]: "127.0.0.1:16101", ids[1]: "127.0.0.1:16102",
                                                           ids[2]: "127.0.0.1:16103"}})
watch = toners.TonerWatch(rules, timeout=0.5)
T0 = datetime.datetime(2026, 11, 1, 9, 0)


def read(at):
    """One reading with a chosen time (as read_all does, but the time is fixed for the test)."""
    s = toners.load_settings()
    found = {pid: dict(toners.read_copier(watch.address(pid, s)[0], s["community"], watch.timeout),
                       address=watch.address(pid, s)[0]) for pid in watch.printers}
    watch.record(found, now=at)
    return found


r = read(T0)
check("three pretend copiers read: counts and toner levels", r[ids[0]]["ok"] and r[ids[0]]["counters"] == {"total": 100000, "black": 70000, "colour": 30000}
      and r[ids[0]]["toners"] == lv(4), (r[ids[0]]["counters"], r[ids[0]]["toners"]))
check("no colour counter / no counters: 'not given' (None)", r[ids[1]]["counters"] == {"total": 50000, "black": None, "colour": None}
      and r[ids[2]]["counters"] == {"total": None, "black": None, "colour": None} and r[ids[2]]["toners"] == {c: None for c in toners.COLOURS})
check("the first reading records nothing", toners.read_changes() == [])

A.set(total=101000, bw=70500, colour=30500, levels=lv(100))
read(T0 + datetime.timedelta(hours=1))
ch = toners.read_changes()
check("black 4% -> 100%: one change, automatic, with the counters of that reading",
      len(ch) == 1 and (ch[0]["colour"], ch[0]["how"], ch[0]["total"], ch[0]["black"], ch[0]["colour_count"], ch[0]["before"], ch[0]["after"])
      == ("black", "automatic", 101000, 70500, 30500, 4, 100), ch)
A.set(total=101500, bw=70800, colour=30700, levels=lv(97, 60 - 20, 70 + 25, 80))  # falling, or +25: nothing
read(T0 + datetime.timedelta(hours=2))
check("levels falling or rising by less than 30 record nothing", len(toners.read_changes()) == 1)

A.set(total=129000, bw=90000, colour=39000, levels=lv(3, 40, 95, 80))
read(T0 + datetime.timedelta(days=20))
A.set(total=129000, bw=90000, colour=39000, levels=lv(100, 40, 95, 80))
read(T0 + datetime.timedelta(days=20, hours=1))
h = toners.history(toners.read_changes(), watch.printers)[ids[0]]["black"]
check("second black change: 19,500 copies by the Black count (70,500 to 90,000, not the total), first shows 'first reading'; average of 1",
      [row["copies"] for row in h["rows"]] == [19500, None] and h["rows"][1]["first"] and (h["average"], h["count"]) == (19500, 1), h)

# Cyan: colour counter on A, total counter (with the note) on B
A.set(total=130000, bw=90500, colour=39500, levels=lv(100, 2, 95, 80)); read(T0 + datetime.timedelta(days=21))
A.set(total=130000, bw=90500, colour=39500, levels=lv(100, 100, 95, 80)); read(T0 + datetime.timedelta(days=21, hours=1))
A.set(total=150000, bw=100000, colour=50000, levels=lv(90, 3, 95, 80)); read(T0 + datetime.timedelta(days=40))
A.set(total=150000, bw=100000, colour=50000, levels=lv(90, 100, 95, 80)); read(T0 + datetime.timedelta(days=40, hours=1))
hc = toners.history(toners.read_changes(), watch.printers)[ids[0]]["cyan"]
check("cyan uses the colour counter (39,500 -> 50,000 = 10,500)", hc["rows"][0]["copies"] == 10500 and not hc["note"], hc["rows"][0])
B.set(total=50000, levels=lv(50, 100)); read(T0 + datetime.timedelta(days=41))
B.set(total=62000, levels=lv(50, 2)); read(T0 + datetime.timedelta(days=60))
B.set(total=62000, levels=lv(50, 100)); read(T0 + datetime.timedelta(days=60, hours=1))
hb = toners.history(toners.read_changes(), watch.printers)[ids[1]]["cyan"]
check("no colour counter: cyan uses the total counter, with the note", hb["rows"][0]["copies"] == 12000 and "total counter" in hb["note"], hb)

# The 'OK only' copier: nothing automatic; by hand with a typed counter
C.set(ok_only=True); read(T0 + datetime.timedelta(days=61))
check("levels 'OK' only: no automatic change", not [c for c in toners.read_changes() if c["copier"] == ids[2]])
why = watch.add_by_hand(ids[2], "black", 84211, None, None, when=T0 + datetime.timedelta(days=61, hours=2))
c3 = [c for c in toners.read_changes() if c["copier"] == ids[2]]
check("Toner replaced by hand with a typed counter works", why is None and len(c3) == 1 and c3[0]["total"] == 84211 and c3[0]["how"] == "by hand", (why, c3))

# Hand entry within 24 h of an automatic one: refused. Removing an entry updates History.
last_black = [c for c in toners.read_changes() if c["copier"] == ids[0] and c["colour"] == "black"][-1]
why = watch.add_by_hand(ids[0], "black", 129500, 90200, 39100, when=last_black["time"] + datetime.timedelta(hours=5))
check("a hand entry within 24 hours of an automatic one is refused with a message", why and "24 hours" in why, why)
watch.remove(last_black["id"])
h = toners.history(toners.read_changes(), watch.printers)[ids[0]]["black"]
check("removing an entry updates History and the average", len(h["rows"]) == 1 and h["average"] is None, h)

# Losing the state file records nothing
count = len(toners.read_changes())
(TMP / toners.STATE_FILE).unlink()
A.set(total=150100, bw=100050, colour=50050, levels=lv(10, 100, 95, 80)); read(T0 + datetime.timedelta(days=70))
A.set(total=150100, bw=100050, colour=50050, levels=lv(100, 100, 95, 80))
(TMP / toners.STATE_FILE).unlink()
read(T0 + datetime.timedelta(days=70, hours=1))
check("deleting the state file and reading again records no change", len(toners.read_changes()) == count)

# A change while PrintRouter was closed: found at start, once
A.set(total=151000, bw=100500, colour=50500, levels=lv(100, 100, 5, 80)); read(T0 + datetime.timedelta(days=80))
A.set(total=151000, bw=100500, colour=50500, levels=lv(100, 100, 100, 80))  # changed while "closed"
watch = toners.TonerWatch(rules, timeout=0.5)  # PrintRouter starts again
read(T0 + datetime.timedelta(days=81)); read(T0 + datetime.timedelta(days=81, hours=1))
mag = [c for c in toners.read_changes() if c["copier"] == ids[0] and c["colour"] == "magenta"]
check("a change made while PrintRouter was closed: recorded once, 'found at start'", len(mag) == 1 and mag[0]["how"] == "found at start", mag)

# A copier that never answers doesn't hold up anything else
B.on = False
import jobs, driverprint, sync
driverprint.build_devmode = lambda *a, **k: None
sent = []
driverprint.print_pdf = lambda *a, **k: sent.append(time.monotonic())
watch.timeout = 3.0
t = threading.Thread(target=watch.read_all, daemon=True); started = time.monotonic(); t.start()
time.sleep(0.2)
J = jobs.Jobs(rules, json.loads((APP / "prices.json").read_text(encoding="utf-8")))
import pypdfium2 as pdfium
pdf = TMP / "a.pdf"; d = pdfium.PdfDocument.new(); d.new_page(595, 842); d.save(str(pdf)); d.close()
s = {"color": "bw", "printer": "auto", "sides": "single", "paper": "A4", "per_side": "1", "paper_type": "Plain & Recycled",
     "tray": "Auto Tray Select", "copies": "1", "rotate": "0"}
job = J.job_for("a.pdf", s, 1, 0, [False], busy=set())
(TMP / "w").mkdir()
J.print_one(TMP / "w", job, pdf, pdf, "A4", None)
send_time = time.monotonic() - started


class Site(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        raw = b'{"format": 1, "orders": []}'
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 8770), Site)
threading.Thread(target=srv.serve_forever, daemon=True).start()
(TMP / sync.TOKEN_FILE).write_text("test-token-not-real", encoding="utf-8")
for d_ in ("pending", "orders", "finished"):
    (TMP / d_).mkdir(exist_ok=True)
r2 = dict(rules, pending_folder=str(TMP / "pending"), orders_folder=str(TMP / "orders"),
          finished_folder=str(TMP / "finished"), website={"url": "http://127.0.0.1:8770", "check_seconds": 60})
w = sync.WebsiteSync(r2); w.check()
sync_time = time.monotonic() - started
reading_busy = t.is_alive()
t.join()
check("while a copier never answers: a job is sent and the website sync checks without waiting",
      reading_busy and send_time < 1.0 and sync_time < 1.5 and sent and w.status()[0] == "Website sync: on",
      f"job after {send_time:.2f} s, sync after {sync_time:.2f} s, reader still waiting: {reading_busy}")
check("a copier that is off shows 'No answer', the others are read", not watch.latest[ids[1]]["ok"]
      and watch.latest[ids[0]]["ok"] and watch.latest[ids[2]]["ok"] and watch.last_good.get(ids[1]) is not None)
srv.shutdown()

# Copier check
B.on = True
watch.timeout = 0.5
path = watch.check_file()
text = path.read_text(encoding="utf-8-sig")
shutil.copyfile(path, OUT / "copier_check.txt")
check("Copier check writes copier_check.txt with the pretend copiers' values and no secrets",
      "Total count: 151000" in text and "Black toner: 100%" in text and "Total: Full Color = 50500" in text
      and "public" not in text and "test-token" not in text and text.count("Answered: yes") == 3, path)

# The Toners screen: three blocks, three counts, four percents; refreshes by itself; 'No answer'
root = tk.Tk(); root.withdraw()
theme.apply(root)
st = ttk.Style(root)
st.configure(".", font=("Segoe UI", 12)); st.configure("Summary.TLabel", font=("Segoe UI", 13, "bold"))
st.configure("Section.TLabelframe.Label", font=("Segoe UI", 12, "bold"))
st.configure("Print.TButton", font=("Segoe UI", 12, "bold"))
watch.timeout = 0.5
watch.read_all()
screen = toners.TonersScreen(root, rules, watch, on_back=lambda: None)


def texts(w):
    out = [w.cget("text")] if w.winfo_class() in ("TLabel", "TButton") else []
    for c in w.winfo_children():
        out += texts(c)
    return out


def pump(secs):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.03)


pump(0.5)
t1 = texts(screen.win)
check("Now: Total / Black / Colour count and four toner percents per copier", t1.count("Total count") == 3
      and t1.count("Black count") == 3 and t1.count("Colour count") == 3 and "151,000" in t1 and "100,500" in t1
      and "50,500" in t1 and t1.count("not given") >= 2 + 3 and t1.count("Some left") == 4, [x for x in t1 if "%" in x or "given" in x][:12])  # 19_06: -3 is "Some left"
A.set(total=151234, bw=100600, colour=50634, levels=lv(88, 100, 100, 80))
watch.read_all(); pump(1.5)
t2 = texts(screen.win)
check("the screen refreshes by itself after a reading", "151,234" in t2 and "88%" in t2)
B.on = False
watch.read_all(); pump(1.5)
t3 = texts(screen.win)
check("a copier switched off shows 'No answer' with its last good time", any(x.startswith("No answer · last good reading") for x in t3))
B.on = True
watch.read_all(); pump(1.5)
screen.win.geometry("1180x980+30+20"); screen.win.attributes("-topmost", True); pump(1.2)
x, y, w_, h_ = screen.win.winfo_rootx(), screen.win.winfo_rooty(), screen.win.winfo_width(), screen.win.winfo_height()
ImageGrab.grab(bbox=(x, y, x + w_, y + h_), all_screens=True).save(OUT / "toners_screen.png")
screen.scroll.canvas.yview_moveto(0.35); pump(0.6)
ImageGrab.grab(bbox=(x, y, x + w_, y + h_), all_screens=True).save(OUT / "toners_history.png")
check("no money on the screen", not any("€" in s_ or "cost" in s_.lower() for s_ in texts(screen.win)))
screen.win.destroy(); root.destroy()
print("ALL OK" if all(results) else "SOME FAILED", f"{sum(results)}/{len(results)}")
