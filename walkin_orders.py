"""Walk-in orders: numbers, folders, order.json and customers (Tesla, 2026-11-17).

Folders, next to ADMIN (C:\\PrintRouter\\Walk-in on the work PC):
- Walk-in\\Open\\#123\\  one per open order, with order.json and one subfolder per item ("1 Business cards 85 x 55");
- Walk-in\\Customers\\<customer folder>\\<YYYY-MM-DD> #123[ cancelled]\\  collected and cancelled orders, never deleted
  (except by Forget customer…);
- Walk-in\\sales_log.csv  one line per collected or cancelled order, with no name (2026-11-17_07).
A first-time customer who says Don't keep (keep_data false) gets no record, and their order folder is deleted for
good at Collected or Cancelled: only the sales line stays.
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
    """walkin_customers.json: {"customers": {id: {id, name, phones, emails, loyalty, loyalty_mode, consent, folder,
    created}}}. loyalty_mode "auto" (the level follows the spending, walkin_prices spend rows) or "manual" (loyalty
    is the level staff picked). consent: the date the customer agreed to have their details kept (2026-11-17_07);
    customers who said Don't keep are never in this file."""

    def __init__(self):
        self.path = routing.app_dir() / CUSTOMERS_FILE
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            self.data.setdefault("customers", {})
        except (OSError, ValueError):
            self.data = {"customers": {}}
        changed = False
        for c in self.all.values():  # customers from before 2026-11-17_07 count as Keep details, automatic loyalty
            if "consent" not in c:
                c["consent"], changed = "before 2026-11-17", True
            if c.get("loyalty_mode") not in ("auto", "manual"):
                c["loyalty_mode"], changed = "auto", True
        if changed:
            try:
                self.save()
            except OSError:
                pass

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

    def known(self, phone, email):
        """True when the phone or the email belongs to a customer (no first-time question then)."""
        return bool(self.by_phone(phone) or self.by_email(email))

    def resolve(self, name, phone, email, loyalty, join=None):
        """The customer for an order (made or updated). loyalty: "auto" (automatic) or a level 0-3 picked by hand
        (manual from now on). join: answer to "Same customer?" when the phone and the email belong to two customers
        (True: join them; False: the phone's customer, nothing linked). A new customer said Keep details: consent
        is today's date."""
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
            keep = {"id": cid, "name": clean_name(name), "phones": [], "emails": [], "loyalty": 0,
                    "loyalty_mode": "auto", "consent": now()[:10], "folder": self._folder(name, phone, email),
                    "created": now()}
            self.all[cid] = keep
        if name:
            keep["name"] = " ".join(str(name).split())
        if loyalty == "auto":
            keep["loyalty_mode"] = "auto"
        else:
            keep["loyalty_mode"], keep["loyalty"] = "manual", int(loyalty or 0)
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
        clear_cache()
        return keep

    # -------------------------------------------------------------- the Customers list (2026-11-17_07)

    def set_loyalty(self, cid, choice):
        """Loyalty…: "auto" (Automatic) or a level 0-3 set by hand."""
        c = self.all[cid]
        if choice == "auto":
            c["loyalty_mode"] = "auto"
        else:
            c["loyalty_mode"], c["loyalty"] = "manual", int(choice)
        self.save()

    def edit(self, cid, name=None, phone="", email=""):
        """Edit details…: a new name, and a phone or email added. Matching stays by phone and email only, so a
        phone or email of another customer is refused. The folder name stays as it was."""
        c = self.all[cid]
        phone, email = norm_phone(phone), norm_email(email)
        if phone:
            other = self.by_phone(phone)
            if other and other["id"] != cid:
                raise ValueError(f"{phone} is already {other['name'] or other['folder']}'s phone.")
        if email:
            if "@" not in email:
                raise ValueError(f"“{email}” isn't an email address.")
            other = self.by_email(email)
            if other and other["id"] != cid:
                raise ValueError(f"{email} is already {other['name'] or other['folder']}'s email.")
        if name is not None and " ".join(str(name).split()):
            c["name"] = " ".join(str(name).split())
        if phone and phone not in c["phones"]:
            c["phones"].append(phone)
        if email and email not in c["emails"]:
            c["emails"].append(email)
        self.save()
        return c

    def forget(self, cid):
        """Forget customer…: their Customers folder is deleted for good (not to the Recycle Bin) and their record
        goes. Their lines in sales_log.csv stay (they never had a name). Refused while they have open orders."""
        with LOCK:
            c = self.all[cid]
            open_numbers = [o["number"] for o in list_open() if o["customer"]["id"] == cid]
            if open_numbers:
                raise ValueError(f"{c['name'] or c['folder']} still has open orders "
                                 f"{', '.join(f'#{n}' for n in sorted(open_numbers))}.")
            folder = customers_dir() / c["folder"]
            if folder.exists():
                delete_for_good(folder)
            del self.all[cid]
            self.save()
            clear_cache()


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


