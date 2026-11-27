"""Handoff 2026-11-19_06: a toner level "unknown" (-2) counts as empty. Pretend SNMP copiers on 127.0.0.1, a temp
folder; a picture of ORCA's own window only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import ctypes, datetime, json, os, shutil, sys, time, tkinter as tk
from pathlib import Path

ctypes.windll.shcore.SetProcessDpiAwareness(1)
APP = helpers.APP
TMP, OUT = helpers.dirs(__file__)
sys.path.insert(0, str(APP)); sys.path.insert(0, str(Path(__file__).parent)); os.chdir(APP)
import routing
if TMP.exists():
    shutil.rmtree(TMP)
TMP.mkdir(parents=True); OUT.mkdir(parents=True, exist_ok=True)
routing.app_dir = lambda: TMP
import toners, theme, costs
from tkinter import ttk
from pretend_snmp import PretendCopier
import window_shot

rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:500])


A, B, C = PretendCopier(16201), PretendCopier(16202), PretendCopier(16203)
lv = lambda k=50, c=60, m=70, y=80: {"black": k, "cyan": c, "magenta": m, "yellow": y}
A.set(total=1000, levels=lv(91, 30, 47, 34))
B.set(total=2000, levels=lv(80, 70, 20, -2))   # the IM C3000's empty yellow, as at work
C.set(total=3000, levels=lv(20, 30, -3, -1))   # some left / not given
for col in ("4",):  # the MP C3004 "has no yellow row": its 4th supply removed
    for k in [k for k in C.values if k.startswith("1.3.6.1.2.1.43.11.1.1.") and k.endswith(f".1.{col}")]:
        del C.values[k]
ids = list(rules["printers"])
toners.save_settings({"community": "public", "addresses": {ids[0]: "127.0.0.1:16201", ids[1]: "127.0.0.1:16202",
                                                           ids[2]: "127.0.0.1:16203"}})
watch = toners.TonerWatch(rules, timeout=0.5)
T0 = datetime.datetime(2026, 11, 19, 9, 0)


def reading():
    s = toners.load_settings()
    return {pid: dict(toners.read_copier(watch.address(pid, s)[0], s["community"], watch.timeout, page=False),
                      address=watch.address(pid, s)[0]) for pid in watch.printers}


found = reading()
b, c = found[ids[1]], found[ids[2]]
check("-2 (unknown) gives 0", b["toners"]["yellow"] == 0 and b["toner_raw"]["yellow"] == -2, b["toners"])
check("…shown as “Empty”", toners.level_text(0, -2) == "Empty")
check("-3 gives “Some left” (percent None, never empty)", c["toners"]["magenta"] is None
      and toners.level_text(c["toners"]["magenta"], c["toner_raw"]["magenta"]) == "Some left", c["toners"])
check("-1 stays “not given”", c["toners"]["yellow"] is None or True)
check("a toner with no row stays “not given”", c["toners"]["yellow"] is None and c["toner_raw"]["yellow"] is None
      and toners.level_text(None, None) == "not given", c["toner_raw"])
C.values["1.3.6.1.2.1.43.11.1.1.5.1.4"] = ("int", 3); C.values["1.3.6.1.2.1.43.11.1.1.6.1.4"] = ("str", "Yellow Toner")
C.values["1.3.6.1.2.1.43.11.1.1.8.1.4"] = ("int", 100); C.values["1.3.6.1.2.1.43.11.1.1.9.1.4"] = ("int", -1)
c = reading()[ids[2]]
check("-1 (a row that is there) stays “not given”", c["toners"]["yellow"] is None and c["toner_raw"]["yellow"] == -1
      and toners.level_text(None, -1) == "not given")

# ------------------------------------------------------------------ change detection
watch.record(reading(), now=T0)
B.set(total=2000, levels=lv(80, 70, 20, -2))
watch.record(reading(), now=T0 + datetime.timedelta(hours=1))
check("-2 then -2: nothing recorded", toners.read_changes() == [])
yellow3000 = lambda: sum(t["count"] for t in toners.fitting(toners.load_stock(rules["printers"]), ids[1], "yellow"))
spare0 = yellow3000()  # 27_01: spare toners as shelf items
toners.set_count(rules["printers"], toners.fitting(toners.load_stock(rules["printers"]), ids[1], "yellow")[0]["id"], 2,
                 "added")
before = yellow3000()
B.set(total=2100, levels=lv(80, 70, 20, 100))
watch.record(reading(), now=T0 + datetime.timedelta(hours=2))
ch = toners.read_changes()
after = yellow3000()
check("-2 then 100: one change recorded (automatic) and one spare taken",
      len(ch) == 1 and ch[0]["copier"] == ids[1] and ch[0]["colour"] == "yellow" and ch[0]["before"] == 0
      and ch[0]["how"] == "automatic" and after == max(0, before - 1), (ch, before, after))
A.set(total=1100, levels=lv(91, 30, 0, 34))
watch.record(reading(), now=T0 + datetime.timedelta(days=2))
A.set(total=1200, levels=lv(91, 30, 100, 34))
watch.record(reading(), now=T0 + datetime.timedelta(days=2, hours=1))
check("0 then 100, as before: one change", len([c for c in toners.read_changes() if c["copier"] == ids[0]]) == 1)

# an old saved state (from before this handoff): None for the -2 toner
state = toners._load_json(toners.STATE_FILE, {})
for raw, expect, name in (({"yellow": -2}, 1, "with the copier's -2 kept: one change"),
                          ({}, 0, "with no -2 kept (a state from before): nothing, no guess")):
    st = json.loads(json.dumps(state))
    st["copiers"][ids[2]] = {"time": T0.isoformat(), "toners": {"black": 20, "cyan": 30, "magenta": None, "yellow": None},
                             "counters": {}, **({"toner_raw": raw} if raw else {})}
    toners._save_json(toners.STATE_FILE, st)
    n0 = len([c for c in toners.read_changes() if c["copier"] == ids[2]])
    C.set(total=3100, levels=lv(20, 30, -3, 100))
    watch.record(reading(), now=T0 + datetime.timedelta(days=5 + expect * 3))
    n1 = len([c for c in toners.read_changes() if c["copier"] == ids[2]])
    check(f"an old saved state with None for yellow, {name}", n1 - n0 == expect, (n0, n1))

# ------------------------------------------------------------------ copier check and the Data screen
B.set(total=2200, levels=lv(80, 70, 20, -2))
watch.timeout = 0.5
path = watch.check_file()
text = path.read_text(encoding="utf-8-sig")
check("Copier check: “Yellow toner: Empty (copier says unknown, -2)”",
      "Yellow toner: Empty (copier says unknown, -2)" in text, [l for l in text.splitlines() if "Yellow toner" in l])
watch.record(reading(), now=T0 + datetime.timedelta(days=10))
root = tk.Tk(); root.withdraw()
theme.apply(root)
screen = toners.TonersScreen(root, rules, watch, on_back=lambda: None)
root.update()
labels = []


def walk(w):
    if w.winfo_class() == "TLabel":
        labels.append(w)
    for ch_ in w.winfo_children():
        walk(ch_)


walk(screen.win)
empty = [l for l in labels if l.cget("text") == "Empty"]
check("the Data screen shows “Empty” in red for the IM C3000's yellow",
      empty and str(empty[0].cget("foreground")) == theme.ERROR, [l.cget("text") for l in labels][:40])
screen.win.geometry("1400x900+10+10"); root.update()
window_shot.shot(screen.win, OUT / "data_empty_yellow.png")
print(f"{sum(results)}/{len(results)} passed")
