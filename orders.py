"""PrintHub orders: read the order folders the website downloads, and check them.

orders/<order number>/order.json lists the steps and the documents in print
order; each document folder holds a PDF and a job.json with its print settings.
A folder without order.json is still being downloaded and is skipped. Orders
with problems are still listed, with the problems, so staff can see them.
The files are only read, never changed. See PRINTHUB_SPEC.md.

Run `py -3.14 orders.py [folder]` to list and check the orders in a folder.
"""
import datetime
import json
import sys
import time
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

import analyze
import layout
import routing

FORMAT = 1  # the order.json / job.json format this app reads
STEPS = ("PRINT", "LAMINATE", "SPIRAL", "CUTTING")
DELIVERY = ("courier", "pickup")
COLORS = ("bw", "color", "auto")
SIDES = ("single", "long", "short")
PAPERS = ("A4", "A3", "A5")
TRAY = "Auto Tray Select"  # orders never pick a tray; the copier does from size and paper type

# Product items (PRINTHUB_SPEC.md 3.4): the owner lays them out in CorelDRAW and saves print.pdf.
PRINT_PDF = "print.pdf"
PRINT_CDR = "print.cdr"  # blank CorelDRAW file put in each product item; CorelDRAW then offers print.pdf on export
OPTIONS_TXT = "Options.txt"  # what the customer ordered, for staff (written by PrintRouter)
PRODUCT_FILES = (".pdf", ".png", ".jpg", ".jpeg", ".ai", ".eps", ".psd")
MAX_PRODUCT_FILES = 5
MAX_CUT_MM = (297, 420)  # A3: the largest the copiers print
SHEET_MM = {"A4": (210, 297), "A3": (297, 420)}  # print.pdf pages must be one of these
SHEET_TOLERANCE_MM = 1.5
BLEED_MM = (0, 7)  # a customer file may be the cut size plus up to about 3 mm bleed on each side
SAVING_SECONDS = 3  # print.pdf changed this recently: CorelDRAW may still be writing it
DOUBLE_SIDED = ("Both sides", "Double-sided")  # Sides choices that mean printing on both sides


class Document:
    """One item of an order: a subfolder with job.json and a PDF (a document),
    or with the customer's files and, once laid out, print.pdf (a product)."""

    def __init__(self, name, folder):
        self.name = name  # subfolder name, e.g. '01'
        self.folder = folder
        self.title = name  # the customer's file name (documents) or product and quantity, shown to staff
        self.kind = "document"
        self.pdf = None  # the file to print: the document, or a product's checked print.pdf
        self.pages = None  # counted in the PDF
        self.job = {}  # job.json as read
        self.problems = []  # make the order Needs attention
        # Products only
        self.files = []  # (path, customer's file name, size note or None, size warning or None)
        self.print_stamp = None  # (size, modified) of print.pdf, to notice when it changes
        self.print_paper = None  # A4 / A3, from the pages of print.pdf
        self.print_state = None  # None (no print.pdf), 'saving', 'bad' or 'ok'
        self.print_problem = None  # why print.pdf can't print (shown, but the order isn't Needs attention)

    @property
    def product(self):
        return self.kind == "product"

    def product_settings(self, sheets, paper_type, sides):
        """print.pdf as the main window's per-file settings: as it is, `sheets` copies, in colour."""
        return {"color": "color", "printer": "auto", "sides": sides, "paper": self.print_paper,
                "per_side": "1", "paper_type": paper_type, "tray": TRAY, "copies": str(sheets), "rotate": "0"}

    def default_paper_type(self, rules):
        """The driver paper type for the customer's Paper choice (rules.json product_papers), or None."""
        return rules.get("product_papers", {}).get(self.job.get("options", {}).get("Paper"))

    def default_sides(self):
        return "long" if self.job.get("options", {}).get("Sides") in DOUBLE_SIDED else "single"

    def settings(self):
        """The job as the main window's per-file settings (app.OPTIONS), printer chosen by the rules."""
        j = self.job
        return {"color": j["color"], "printer": "auto", "sides": j["sides"], "paper": j["paper"],
                "per_side": str(j["per_side"]), "paper_type": j["paper_type"], "tray": TRAY,
                "copies": str(j["copies"]), "rotate": "0"}


class Order:
    def __init__(self, folder):
        self.folder = folder
        self.number = folder.name
        self.paid_at = None  # timezone-aware datetime
        self.delivery = None
        self.steps = []
        self.note = ""
        self.documents = []
        self.problems = []  # about the order itself; each document keeps its own

    @property
    def ok(self):
        return not self.all_problems()

    def all_problems(self):
        return self.problems + [f"{d.name} ({d.title}): {p}" for d in self.documents for p in d.problems]


