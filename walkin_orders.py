"""Walk-in orders: numbers, folders, order.json and customers (Tesla, 2026-11-17).

Folders, next to ADMIN (C:\\PrintRouter\\Walk-in on the work PC):
- Walk-in\\Open\\#123\\  one per open order, with order.json and one subfolder per item ("1 Business cards 85 x 55");
- Walk-in\\Customers\\<customer folder>\\<YYYY-MM-DD> #123[ cancelled]\\  collected and cancelled orders, never deleted.
Numbers #100 to #299: the lowest one no folder in Open uses. Customers are matched by phone or email, never by name,
and kept in walkin_customers.json in ADMIN (local, gitignored: customer details never go to GitHub).
Every file is written safely (temp file, then rename).
"""
import datetime
import json
import math
import os
import re
import shutil
import threading
import uuid
from pathlib import Path

import convert
import routing

FIRST, LAST = 100, 299
CUSTOMERS_FILE = "walkin_customers.json"
ORDER_FILE = "order.json"
DOC_TYPES = convert.SUPPORTED_EXT  # what a document item accepts (converted to PDF when printed)
STATUSES = ("waiting", "ready_to_print", "printed", "ready_for_pickup", "collected", "cancelled")
LOCK = threading.RLock()


def base_dir():
    return routing.app_dir().parent / "Walk-in"


def open_dir():
    return base_dir() / "Open"


def customers_dir():
    return base_dir() / "Customers"


