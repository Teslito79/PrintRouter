"""Counter -> PDF export. Temp folder only; the real print_log.csv is never used."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests\ (helpers)
import helpers  # tests\helpers.py: temp folders, safety guard, the price template (2026-11-27_03)
import csv, ctypes, datetime, json, os, re, shutil, sys, time, tkinter as tk
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
import jobs, costs, counter, counter_pdf, theme
from tkinter import messagebox, filedialog, ttk
import pypdfium2 as pdfium
from PIL import ImageGrab

rules = json.loads((APP / "rules.json").read_text(encoding="utf-8"))
results = []


def check(name, ok, info=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name, "|", info)


# ------------------------------------------------------------ the test log (as in handoff 2026-11-15_02)
H = jobs.LOG_COLUMNS


def row(time_, file_, source, order, product, qty, size, cs, bs, sheets, paper_name, paper_type="Plain & Recycled"):
    return [time_, file_, "1", "1", "color" if cs else "bw", "single", size, paper_type, "Auto Tray Select", "", "x",
            "", str(sheets), "0.00", source, order, product, str(qty) if qty else "", size, str(cs), str(bs), paper_name]


rows = [H,
        ["2025-12-30 10:00:00", "PH-10011 01 menu.pdf", "2", "3", "color", "single", "A4", "Plain & Recycled",
         "Auto Tray Select", "document", "MP C3004", "", "6", "1.20"],
        ["2026-11-15 09:00:00", "flyer.pdf", "1", "4", "bw", "single", "A3", "Plain & Recycled", "Auto Tray Select",
         "document", "IM C4510", "", "4", "0.80"],
        ["broken line"],
        row("2026-11-15 12:00:00", "a_bw.pdf", "walk-in", "", "", 0, "A4", 0, 6, 6, ""),
        row("2026-11-14 12:00:00", "b_colour.pdf", "walk-in", "", "", 0, "A4", 10, 0, 5, ""),
        row("2026-11-10 12:00:00", "c_mixed.pdf", "walk-in", "", "", 0, "A4", 6, 6, 12, ""),
        row("2026-11-05 12:00:00", "PH-40000 01 Flyers", "printhub", "PH-40000", "Flyers", 200, "A3", 20, 0, 20,
            "Silk 300 gsm", "Thick 4(257 to 300 g/m2)"),
        row("2026-10-20 12:00:00", "PH-40001 01 Cards", "printhub", "PH-40001", "Business cards", 100, "A4", 26, 0, 13,
            "Silk 300 gsm", "Thick 4(257 to 300 g/m2)"),
        row("2026-11-13 12:00:00", "PH-30001 01 01", "printhub", "PH-30001", "Document", 0, "A4", 8, 0, 4, "",
            "Thick 4(257 to 300 g/m2)"),
        row("2026-11-12 16:45:00", "Προσφορά Λευκωσία.pdf", "walk-in", "", "", 0, "A4", 3, 0, 3, "")]
# Enough jobs in March to fill three pages of the job list
for i in range(150):
    d = datetime.datetime(2026, 3, 2, 8, 0) + datetime.timedelta(minutes=37 * i)
    rows.append(row(f"{d:%Y-%m-%d %H:%M:%S}", f"march job {i + 1:03d}.pdf", "walk-in", "", "", 0,
                    "A4" if i % 3 else "A3", i % 2 * 2, 2 - i % 2 * 2, 2, ""))
with open(TMP / jobs.LOG_FILE, "w", newline="", encoding="utf-8-sig") as f:
    csv.writer(f).writerows(rows)
log_before = (TMP / jobs.LOG_FILE).read_bytes()

data = costs.empty(rules)
data["copy"]["A3"]["color"] = 0.20
data["copy"]["A4"]["color"] = 0.10
data["copy"]["A4"]["bw"] = 0.03
next(p for p in data["papers"] if p["name"] == "Silk 300 gsm")["A3"] = 0.05
costs.save(data)

# ------------------------------------------------------------ the screen and the export
root = tk.Tk(); root.withdraw()
theme.apply(root)
ttk.Style(root).configure("Summary.TLabel", font=("Segoe UI", 13, "bold"))
ttk.Style(root).configure(".", font=("Segoe UI", 12))
ttk.Style(root).configure("Section.TLabelframe.Label", font=("Segoe UI", 12, "bold"))
opened, messages = [], []
counter.os.startfile = lambda p: opened.append(p)
messagebox.showwarning = lambda **k: messages.append(k["message"])
target = {"path": None}
dialog_args = {}


def fake_save(**k):
    dialog_args.update(k)
    return target["path"]


filedialog.asksaveasfilename = fake_save


def pump(secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.02)


screen = counter.CounterScreen(root, rules, on_back=lambda: None, today=datetime.date(2026, 11, 15))
pump()
check("tick boxes on by default", screen.with_costs.get() and screen.with_jobs.get())


def pdf_text(path):
    doc = pdfium.PdfDocument(str(path))
    pages = []
    for p in doc:
        t = p.get_textpage().get_text_range()
        pages.append([re.sub(r"\s+", " ", line.replace("\xa0", " ").replace("\xad", "-").replace("\x02", "-")).strip() for line in t.splitlines()])
    doc.close()
    return pages


def section_chunks(lines):
    """Lines of each section (Total, Walk-in, PrintHub), before the job list."""
    out, current = {}, None
    for line in lines:
        if line == "List of jobs":
            break
        if line in ("Total", "Walk-in", "PrintHub"):
            current = line
            out[current] = []
        elif current:
            out[current].append(line)
    return out


def expected_rows(s, with_costs, title="PrintHub"):
    """The rows the PDF shows for a section: products and "Orders printed" under PrintHub only (as the screen)."""
    num, euro = counter.number, costs.euro
    rows = []
    for size in [x for x in counter.SIZES + ("Other",) if x in s["sizes"] or x in counter.SIZES]:
        c = s["sizes"].get(size, {"color": 0, "bw": 0, "color_sheets": 0, "bw_sheets": 0, "cost": 0.0})
        rows.append(" ".join([size, num(c["color"]), num(c["color_sheets"]), num(c["bw"]), num(c["bw_sheets"])]
                             + ([euro(c["cost"])] if with_costs else [])))
    for p in s["papers"]:
        rows.append(" ".join([p["paper"], p["size"], num(p["sheets"]), num(p["color"]), num(p["bw"])]
                             + ([euro(p["cost"])] if with_costs else [])))
    for p in (s["products"] if title == "PrintHub" else []):
        rows.append(" ".join([p["product"], num(len(p["orders"])), num(p["pieces"]), num(p["sheets"])]
                             + ([euro(p["cost"])] if with_costs else [])))
    if with_costs:
        rows.append(f"Cost: {euro(s['cost'])}" + (f" Orders printed: {s['orders']}" if title == "PrintHub" else ""))
    return rows


def export(name, how, with_costs=True, with_jobs=True):
    if how == "custom":
        screen.from_var.set("1/3/2026"); screen.to_var.set("12/11/2026"); screen.custom()
    else:
        screen.choose(how)
    screen.with_costs.set(with_costs); screen.with_jobs.set(with_jobs)
    target["path"] = str(OUT / name)
    screen.export_pdf()
    pump(0.1)
    return OUT / name


for how, name in (("This week", "week.pdf"), ("This year", "year.pdf"), ("custom", "custom.pdf")):
    path = export(name, how)
    pages = pdf_text(path)
    lines = [l for p in pages for l in p]
    chunks = section_chunks(lines)
    ok = all(all(r in chunks.get(title, []) for r in expected_rows(s, True, title)) for title, s in screen.result)
    missing = [(title, r) for title, s in screen.result for r in expected_rows(s, True, title) if r not in chunks.get(title, [])]
    total, walk, hub = (s for _, s in screen.result)
    summed = all(total["sizes"].get(z, {}).get(k, 0) == walk["sizes"].get(z, {}).get(k, 0) + hub["sizes"].get(z, {}).get(k, 0)
                 for z in ("A3", "A4") for k in ("color", "bw", "color_sheets", "bw_sheets"))
    check(f"{how}: every number in the PDF equals the screen's; Walk-in + PrintHub = Total", ok and summed and
          lines[0] == "ORCA: what was printed" and counter.range_text(screen.start, screen.end) in lines, missing[:3])
    # Job list: every job once, total row = Total section
    job_lines = [l for l in lines if re.match(r"\d\d/\d\d/\d{4} \d\d:\d\d ", l)]
    check(f"{how}: every job listed once", len(job_lines) == len(screen.entries)
          and all(sum(1 for l in job_lines if l.startswith(f"{e['time']:%d/%m/%Y %H:%M}") and
                      (e["order"] or e["file"][:12]) in l) >= 1 for e in screen.entries),
          (len(job_lines), len(screen.entries)))
    t = total
    tot_line = " ".join(["Total", f"{len(screen.entries)} jobs",
                         counter.number(sum(v["color_sheets"] + v["bw_sheets"] for v in t["sizes"].values())),
                         counter.number(sum(v["color"] for v in t["sizes"].values())),
                         counter.number(sum(v["bw"] for v in t["sizes"].values())), costs.euro(t["cost"])])
    check(f"{how}: total row equals the Total section", tot_line in lines, tot_line)
    if how == "This week":
        check("file name and Documents folder offered", dialog_args["initialfile"] == "PrintRouter counter 2026-11-09 to 2026-11-15.pdf"
              and Path(dialog_args["initialdir"]).name.lower() in ("documents", "έγγραφα") or "Documents" in dialog_args["initialdir"],
              (dialog_args["initialfile"], dialog_args["initialdir"]))
        check("the hand-turned product counts once", sum("PH-30001" in l for l in job_lines) == 1)
        check("Greek file name shows correctly", any("Προσφορά Λευκωσία.pdf" in l for l in job_lines))
        check("the PDF opened after saving", opened and opened[-1] == str(path))
    if how == "This year":
        n = len(pages)
        heads = sum(1 for l in lines if l.startswith("Date and time From Order"))
        job_pages = [p for p in pages if any(re.match(r"\d\d/\d\d/\d{4} \d\d:\d\d ", l) for l in p)]
        check("long list: 3+ pages of jobs, header row on each, page numbers right",
              len(job_pages) >= 3 and heads == len(job_pages)
              and all(f"Page {i} of {n}" in p for i, p in enumerate(pages, start=1)), (n, len(job_pages), heads))
        check("no cut rows: every job line is complete", all(re.match(r"\d\d/\d\d/\d{4} \d\d:\d\d (Walk-in|PrintHub) ", l)
                                                             and re.search(r"€ [\d ]+\.\d\d$", l) for l in job_lines))
        shutil.copyfile(path, OUT / "Counter with costs and the list of jobs (This year).pdf")

path = export("nocost.pdf", "This year", with_costs=False, with_jobs=False)
text = " ".join(l for p in pdf_text(path) for l in p)
check("Include costs off: no 'Cost' and no euro sign anywhere", "Cost" not in text and "cost" not in text and "€" not in text)
check("Include the list of jobs off: no list", "List of jobs" not in text and not re.search(r"\d\d/\d\d/\d{4} \d\d:\d\d", text))
shutil.copyfile(path, OUT / "Counter without costs or jobs (This year).pdf")

screen.from_var.set("1/1/2024"); screen.to_var.set("31/1/2024"); screen.custom()
check("empty range: one-day name, no list", True)
path = export("empty.pdf", "custom")  # custom resets the range; use an empty one instead
screen.from_var.set("1/1/2024"); screen.to_var.set("31/1/2024"); screen.custom()
target["path"] = str(OUT / "empty.pdf"); screen.export_pdf()
text = [l for p in pdf_text(OUT / "empty.pdf") for l in p]
check("an empty range exports with 'Nothing printed in this period'", text.count("Nothing printed in this period") == 3, text)
screen.from_var.set("15/11/2026"); screen.to_var.set("15/11/2026"); screen.custom()
target["path"] = str(OUT / "oneday.pdf"); screen.export_pdf()
check("one-day range: one date in the file name", dialog_args["initialfile"] == "ORCA counter 2026-11-15.pdf",
      dialog_args["initialfile"])

# Open in a viewer (the file is held open): a plain message, the old file is kept, nothing breaks
held = open(OUT / "week.pdf", "rb")
before = (OUT / "week.pdf").stat().st_size
messages.clear()
screen.choose("This week")
target["path"] = str(OUT / "week.pdf"); screen.export_pdf()
held.close()
check("exporting over a PDF open in a viewer: the message, no crash", messages and "Close the PDF and try again" in messages[0]
      and (OUT / "week.pdf").stat().st_size == before and not list(OUT.glob("~*")), messages)
check("the export never changed print_log.csv", (TMP / jobs.LOG_FILE).read_bytes() == log_before)

# The tick boxes are remembered
screen.with_costs.set(False); screen.with_jobs.set(True); screen.save_settings()
screen.win.destroy()
screen = counter.CounterScreen(root, rules, on_back=lambda: None, today=datetime.date(2026, 11, 15))
check("tick boxes kept after a restart", (screen.with_costs.get(), screen.with_jobs.get()) == (False, True))
screen.with_costs.set(True); screen.save_settings()

# Screenshot of the Counter with the new button, and the PDF pages as pictures
screen.win.geometry("1100x700+30+30"); screen.win.attributes("-topmost", True); pump(1.2)
x, y, w, h = screen.win.winfo_rootx(), screen.win.winfo_rooty(), screen.win.winfo_width(), screen.win.winfo_height()
ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(OUT / "counter_export_button.png")
doc = pdfium.PdfDocument(str(OUT / "Counter with costs and the list of jobs (This year).pdf"))
for i in (0, 2):
    doc[i].render(scale=1.4).to_pil().save(OUT / f"pdf_page{i + 1}.png")
doc.close()
root.destroy()
print("ALL OK" if all(results) else "SOME FAILED", f"{sum(results)}/{len(results)}")
