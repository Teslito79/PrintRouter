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
from pathlib import Path

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


class Document:
    """One document of an order: a subfolder with job.json and a PDF."""

    def __init__(self, name, folder):
        self.name = name  # subfolder name, e.g. '01'
        self.folder = folder
        self.title = name  # the customer's file name, shown to staff
        self.pdf = None
        self.pages = None  # counted in the PDF
        self.job = {}  # job.json as read
        self.problems = []

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


def orders_dir(rules):
    return routing.app_dir() / rules.get("orders_folder", "orders")


def load_orders(folder, rules):
    """Every complete order in the folder, oldest payment first."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    # Folders starting with '.' are still being copied in under a temporary name.
    orders = [load_order(sub, rules) for sub in sorted(folder.iterdir())
              if sub.is_dir() and not sub.name.startswith(".") and (sub / "order.json").is_file()]
    latest = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)  # no date: last
    orders.sort(key=lambda o: (o.paid_at or latest, o.number))
    return orders


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
            print(f"    {d.name}  {d.title}  {d.pages or '?'} p  "
                  f"{j.get('color')} {j.get('sides')} {j.get('paper')} {j.get('paper_type')} x{j.get('copies')}")
        for problem in o.all_problems():
            print(f"    ! {problem}")
        print()


if __name__ == "__main__":
    main()