def place(items, priced, customer, source, loyalty_line, keep_data=True):
    """Make the order: the lowest free number, its folder with one subfolder per item, order.json.
    The total due is priced["due"] (the staff's rounding, priced["rounding"]): kept as changed_total.
    keep_data False (Don't keep): customer is only what was typed, with an id of its own and no record.
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
                                  note=line["note"], working=line.get("working", []), file=None, sheets=None))
        order = {"format": 1, "number": number, "source": source, "created": now(),
                 "customer": {"id": customer["id"], "name": customer.get("entered_name", customer["name"]),
                              "phone": customer.get("entered_phone", ""), "email": customer.get("entered_email", "")},
                 "loyalty": {"level": (loyalty_line or {}).get("level", 0), "pct": (loyalty_line or {}).get("pct"),
                             "amount": (loyalty_line or {}).get("amount", 0.0)},
                 "items": out_items, "volume": priced["volume"], "total": priced["total"],
                 "changed_total": priced["due"] if priced.get("rounding") else None,
                 "rounding": priced.get("rounding"), "keep_data": bool(keep_data), "status": "waiting",
                 "times": {"placed": now(), "printed": None, "ready": None, "collected": None, "cancelled": None},
                 "paid": None, "_folder": folder}
        save_order(order)
        prepare_products(order)
        return order


def price_due(order):
    return order["changed_total"] if order.get("changed_total") is not None else order["total"]


# ------------------------------------------------------------------ adding to an open order (2026-11-24_02)
# Tesla: a customer's order is printed and waiting for pickup, then they email something else: "We need those orders
# to merge and use the same order number and add the new order and make a new total". ORCA asks at Place order; the
# whole order is priced again as one; only the new items print, with their own cover sheet ("#123 (added)").
#
# Print rounds: every item has "round" (0 for the items placed first). order["round"] is the round whose items print
# now; "parts" are that round's parts (walkin_queue). Items added after the order was sent get the next round; once
# every part of the round is collected, its parts move to "earlier_parts" and the next round starts (Waiting for PDF
# or Ready to print). Items added before anything was sent simply join the round that hasn't printed yet.
# order["added"]: [{"time", "items": [4, 5] (numbers as staff see them), "round", "total_before", "total_after"}].


def round_of(item):
    return item.get("round", 0)


def current_round(order):
    return order.get("round", 0)


def round_items(order, rnd=None):
    """[(index from 0, item)] of a round (the round printing now by default)."""
    rnd = current_round(order) if rnd is None else rnd
    return [(i, item) for i, item in enumerate(order["items"]) if round_of(item) == rnd]


def pending_items(order):
    """Items added while the round before was still on the copiers: they print in a later round."""
    return [(i, item) for i, item in enumerate(order["items"]) if round_of(item) > current_round(order)]


def _ranges(numbers):
    """[1, 2, 3] -> "1-3", [4] -> "4", [1, 3] -> "1, 3"."""
    numbers = sorted(numbers)
    if not numbers:
        return ""
    if numbers == list(range(numbers[0], numbers[-1] + 1)) and len(numbers) > 1:
        return f"{numbers[0]}-{numbers[-1]}"
    return ", ".join(str(n) for n in numbers)


def added_note(order):
    """For the status: "items 4-5 added; 1-3 printed", "items 4-5 added; they print after 1-3", or ""."""
    if not order.get("added"):
        return ""
    last = order["added"][-1]
    new = _ranges(last["items"])
    rnd = current_round(order)
    if pending_items(order):
        waiting = _ranges([i + 1 for i, item in enumerate(order["items"]) if round_of(item) <= rnd
                           and (i + 1) not in last["items"]])
        return f"item{'s' if len(last['items']) > 1 else ''} {new} added; they print after {waiting}"
    printed = _ranges([i + 1 for i, item in enumerate(order["items"]) if round_of(item) < rnd])
    word = f"item{'s' if len(last['items']) > 1 else ''} {new} added"
    return f"{word}; {printed} printed" if printed else word


def added_lines(order):
    """Details…: "Items 4-5 added 24 Nov 10:12" for each time items were added."""
    out = []
    for a in order.get("added", []):
        t = datetime.datetime.fromisoformat(a["time"])
        n = len(a["items"])
        out.append(f"Item{'s' if n > 1 else ''} {_ranges(a['items'])} added {t.day} {t:%b %H:%M}")
    return out


def open_orders_for(phone="", email="", customers=None):
    """The open orders (not collected or cancelled: every order in Walk-in\\Open) of the customer a phone or email
    belongs to, by phone or email only, never by name: the customer record's phones and emails, and the phone and
    email typed on each order (Don't keep orders have no record). Oldest first."""
    phone, email = norm_phone(phone), norm_email(email)
    if not phone and not email:
        return []
    customers = customers or Customers()
    ids = {c["id"] for c in (customers.by_phone(phone), customers.by_email(email)) if c}
    out = []
    for order in list_open():
        c = order.get("customer") or {}
        typed_phone, typed_email = norm_phone(c.get("phone", "")), norm_email(c.get("email", ""))
        if c.get("id") in ids or (phone and typed_phone == phone) or (email and typed_email == email):
            out.append(order)
    return sorted(out, key=lambda o: o["created"])


def price_with(order, new_items, rounding=None, pl=None, rules=None):
    """The whole order priced again as one with the new items (the current price list, the order's own loyalty,
    the screen's rounding): walkin_pricing.price_order's result; "problems" names any empty price cell."""
    import walkin_prices
    import walkin_pricing
    pl = pl or walkin_prices.current()
    level = (order.get("loyalty") or {}).get("level") or 0
    return walkin_pricing.price_order(pl, list(order["items"]) + list(new_items), loyalty=level, rounding=rounding,
                                      rules=rules)


def add_items(order, new_items, rounding=None, pl=None, rules=None):
    """Append new items to an open order (written safely, like place): their folders, CorelDRAW files and
    Options.txt; the whole order priced again (rounding reset, then the screen's applied); an "added" record. Returns
    the order. Raises ValueError with the message for staff."""
    import walkin_pricing
    with LOCK:
        folder = order["_folder"]
        try:
            order = load_order(folder)  # the newest state (the sending thread may have written to it)
        except (OSError, ValueError):
            raise ValueError(f"#{order['number']} is no longer open.") from None
        if order["status"] in ("collected", "cancelled"):
            raise ValueError(f"#{order['number']} is no longer open.")
        priced = price_with(order, new_items, rounding, pl, rules)
        if priced["problems"]:
            raise ValueError("\n".join(priced["problems"]))
        before = price_due(order)
        parts = order.get("parts") or {}
        sent = bool(parts)
        all_collected = sent and all(p["state"] == "collected" for p in parts.values())
        rnd = current_round(order)
        if sent:  # the items already sent print no more: the new ones get a round of their own
            rnd = max([round_of(item) for item in order["items"]] + [rnd]) + 1
        first = len(order["items"]) + 1
        for i, item in enumerate(new_items, start=first):
            sub = walkin_pricing.folder_name(i, item)
            (folder / sub).mkdir(exist_ok=True)
            order["items"].append(dict(item, description=walkin_pricing.describe(item), folder=sub, price=0.0,
                                       note="", working=[], file=None, sheets=None, round=rnd))
        for item, line in zip(order["items"], priced["lines"]):  # every item's price and working, as placed now
            item.update(price=line["price"], note=line["note"], working=line.get("working", []))
        loyalty = priced.get("loyalty") or {}
        order["loyalty"] = {"level": loyalty.get("level", (order.get("loyalty") or {}).get("level", 0)),
                            "pct": loyalty.get("pct"), "amount": loyalty.get("amount", 0.0)}
        order["volume"], order["total"] = priced["volume"], priced["total"]
        order["changed_total"] = priced["due"] if priced.get("rounding") else None
        order["rounding"] = priced.get("rounding")
        order.setdefault("added", []).append({"time": now(), "items": list(range(first, len(order["items"]) + 1)),
                                              "round": rnd, "total_before": before, "total_after": price_due(order)})
        if all_collected:  # printed (or ready for pickup): the new round starts now
            next_round(order)
        elif not sent and order["status"] not in ("waiting", "ready_to_print"):
            order["status"] = "waiting"
        save_order(order)
        clear_cache()
        prepare_products(order, rules)
        return refresh(order, rules)


def next_round(order):
    """Every part of the round is collected and items wait in a later round: that round prints next (its parts made
    when first sent). Returns True when a round started (the caller saves); False: the order is simply Printed."""
    later = [round_of(item) for _, item in pending_items(order)]
    if not later:
        return False
    if order.get("parts"):
        order.setdefault("earlier_parts", []).append({"round": current_round(order), "parts": order["parts"]})
    order["parts"] = None
    order["round"] = min(later)
    order["status"] = "waiting"  # refresh() makes it Ready to print when the new items have their files
    return True


def stem(order, index):
    """'W100-2': the CorelDRAW file and the print sheet of order #100, item 2 (no #: CorelDRAW and some Windows
    tools handle it badly)."""
    return f"W{order['number']}-{index}"


def item_index(order, item):
    return order["items"].index(item) + 1


def _files(order, item):
    folder = order["_folder"] / item["folder"]
    try:
        return sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith((".", "~")))
    except OSError:
        return []


