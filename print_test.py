"""Find out which print settings a printer's driver actually obeys.

Sends a series of small test jobs to ONE printer through SumatraPDF, each
with different settings (duplex, color/B&W, paper size, copies). Every test
page prints its own name and the settings that were requested, plus visual
checks (color bars, a 100 mm ruler, a border 10 mm from the paper edge), so
you can compare the paper you get against what was asked for.

Needs only the Python standard library and SumatraPDF.

Examples:
    python print_test.py --list
    python print_test.py "RICOH IM C4510 PCL 6" --dry-run
    python print_test.py "RICOH IM C4510 PCL 6"
    python print_test.py "RICOH IM C4510 PCL 6" --only 3,5
"""
import argparse
import csv
import datetime
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "test_results"

SUMATRA_CANDIDATES = [
    HERE / "tools" / "SumatraPDF" / "SumatraPDF.exe",  # portable copy, bundled with the app
    Path(os.environ.get("LOCALAPPDATA", "")) / "SumatraPDF" / "SumatraPDF.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "SumatraPDF" / "SumatraPDF.exe",
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "SumatraPDF" / "SumatraPDF.exe",
]

# Width x height in millimetres, portrait. Keys are SumatraPDF's paper names.
PAPER_MM = {
    "A3": (297, 420),
    "A4": (210, 297),
    "A5": (148, 210),
    "letter": (215.9, 279.4),
    "legal": (215.9, 355.6),
    "tabloid": (279.4, 431.8),
}

MM = 72 / 25.4  # PDF points per millimetre


def build_tests(base):
    """Return (id, sumatra settings, paper of the test PDF, what to check)."""
    other = "letter" if base == "A4" else "A4"
    return [
        ("baseline", "", base, [
            "Nothing was requested: this shows the driver's DEFAULTS.",
            "Write down: one or two sided? Color or grey? Which paper size?",
        ]),
        ("one-sided", f"simplex,color,paper={base}", base, [
            f"Expect: 2 separate sheets, printed on one side only, in color, on {base}.",
        ]),
        ("duplex-long", f"duplexlong,color,paper={base}", base, [
            "Expect: ONE sheet, page 2 on the back.",
            "Flip the sheet like a book page (left to right): page 2 should be upright.",
        ]),
        ("duplex-short", f"duplexshort,color,paper={base}", base, [
            "Expect: ONE sheet, page 2 on the back.",
            "Flip the sheet like a notepad (top to bottom): page 2 should be upright.",
        ]),
        ("black-white", f"simplex,monochrome,paper={base}", base, [
            "Expect: the color bars come out GREY. Any color at all = setting ignored.",
        ]),
        ("paper-A3", "simplex,color,paper=A3", "A3", [
            "Expect: printed on A3 paper. The 100 mm line must measure 100 mm.",
            "If the printer panel asks you to load paper, note that too.",
        ]),
        (f"paper-{other}", f"simplex,color,paper={other}", other, [
            f"Expect: printed on {other} paper. The 100 mm line must measure 100 mm.",
            "If the printer panel asks you to load paper, note that too.",
        ]),
        ("copies-2", f"simplex,color,paper={base},2x", base, [
            "Expect: 2 copies of the document = 4 one-sided sheets in total.",
        ]),
        ("combo", "duplexlong,monochrome,paper=A3,2x", "A3", [
            "Expect: 2 copies, each ONE A3 sheet, double sided (long edge), grey only.",
        ]),
        ("bypass-tray", f"simplex,color,paper={base},bin=Bypass Tray", base, [
            "Expect: both sheets are pulled from the BYPASS (manual feed) tray.",
            "If it used a normal tray, or the panel asked for paper, note that.",
        ]),
    ]


# ---------------------------------------------------------------- PDF writing

