"""The Counter's PDF export: the chosen period on white A4 pages (Tesla, 2026-11-15).

Drawn with pypdfium2 (already used for printing), with Arial embedded so the text is real text
and Greek file names show. Only reads; never changes print_log.csv.
"""
import ctypes
import datetime
import os
from pathlib import Path

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import ImageFont

import costs
import counter


PAGE_W, PAGE_H = 595.0, 842.0  # A4 upright, points
MARGIN = 42.0
WIDTH = PAGE_W - 2 * MARGIN
FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
FONTS = {False: FONT_DIR / "arial.ttf", True: FONT_DIR / "arialbd.ttf"}  # Arial has Greek letters
NOTE = "Counts what was sent from PrintRouter. Photocopies made at the copier are not included."


def file_name(start, end):
    """'PrintRouter counter 2026-11-09 to 2026-11-15.pdf' (one date for a one-day range)."""
    if start == end:
        return f"PrintRouter counter {start:%Y-%m-%d}.pdf"
    return f"PrintRouter counter {start:%Y-%m-%d} to {end:%Y-%m-%d}.pdf"


class Writer:
    """Pages, text, lines and tables that continue on the next page with their header row."""

    def __init__(self):
        self.doc = pdfium.PdfDocument.new()
        self._keep = []  # font data must stay alive until the PDF is saved
        self.fonts, self.measure = {}, {}
        for bold, path in FONTS.items():
            data = path.read_bytes()
            buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
            self._keep.append(buf)
            self.fonts[bold] = raw.FPDFText_LoadFont(self.doc.raw, buf, len(data), raw.FPDF_FONT_TRUETYPE, 1)
            if not self.fonts[bold]:
                raise RuntimeError(f"Can't load the font {path.name}")
            self.measure[bold] = ImageFont.truetype(str(path), 100)
        self.pages = []
        self.new_page()

    def new_page(self):
        self.page = self.doc.new_page(PAGE_W, PAGE_H)
        self.pages.append(self.page)
        self.y = PAGE_H - MARGIN  # top of the next line

    def width(self, text, size, bold=False):
        return self.measure[bold].getlength(text) * size / 100

    def fit(self, text, size, bold, room):
        if self.width(text, size, bold) <= room:
            return text
        while text and self.width(text + "…", size, bold) > room:
            text = text[:-1]
        return text + "…"

    def text(self, x, baseline, text, size, bold=False, align="left", page=None):
        if not text:
            return
        if align == "right":
            x -= self.width(text, size, bold)
        obj = raw.FPDFPageObj_CreateTextObj(self.doc.raw, self.fonts[bold], float(size))
        buf = ctypes.create_string_buffer((text + "\x00").encode("utf-16-le"))
        raw.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(raw.FPDF_WCHAR)))
        raw.FPDFPageObj_SetFillColor(obj, 0, 0, 0, 255)
        raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, float(x), float(baseline))
        raw.FPDFPage_InsertObject((page or self.page).raw, obj)

    def rule(self, y, x=MARGIN, width=WIDTH, thick=0.5, grey=0):
        rect = raw.FPDFPageObj_CreateNewRect(float(x), float(y), float(width), float(thick))
        raw.FPDFPageObj_SetFillColor(rect, grey, grey, grey, 255)
        raw.FPDFPath_SetDrawMode(rect, raw.FPDF_FILLMODE_ALTERNATE, 0)
        raw.FPDFPage_InsertObject(self.page.raw, rect)

    def room(self, height):
        """Start a new page unless `height` points still fit on this one."""
        if self.y - height < MARGIN + 20:
            self.new_page()

    def line(self, text, size=10, bold=False, gap=4):
        self.room(size + gap)
        self.text(MARGIN, self.y - size, self.fit(text, size, bold, WIDTH), size, bold)
        self.y -= size + gap

    def space(self, points):
        self.y -= points

    def table(self, columns, rows, size=9, total=None):
        """columns: [(heading, width share, 'left'/'right')]. A row never splits; the header repeats."""
        shares = sum(c[1] for c in columns)
        widths = [WIDTH * c[1] / shares for c in columns]
        lefts = [MARGIN + sum(widths[:i]) for i in range(len(columns))]
        row_h = size + 5

        def cells(values, bold):
            for (head, _, align), left, w, value in zip(columns, lefts, widths, values):
                value = self.fit(str(value), size, bold, w - 6)
                x = left + w - 4 if align == "right" else left
                self.text(x, self.y - size, value, size, bold, align)
            self.y -= row_h

        def header():
            cells([c[0] for c in columns], True)
            self.rule(self.y + 2)

        self.room(row_h * 2)
        header()
        for values in rows:
            if self.y - row_h < MARGIN + 20:
                self.new_page()
                header()
            cells(values, False)
        if total is not None:
            self.room(row_h + 3)
            self.rule(self.y + 1)
            self.y -= 2
            cells(total, True)

    def save(self, path):
        count = len(self.pages)
        for n, page in enumerate(self.pages, start=1):
            if count > 1:
                self.text(PAGE_W - MARGIN, MARGIN - 14, f"Page {n} of {count}", 8, align="right", page=page)
            raw.FPDFPage_GenerateContent(page.raw)
        self.doc.save(str(path))
        self.doc.close()