def item_file(order, item):
    """The file that prints: documents, the file staff dropped in (any accepted type); products, only the exported
    print sheet W100-2.pdf (None until it is there)."""
    if item["kind"] == "product":
        pdf = order["_folder"] / item["folder"] / f"{stem(order, item_index(order, item))}.pdf"
        return pdf if pdf.is_file() else None
    files = [p for p in _files(order, item) if p.suffix.lower() in DOC_TYPES]
    return files[0] if files else None


def customer_files(order, item):
    """A product item's customer files: everything except ORCA's Options.txt, the .cdr and the print sheet."""
    own = {f"{stem(order, item_index(order, item))}{ext}".lower() for ext in (".cdr", ".pdf")} | {"options.txt"}
    return [p for p in _files(order, item) if p.name.lower() not in own]


def sheet_state(order, item):
    """For a product item: ("none" | "saving" | "bad" | "ok", text, stamp). Only W100-2.pdf is checked, and not
    while it was changed in the last seconds (CorelDRAW may still be writing it), as in PrintHub."""
    import time
    import orders as ph_orders
    path = item_file(order, item)
    name = f"{stem(order, item_index(order, item))}.pdf"
    if path is None:
        return "none", "", None
    try:
        st = path.stat()
    except OSError:
        return "none", "", None
    stamp = [st.st_size, st.st_mtime_ns]
    if 0 <= time.time() - st.st_mtime < ph_orders.SAVING_SECONDS:
        return "saving", f"{name} is being saved…", stamp
    paper, info = pdf_sheet(path)
    if paper is None:
        return "bad", f"{name}: {info}", stamp
    return "ok", paper, stamp


