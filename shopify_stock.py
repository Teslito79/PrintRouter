"""Shopify stock at the end of the day, On display and the restock list (2026-11-19_09, Tesla: Inventory should show
what was sold today, so staff know what to bring from storage to the shelves).

At the end of the day Tesla exports Shopify's inventory (a CSV: Handle, Title, Option1-3 Name / Value, SKU, ...,
Location, ..., On hand (current), ...) and loads it with "End of day: load Shopify stock". Each row is a product
variant, keyed by Handle + Option1/2/3 Value. The difference from the last load is what sold (went down) or came in
(went up); same-day sales and deliveries are Tesla's own business. Shopify's number wins over ORCA's own changes.

An item restocked every day has an amount On display. ORCA keeps how many are On the shelf: full when the amount is
first set; each load takes what sold off it (to 0 at the least); deliveries go to storage. In storage = stock minus
on the shelf (0 at the least). The restock list says how many to bring: "Pen blue: bring 6 (on display 10, on the
shelf 4)", "bring 3, only 3 in storage" (yellow), "Order more" (red, none in storage). Restocked fills the shelf.

Each load is kept: a copy of the file in inventory_loads\\ (local, gitignored) and its time in inventory.json.
ORCA's own items linked for printing (paper, finishing) are never touched by a load.
"""
import csv
import datetime
import os
import shutil

import inventory as inv
import routing

LOADS = "inventory_loads"
NEEDED = ("Handle", "Title", "SKU", "On hand (current)")
DEFAULT = "Default Title"


def is_shopify(header):
    return all(h in header for h in NEEDED)


def key_of(row):
    return "|".join(str(row.get(k) or "").strip() for k in ("Handle", "Option1 Value", "Option2 Value", "Option3 Value"))


def name_of(row):
    """Title plus the option values that aren't "Default Title": "Handcraft Yarn 25g KEYROAD - Red"."""
    options = [str(row.get(f"Option{i} Value") or "").strip() for i in (1, 2, 3)]
    options = [o for o in options if o and o != DEFAULT]
    return str(row.get("Title") or "").strip() + (" - " + " / ".join(options) if options else "")


def _int(text):
    t = str(text or "").strip().replace(",", ".")
    try:
        return int(float(t)) if t else 0
    except ValueError:
        return 0


def read_export(path):
    """{key: {"name", "sku", "stock"}}, [problems], locations: the stock added up over the locations of a key."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        if not is_shopify(header):
            raise ValueError("This isn't a Shopify inventory export (it needs the columns Handle, Title, SKU and "
                             "On hand (current)).")
        rows = list(reader)
    out, locations = {}, set()
    for row in rows:
        key = key_of(row)
        if not key.strip("|"):
            continue
        locations.add(str(row.get("Location") or "").strip())
        item = out.setdefault(key, {"name": name_of(row), "sku": str(row.get("SKU") or "").strip(), "stock": 0})
        item["stock"] += _int(row.get("On hand (current)"))
    skus = {}
    for key, item in out.items():
        if item["sku"]:
            skus.setdefault(item["sku"], []).append(key)
    for key, item in out.items():  # SKU as the barcode only where it belongs to one row
        item["barcode"] = item["sku"] if item["sku"] and len(skus[item["sku"]]) == 1 else ""
    return out, len(locations - {""})


# ------------------------------------------------------------------ On display and the shelf

def storage(item):
    """In storage: the stock minus what is on the shelf, 0 at the least (shown, never typed)."""
    if item.get("display") is None:
        return max(0, item.get("stock", 0))
    return max(0, item.get("stock", 0) - (item.get("shelf") or 0))


def set_display(inventory, item_id, amount):
    """On display (open to staff, logged). First set: the shelf counts as full. Raised: the shelf stays. Lowered
    under the shelf: the shelf becomes the amount. Emptied: off the restock list."""
    item = inventory.get(item_id)
    old = item.get("display")
    amount = None if amount in (None, "") else max(0, int(amount))
    if amount == old:
        return item
    item["display"] = amount
    if amount is None:
        item.pop("shelf", None)
    elif old is None or item.get("shelf") is None:
        item["shelf"] = amount
    elif item["shelf"] > amount:
        item["shelf"] = amount
    inventory.save()
    inv.log(item, 0, f"on display {'-' if old is None else old} -> {'-' if amount is None else amount}")
    return item


def restock_lines(inventory):
    """[(item, bring, kind, text)] for every item with a display amount whose shelf is under it, by category then
    name. kind: "ok", "short" (yellow), "order" (red)."""
    out = []
    for it in inventory.items:
        if it.get("display") is None or it.get("gone"):
            continue
        need = it["display"] - (it.get("shelf") or 0)
        if need <= 0:
            continue
        have = storage(it)
        bring = min(need, have)
        if have <= 0:
            kind, text = "order", f"{it['name']}: Order more (on display {it['display']}, on the shelf {it.get('shelf') or 0})"
        elif have < need:
            kind, text = "short", f"{it['name']}: bring {bring}, only {have} in storage"
        else:
            kind, text = "ok", f"{it['name']}: bring {bring} (on display {it['display']}, on the shelf {it.get('shelf') or 0})"
        out.append((it, bring, kind, text))
    out.sort(key=lambda x: ((x[0].get("category") or "").lower(), x[0]["name"].lower()))
    return out


def restocked(inventory, item_id):
    """The shelf back to the display amount, or to what storage allowed; logged."""
    item = inventory.get(item_id)
    if item is None or item.get("display") is None:
        return 0
    bring = min(item["display"] - (item.get("shelf") or 0), storage(item))
    if bring <= 0:
        return 0
    item["shelf"] = (item.get("shelf") or 0) + bring
    inventory.save()
    inv.log(item, 0, f"restocked {bring} to the shelf")
    return bring


# ------------------------------------------------------------------ the load

def last_load(inventory):
    return inventory.data.get("shopify_load")


def older_than_last(inventory, path):
    """The last load's time text when this file is the same or older than the one loaded last (file time), else None."""
    last = last_load(inventory)
    if not last:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if mtime <= last.get("file_mtime", 0):
        return datetime.datetime.fromisoformat(last["time"]).strftime("%d %b %H:%M")
    return None


