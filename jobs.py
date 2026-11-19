"""Print jobs: turn a file's settings into a job, check it against the printers, and send it.

Shared by the main window and the PrintHub view, so both route, check, price
and print in exactly the same way.
"""
import csv
import datetime
import math
import os
import threading

import analyze
import convert
import driverprint
import layout
import receipt
import routing

# pdfium can only be used by one thread at a time; hold this around all PDF work
# (converting, analysing, laying out pages, printing).
PDF_LOCK = threading.RLock()
MAX_COPIES = 999  # per print job (the copiers' limit); more copies are sent as several jobs


LOG_FILE = "print_log.csv"
# print_log.csv columns. The last eight were added on 2026-11-15 (Counter screen); older lines
# have only the first fourteen and are still read (counter.py).
LOG_COLUMNS = ["time", "file", "pages", "copies", "color", "sides", "paper", "paper type", "tray", "content",
               "printer", "reason", "sheets", "price",
               "source", "order", "product", "quantity", "sheet size", "color sides", "bw sides", "paper name"]


def sheet_size(paper):
    """The sheet that goes through the copier: A5 is printed 2-up on A4."""
    return "A4" if paper == "A5" else paper


def printed_sides(job, rules):
    """(colour sides, B&W sides) the copier prints for a job, copies included."""
    if job.get("hand") and not job["duplex"]:
        total = 2 * job["sheets"]  # a hand-turned product: page 1 on the fronts, page 2 on the backs
    elif job["paper"] == "A5":
        per_run = job["pages"] if rules.get("a5_layout") == "same_page_twice" else math.ceil(job["pages"] / 2)
        total = per_run * job["print_copies"]  # A4 sides holding the A5 pages
    else:
        total = layout.printed_sides(job["pages"], job["per_side"]) * job["copies"]
    if job.get("mixed"):
        # color_units: colour sides per copy (A5: colour A5 pages, spread over the A4 sides)
        per_copy = (layout.printed_sides(job["pages"], job["per_side"]) if job["paper"] != "A5"
                    else job["pages"])
        color = round(total * job["color_units"] / per_copy) if per_copy else 0
        return color, total - color
    return (total, 0) if job["color"] else (0, total)