def laid_out(order, item):
    """True when Layout done was pressed for the print sheet as it is now (a changed PDF needs it again)."""
    state, _, stamp = sheet_state(order, item)
    return state == "ok" and bool(item.get("sheets")) and item.get("stamp") == stamp


def missing(order):
    """What an order still needs before it can print (empty: ready): the items of the round printing now (items
    printed in an earlier round, or added for a later one, don't hold it up)."""
    out = []
    for i, item in enumerate(order["items"], start=1):
        if round_of(item) != current_round(order):
            continue
        if item["kind"] == "document":
            if item_file(order, item) is None:
                out.append(f"item {i}: no file in “{item['folder']}”")
        elif not laid_out(order, item):
            out.append(f"item {i}: waiting for layout")
    return out


def refresh(order, rules=None):
    """Note each item's file, give product items their CorelDRAW file and Options.txt if missing (older orders),
    and move the order between waiting and ready_to_print (saves when it changed)."""
    if order["status"] in ("waiting", "ready_to_print"):
        prepare_products(order, rules)
    changed = False
    for item in order["items"]:
        f = item_file(order, item)
        name = f.name if f else None
        if item.get("file") != name:
            item["file"], changed = name, True
    if order["status"] in ("waiting", "ready_to_print"):
        status = "ready_to_print" if not missing(order) else "waiting"
        if status != order["status"]:
            order["status"], changed = status, True
    if changed:
        save_order(order)
    return order


