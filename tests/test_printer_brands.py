"""Handoff 2026-11-18_03: printers of other brands. Real drivers on this PC are only read (capabilities, a DEVMODE
built in memory); other brands are pretend capability lists; nothing is printed; pictures of ORCA's windows only."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import copy, ctypes, importlib.util, json, os, shutil, subprocess, sys, time, tkinter as tk
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
for f in ("prices.json", "icon.ico", "Walk-in_Prices.xlsx"):
    shutil.copyfile(APP / f, ADMIN / f)
shipped = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
for d in ("pending", "orders", "finished"):
    (ADMIN / d).mkdir()
shipped.update(pending_folder=str(ADMIN / "pending"), orders_folder=str(ADMIN / "orders"),
               finished_folder=str(ADMIN / "finished"), templates_folder=str(APP / "templates"))
(ADMIN / "rules.json").write_text(json.dumps(shipped, indent=1), encoding="utf-8")
routing.app_dir = lambda: ADMIN
REAL = routing.installed_printers() or []
import driverprint as dp
import appicon, copy_counter as cc, jobs, mainmenu, toners, settings_screen as ss
from tkinter import ttk
import window_shot

results = []


def check(name, ok, info=""):
    results.append(bool(ok))
    print(("PASS " if ok else "FAIL ") + name, "|", str(info)[:600])


PAPERS, TRAYS = shipped["paper_types"], shipped["trays"]
NS = {"psf": dp.PSF, "psk": dp.PSK}


def caps(media, bins, prefix="ns0000"):
    """A pretend driver's capabilities, in the form driverprint.capabilities gives."""
    return {"features": {"PageMediaType": {m: f"{prefix}:Media{i}" for i, m in enumerate(media)},
                         "JobInputBin": {b: f"{prefix}:Bin{i}" for i, b in enumerate(bins)}},
            "namespaces": {"psf": dp.PSF, "psk": dp.PSK, prefix: "http://example.invalid/driver"}}


HP = caps(["Plain", "HP EcoFFICIENT", "Light (60-74g)", "Intermediate (85-95g)", "Mid-weight (96-110g)",
           "Heavy 1 (111-175g)", "Heavy 2 (176-220g)", "Heavy 3 (221-256g)", "Extra Heavy (257-300g)", "Cardstock",
           "Labels", "Envelope", "Recycled", "Bond", "Letterhead", "Preprinted", "Colored", "Glossy", "Matte"],
          ["Automatically Select", "Manual Feed", "Tray 1", "Tray 2", "Tray 3"])
CANON = caps(["Plain 1", "Plain 2", "Recycled", "Heavy 1 (106-128 g/m2)", "Heavy 2 (129-163 g/m2)",
              "Heavy 3 (164-220 g/m2)", "Heavy 4 (221-256 g/m2)", "Coated 1", "Labels", "Envelope", "Bond",
              "Color"], ["Auto", "Multi-purpose Tray", "Drawer 1", "Drawer 2"])
KYOCERA = caps(["Plain", "Thin", "Heavy 1", "Heavy 2", "Heavy 3", "Cardstock", "Labels", "Envelope", "Coated",
                "Recycled", "Letterhead", "Bond", "Preprinted", "Color"], ["Auto", "MP Tray", "Cassette 1", "Cassette 2"])
EPSON = caps(["Plain Paper", "Thick Paper (91-163g)", "Extra Thick Paper (164-256g)", "Envelope", "Letterhead",
              "Recycled Paper", "Glossy Paper"], ["Auto Selection", "MP Tray", "Cassette 1"])
RICOH = caps(PAPERS, TRAYS, "ns0001")
FAKES = {"HP LaserJet Test": HP, "Canon iR Test": CANON, "Kyocera Test": KYOCERA, "Epson Test": EPSON}
for q in ["RICOH IM C4510 PCL 6", "RICOH IM C3000 PCL 6_1", "RICOH MP C3004 PCL 6"]:
    dp._caps_cache[q] = RICOH
dp._caps_cache.update(FAKES)