def _upgrade_header(path):
    """An old print_log.csv gets the new column names in its first line; every line is kept."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            first = next(csv.reader(f), None)
    except OSError:
        return
    if not first or first[0] != "time" or len(first) >= len(LOG_COLUMNS):
        return
    text = path.read_text(encoding="utf-8-sig")
    rest = text.split("\n", 1)[1] if "\n" in text else ""
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow(LOG_COLUMNS)
        f.write(rest)
    os.replace(tmp, path)


def sides_pdf(pdf, side, out):
    """The fronts (pages 1, 3, 5, ...) or the backs (pages 2, 4, 6, ...) of a laid-out PDF, for printing
    both sides by hand. With an odd page count the backs end with a blank page, so every front
    has its back. Call under PDF_LOCK."""
    import pypdfium2 as pdfium
    src = pdfium.PdfDocument(str(pdf))
    dest = pdfium.PdfDocument.new()
    try:
        count = len(src)
        indexes = list(range(0 if side == "fronts" else 1, count, 2))
        if indexes:
            dest.import_pages(src, indexes)
        if side == "backs" and count % 2:
            w, h = src[count - 1].get_size()
            dest.new_page(w, h)
        dest.save(str(out))
    finally:
        dest.close()
        src.close()
    return out


class Jobs:
    def __init__(self, rules, prices):
        self.rules = rules
        self.prices = prices
        self.printers = rules["printers"]
        self.printer_options = self._read_printer_options()
        # Functions giving the copiers ORCA is using right now (the PrintHub view, the main
        # window's batch being sent); a colour job then goes to the rule's if_busy copier.
        self.busy_sources = []
        self._missing = (0.0, set())

    def missing(self):
        """Printers whose Windows printer isn't on this PC (Settings: "Not found"); routing skips them like busy
        ones when another can take the job. Asked again at most every 30 seconds."""
        import time
        when, found = self._missing
        if time.monotonic() - when > 30:
            found = routing.missing_printers(self.rules)
            self._missing = (time.monotonic(), found)
        return found

    def settings_changed(self):
        """Settings were saved (2026-11-18_02): read the drivers' options and the installed printers again."""
        self._missing = (0.0, set())
        self.printer_options = self._read_printer_options()

    def busy(self):
        found = set()
        for source in self.busy_sources:
            try:
                found |= set(source())
            except Exception:
                pass
        return found

    def _read_printer_options(self):
        """Paper types and trays each printer's driver offers: {printer id: {feature: set}}."""
        options = {}
        for pid, p in self.printers.items():
            try:
                options[pid] = {f: set(driverprint.option_names(p["queue"], f))
                                for f in ("PageMediaType", "JobInputBin")}
            except Exception:
                options[pid] = None  # couldn't read; the printer will report problems itself
        return options

    def warm_up_checks(self):
        """Ask the drivers about every combination in the background, so the window never waits."""
        for pid, p in self.printers.items():
            if not self.printer_options.get(pid):
                continue
            for paper_type in self.rules["paper_types"]:
                for paper in ("A4", "A3"):
                    for duplex in (False, True):
                        for color in (False, True):
                            try:
                                driverprint.refused_settings(p["queue"], paper, color, duplex,
                                                             paper_type, self.rules["defaults"]["tray"])
                            except Exception:
                                pass

    def missing_options(self, printer_id, job):
        """Text naming what the printer doesn't offer for this job, or None."""
        offered = self.printer_options.get(printer_id)
        if not offered:
            return None
        missing = []
        if job["paper_type"] not in offered["PageMediaType"]:
            missing.append(receipt.short_paper_type(job["paper_type"]))
        if job["tray"] not in offered["JobInputBin"]:
            missing.append(job["tray"])
        return f"No {', '.join(missing)} on this printer" if missing else None

    # ------------------------------------------------------------- the jobs

    def job_for(self, name, settings, pages, coverage, page_colors, max_copies=MAX_COPIES, busy=None):
        """The print job for one converted file, or None if its settings can't print yet.

        settings: the per-file options (app.OPTIONS); coverage and page_colors come from analyze.
        PrintHub products add "product": True and "gsm" (from the website paper name).
        max_copies: above MAX_COPIES (PrintHub products), print_one sends several jobs.
        busy: copiers in use now (default: ask busy_sources); the choice is made again when sent.
        """
        s = settings
        if s["printer"] != "auto" and s["printer"] not in self.printers:
            return None
        try:
            copies = int(s["copies"])
        except ValueError:
            return None
        if not 1 <= copies <= max_copies:
            return None
        per_side = int(s["per_side"])
        color_units = None
        if s["color"] == "auto":
            # Charged pages per copy in color: each A5 piece, or each printed side
            # (with several pages per side, a side is color if any page on it is).
            groups = page_colors if s["paper"] == "A5" else [
                any(page_colors[i:i + per_side]) for i in range(0, len(page_colors), per_side)]
            color_units = sum(groups)
        job = {
            "file_name": name,
            "pages": pages,
            "copies": copies,
            "color": s["color"] == "color" or bool(color_units),
            "mixed": bool(color_units) and color_units < len(groups),
            "duplex": s["sides"] != "single",
            "flip": s["sides"],  # single / long / short
            "paper": s["paper"],
            "per_side": per_side,
            "paper_type": s["paper_type"],
            "tray": s["tray"],
            "rotate": s["rotate"] == "1",
            "product": bool(s.get("product")),
            "gsm": s.get("gsm"),
        }
        if job["mixed"]:
            job["color_units"] = color_units
        if not routing.plain(self.rules, job["paper_type"]):
            job["tray"] = routing.BYPASS  # Tesla, 2026-11-13: special paper always from the bypass
            if job["duplex"] and routing.hand_turned(self.rules, job["paper_type"], job["gsm"]):
                # Both sides, turned by hand: fronts and backs are sent as two one-sided jobs
                # (print_one with side=...); duplex stays True so sheets and prices count both sides.
                job["hand"] = True
        if s["printer"] == "auto":
            # Color with many pictures goes elsewhere than color documents (see rules.json).
            job["content"] = (routing.resolve_content(self.rules, "auto", coverage)
                              if job["color"] else "document")
            printer_id, reason = routing.choose_printer(self.rules, job,
                                                        self.busy() if busy is None else busy, self.missing())
            if job["rotate"]:
                printer_id, reason = self.rules["rotate_sort"]["printer"], "Rotate sort"
        else:
            job["content"] = ""
            printer_id, reason = s["printer"], "Picked"
        print_copies, sheets = layout.plan(job["pages"], copies, job["duplex"], job["paper"],
                                           self.rules["a5_layout"], job["per_side"])
        job.update(printer=printer_id, reason=reason, print_copies=print_copies, sheets=sheets)
        if job["paper"] == "A5" and job["per_side"] > 1:
            job["problem"] = "A5 is already 2 on A4: set Pages per side to 1"
        else:
            job["problem"] = (self.rotate_problem(printer_id, job) or self.weight_problem(printer_id, job)
                              or self.capability_problem(printer_id, job)
                              or self.missing_options(printer_id, job) or self.refused(printer_id, job))
        return job

    def weight_problem(self, printer_id, job):
        """Text when the paper is heavier than this copier takes (rules.json printers max_gsm), or None."""
        limit = routing.max_gsm(self.rules, printer_id)
        if job["gsm"] and limit and job["gsm"] > limit:
            return f"{self.printers[printer_id]['label']} takes up to {limit} gsm, this is {job['gsm']} gsm"
        return None

    def capability_problem(self, printer_id, job):
        """Text when no printer can take this job (colour on B&W only, A3 on A4 only: Settings), or None."""
        why = routing.unable(self.rules, printer_id, job)
        return f"No printer can take this: {why}" if why else None

    def rotate_problem(self, printer_id, job):
        """Text saying why rotate sort can't be used for this job, or None."""
        if not job["rotate"]:
            return None
        rs = self.rules["rotate_sort"]
        if rs.get("printer") not in self.printers:
            return "Rotate sort isn't set up on this PC's printers"
        if printer_id != rs["printer"]:
            return f"Rotate sort only on {self.printers[rs['printer']]['label']}"
        if job["paper"] != "A4":
            return "Rotate sort is for A4 only"
        if not routing.plain(self.rules, job["paper_type"]):
            return "Rotate sort is for plain paper (other paper prints from the Bypass Tray)"
        if job["tray"] != self.rules["defaults"]["tray"]:
            return f"Rotate sort uses {' and '.join(rs['trays'])}: set Tray to {self.rules['defaults']['tray']}"
        return None

    def refused(self, printer_id, job):
        """Text naming settings the printer's driver would quietly drop, or None."""
        if not self.printer_options.get(printer_id):
            return None
        paper = "A4" if job["paper"] == "A5" else job["paper"]  # A5 is printed two-up on A4
        trays = self.rules["rotate_sort"]["trays"] if job["rotate"] else [job["tray"]]
        refused = []
        try:
            for tray in trays:
                # A hand-turned job is sent as two one-sided jobs: the driver never sees duplex.
                for r in driverprint.refused_settings(self.printers[printer_id]["queue"], paper, job["color"],
                                                      job["duplex"] and not job.get("hand"), job["paper_type"],
                                                      tray):
                    if r not in refused:
                        refused.append(r)
        except Exception:
            return None  # can't check; the printer will report problems itself
        return f"Can't do {', '.join(refused)} here" if refused else None

    def settings_text(self, settings, job):
        s = settings
        mode = receipt.color_text(job) if job else {"bw": "B&W", "color": "Color", "auto": "Auto color"}[s["color"]]
        if s["color"] == "auto" and job and not job["mixed"]:
            mode += " (auto)"
        parts = [mode, "Both sides by hand" if job and job.get("hand") else receipt.SIDES[s["sides"]],
                 "A5 (2 on A4)" if s["paper"] == "A5" else s["paper"]]
        if s["per_side"] != "1":
            parts.append(f"{s['per_side']} per side")
        if s["paper_type"] != receipt.DEFAULT_PAPER_TYPE:
            parts.append(receipt.short_paper_type(s["paper_type"]))
        tray = job["tray"] if job else s["tray"]
        if tray != receipt.DEFAULT_TRAY:
            parts.append(tray)
        parts.append(f"× {s['copies']}")
        if s["rotate"] == "1":
            parts.append("Rotate sort")
        return " · ".join(parts)

    # ------------------------------------------------------------- printing

    def print_one(self, work_dir, job, src, pdf, pdf_paper, rotate_trays, side=None):
        """Lay out and send one file. work_dir: this file's own temp folder.

        rotate_trays: endless iterator over the rotate sort trays, shared by the whole batch,
        so the stacks keep alternating from one file to the next.
        side: 'fronts' or 'backs' of a hand-turned job (job["hand"]): after the layout, only the odd
        or the even printed sides are sent, one-sided."""
        with PDF_LOCK:
            if convert.needs_paper(src) and pdf_paper != job["paper"]:
                pdf = work_dir / f"document_{job['paper']}.pdf"
                convert.to_pdf(src, pdf, job["paper"])
            send_paper, flip = job["paper"], job["flip"]
            if job["paper"] == "A5":
                # The flip is meant for the cut A5 pieces; a5_on_a4 turns the backs to
                # match, and the A4 sheet itself is always flipped on its long edge.
                a5 = work_dir / "a5_on_a4.pdf"
                layout.a5_on_a4(pdf, a5, self.rules["a5_layout"], job["duplex"], job["flip"])
                pdf, send_paper, flip = a5, "A4", "long"
            elif job["per_side"] > 1:
                combined = work_dir / f"{job['per_side']}_per_side.pdf"
                layout.n_up(pdf, combined, job["per_side"], job["paper"])
                pdf = combined
            if side:
                pdf = sides_pdf(pdf, side, work_dir / f"{side}.pdf")
                job = dict(job, duplex=False)  # each half is printed one-sided; the stack is turned by hand
            queue_name = self.printers[job["printer"]]["queue"]
            if job["rotate"]:
                # Each copy is its own job, taking turns between the trays (portrait / landscape
                # A4), so the copier lays every copy crosswise on the one before.
                for n in range(1, job["print_copies"] + 1):
                    self._send(pdf, queue_name, job, send_paper, flip, next(rotate_trays), 1,
                               f"{job['file_name']} ({n} of {job['print_copies']})")
                return
            total = job["print_copies"]
            if total <= MAX_COPIES:
                self._send(pdf, queue_name, job, send_paper, flip, job["tray"], total, job["file_name"])
                return
            # More copies than one job may hold: several jobs, one after another on the same copier.
            parts = -(-total // MAX_COPIES)
            for n in range(parts):
                copies = min(MAX_COPIES, total - n * MAX_COPIES)
                self._send(pdf, queue_name, job, send_paper, flip, job["tray"], copies,
                           f"{job['file_name']} (part {n + 1} of {parts})")

    def _send(self, pdf, queue_name, job, paper, flip, tray, copies, doc_name):
        if not job["mixed"]:
            devmode = driverprint.build_devmode(queue_name, paper, job["color"], job["duplex"], copies,
                                                job["paper_type"], tray, short_edge=flip == "short")
            driverprint.print_pdf(pdf, queue_name, devmode, doc_name, actual_size=job.get("actual_size", False))
            return
        # Mixed: switch between color and black & white page by page, as printed.
        devmodes = [driverprint.build_devmode(queue_name, paper, color, job["duplex"], 1,
                                              job["paper_type"], tray, short_edge=flip == "short")
                    for color in (True, False)]
        driverprint.print_pdf(pdf, queue_name, devmodes[0], doc_name, mono_devmode=devmodes[1],
                              page_color=analyze.color_pages(pdf), copies=copies, duplex=job["duplex"],
                              actual_size=job.get("actual_size", False))

    def log(self, job, printer_label):
        """One line in print_log.csv per job sent (a hand-turned job once, with both sides).
        job["log_info"] (PrintHub): source, order, product, quantity, paper_name, file."""
        path = routing.app_dir() / LOG_FILE
        info = job.get("log_info") or {}
        try:
            color_sides, bw_sides = printed_sides(job, self.rules)
            row = [datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), info.get("file", job["file_name"]),
                   job["pages"], job["copies"],
                   "mixed" if job["mixed"] else "color" if job["color"] else "bw",
                   receipt.SIDES[job["flip"]].lower(), job["paper"], job["paper_type"],
                   job["tray"], job["content"], printer_label,
                   job["reason"], job["sheets"], f"{receipt.total_price(self.prices, job):.2f}",
                   info.get("source", "walk-in"), info.get("order", ""), info.get("product", ""),
                   info.get("quantity", ""), sheet_size(job["paper"]), color_sides, bw_sides,
                   info.get("paper_name", "")]
            _upgrade_header(path)
            new = not path.exists()
            with open(path, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(LOG_COLUMNS)
                w.writerow(row)
        except Exception:
            pass  # the log must never stop a print