def pending_dir(rules):
    """Where the website's orders arrive (next to the app unless a full path is given). They wait
    here until every product item is laid out; orders with documents only move on at once."""
    return _named_dir(rules.get("pending_folder", "Pending Orders"))


def orders_dir(rules):
    """Orders ready for the copiers: moved here from Pending Orders."""
    return _named_dir(rules.get("orders_folder", "Orders"))


def finished_dir(rules):
    """Where an order folder is moved once it is Ready for courier / pickup."""
    return _named_dir(rules.get("finished_folder", "Finished Orders"))


def templates_dir(rules):
    """blank.cdr (and <product id>.cdr) copied into each product item as print.cdr."""
    return _named_dir(rules.get("templates_folder", "templates"))


def _named_dir(name):
    folder = routing.app_dir() / name
    # Windows ignores case: show the folder as named in rules.json (e.g. an old 'orders' becomes 'Orders').
    try:
        if folder.is_dir() and folder.resolve().name != folder.name and folder.resolve().name.lower() == folder.name.lower():
            tmp = folder.with_name(folder.name + ".renaming")
            folder.resolve().rename(tmp)
            tmp.rename(folder)
    except OSError:
        pass
    return folder


def load_orders(folder, rules):
    """Every complete order in the folder, oldest payment first."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    # Folders starting with '.' are still being copied in under a temporary name.
    orders = [load_order(sub, rules) for sub in sorted(folder.iterdir())
              if sub.is_dir() and not sub.name.startswith(".") and (sub / "order.json").is_file()]
    return sort_orders(orders)


def sort_orders(orders):
    """Oldest payment first."""
    latest = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)  # no date: last
    return sorted(orders, key=lambda o: (o.paid_at or latest, o.number))


def _plain_name(value):
    """True for a bare file or folder name: nothing that points outside the order folder."""
    return isinstance(value, str) and value not in ("", ".", "..") and Path(value).name == value


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _read_json(path, problems):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        problems.append(f"Can't read {path.name}: {e}")
        return None
    if not isinstance(data, dict):
        problems.append(f"{path.name} is not a JSON object")
        return None
    if data.get("format") != FORMAT:
        problems.append(f"{path.name} has format {data.get('format')!r}; this app reads format {FORMAT}")
        return None
    return data


def load_order(folder, rules):
    order = Order(Path(folder))
    p = order.problems
    data = _read_json(order.folder / "order.json", p)
    if data is None:
        return order
    if data.get("order") != order.number:
        p.append(f"Order number {data.get('order')!r} doesn't match the folder name")
    try:
        order.paid_at = datetime.datetime.fromisoformat(data["paid_at"]).astimezone()
    except (KeyError, TypeError, ValueError):
        p.append("paid_at is missing or not a date and time")
    order.delivery = data.get("delivery")
    if order.delivery not in DELIVERY:
        p.append(f"Delivery must be {' or '.join(DELIVERY)}, not {order.delivery!r}")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps or steps[0] != "PRINT":
        p.append("steps must be a list starting with PRINT")
    else:
        order.steps = steps
        unknown = [str(s) for s in steps if s not in STEPS]
        if unknown:
            p.append(f"Unknown step: {', '.join(unknown)}")
        if len(set(map(str, steps))) != len(steps):
            p.append("A step is listed twice")
    order.note = str(data.get("note") or "")
    names = data.get("documents")
    if not isinstance(names, list) or not names:
        p.append("documents must be a list of folder names")
    elif len(set(map(str, names))) != len(names):
        p.append("A document is listed twice")
    else:
        order.documents = [load_document(order.folder, name, rules) for name in names]
    return order


def load_document(order_folder, name, rules):
    doc = Document(str(name), order_folder / str(name))
    p = doc.problems
    if not _plain_name(name):
        p.append("Not a folder name")
        return doc
    if not doc.folder.is_dir():
        p.append("Folder is missing")
        return doc
    job = _read_json(doc.folder / "job.json", p)
    if job is None:
        return doc
    doc.job = job
    kind = job.get("kind", "document")
    if kind == "product":
        load_product(doc)
        return doc
    if kind != "document":
        p.append(f"kind {kind!r} is not allowed (document or product)")
        return doc
    doc.title = str(job.get("title") or name)

    for key, allowed in (("color", COLORS), ("sides", SIDES), ("paper", PAPERS),
                         ("paper_type", rules["paper_types"])):
        if job.get(key) not in allowed:
            p.append(f"{key} {job.get(key)!r} is not allowed")
    if not _whole(job.get("per_side")) or job["per_side"] not in layout.PER_SIDE:
        p.append(f"per_side {job.get('per_side')!r} is not allowed")
    elif job.get("paper") == "A5" and job["per_side"] > 1:
        p.append("A5 is already 2 on A4: per_side must be 1")
    if not _whole(job.get("copies")) or not 1 <= job["copies"] <= 999:
        p.append(f"copies {job.get('copies')!r} must be a whole number from 1 to 999")

    file = job.get("file")
    if not _plain_name(file) or Path(file).suffix.lower() != ".pdf":
        p.append(f"file {file!r} must be a PDF in the document folder")
        return doc
    if not (doc.folder / file).is_file():
        p.append(f"{file} is missing")
        return doc
    try:
        doc.pages = analyze.page_count(doc.folder / file)
    except Exception as e:
        p.append(f"Can't open {file}: {e}")
        return doc
    doc.pdf = doc.folder / file
    if job.get("pages") != doc.pages:
        p.append(f"The website counted {job.get('pages')!r} pages, the PDF has {doc.pages}")
    return doc


def _size_mm(value):
    """(width, height) for a [width, height] list of two positive numbers, else None."""
    if (isinstance(value, list) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in value)):
        return float(value[0]), float(value[1])
    return None


def mm_text(size):
    w, h = size
    return f"{w:g} x {h:g} mm"


def load_product(doc):
    """Check a product item's job.json and its files; look for the owner's print.pdf."""
    job, p = doc.job, doc.problems
    doc.kind = "product"
    name, quantity, options = job.get("name"), job.get("quantity"), job.get("options")
    if not isinstance(job.get("product"), str) or not job["product"]:
        p.append("product id is missing")
    if not isinstance(name, str) or not name:
        p.append("name is missing")
        name = str(job.get("product") or "Product")
    if not _whole(quantity) or quantity < 1:
        p.append(f"quantity {quantity!r} must be a whole number of at least 1")
        quantity = "?"
    doc.title = f"{name} × {quantity}"
    if not isinstance(options, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                for k, v in options.items()):
        p.append("options must be choice names and the chosen text")
        job["options"] = {}
    cut = _size_mm(job.get("cut_mm"))
    if cut is None:
        p.append(f"cut_mm {job.get('cut_mm')!r} must be [width, height] in mm")
    elif min(cut) > MAX_CUT_MM[0] or max(cut) > MAX_CUT_MM[1]:
        p.append(f"Cut size {mm_text(cut)} is larger than A3")
    if "folded_mm" in job and _size_mm(job["folded_mm"]) is None:
        p.append(f"folded_mm {job.get('folded_mm')!r} must be [width, height] in mm")

    files, titles = job.get("files"), job.get("titles", job.get("files"))
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_PRODUCT_FILES:
        p.append(f"files must list 1 to {MAX_PRODUCT_FILES} customer files")
        files = []
    if not isinstance(titles, list) or len(titles) != len(files):
        titles = files
    for file, title in zip(files, titles):
        if not _plain_name(file) or Path(file).suffix.lower() not in PRODUCT_FILES:
            p.append(f"file {file!r} must be one of {', '.join(PRODUCT_FILES)} in the item folder")
            continue
        if file.lower() == PRINT_PDF:
            p.append(f"A customer file can't be called {PRINT_PDF}: that name is kept for the laid-out sheet")
            continue
        path = doc.folder / file
        if not path.is_file():
            p.append(f"{file} is missing")
            continue
        note, warning = customer_file_size(path, cut)
        doc.files.append((path, str(title or file), note, warning))
    check_print_pdf(doc)


def customer_file_size(path, cut):
    """(size text, warning or None) for a customer file compared with the ordered cut size."""
    try:
        sizes = cached_sizes_mm(path)
    except Exception as e:
        return f"can't read the size ({e})", None
    if not sizes:
        return "size not checked", None  # e.g. .eps, .psd: open it to see
    text = ", ".join(mm_text(s) for s in dict.fromkeys(sizes))
    if cut is None:
        return text, None
    wrong = [s for s in sizes if not fits_cut(s, cut)]
    if not wrong:
        return text, None
    return text, f"{mm_text(wrong[0])}, ordered {mm_text(cut)}"


_sizes = {}  # (path, size, modified) -> page sizes: files are opened again only when they change


def cached_sizes_mm(path):
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _sizes:
        _sizes[key] = file_sizes_mm(path)
    return _sizes[key]


def file_sizes_mm(path):
    """Page sizes in mm, rounded: every page of a PDF (or .ai saved with PDF content), or an image
    that records its resolution. Empty if it can't be told."""
    suffix = path.suffix.lower()
    if suffix in (".pdf", ".ai"):
        try:
            pdf = pdfium.PdfDocument(str(path))
        except Exception:
            if suffix == ".ai":
                return []  # an older .ai without PDF content
            raise
        try:
            sizes = []
            for i in range(len(pdf)):
                w, h = pdf.get_page_size(i)
                sizes.append((round(w * 25.4 / 72, 1), round(h * 25.4 / 72, 1)))
            return sizes
        finally:
            pdf.close()
    if suffix in (".png", ".jpg", ".jpeg"):
        with Image.open(path) as img:
            dpi = img.info.get("dpi")
            if not dpi or not dpi[0] or not dpi[1] or min(dpi) < 30:
                return []  # no real resolution saved: size unknown
            return [(round(img.width * 25.4 / float(dpi[0]), 1), round(img.height * 25.4 / float(dpi[1]), 1))]
    return []


