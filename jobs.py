"""Print jobs: turn a file's settings into a job, check it against the printers, and send it.

Shared by the main window and the PrintHub view, so both route, check, price
and print in exactly the same way.
"""
import csv
import datetime
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


class Jobs:
    def __init__(self, rules, prices):
        self.rules = rules
        self.prices = prices
        self.printers = rules["printers"]
        self.printer_options = self._read_printer_options()

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

    def job_for(self, name, settings, pages, coverage, page_colors, max_copies=MAX_COPIES):
        """The print job for one converted file, or None if its settings can't print yet.

        settings: the per-file options (app.OPTIONS); coverage and page_colors come from analyze.
        max_copies: above MAX_COPIES (PrintHub products), print_one sends several jobs.
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
        }
        if job["mixed"]:
            job["color_units"] = color_units
        if s["printer"] == "auto":
            # Color with many pictures goes elsewhere than color documents (see rules.json).
            job["content"] = (routing.resolve_content(self.rules, "auto", coverage)
                              if job["color"] else "document")
            printer_id, reason = routing.choose_printer(self.rules, job)
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
            job["problem"] = (self.rotate_problem(printer_id, job) or self.missing_options(printer_id, job)
                              or self.refused(printer_id, job))
        return job

    def rotate_problem(self, printer_id, job):
        """Text saying why rotate sort can't be used for this job, or None."""
        if not job["rotate"]:
            return None
        rs = self.rules["rotate_sort"]
        if printer_id != rs["printer"]:
            return f"Rotate sort only on {self.printers[rs['printer']]['label']}"
        if job["paper"] != "A4":
            return "Rotate sort is for A4 only"
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
                for r in driverprint.refused_settings(self.printers[printer_id]["queue"], paper, job["color"],
                                                      job["duplex"], job["paper_type"], tray):
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
        parts = [mode, receipt.SIDES[s["sides"]],
                 "A5 (2 on A4)" if s["paper"] == "A5" else s["paper"]]
        if s["per_side"] != "1":
            parts.append(f"{s['per_side']} per side")
        if s["paper_type"] != receipt.DEFAULT_PAPER_TYPE:
            parts.append(receipt.short_paper_type(s["paper_type"]))
        if s["tray"] != receipt.DEFAULT_TRAY:
            parts.append(s["tray"])
        parts.append(f"× {s['copies']}")
        if s["rotate"] == "1":
            parts.append("Rotate sort")
        return " · ".join(parts)

    # ------------------------------------------------------------- printing

    def print_one(self, work_dir, job, src, pdf, pdf_paper, rotate_trays):
        """Lay out and send one file. work_dir: this file's own temp folder.

        rotate_trays: endless iterator over the rotate sort trays, shared by the whole batch,
        so the stacks keep alternating from one file to the next."""
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
        path = routing.app_dir() / "print_log.csv"
        try:
            new = not path.exists()
            with open(path, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["time", "file", "pages", "copies", "color", "sides", "paper", "paper type",
                                "tray", "content", "printer", "reason", "sheets", "price"])
                w.writerow([datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job["file_name"],
                            job["pages"], job["copies"],
                            "mixed" if job["mixed"] else "color" if job["color"] else "bw",
                            receipt.SIDES[job["flip"]].lower(), job["paper"], job["paper_type"],
                            job["tray"], job["content"], printer_label,
                            job["reason"], job["sheets"], f"{receipt.total_price(self.prices, job):.2f}"])
        except OSError:
            pass  # the log must never stop a print