def layout_done(order, item, sheets):
    """Layout done: the sheet count for the print sheet as it is now."""
    item["sheets"] = int(sheets)
    item["stamp"] = sheet_state(order, item)[2]
    save_order(order)
    refresh(order)


# ------------------------------------------------------------------ CorelDRAW file and Options.txt

_RULES = {}


def _rules(rules=None):
    if rules is not None:
        return rules
    key = str(routing.app_dir())
    if key not in _RULES:
        _RULES[key] = routing.load_rules()
    return _RULES[key]


def product_doc(order, index, item):
    """The item as an orders.Document, so the template, pieces and tray lines are worked out as PrintHub does."""
    import orders as ph_orders
    import walkin_catalogue as cat
    import walkin_pricing
    p = walkin_pricing.product_of(item)
    doc = ph_orders.Document(str(index), order["_folder"] / item["folder"])
    doc.kind = "product"
    doc.job = {"product": p["id"], "name": p["name"], "quantity": item["qty"],
               "cut_mm": list(cat.CUT_MM.get(cat.size_of(p, item["picks"]), (0, 0))),
               "options": {o["label"]: o["choices"][item["picks"].get(o["key"], 0)] for o in p["options"]}}
    return doc


def options_text(order, index, item, doc, template_line, pieces, rules):
    """Options.txt for a walk-in product item, in the style of PrintHub's."""
    import orders as ph_orders
    import product_files
    c = order["customer"]
    name = stem(order, index)
    lines = [f"Order #{order['number']}   item {index}   {order['source']}   "
             f"placed {order['created'][:16].replace('T', ' ')}",
             "Customer: " + (" · ".join(x for x in (c.get("name"), c.get("phone"), c.get("email")) if x) or "-"), ""]
    lines.append(f"{doc.job['name']}   quantity {item['qty']}")
    lines += [f"  {line}" for line in ph_orders.product_lines(doc) + product_files.tray_lines(doc, rules)]
    lines += ["", template_line]
    if pieces:
        lines.append(pieces)
    lines += ["", f"Put the customer's design in this folder. Lay it out in {name}.cdr, export {name}.pdf into this "
                  f"folder, then press Layout done in Walk-in."]
    return "\n".join(lines) + "\n"


def prepare_products(order, rules=None):
    """Each product item's folder gets W100-2.cdr (the template PrintHub would choose) and Options.txt, once:
    never over an existing file. A missing template (blank.cdr too) leaves only Options.txt, which says so."""
    import orders as ph_orders
    import product_files
    rules = _rules(rules)
    templates = ph_orders.templates_dir(rules)
    for index, item in enumerate(order["items"], start=1):
        if item["kind"] != "product":
            continue
        folder = order["_folder"] / item["folder"]
        if not folder.is_dir():
            continue
        name = stem(order, index)
        cdr, options = folder / f"{name}.cdr", folder / "Options.txt"
        if cdr.exists() and options.exists():
            continue
        doc = product_doc(order, index, item)
        template, line = product_files.choose_template(doc, templates)
        if template is not None:
            product_files.write_once(cdr, template=template)
        product_files.write_once(options, text=options_text(order, index, item, doc, line,
                                                            product_files.pieces_line(doc, rules), rules))


def prepare_all(rules=None):
    """At start: open orders whose product folders lack the CorelDRAW file or Options.txt get them."""
    for order in list_open():
        try:
            prepare_products(order, rules)
        except Exception:
            continue


def set_status(order, status):
    order["status"] = status
    key = {"printed": "printed", "ready_for_pickup": "ready", "collected": "collected", "cancelled": "cancelled"}.get(status)
    if key:
        order["times"][key] = now()
    save_order(order)


def rounded_text(order):
    """" (rounded)" / " (changed price)" (a typed price, test orders from before 2026-11-17_07) / ""."""
    if order.get("changed_total") is None or abs(order["changed_total"] - order["total"]) < 0.005:
        return ""
    return " (rounded)" if order.get("rounding") else " (changed price)"