def fits_cut(size, cut):
    """True if a page is the cut size, or the cut size plus bleed, either way round."""
    lo, hi = BLEED_MM
    for w, h in (size, size[::-1]):
        if all(c + lo - 1 <= v <= c + hi + 1 for v, c in zip((w, h), cut)):
            return True
    return False


def check_print_pdf(doc):
    """Look at the owner's print.pdf: there yet, still being saved, and A4 or A3 on every page."""
    path = doc.folder / PRINT_PDF
    doc.pdf = doc.pages = doc.print_paper = doc.print_problem = doc.print_stamp = None
    doc.print_state = None
    try:
        st = path.stat()
    except OSError:
        return
    doc.print_stamp = [st.st_size, st.st_mtime_ns]
    # A time in the future (a PC or share whose clock is ahead) doesn't count as saving.
    if 0 <= time.time() - st.st_mtime < SAVING_SECONDS:
        doc.print_state = "saving"
        doc.print_problem = f"{PRINT_PDF} is still being saved"
        return
    try:
        sizes = cached_sizes_mm(path)
    except Exception as e:
        doc.print_state, doc.print_problem = "bad", f"Can't open {PRINT_PDF}: {e}"
        return
    if not sizes:
        doc.print_state, doc.print_problem = "bad", f"{PRINT_PDF} has no pages"
        return
    papers = set()
    for size in sizes:
        paper = next((name for name, sheet in SHEET_MM.items()
                      if any(all(abs(v - s) <= SHEET_TOLERANCE_MM for v, s in zip(size, turned))
                             for turned in (sheet, sheet[::-1]))), None)
        if paper is None:
            doc.print_state = "bad"
            doc.print_problem = f"{PRINT_PDF} has a {mm_text(size)} page: export it as A4 or A3"
            return
        papers.add(paper)
    if len(papers) > 1:
        doc.print_state, doc.print_problem = "bad", f"{PRINT_PDF} mixes A4 and A3 pages: make one file per size"
        return
    doc.pdf, doc.pages, doc.print_paper, doc.print_state = path, len(sizes), papers.pop(), "ok"