# ------------------------------------------------------------------ real drivers on this PC: read only
for q in REAL:
    try:
        f = dp.capabilities(q)["features"]
        sug = dp.suggest(PAPERS, f.get("PageMediaType", {}), "paper")
        sug.update({("tray", k): v for k, v in dp.suggest(TRAYS, f.get("JobInputBin", {}), "tray").items()})
        dp.use_maps({"x": {"queue": q, "paper_map": {n: v[0] for n, v in dp.suggest(PAPERS, f.get("PageMediaType", {}), "paper").items()},
                           "tray_map": {n: v[0] for n, v in dp.suggest(TRAYS, f.get("JobInputBin", {}), "tray").items()}}})
        bad = []
        for pt in PAPERS:
            for tray in TRAYS:
                try:
                    dp.ticket_for(q, pt, tray)
                except dp.DriverError as e:
                    bad.append((pt, tray, str(e)))
        dm = dp.build_devmode(q, "A4", False, False, 1, "Thick 3(221 to 256 g/m2)", "Bypass Tray")
        check(f"real driver “{q}”: suggestions made, every ORCA paper type and tray builds a ticket, a DEVMODE is "
              f"built (read only)", len(sug) == len(PAPERS) + len(TRAYS) and not bad and len(dm) > 100,
              (bad[:2], len(dm)))
    except Exception as e:
        check(f"real driver “{q}”", False, f"{type(e).__name__}: {e}")
pdfq = next((q for q in REAL if "PDF" in q), None)
if pdfq:
    dp.use_maps({"x": {"queue": pdfq, "paper_map": {p: dp.DEFAULT for p in PAPERS}, "tray_map": {t: dp.DEFAULT for t in TRAYS}}})
    t = dp.ticket_for(pdfq, "Labels", "Bypass Tray")
    check("“Printer's default” leaves the feature out of the ticket", "PageMediaType" not in t and "JobInputBin" not in t, t)
    dp.use_maps({})
    try:
        dp.ticket_for(pdfq, "Labels", None)
        fails = False
    except dp.DriverError:
        fails = True
    check("…without a translation the same job fails as it did before (why this handoff exists)", fails)
dp.use_maps({})

# ------------------------------------------------------------------ pretend drivers: HP, Canon, Kyocera, Epson
hp = dp.suggest(PAPERS, HP["features"]["PageMediaType"], "paper")
check("HP: “Heavy 2 (176-220g)” is suggested for Thick 2, “Heavy 3 (221-256g)” for Thick 3, Labels matched",
      hp["Thick 2(170 to 220 g/m2)"] == ("Heavy 2 (176-220g)", True) and hp["Thick 3(221 to 256 g/m2)"][0] == "Heavy 3 (221-256g)"
      and hp["Labels"] == ("Labels", True) and hp["Cardstock"] == ("Cardstock", True)
      and hp["Plain & Recycled"] == ("Plain", True), hp)
bypass = {name: dp.suggest(["Bypass Tray"], c["features"]["JobInputBin"], "tray")["Bypass Tray"] for name, c in FAKES.items()}
check("the Bypass Tray: “Manual Feed” (HP), “Multi-purpose Tray” (Canon), “MP Tray” (Kyocera, Epson)",
      bypass == {"HP LaserJet Test": ("Manual Feed", True), "Canon iR Test": ("Multi-purpose Tray", True),
                 "Kyocera Test": ("MP Tray", True), "Epson Test": ("MP Tray", True)}, bypass)
canon = dp.suggest(PAPERS, CANON["features"]["PageMediaType"], "paper")
check("Canon: Thick 3 (221-256) -> “Heavy 4 (221-256 g/m2)”, trays by number (“Drawer 1”)",
      canon["Thick 3(221 to 256 g/m2)"][0] == "Heavy 4 (221-256 g/m2)"
      and dp.suggest(["Tray 1"], CANON["features"]["JobInputBin"], "tray")["Tray 1"] == ("Drawer 1", True), canon)
epson = dp.suggest(PAPERS, EPSON["features"]["PageMediaType"], "paper")
check("a driver with no labels type (Epson): Labels is “Printer's default”, marked for picking by hand",
      epson["Labels"] == (dp.DEFAULT, False) and epson["Thick 3(221 to 256 g/m2)"][0] == "Extra Thick Paper (164-256g)", epson)

# ------------------------------------------------------------------ Tesla's copiers: exactly as today
spec = importlib.util.spec_from_loader("old_dp", loader=None)
old = importlib.util.module_from_spec(spec)
exec(subprocess.run(["git", "show", "1df00c2:driverprint.py"], capture_output=True, text=True, check=True,
                    encoding="utf-8").stdout, old.__dict__)