def _esc(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _text(x_mm, y_mm, size, text, bold=False):
    font = "F2" if bold else "F1"
    return f"0 0 0 rg BT /{font} {size} Tf {x_mm * MM:.2f} {y_mm * MM:.2f} Td ({_esc(text)}) Tj ET\n"


def _rect(x_mm, y_mm, w_mm, h_mm, fill=None, stroke_width=None):
    r = f"{x_mm * MM:.2f} {y_mm * MM:.2f} {w_mm * MM:.2f} {h_mm * MM:.2f} re"
    if fill is not None:
        return f"{fill[0]} {fill[1]} {fill[2]} rg {r} f\n"
    return f"0 0 0 RG {stroke_width} w {r} S\n"


def _line(x1, y1, x2, y2, width=0.8):
    return f"0 0 0 RG {width} w {x1 * MM:.2f} {y1 * MM:.2f} m {x2 * MM:.2f} {y2 * MM:.2f} l S\n"


def page_front(w, h, num, total, test_id, settings, printer, paper, checks, sent):
    c = _rect(10, 10, w - 20, h - 20, stroke_width=1.5)
    c += _text(w / 2 - 15, h - 18, 12, "TOP OF PAGE", bold=True)
    y = h - 32
    c += _text(20, y, 20, f"PRINT TEST {num}/{total}: {test_id}", bold=True)
    y -= 9
    c += _text(20, y, 11, f"Printer: {printer}")
    y -= 6
    c += _text(20, y, 11, f"Requested: {settings or '(nothing - driver defaults)'}")
    y -= 6
    c += _text(20, y, 11, f"PDF page size: {paper}    Sent: {sent}")
    y -= 16
    c += _text(20, y, 30, "PAGE 1 of 2  (FRONT)", bold=True)
    y -= 12
    for line in checks:
        c += _text(20, y, 11, line)
        y -= 6

    # Color bars: should be grey when B&W was requested.
    y -= 20
    bars = [("RED", (1, 0, 0)), ("GREEN", (0, 0.7, 0)), ("BLUE", (0, 0, 1)),
            ("YELLOW", (1, 0.9, 0)), ("MAGENTA", (1, 0, 1))]
    for i, (name, rgb) in enumerate(bars):
        x = 20 + i * 34
        c += _rect(x, y, 30, 18, fill=rgb)
        c += _text(x, y - 5, 9, name)
    y -= 14
    c += _text(20, y, 11, "If B&W was requested, the bars above must be grey.")

    # 100 mm ruler: shorter means the page was shrunk to fit other paper.
    y -= 20
    c += _line(20, y, 120, y, width=1.2)
    for i in range(11):
        tick = 4 if i % 5 == 0 else 2
        c += _line(20 + i * 10, y, 20 + i * 10, y + tick, width=0.6)
    c += _text(20, y - 6, 11, "This line should measure exactly 100 mm.")
    c += _text(20, y - 12, 11, "Shorter = the page was shrunk (paper size not obeyed).")
    c += _text(20, y - 22, 11, f"The outer border is 10 mm from each edge of {paper} paper.")
    return c


def page_back(w, h, num, total, test_id):
    c = _rect(10, 10, w - 20, h - 20, stroke_width=1.5)
    c += _text(w / 2 - 15, h - 18, 12, "TOP OF PAGE", bold=True)
    c += _text(20, h / 2 + 10, 40, "PAGE 2 of 2", bold=True)
    c += _text(20, h / 2 - 5, 30, "(BACK)", bold=True)
    c += _text(20, h / 2 - 20, 14, f"Test {num}/{total}: {test_id}")
    return c


def write_pdf(path, w_mm, h_mm, page_streams):
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        None,  # page tree, filled in below
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    kids = []
    for stream in page_streams:
        data = stream.encode("latin-1")
        content_no = len(objects) + 2
        kids.append(len(objects) + 1)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w_mm * MM:.2f} {h_mm * MM:.2f}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_no} 0 R >>"
        )
        objects.append(f"<< /Length {len(data)} >>\nstream\n{stream}endstream")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("latin-1")
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1")
    Path(path).write_bytes(out)


# ------------------------------------------------------------------- printing

def find_sumatra(explicit):
    if explicit:
        return Path(explicit) if Path(explicit).is_file() else None
    for p in SUMATRA_CANDIDATES:
        if p.is_file():
            return p
    found = shutil.which("SumatraPDF")
    return Path(found) if found else None


def windows_printers():
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"],
        capture_output=True, text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main():
    ap = argparse.ArgumentParser(description="Send test pages to one printer with different settings.")
    ap.add_argument("printer", nargs="?", help="exact printer name, as shown by --list")
    ap.add_argument("--list", action="store_true", help="list the printers Windows sees and exit")
    ap.add_argument("--only", help="comma-separated test numbers to run, e.g. 3,5")
    ap.add_argument("--base-paper", default="A4", choices=["A4", "letter"],
                    help="normal paper size of the shop (default A4)")
    ap.add_argument("--dry-run", action="store_true", help="make the PDFs and show the commands, but don't print")
    ap.add_argument("--sumatra", help="path to SumatraPDF.exe if it isn't found automatically")
    args = ap.parse_args()

    printers = windows_printers()
    if args.list or not args.printer:
        print("Printers Windows sees:")
        for p in printers:
            print(f"  {p}")
        if not args.list:
            print('\nRun again with a printer name, e.g.: python print_test.py "RICOH IM C4510 PCL 6"')
        return 0

    if args.printer not in printers:
        print(f'Printer "{args.printer}" not found. Names must match exactly; use --list.')
        return 1

    sumatra = find_sumatra(args.sumatra)
    if not sumatra and not args.dry_run:
        print("SumatraPDF.exe not found. Install it (winget install SumatraPDF.SumatraPDF) or pass --sumatra.")
        return 1

    tests = build_tests(args.base_paper)
    total = len(tests)
    chosen = range(1, total + 1)
    if args.only:
        chosen = [int(n) for n in args.only.split(",")]
        bad = [n for n in chosen if not 1 <= n <= total]
        if bad:
            print(f"No such test number(s): {bad}. Tests are numbered 1-{total}.")
            return 1

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUT_DIR / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "results.csv"

    with open(log_path, "w", newline="", encoding="utf-8-sig") as f:
        log = csv.writer(f)
        log.writerow(["test_no", "test", "printer", "settings_sent", "exit_code",
                      "what_to_check", "OBEYED? (fill in)", "notes (fill in)"])
        for num in chosen:
            test_id, settings, paper, checks = tests[num - 1]
            w, h = PAPER_MM[paper]
            sent = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pdf = run_dir / f"test{num:02d}_{test_id}.pdf"
            write_pdf(pdf, w, h, [
                page_front(w, h, num, total, test_id, settings, args.printer, paper, checks, sent),
                page_back(w, h, num, total, test_id),
            ])

            cmd = [str(sumatra or "SumatraPDF.exe"), "-print-to", args.printer]
            if settings:
                cmd += ["-print-settings", settings]
            cmd += ["-silent", str(pdf)]

            print(f"[{num}/{total}] {test_id:<14} settings: {settings or '(defaults)'}")
            if args.dry_run:
                print("    " + subprocess.list2cmdline(cmd))
                code = "dry-run"
            else:
                code = subprocess.run(cmd).returncode
                if code != 0:
                    print(f"    SumatraPDF exit code {code} - job may not have been sent")
                time.sleep(2)  # keep the jobs clearly separate in the queue
            log.writerow([num, test_id, args.printer, settings, code, " ".join(checks), "", ""])

    print(f"\nTest PDFs and checklist: {run_dir}")
    print(f"Open {log_path.name} in Excel and fill in the OBEYED column for each sheet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
