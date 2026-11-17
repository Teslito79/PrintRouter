"""Printing walk-in orders (Print Jobs, 2026-11-17): settings from the order, the copier from routing, a cover
sheet first, every print logged in print_log.csv as source walk-in with the order number #123.

- Preparer: converts and checks each item's file in the background (documents to PDF with convert.py, page count
  and colour; products: the laid-out PDF must be A4 or A3), so the screen never waits.
- settings_for / job_for: the print settings of an item (staff can override them per item, kept in order.json).
- cover_pdf: the plain A4 cover sheet (customer, number, total, date, items).
- Sender: sends one order after the other on its own thread: the cover sheet on the copier of the order's first
  part, before that part, then each copier's items; hand-turned items wait for "turn the stack" (asked on screen).
"""
import datetime
import math
import queue
import re
import tempfile
import threading
from pathlib import Path

import analyze
import convert
import jobs
import orders as ph_orders
import routing
import walkin_catalogue as cat
import walkin_orders
import walkin_pricing

WORK_DIR = Path(tempfile.gettempdir()) / "ORCA" / "walk-in"
TRAY = ph_orders.TRAY
DOC_PAPER_TYPES = {"Normal 80 gsm": "Plain & Recycled", "Glossy 100 gsm": "Coated (Glossy)"}  # as the website's feed
PLAIN = "Plain & Recycled"
COVER = "Cover sheet"


def paper_type_for(rules, paper_name, product=False):
    """The driver paper type for a paper name: the website mapping (rules.json product_papers for products, the
    feed's mapping for documents), else the owner's rule by gsm (80: plain, up to 256: Thick 3, then Thick 4)."""
    if product and paper_name in rules.get("product_papers", {}):
        return rules["product_papers"][paper_name]
    if paper_name in DOC_PAPER_TYPES:
        return DOC_PAPER_TYPES[paper_name]
    gsm = routing.paper_gsm(paper_name)
    if gsm is None or gsm <= 81:
        return PLAIN
    return "Thick 3(221 to 256 g/m2)" if gsm <= 256 else "Thick 4(257 to 300 g/m2)"


# ------------------------------------------------------------------ preparing files

class Preparer:
    """Converts and checks item files in the background; results by (path, size, mtime)."""

    def __init__(self):
        self.done = {}
        self.wanted = queue.Queue()
        self.busy = set()
        self.lock = threading.Lock()
        threading.Thread(target=self._work, daemon=True).start()

    @staticmethod
    def key(path, item):
        st = path.stat()
        return (str(path), st.st_size, st.st_mtime_ns, item["kind"], item.get("size"))

    def get(self, order, item):
        """The prepared file, {"error": ...}, or None while it is being prepared (asked for in the background)."""
        path = walkin_orders.item_file(order, item)
        if path is None:
            return None
        try:
            key = self.key(path, item)
        except OSError:
            return None
        with self.lock:
            if key in self.done:
                return self.done[key]
            if key not in self.busy:
                self.busy.add(key)
                self.wanted.put((key, path, dict(item)))
        return None

    def _work(self):
        while True:
            key, path, item = self.wanted.get()
            try:
                result = self.prepare(path, item)
            except Exception as e:
                result = {"error": f"{path.name}: {e}"}
            with self.lock:
                self.done[key] = result
                self.busy.discard(key)

    @staticmethod
    def prepare(path, item):
        if item["kind"] == "product":
            paper, info = walkin_orders.pdf_sheet(path)
            if paper is None:
                return {"error": f"{path.name}: {info}"}
            with jobs.PDF_LOCK:
                coverage = analyze.color_coverage(path)
                colors = analyze.color_pages(path)
            return {"pdf": path, "paper": paper, "pages": info, "coverage": coverage, "page_colors": colors}
        work = WORK_DIR / re.sub(r"\W", "_", str(path))[-80:]
        work.mkdir(parents=True, exist_ok=True)
        pdf = work / f"document_{item['size']}.pdf"
        with jobs.PDF_LOCK:
            convert.to_pdf(path, pdf, item["size"])
            pages = analyze.page_count(pdf)
            coverage = analyze.color_coverage(pdf)
            colors = analyze.color_pages(pdf)
        return {"pdf": pdf, "paper": item["size"], "pages": pages, "coverage": coverage, "page_colors": colors,
                "src": path}


# ------------------------------------------------------------------ settings and jobs

def settings_for(rules, item, prepared):
    """The print settings of an item, from the order (staff overrides in item["print"] win)."""
    if item["kind"] == "product":
        p = walkin_pricing.product_of(item)
        paper = cat.choice(p, "paper", item["picks"])
        both = cat.choice(p, "sides", item["picks"]) == "Both sides"
        s = {"color": "color", "printer": "auto", "sides": "long" if both else "single",
             "paper": (prepared or {}).get("paper") or "A4", "per_side": "1",
             "paper_type": paper_type_for(rules, paper, product=True), "tray": TRAY,
             "copies": str(item.get("sheets") or 1), "rotate": "0", "product": True, "gsm": routing.paper_gsm(paper)}
    else:
        s = {"color": {"bw": "bw", "color": "color", "mixed": "auto"}[item["color"]], "printer": "auto",
             "sides": "long" if item["sides"] == "double" else "single", "paper": item["size"],
             "per_side": str(item.get("per_side", 1)), "paper_type": paper_type_for(rules, item["paper"]),
             "tray": TRAY, "copies": str(item["copies"]), "rotate": "0"}
    s.update(item.get("print") or {})
    return s