def delete_for_good(path):
    """Delete a folder permanently (not to the Recycle Bin): Don't keep orders and forgotten customers."""
    import stat

    def again(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onexc=again)


def finish(order, cancelled=False):
    """Collected (or cancelled): note it and write the sales line; then the folder moves into the customer's folder,
    or, for a customer who said Don't keep, is deleted for good. The number is free. Returns the new folder or None."""
    with LOCK:
        keep = order.get("keep_data", True) is not False
        if cancelled:
            set_status(order, "cancelled")
        else:
            order["paid"] = price_due(order)
            set_status(order, "collected")
        if keep:
            customers = Customers()
            c = customers.all.get(order["customer"]["id"])
            folder_name = c["folder"] if c else clean_name(order["customer"].get("name") or "Customer")
            day = order["created"][:10]
            dest = _free_path(customers_dir() / folder_name /
                              f"{day} #{order['number']}{' cancelled' if cancelled else ''}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(order["_folder"]), str(dest))
            order["_folder"] = dest
        else:
            delete_for_good(order["_folder"])
            dest = None
        write_sale(order)
        clear_cache()
        if keep and not cancelled:
            update_level(order["customer"]["id"])
        return dest


# ------------------------------------------------------------------ sales log and spending (2026-11-17_07)

SALES_FILE = "sales_log.csv"
SALES_HEAD = ["date", "order", "status", "items", "paid", "source", "copier"]  # source, copier: 2026-11-17_10


def sales_path():
    return base_dir() / SALES_FILE


def items_short(order):
    """'100 x Business cards; Document A4 12 pages x 2' (no name, phone or email)."""
    out = []
    for item in order["items"]:
        if item["kind"] == "document":
            pages = f"{item['pages']} page{'' if item['pages'] == 1 else 's'}"
            out.append(f"Document {item['size']} {pages} x {item['copies']}")
        else:
            import walkin_pricing
            p = walkin_pricing.product_of(item)
            out.append(f"{item['qty']} x {p['name'] if p else item.get('product')}")
    return "; ".join(out)


def write_sale(order):
    """One line in Walk-in\\sales_log.csv for every collected or cancelled walk-in order, with no name: the date,
    the number, collected / cancelled, the items in short and the amount paid."""
    cancelled = order["status"] == "cancelled"
    day = (order["times"].get("cancelled" if cancelled else "collected") or now())[:10]
    write_sales_line({"date": day, "order": f"#{order['number']}", "status": "cancelled" if cancelled else "collected",
                      "items": items_short(order), "paid": f"{0 if cancelled else price_due(order):.2f}",
                      "source": "walk-in order", "copier": ""})


def write_sales_line(row):
    """Add one line to sales_log.csv (columns SALES_HEAD; a file from before the source and copier columns gets them,
    its lines marked walk-in order). Written safely (temp file, rename)."""
    import csv
    import io
    path = sales_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with LOCK:
        rows = read_sales()
        for r in rows:
            r.setdefault("source", "walk-in order")
            r["source"] = r.get("source") or "walk-in order"
            r["copier"] = r.get("copier") or ""
        rows.append(row)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=SALES_HEAD, lineterminator="\r\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in SALES_HEAD})
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(buf.getvalue(), encoding="utf-8-sig")
        os.replace(tmp, path)


def read_sales():
    import csv
    try:
        with open(sales_path(), encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


_cache = {"history": None}


def clear_cache():
    _cache["history"] = None


def history():
    """Collected and cancelled orders (read once per session, again after Collected / cancel / join / forget)."""
    with LOCK:
        if _cache["history"] is None:
            _cache["history"] = list_history()
        return _cache["history"]


def collected_on(order):
    """The date an order was collected: stored at Collected; for older orders the date its folder was moved, or
    the date it was placed."""
    when = (order.get("times") or {}).get("collected")
    if when:
        return datetime.date.fromisoformat(when[:10])
    try:
        return datetime.date.fromtimestamp(order["_folder"].stat().st_mtime)
    except (OSError, KeyError):
        return datetime.date.fromisoformat(order["created"][:10])


def spending(cid, today=None):
    """{spent_12, all_time, orders, last_visit, history}: what the customer paid for collected orders (the amount
    due: changed_total if set, else total), in the last 365 days and all time. Cancelled and open orders don't
    count. Read from every order folder whose order.json carries the customer's id."""
    today = today or datetime.date.today()
    mine = [o for o in history() if o["customer"].get("id") == cid]
    spent = total = 0.0
    count = 0
    last = None
    for o in mine:
        placed = o["created"][:10]
        last = max(last or placed, placed)
        if o["status"] != "collected":
            continue
        count += 1
        due = price_due(o)
        total += due
        if (today - collected_on(o)).days <= 365:
            spent += due
    for o in list_open():
        if o["customer"].get("id") == cid:
            last = max(last or o["created"][:10], o["created"][:10])
    return {"spent_12": round(spent, 2), "all_time": round(total, 2), "orders": count, "last_visit": last,
            "history": mine}


def spent_12_months(cid, today=None):
    return spending(cid, today)["spent_12"]


def level_of(customer, pl=None, today=None):
    """(level 0-3, "auto" / "manual", spent in 12 months) for a customer record."""
    import walkin_prices
    pl = pl or walkin_prices.current()
    spent = spent_12_months(customer["id"], today)
    if customer.get("loyalty_mode") == "manual":
        return int(customer.get("loyalty") or 0), "manual", spent
    return pl.level_for(spent), "auto", spent


def update_level(cid):
    """At Collected: an automatic customer's level is worked out again (and stored, for the record)."""
    customers = Customers()
    c = customers.all.get(cid)
    if c and c.get("loyalty_mode", "auto") == "auto":
        level = level_of(c)[0]
        if c.get("loyalty") != level:
            c["loyalty"] = level
            customers.save()


def customer_matches(c, text):
    """The Customers list search, by the same rules as the order search: phone (any way written, 4+ digits),
    name or email."""
    t = text.strip().lower()
    if not t:
        return True
    phone = norm_phone(text)
    if phone and len(re.sub(r"\D", "", text)) >= 4:
        if any(phone in p or p.endswith(phone.lstrip("+")) for p in c.get("phones", [])):
            return True
    return t in (c.get("name") or "").lower() or any(t in e for e in c.get("emails", []))


# ------------------------------------------------------------------ files dropped onto an item (2026-11-17)

MAX_DROP = 200 * 1024 * 1024  # 200 MB (planning window)


def drop_problem(path, kind):
    """Why this file can't go onto an item of this kind ("document" / "product"), or None. Nothing is copied
    when there is a problem."""
    path = Path(path)
    if path.is_dir():
        return f"{path.name} is a folder: drop the files inside it instead."
    try:
        size = path.stat().st_size
    except OSError:
        return f"{path.name} can't be read (was it moved, or is the USB stick out?)."
    if size == 0:
        return f"{path.name} is empty (0 bytes)."
    if size > MAX_DROP:
        return f"{path.name} is {size / 1024 / 1024:,.0f} MB: ORCA takes files up to 200 MB."
    if kind == "document" and path.suffix.lower() not in DOC_TYPES:
        return (f"{path.name}: a document takes PDF, pictures or Office files "
                f"({', '.join(sorted(DOC_TYPES))}).")
    return None


def drop_conflicts(order, item, paths):
    """The files already in the item's folder that the dropped ones would replace: for a document item the file
    that prints now; for a product item a file of the same name."""
    folder = order["_folder"] / item["folder"]
    if item["kind"] == "document":
        current = item_file(order, item)
        return [current] if current else []
    return [folder / Path(p).name for p in paths if (folder / Path(p).name).is_file()]


def add_file(order, item, src, replace=()):
    """Copy one dropped file into the item's folder (the original stays where it was), through a hidden temp file
    so ORCA never sees half a file. `replace`: files of the folder to send to the Recycle Bin first (asked)."""
    import cleanup
    src = Path(src)
    folder = order["_folder"] / item["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    for old in replace:
        if Path(old).is_file():
            why = cleanup.recycle(old)
            if why:
                raise OSError(f"could not move {Path(old).name} to the Recycle Bin: {why}")
    dest = folder / src.name
    tmp = folder / f".{src.name}.{uuid.uuid4().hex[:6]}.part"
    try:
        shutil.copy2(src, tmp)  # keeps the file's time: a dropped W100-2.pdf is not "still being saved"
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
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