def product_lines(doc):
    """What the customer ordered for a product item, one line each: shown in PrintHub,
    written to Options.txt and listed by main()."""
    j = doc.job
    lines = [f"{k}: {v}" for k, v in (j.get("options") or {}).items()]
    cut, folded = _size_mm(j.get("cut_mm")), _size_mm(j.get("folded_mm"))
    if cut:
        lines.append(f"Cut size: {mm_text(cut)}" + (f", folded {mm_text(folded)}" if folded else ""))
    if j.get("note"):
        lines.append(f"Customer note: {j['note']}")
    for path, title, note, warning in doc.files:
        name = title if title == path.name else f"{path.name} ({title})"
        lines.append(f"File: {name}  {note}" + (f"   WRONG SIZE: {warning}" if warning else ""))
    return lines


def main():
    rules = routing.load_json("rules.json")
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else orders_dir(rules)
    orders = load_orders(folder, rules)
    print(f"{len(orders)} order(s) in {folder}\n")
    for o in orders:
        when = o.paid_at.strftime("%Y-%m-%d %H:%M") if o.paid_at else "?"
        print(f"{o.number}  paid {when}  {o.delivery}  steps: {' > '.join(map(str, o.steps))}"
              + ("" if o.ok else "  NEEDS ATTENTION"))
        for d in o.documents:
            j = d.job
            if d.product:
                print(f"    {d.name}  {d.title}")
                for line in product_lines(d):
                    print(f"        {line}")
                print(f"        {PRINT_PDF}: " + (f"{d.pages} p {d.print_paper}" if d.print_state == "ok"
                                                  else d.print_problem or "not there yet"))
                continue
            print(f"    {d.name}  {d.title}  {d.pages or '?'} p  "
                  f"{j.get('color')} {j.get('sides')} {j.get('paper')} {j.get('paper_type')} x{j.get('copies')}")
        for problem in o.all_problems():
            print(f"    ! {problem}")
        print()


if __name__ == "__main__":
    main()