def job_for(shared_jobs, rules, item, prepared, printer=None, busy=None):
    """The print job for an item (None when it can't be worked out), with the copier routed or picked."""
    if not prepared or "error" in prepared:
        return None
    s = settings_for(rules, item, prepared)
    if printer:
        s["printer"] = printer
    job = shared_jobs.job_for(item["folder"], s, prepared["pages"], prepared["coverage"], prepared["page_colors"],
                              9999 if item["kind"] == "product" else jobs.MAX_COPIES, busy=busy)
    if job is not None and item["kind"] == "product":
        job["actual_size"] = True  # the laid-out sheet exactly as it is
    return job


def cover_job(shared_jobs, printer):
    s = {"color": "bw", "printer": printer, "sides": "single", "paper": "A4", "per_side": "1", "paper_type": PLAIN,
         "tray": TRAY, "copies": "1", "rotate": "0"}
    return shared_jobs.job_for(COVER, s, 1, 0.0, [False])


def log_info(order, item=None):
    if item is None:
        return {"source": "walk-in", "order": f"#{order['number']}", "product": COVER, "quantity": "",
                "paper_name": "", "file": f"#{order['number']} {COVER}"}
    if item["kind"] == "product":
        p = walkin_pricing.product_of(item)
        return {"source": "walk-in", "order": f"#{order['number']}", "product": p["name"], "quantity": item["qty"],
                "paper_name": cat.choice(p, "paper", item["picks"]), "file": f"#{order['number']} {item['folder']}"}
    return {"source": "walk-in", "order": f"#{order['number']}", "product": "Document", "quantity": "",
            "paper_name": item["paper"], "file": f"#{order['number']} {item['folder']}"}


# ------------------------------------------------------------------ the cover sheet

def cover_pdf(order, path, when=None):
    """A plain A4 page: customer, the number large, the total, the date, the items."""
    import counter_pdf
    when = when or datetime.datetime.now()
    w = counter_pdf.Writer()
    c = order["customer"]
    w.line("ORCA walk-in order", 12, gap=14)
    w.line(f"#{order['number']}", 72, True, 22)
    for text in (c.get("name"), c.get("phone"), c.get("email")):
        if text:
            w.line(text, 18, True, 8)
    w.space(10)
    due = walkin_orders.price_due(order)
    w.line(f"Total: EUR {due:,.2f}" + ("  (changed price)" if order.get("changed_total") is not None else ""), 18, True, 8)
    w.line(f"Printed {when.day} {when:%b %Y, %H:%M}   ·   placed {order['created'][:10]}", 11, gap=16)
    w.line("Items", 13, True, 6)
    for i, item in enumerate(order["items"], start=1):
        w.line(f"{i}. {item['description']}", 11, gap=5)
    w.save(path)
    return path


# ------------------------------------------------------------------ sending

class Sender:
    """Sends planned orders one after another on its own thread; messages for the screen go to self.results."""

    def __init__(self, shared_jobs):
        self.jobs = shared_jobs
        self.todo = queue.Queue()
        self.results = queue.Queue()
        self.sending = set()  # copiers in use by the current order (busy for the colour choice)
        self.active = 0
        shared_jobs.busy_sources.append(lambda: set(self.sending))
        threading.Thread(target=self._work, daemon=True).start()

    def busy(self):
        return self.active > 0

    def send(self, order, plan):
        """plan: [(printer, [(item index or None for the cover, job, pdf)])] in the order to send."""
        self.active += 1
        self.todo.put((order, plan))

    def _work(self):
        while True:
            order, plan = self.todo.get()
            self.sending = {printer for printer, _ in plan}
            failed = None
            try:
                for printer, parts in plan:
                    for index, job, pdf in parts:
                        label = self.jobs.printers[printer]["label"]
                        name = COVER if index is None else order["items"][index]["folder"]
                        self.results.put(("progress", order["number"], f"#{order['number']}: {name} → {label}…"))
                        work = WORK_DIR / f"send_{order['number']}_{index}"
                        work.mkdir(parents=True, exist_ok=True)
                        if job.get("hand"):
                            self.jobs.print_one(work, job, pdf, pdf, job["paper"], None, side="fronts")
                            answer = {"event": threading.Event(), "ok": False}
                            self.results.put(("turn", order["number"], name, label, answer))
                            answer["event"].wait()
                            if not answer["ok"]:
                                raise RuntimeError(f"{name}: the fronts were sent, the backs were NOT")
                            self.jobs.print_one(work, job, pdf, pdf, job["paper"], None, side="backs")
                        else:
                            self.jobs.print_one(work, job, pdf, pdf, job["paper"], None)
                        job["log_info"] = log_info(order, None if index is None else order["items"][index])
                        self.jobs.log(job, label)
            except Exception as e:
                failed = str(e)
            self.sending = set()
            self.active -= 1
            self.results.put(("done", order["number"], failed))