def matches_for_first_load(inventory, export):
    """ORCA items (not linked for printing, not from Shopify yet) a first load would take over: [(item, key)] by
    barcode, else by exact name."""
    by_code = {it["barcode"]: k for k, it in export.items() if it["barcode"]}
    by_name = {}
    for k, it in export.items():
        by_name.setdefault(it["name"].strip().lower(), []).append(k)
    out, used = [], set()
    for item in inventory.items:
        if item.get("shopify_key") or item.get("link"):
            continue
        key = next((by_code[c] for c in item.get("barcodes", []) if c in by_code), None)
        if key is None:
            names = by_name.get(item["name"].strip().lower(), [])
            key = names[0] if len(names) == 1 else None
        if key and key not in used:
            used.add(key)
            out.append((item, key))
    return out


def load(inventory, path, take_over=True, now=None):
    """Load a Shopify export. Returns {"since", "first", "sold": [(name, n)], "came": [(name, n)], "new": [names],
    "gone": [names], "locations": n, "items": n}. Shopify items: name, barcode (SKU when unique), stock = On hand
    (current); ORCA's settings on them (category, minimum, sale price, display, notes, link) are kept. Items no longer
    in the file are marked gone, never deleted. take_over: on the first load, ORCA items matched by barcode or name
    become those Shopify items."""
    import uuid
    now = now or datetime.datetime.now().replace(microsecond=0)
    export, locations = read_export(path)
    last = last_load(inventory)
    first = last is None
    by_key = {it["shopify_key"]: it for it in inventory.items if it.get("shopify_key")}
    if first and take_over:
        for item, key in matches_for_first_load(inventory, export):
            item["shopify_key"] = key
            by_key[key] = item
    codes = {c: it["id"] for it in inventory.items for c in it.get("barcodes", [])}
    sold, came, new, gone, log_rows = [], [], [], [], []
    for key, row in export.items():
        item = by_key.get(key)
        if item is None:
            item = {"id": uuid.uuid4().hex[:8], "name": row["name"], "category": "", "barcodes": [], "unit": "piece",
                    "stock": 0, "per_unit": 1, "minimum": None, "price": None, "link": None, "notes": "",
                    "shopify_key": key}
            inventory.items.append(item)
            by_key[key] = item
            if not first:
                new.append(row["name"])
        before_load = item.get("shopify_stock")
        if before_load is not None and not first:
            diff = row["stock"] - before_load
            if diff < 0:
                sold.append((item["name"] if item.get("name") else row["name"], -diff))
                if item.get("display") is not None:
                    item["shelf"] = max(0, (item.get("shelf") or 0) + diff)
            elif diff > 0:
                came.append((row["name"], diff))
        item["name"] = row["name"]
        item["shopify"] = True
        item["gone"] = False
        if row["barcode"] and row["barcode"] not in item.get("barcodes", []) \
                and codes.get(row["barcode"], item["id"]) == item["id"]:
            item["barcodes"] = [row["barcode"]] + [c for c in item.get("barcodes", []) if c != row["barcode"]]
            codes[row["barcode"]] = item["id"]
        change = row["stock"] - item.get("stock", 0)
        item["stock"] = row["stock"]
        item["shopify_stock"] = row["stock"]
        if change:
            log_rows.append((item, change))
    for key, item in by_key.items():
        if key not in export and not item.get("gone"):
            item["gone"] = True
            gone.append(item["name"])
    since = last["time"] if last else None
    folder = routing.app_dir() / LOADS
    folder.mkdir(exist_ok=True)
    copy = folder / f"{now:%Y-%m-%d %H%M%S} {os.path.basename(path)}"
    shutil.copyfile(path, copy)
    inventory.data["shopify_load"] = {"time": now.isoformat(), "file_mtime": os.path.getmtime(path),
                                      "file": os.path.basename(path), "copy": copy.name}
    inventory.data.setdefault("shopify_loads", []).append(inventory.data["shopify_load"])
    inventory.save()
    log_many(log_rows, "shopify")
    return {"since": since, "first": first, "sold": sold, "came": came, "new": new, "gone": gone,
            "locations": locations, "items": len(export)}


def log_many(rows, reason):
    """Many inventory_log.csv lines at once (a load changes thousands of items)."""
    p = routing.app_dir() / inv.LOG_FILE
    try:
        new = not p.exists()
        with open(p, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(inv.LOG_COLUMNS)
            stamp = inv.now().isoformat(sep=" ")
            for item, delta in rows:
                w.writerow([stamp, item["id"], item["name"], f"{int(delta):+d}", item.get("stock", 0), reason, ""])
    except OSError:
        pass


def since_text(result):
    if result["first"]:
        return "First load: from tomorrow ORCA shows what sold"
    return "Since " + datetime.datetime.fromisoformat(result["since"]).strftime("%d %b %H:%M")