JOBS5 = [("B&W plain A4", "Plain & Recycled", "Auto Tray Select"), ("colour plain A4", "Plain & Recycled", "Auto Tray Select"),
         ("Silk 250 both sides (hand-turned)", "Thick 3(221 to 256 g/m2)", "Bypass Tray"),
         ("Gloss 130 A3 from the bypass", "Thick 3(221 to 256 g/m2)", "Bypass Tray"),
         ("Smooth white 350", "Thick 4(257 to 300 g/m2)", "Bypass Tray")]
rules = routing.load_rules()
dp.use_maps(rules["printers"])
same = all(dp.ticket_for(q, pt, tray) == old._ticket(RICOH, {"PageMediaType": pt, "JobInputBin": tray})
           for q in ("RICOH IM C4510 PCL 6", "RICOH IM C3000 PCL 6_1", "RICOH MP C3004 PCL 6") for _, pt, tray in JOBS5)
check("Tesla's copiers: the print ticket for B&W plain, colour plain, Silk 250, Gloss 130 A3, Smooth white 350 is "
      "exactly today's (no map, ORCA's names)", same)
if pdfq:
    dm_new = dp.build_devmode(pdfq, "A4", True, True, 2)
    dm_old = old.build_devmode(pdfq, "A4", True, True, 2)
    check("…and a DEVMODE built by the new code is byte for byte the old one's (Microsoft Print to PDF, no map)",
          bytes(dm_new) == bytes(dm_old), (len(dm_new), len(dm_old)))
check("…the Ricoh driver offers ORCA's names: “nothing to set”",
      dp.uses_orca_names("RICOH IM C4510 PCL 6", PAPERS, ["Auto Tray Select", "Bypass Tray"]))

# ------------------------------------------------------------------ the translated print path (a pretend HP)
prices = json.loads((APP / "prices.json").read_text(encoding="utf-8"))
hp_map = {n: v[0] for n, v in dp.suggest(PAPERS, HP["features"]["PageMediaType"], "paper").items()}
hp_map["Special 1"] = dp.DEFAULT
tray_map = {n: v[0] for n, v in dp.suggest(TRAYS, HP["features"]["JobInputBin"], "tray").items()}
rules["printers"]["HP"] = {"queue": "HP LaserJet Test", "label": "HP Office", "paper_map": hp_map, "tray_map": tray_map}
J = jobs.Jobs(rules, prices)
s = {"printer": "HP", "copies": "1", "per_side": "1", "color": "color", "sides": "long", "paper": "A4",
     "paper_type": "Thick 3(221 to 256 g/m2)", "tray": "Auto Tray Select", "rotate": "0", "product": True, "gsm": 250}
job = J.job_for("cards.pdf", s, 2, None, [True, True])
ticket = dp.ticket_for("HP LaserJet Test", job["paper_type"], job["tray"])
check("a Silk 250 product on the HP: the ticket says Heavy 3 and Manual Feed (ORCA keeps its own names)",
      job["paper_type"] == "Thick 3(221 to 256 g/m2)" and job["tray"] == "Bypass Tray"
      and HP["features"]["PageMediaType"]["Heavy 3 (221-256g)"] in ticket and HP["features"]["JobInputBin"]["Manual Feed"] in ticket
      and not job["problem"], (job["problem"], ticket[-260:]))
check("…the job line says nothing about a default when none was used", "default" not in J.settings_text(s, job),
      J.settings_text(s, job))
s2 = dict(s, paper_type="Special 1", product=False, gsm=None)
job2 = J.job_for("odd.pdf", s2, 1, None, [True])
check("…and says it once when the paper type was left at the printer's default",
      J.settings_text(s2, job2).endswith("printed with the printer's default paper type") and not job2["problem"]
      and "PageMediaType" not in dp.ticket_for("HP LaserJet Test", "Special 1", None), J.settings_text(s2, job2))

# ------------------------------------------------------------------ the Data screen and the copy counter, unknown brand
root = tk.Tk(); root.withdraw(); appicon.apply(root)
toners.TIMEOUT = 0.2
menu = mainmenu.MainMenu(root)
menu.toners.timeout = 0.2
unknown = {"ok": True, "version": "v1", "model": "Brother HL-X", "sysdescr": "Brother", "address": "10.0.0.9",
           "where": "typed", "counters": {"total": 12345, "black": None, "colour": None},
           "toners": {c: None for c in toners.COLOURS}, "raw": {"supplies": [], "counters": [], "life": 12345},
           "error": None, "page": {"ok": False, "error": "no counter page"}}