def now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _write_json(path, data):
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def clean_name(text):
    """A folder name Windows allows: no <>:"/\\|?* or control characters, no dot or space at the end."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", str(text or ""))
    return " ".join(text.split()).rstrip(". ")


# ------------------------------------------------------------------ customers

def norm_phone(text):
    """Digits and a leading +; an 8-digit Cyprus number starting with 2 or 9 gets +357."""
    text = str(text or "").strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    if text.startswith("+"):
        return "+" + digits
    if text.startswith("00"):
        return "+" + digits[2:]
    if len(digits) == 8 and digits[0] in "29":
        return "+357" + digits
    if len(digits) == 11 and digits.startswith("357"):
        return "+" + digits
    return digits


def norm_email(text):
    return str(text or "").strip().lower()


class Customers:
    """walkin_customers.json: {"customers": {id: {id, name, phones, emails, loyalty, folder, created}}}."""

    def __init__(self):
        self.path = routing.app_dir() / CUSTOMERS_FILE
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            self.data.setdefault("customers", {})
        except (OSError, ValueError):
            self.data = {"customers": {}}

    @property
    def all(self):
        return self.data["customers"]

    def save(self):
        _write_json(self.path, self.data)

    def by_phone(self, phone):
        phone = norm_phone(phone)
        return next((c for c in self.all.values() if phone and phone in c["phones"]), None)

    def by_email(self, email):
        email = norm_email(email)
        return next((c for c in self.all.values() if email and email in c["emails"]), None)

    def lookup(self, phone="", email=""):
        """The customer a typed phone or email belongs to (to fill in name and loyalty), or None."""
        return self.by_phone(phone) or self.by_email(email)

    def conflict(self, phone, email):
        """(phone's customer, email's customer) when they are two different customers, else None."""
        a, b = self.by_phone(phone), self.by_email(email)
        return (a, b) if a and b and a["id"] != b["id"] else None

    def _folder(self, name, phone, email):
        name = clean_name(name)
        detail = phone or email
        base = f"{name} - {detail}" if name and detail else (name or detail or "Customer")
        base = clean_name(base)
        taken = {c["folder"].lower() for c in self.all.values()}
        try:
            taken |= {d.name.lower() for d in customers_dir().iterdir()}
        except OSError:
            pass
        folder, n = base, 2
        while folder.lower() in taken:
            folder, n = f"{base} ({n})", n + 1
        return folder

    def resolve(self, name, phone, email, loyalty, join=None):
        """The customer for an order (made or updated). join: answer to "Same customer?" when the phone and the
        email belong to two customers (True: join them; False: the phone's customer, nothing linked)."""
        phone, email = norm_phone(phone), norm_email(email)
        clash = self.conflict(phone, email)
        if clash and join is None:
            raise ValueError("ask")
        link = True
        if clash and join:
            keep = self.merge(*clash)
        elif clash:
            keep, link = clash[0], False
        else:
            keep = self.lookup(phone, email)
        if keep is None:
            cid = uuid.uuid4().hex[:10]
            keep = {"id": cid, "name": clean_name(name), "phones": [], "emails": [], "loyalty": loyalty,
                    "folder": self._folder(name, phone, email), "created": now()}
            self.all[cid] = keep
        if name:
            keep["name"] = " ".join(str(name).split())
        keep["loyalty"] = loyalty
        if phone and phone not in keep["phones"] and (link or not self.by_phone(phone)):
            keep["phones"].append(phone)
        if email and email not in keep["emails"] and link:
            keep["emails"].append(email)
        (customers_dir() / keep["folder"]).mkdir(parents=True, exist_ok=True)
        self.save()
        return keep

    def merge(self, a, b):
        """Join two customers: the older record and folder stay; the other's collected folders move into it and
        its open orders point to it."""
        keep, gone = sorted((a, b), key=lambda c: (c.get("created", ""), c["id"]))
        for p in gone["phones"]:
            if p not in keep["phones"]:
                keep["phones"].append(p)
        for e in gone["emails"]:
            if e not in keep["emails"]:
                keep["emails"].append(e)
        src, dest = customers_dir() / gone["folder"], customers_dir() / keep["folder"]
        dest.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            for item in list(src.iterdir()):
                target = _free_path(dest / item.name)
                shutil.move(str(item), str(target))
                _repoint(target / ORDER_FILE, keep)
            try:
                src.rmdir()
            except OSError:
                pass
        for order in list_open():
            if order["customer"]["id"] == gone["id"]:
                order["customer"]["id"] = keep["id"]
                save_order(order)
        del self.all[gone["id"]]
        self.save()
        return keep


def _repoint(path, customer):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["customer"]["id"] = customer["id"]
        _write_json(path, data)
    except (OSError, ValueError, KeyError):
        pass


def _free_path(path):
    if not path.exists():
        return path
    n = 2
    while path.with_name(f"{path.name} ({n})").exists():
        n += 1
    return path.with_name(f"{path.name} ({n})")


# ------------------------------------------------------------------ orders

def used_numbers():
    nums = set()
    try:
        for d in open_dir().iterdir():
            m = re.fullmatch(r"#(\d+)", d.name)
            if d.is_dir() and m:
                nums.add(int(m.group(1)))
    except OSError:
        pass
    return nums


def next_number():
    used = used_numbers()
    return next((n for n in range(FIRST, LAST + 1) if n not in used), None)


def save_order(order):
    data = {k: v for k, v in order.items() if not k.startswith("_")}
    _write_json(order["_folder"] / ORDER_FILE, data)


def load_order(folder):
    data = json.loads((folder / ORDER_FILE).read_text(encoding="utf-8"))
    data["_folder"] = folder
    return data


def list_open():
    out = []
    try:
        folders = sorted(open_dir().iterdir(), key=lambda d: d.name)
    except OSError:
        return out
    for d in folders:
        if d.is_dir() and (d / ORDER_FILE).is_file():
            try:
                out.append(load_order(d))
            except (OSError, ValueError):
                continue
    return out


def list_history():
    out = []
    try:
        customers = list(customers_dir().iterdir())
    except OSError:
        return out
    for c in customers:
        if not c.is_dir():
            continue
        for d in c.iterdir():
            if d.is_dir() and (d / ORDER_FILE).is_file():
                try:
                    out.append(load_order(d))
                except (OSError, ValueError):
                    continue
    return out


def place(items, priced, customer, source, loyalty_line, changed_total=None):
    """Make the order: the lowest free number, its folder with one subfolder per item, order.json.
    Returns the order, or raises ValueError with the message for staff."""
    import walkin_pricing
    with LOCK:
        number = next_number()
        if number is None:
            raise ValueError(f"All order numbers #{FIRST}-#{LAST} are in use. Collect or cancel an order first.")
        folder = open_dir() / f"#{number}"
        folder.mkdir(parents=True)
        out_items = []
        for i, (item, line) in enumerate(zip(items, priced["lines"]), start=1):
            sub = walkin_pricing.folder_name(i, item)
            (folder / sub).mkdir()
            out_items.append(dict(item, description=walkin_pricing.describe(item), folder=sub, price=line["price"],
                                  note=line["note"], file=None, sheets=None))
        order = {"format": 1, "number": number, "source": source, "created": now(),
                 "customer": {"id": customer["id"], "name": customer.get("entered_name", customer["name"]),
                              "phone": customer.get("entered_phone", ""), "email": customer.get("entered_email", "")},
                 "loyalty": {"level": (loyalty_line or {}).get("level", 0), "pct": (loyalty_line or {}).get("pct"),
                             "amount": (loyalty_line or {}).get("amount", 0.0)},
                 "items": out_items, "volume": priced["volume"], "total": priced["total"],
                 "changed_total": changed_total, "status": "waiting",
                 "times": {"placed": now(), "printed": None, "ready": None, "collected": None, "cancelled": None},
                 "paid": None, "_folder": folder}
        save_order(order)
        return order


def price_due(order):
    return order["changed_total"] if order.get("changed_total") is not None else order["total"]


def item_file(order, item):
    """The file staff dropped into the item's subfolder (documents: any accepted type; products: a PDF), or None."""
    folder = order["_folder"] / item["folder"]
    try:
        files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith((".", "~")))
    except OSError:
        return None
    if item["kind"] == "product":
        files = [p for p in files if p.suffix.lower() == ".pdf"]
    else:
        files = [p for p in files if p.suffix.lower() in DOC_TYPES]
    return files[0] if files else None