def build(path, result, entries, start, end, cost_table, include_costs, include_jobs, now=None):
    """Write the PDF for one period. result: counter.sections(...); entries: the period's log lines."""
    now = now or datetime.datetime.now()
    w = Writer()
    euro = costs.euro
    num = counter.number
    w.line("PrintRouter: what was printed", 18, True, 8)
    w.line(counter.range_text(start, end), 13, True, 4)
    w.line(f"Made {now.day} {now:%b %Y, %H:%M}", 9, gap=4)
    w.line(NOTE, 9, gap=10)

    for title, s in result:
        w.room(70)
        w.space(6)
        w.line(title, 14, True, 6)
        if not s["count"]:
            w.line("Nothing printed in this period", 10)
            continue
        head = []
        if include_costs:
            head.append(f"Cost: {euro(s['cost'])}")
        if title == "PrintHub":
            head.append(f"Orders printed: {s['orders']}")
        if head:
            w.line("     ".join(head), 11, True)
        if include_costs and s["missing"]:
            w.line("Some costs are not set (see Prices)", 9)
        w.space(2)
        cols = [("Size", 2, "left"), ("Colour sides", 2, "right"), ("Colour sheets", 2, "right"),
                ("B&W sides", 2, "right"), ("B&W sheets", 2, "right")] + ([("Cost", 2, "right")] if include_costs else [])
        rows = []
        for size in [x for x in counter.SIZES + ("Other",) if x in s["sizes"] or x in counter.SIZES]:
            c = s["sizes"].get(size, {"color": 0, "bw": 0, "color_sheets": 0, "bw_sheets": 0, "cost": 0.0})
            rows.append([size, num(c["color"]), num(c["color_sheets"]), num(c["bw"]), num(c["bw_sheets"])]
                        + ([euro(c["cost"])] if include_costs else []))
        w.table(cols, rows)
        w.space(6)
        w.line("By paper", 10, True, 3)
        cols = [("Paper", 6, "left"), ("Sheet size", 2, "left"), ("Sheets", 2, "right"),
                ("Colour sides", 2, "right"), ("B&W sides", 2, "right")] + ([("Cost", 2, "right")] if include_costs else [])
        w.table(cols, [[p["paper"], p["size"], num(p["sheets"]), num(p["color"]), num(p["bw"])]
                       + ([euro(p["cost"])] if include_costs else []) for p in s["papers"]])
        if title == "PrintHub":
            w.space(6)
            w.line("By product", 10, True, 3)
            cols = [("Product", 6, "left"), ("Orders", 2, "right"), ("Pieces ordered", 2, "right"),
                    ("Sheets", 2, "right")] + ([("Cost", 2, "right")] if include_costs else [])
            w.table(cols, [[p["product"], num(len(p["orders"])), num(p["pieces"]), num(p["sheets"])]
                           + ([euro(p["cost"])] if include_costs else []) for p in s["products"]])

    if include_jobs and entries:
        w.new_page()
        w.line("List of jobs", 14, True, 6)
        cols = [("Date and time", 3.4, "left"), ("From", 1.8, "left"), ("Order", 2.0, "left"),
                ("Product or file", 4.4, "left"), ("Paper", 3.8, "left"), ("Size", 1.1, "left"),
                ("Sheets", 1.7, "right"), ("Colour", 1.6, "right"), ("B&W", 1.4, "right")]
        if include_costs:
            cols.append(("Cost", 1.9, "right"))
        rows, totals = [], [0, 0, 0, 0.0]
        for e in sorted(entries, key=lambda e: e["time"]):
            cost = cost_table.job_cost(e["size"], e["color"], e["bw"], e["sheets"], e["paper"])[0]
            totals = [totals[0] + e["sheets"], totals[1] + e["color"], totals[2] + e["bw"], totals[3] + cost]
            what = e["product"] if e["source"] == "printhub" and e["product"] else e.get("file", "")
            rows.append([f"{e['time']:%d/%m/%Y %H:%M}", "PrintHub" if e["source"] == "printhub" else "Walk-in",
                         e["order"], what, e["paper"], e["size"], num(e["sheets"]), num(e["color"]), num(e["bw"])]
                        + ([euro(cost)] if include_costs else []))
        total = ["Total", f"{len(rows)} jobs", "", "", "", "", num(totals[0]), num(totals[1]), num(totals[2])]
        w.table(cols, rows, size=8, total=total + ([euro(totals[3])] if include_costs else []))
    w.save(path)


def export(path, result, entries, start, end, cost_table, include_costs, include_jobs):
    """Write the PDF beside the target first, then put it in place: a PDF open in a viewer stays as it
    was and the error is raised (OSError) for the caller's message."""
    path = Path(path)
    tmp = path.with_name(f"~{path.stem}.tmp.pdf")
    try:
        build(tmp, result, entries, start, end, cost_table, include_costs, include_jobs)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