try:
    menu.toners.record({"C4510": unknown})
    data = toners.TonersScreen(root, menu.rules, menu.toners, on_back=lambda: None)
    root.update()
    texts = []

    def walk(w):
        if w.winfo_class() == "TLabel":
            texts.append(w.cget("text"))
        for c in w.winfo_children():
            walk(c)
    walk(data.win)
    ok = "12,345" in texts and texts.count("not given") >= 2
    data.win.destroy()
except Exception as e:
    ok, texts = False, [f"{type(e).__name__}: {e}"]
check("the Data screen with a brand that answers the SNMP total only: “not given” lines, no errors", ok, texts[:12])
menu.copy_counter.read_func = lambda pid: {"how": "total", "total": 500}
c = menu.copy_counter.start("C3000")
check("…and the copy counter falls back to the total counter by itself", c.how == "total")
menu.copy_counter.cancel("C3000")

# ------------------------------------------------------------------ the printer edit: Paper and trays
routing.installed_printers = lambda: list(REAL) + ["HP LaserJet Test", "RICOH IM C4510 PCL 6", "RICOH IM C3000 PCL 6_1",
                                                   "RICOH MP C3004 PCL 6", "XP-80C"]
S = ss.SettingsScreen(menu, on_back=lambda: None)
S.win.geometry("1240x1000+10+10"); root.update()
dlg = ss.PrinterDialog(S, None)
dlg.vars["queue"].set("HP LaserJet Test"); dlg.fill_maps(suggest=True); root.update()
check("Add printer with an HP: the Paper and trays part suggests, Labels -> Labels, Bypass -> Manual Feed",
      dlg.map_vars["paper"]["Labels"].get() == "Labels" and dlg.map_vars["tray"]["Bypass Tray"].get() == "Manual Feed"
      and dlg.map_vars["paper"]["Thick 2(170 to 220 g/m2)"].get() == "Heavy 2 (176-220g)")
yellow = [n for (k, n), good in dlg.map_good.items() if not good]
check("…names with no good match are “Printer's default” in yellow (Special 1-3, Large Capacity Tray)",
      set(yellow) >= {"Special 1", "Special 2", "Special 3", "Large Capacity Tray"}
      and dlg.map_vars["paper"]["Special 1"].get() == dp.DEFAULT, yellow)
dlg.vars["label"].set("HP Office")
dlg.dlg.update(); dlg.dlg.geometry("+20+20"); root.update()
window_shot.shot(dlg.dlg, OUT / "paper_and_trays_hp.png")
dlg.map_vars["paper"]["Special 1"].set("Plain")
dlg.done(); root.update()
saved = S.printers.get("HPOffice", {})
check("…OK keeps the translation with the printer (paper_map / tray_map), a hand pick included",
      saved.get("paper_map", {}).get("Special 1") == "Plain" and saved.get("tray_map", {}).get("Bypass Tray") == "Manual Feed")
d2 = ss.PrinterDialog(S, "HPOffice"); root.update()
check("…Edit shows it as saved; Suggest again suggests afresh",
      d2.map_vars["paper"]["Special 1"].get() == "Plain")
d2.fill_maps(suggest=True); root.update()
check("…", d2.map_vars["paper"]["Special 1"].get() == dp.DEFAULT)
d2.dlg.destroy()
d3 = ss.PrinterDialog(S, "C4510"); root.update(); d3.dlg.geometry("+20+20"); root.update()
texts3 = [w.cget("text") for w in d3.maps_box.winfo_children() if w.winfo_class() == "TLabel"]
check("a Ricoh: “This printer uses ORCA's paper names: nothing to set”, and no map is saved",
      texts3 == ["This printer uses ORCA's paper names: nothing to set"] and d3.maps() == {}, texts3)
window_shot.shot(d3.dlg, OUT / "paper_and_trays_ricoh.png")
d3.dlg.destroy()
S.save(); root.update()
check("Save: the map is in settings.json and in use at once",
      json.loads((ADMIN / "settings.json").read_text(encoding="utf-8"))["printers"]["HPOffice"]["tray_map"]["Bypass Tray"] == "Manual Feed"
      and dp.translate("HP LaserJet Test", "tray", "Bypass Tray") == "Manual Feed"
      and dp.translate("RICOH IM C4510 PCL 6", "tray", "Bypass Tray") == "Bypass Tray")
print(f"{sum(results)}/{len(results)} passed")