def missing(order):
    """What an order still needs before it can print (empty: ready)."""
    out = []
    for i, item in enumerate(order["items"], start=1):
        f = item_file(order, item)
        if f is None:
            out.append(f"item {i}: no {'PDF' if item['kind'] == 'product' else 'file'} in “{item['folder']}”")
        elif item["kind"] == "product" and not item.get("sheets"):
            out.append(f"item {i}: confirm the sheet count")
    return out


def refresh(order):
    """Note each item's file and move the order between waiting and ready_to_print (saves when it changed)."""
    changed = False
    for item in order["items"]:
        f = item_file(order, item)
        name = f.name if f else None
        if item.get("file") != name:
            item["file"], changed = name, True
            if item["kind"] == "product":
                item["sheets"] = None  # a new PDF: the sheet count is confirmed again
    if order["status"] in ("waiting", "ready_to_print"):
        status = "ready_to_print" if not missing(order) else "waiting"
        if status != order["status"]:
            order["status"], changed = status, True
    if changed:
        save_order(order)
    return order


def set_status(order, status):
    order["status"] = status
    key = {"printed": "printed", "ready_for_pickup": "ready", "collected": "collected", "cancelled": "cancelled"}.get(status)
    if key:
        order["times"][key] = now()
    save_order(order)


def change_price(order, value):
    order["changed_total"] = None if value is None else round(float(value), 2)
    save_order(order)


def finish(order, cancelled=False):
    """Collected (or cancelled): note it, then move the folder into the customer's folder; the number is free."""
    with LOCK:
        customers = Customers()
        c = customers.all.get(order["customer"]["id"])
        folder_name = c["folder"] if c else clean_name(order["customer"].get("name") or "Customer")
        day = order["created"][:10]
        dest = _free_path(customers_dir() / folder_name / f"{day} #{order['number']}{' cancelled' if cancelled else ''}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if cancelled:
            set_status(order, "cancelled")
        else:
            order["paid"] = price_due(order)
            set_status(order, "collected")
        shutil.move(str(order["_folder"]), str(dest))
        order["_folder"] = dest
        return dest


def matches(order, text):
    """Search: phone (any way written), name, email or order number (with or without #)."""
    t = text.strip().lower()
    if not t:
        return True
    c = order["customer"]
    if t.lstrip("#").isdigit() and str(order["number"]) == t.lstrip("#"):
        return True
    phone = norm_phone(text)
    if phone and len(re.sub(r"\D", "", text)) >= 4:
        cust = Customers().all.get(c["id"], {})
        phones = set(cust.get("phones", [])) | {norm_phone(c.get("phone"))}
        if any(phone in p or p.endswith(phone.lstrip("+")) for p in phones if p):
            return True
    if t in (c.get("name") or "").lower() or t in (c.get("email") or "").lower():
        return True
    cust = Customers().all.get(c["id"], {})
    return any(t in e for e in cust.get("emails", [])) or t in (cust.get("name") or "").lower()


# ------------------------------------------------------------------ product sheets

def pieces_for(rules, cut, paper):
    """Pieces per sheet from rules.json pieces_per_sheet (cut size WxH or HxW, A4/A3), or None."""
    if not cut or paper not in ("A4", "A3"):
        return None
    table = rules.get("pieces_per_sheet") or {}
    w, h = (math.floor(v + 0.5) for v in cut)
    for a, b in ((w, h), (h, w)):
        entry = table.get(f"{a}x{b}")
        if isinstance(entry, dict) and isinstance(entry.get(paper), int) and entry[paper] > 0:
            return entry[paper]
    return None


def pdf_sheet(path):
    """'A4' / 'A3' for a laid-out PDF whose pages are all that size, else (None, why)."""
    import orders
    try:
        sizes = orders.cached_sizes_mm(Path(path))
    except Exception as e:
        return None, f"can't open the PDF: {e}"
    papers = set()
    for size in sizes:
        paper = next((name for name, sheet in orders.SHEET_MM.items()
                      if any(all(abs(v - s) <= orders.SHEET_TOLERANCE_MM for v, s in zip(size, turned))
                             for turned in (sheet, sheet[::-1]))), None)
        if paper is None:
            return None, f"a page is {orders.mm_text(size)}: export it as A4 or A3"
        papers.add(paper)
    if len(papers) != 1:
        return None, "the PDF mixes A4 and A3 pages" if papers else "the PDF has no pages"
    return papers.pop(), len(sizes)
