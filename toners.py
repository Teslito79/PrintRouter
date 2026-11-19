"""Toner tracking: copier counters and toner levels over SNMP, toner changes, the Data screen (called Toners until 2026-11-16)
(Tesla, 2026-11-16).

Reading only. Each copier in rules.json is asked with a few SNMP v2c GET / GETNEXT requests
(falling back to v1), written here with no extra library: the standard Printer MIB (total counter,
toner supplies) and Ricoh's counter table. A background thread reads every copier at start and every
10 minutes, each copier on its own thread with short timeouts, so nothing else ever waits.

A toner change is found when a toner's level rises by 30 points or more between two readings, or
entered by hand. Local files next to the app, not on GitHub:
- toner_log.csv: the changes (opens in Excel);
- toner_state.json: the last readings (losing it records nothing, never a false change);
- toner_settings.json: addresses typed per copier and the SNMP community;
- copier_check.txt: written by Copier check, everything the copiers answered.
"""
import csv
import datetime
import json
import os
import re
import socket
import threading
import time
import tkinter as tk
import uuid
from tkinter import messagebox, ttk

import routing
import theme

COLOURS = ("black", "cyan", "magenta", "yellow")
COLOUR_NAMES = {"black": "Black", "cyan": "Cyan", "magenta": "Magenta", "yellow": "Yellow"}
BAR_COLOURS = {"black": "#D0D0D0", "cyan": "#22B8CF", "magenta": "#E64980", "yellow": "#FAB005"}
LOG_FILE = "toner_log.csv"
STATE_FILE = "toner_state.json"
SETTINGS_FILE = "toner_settings.json"
CHECK_FILE = "copier_check.txt"
LOG_COLUMNS = ["id", "time", "copier", "colour", "total", "black count", "colour count", "level before",
               "level after", "how"]
STOCK_FILE = "toner_stock.json"  # spare toners on the shelf, per copier and colour (2026-11-16)
STOCK_LOG = "toner_stock_log.csv"
STOCK_COLUMNS = ["time", "copier", "colour", "change", "new count", "reason"]
STOCK_LOCK = threading.RLock()
EVERY = 600  # seconds between readings
JUMP = 30  # a level rising this much (points) is a new toner
SAME_CHANGE = datetime.timedelta(hours=24)
TIMEOUT = 1.5
WALK_LIMIT = 300

# ------------------------------------------------------------------ SNMP (BER), just what is needed

OID_SYSDESCR = "1.3.6.1.2.1.1.1.0"
OID_MODEL = "1.3.6.1.2.1.25.3.2.1.3.1"  # hrDeviceDescr.1
OID_LIFE_COUNT = "1.3.6.1.2.1.43.10.2.1.4.1.1"  # prtMarkerLifeCount: the total counter
OID_SUPPLIES = "1.3.6.1.2.1.43.11.1.1"  # prtMarkerSuppliesTable
SUP_TYPE, SUP_DESC, SUP_MAX, SUP_LEVEL = "5", "6", "8", "9"
OID_RICOH_COUNTERS = "1.3.6.1.4.1.367.3.2.1.2.19.5.1"  # Ricoh counter table: .5 name, .9 value
RICOH_NAME, RICOH_VALUE = "5", "9"
GET, GETNEXT, RESPONSE = 0xA0, 0xA1, 0xA2


def _len(n):
    if n < 0x80:
        return bytes([n])
    out = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(out)]) + out


def _tlv(tag, body):
    return bytes([tag]) + _len(len(body)) + body


def _int(n):
    return _tlv(0x02, n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True))


def _oid(text):
    parts = [int(p) for p in text.split(".")]
    body = bytes([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        chunk = [p & 0x7F]
        p >>= 7
        while p:
            chunk.insert(0, 0x80 | (p & 0x7F))
            p >>= 7
        body += bytes(chunk)
    return _tlv(0x06, body)


def request(community, pdu_type, oids, request_id=1, version=1):
    """An SNMP message: version 1 = v2c, 0 = v1."""
    binds = b"".join(_tlv(0x30, _oid(o) + b"\x05\x00") for o in oids)
    pdu = _tlv(pdu_type, _int(request_id) + _int(0) + _int(0) + _tlv(0x30, binds))
    return _tlv(0x30, _int(version) + _tlv(0x04, community.encode()) + pdu)


def _read(data, i):
    tag = data[i]
    n = data[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(data[i:i + k], "big")
        i += k
    return tag, data[i:i + n], i + n


def _decode_oid(body):
    parts = [body[0] // 40, body[0] % 40]
    n = 0
    for b in body[1:]:
        n = (n << 7) | (b & 0x7F)
        if not b & 0x80:
            parts.append(n)
            n = 0
    return ".".join(map(str, parts))


NO_VALUE = object()  # noSuchObject / noSuchInstance / endOfMibView


def _value(tag, body):
    if tag == 0x02:
        return int.from_bytes(body, "big", signed=True)
    if tag in (0x41, 0x42, 0x43, 0x46):  # Counter32, Gauge32, TimeTicks, Counter64
        return int.from_bytes(body, "big")
    if tag == 0x04:
        return body.decode("utf-8", "replace").rstrip("\x00").strip()
    if tag == 0x06:
        return _decode_oid(body)
    if tag == 0x40:
        return ".".join(map(str, body))
    if tag in (0x05, 0x80, 0x81, 0x82):
        return NO_VALUE
    return body.hex()


def parse_response(data):
    """(request id, error status, [(oid, value)]) from an SNMP response."""
    _, msg, _ = _read(data, 0)
    i = 0
    _, _, i = _read(msg, i)  # version
    _, _, i = _read(msg, i)  # community
    tag, pdu, _ = _read(msg, i)
    if tag != RESPONSE:
        raise ValueError("not a response")
    j = 0
    _, rid, j = _read(pdu, j)
    _, err, j = _read(pdu, j)
    _, _, j = _read(pdu, j)
    _, binds, _ = _read(pdu, j)
    out, k = [], 0
    while k < len(binds):
        _, bind, k = _read(binds, k)
        _, oid, m = _read(bind, 0)
        vtag, vbody, _ = _read(bind, m)
        out.append((_decode_oid(oid), _value(vtag, vbody)))
    return int.from_bytes(rid, "big", signed=True), int.from_bytes(err, "big"), out


class Snmp:
    """One copier: GET and GETNEXT walks over UDP, short timeouts, read-only."""

    def __init__(self, address, community="public", version=1, timeout=TIMEOUT):
        host, _, port = address.partition(":")
        self.target = (host.strip(), int(port) if port else 161)
        self.community, self.version, self.timeout = community, version, timeout
        self.rid = int(time.time()) & 0x3FFFFFFF

    def _ask(self, pdu_type, oids):
        self.rid += 1
        packet = request(self.community, pdu_type, oids, self.rid, self.version)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(self.timeout)
            s.sendto(packet, self.target)
            end = time.monotonic() + self.timeout
            while True:
                s.settimeout(max(0.05, end - time.monotonic()))
                data, _ = s.recvfrom(65535)
                rid, err, binds = parse_response(data)
                if rid == self.rid:
                    return err, binds

    def get(self, oids):
        """{oid: value} for the oids the copier has (missing ones are left out)."""
        err, binds = self._ask(GET, oids)
        if err:  # v1 refuses the whole request when one oid is missing: ask one by one
            out = {}
            for oid in oids:
                e, b = self._ask(GET, [oid])
                if not e:
                    out.update((o, v) for o, v in b if v is not NO_VALUE)
            return out
        return {o: v for o, v in binds if v is not NO_VALUE}

    def walk(self, base):
        """[(oid, value)] under base, in order (at most WALK_LIMIT)."""
        out, oid = [], base
        for _ in range(WALK_LIMIT):
            err, binds = self._ask(GETNEXT, [oid])
            if err or not binds:
                break
            oid, value = binds[0]
            if value is NO_VALUE or not oid.startswith(base + "."):
                break
            out.append((oid, value))
        return out


# ------------------------------------------------------------------ reading a copier

def queue_address(queue):
    """The copier's network address from its Windows queue's TCP/IP port (the port's host address,
    as PowerShell's PrinterHostAddress; port names can be out of date), or None. Reading only."""
    port = None
    try:
        import win32print
        h = win32print.OpenPrinter(queue)
        try:
            port = win32print.GetPrinter(h, 2)["pPortName"]
        finally:
            win32print.ClosePrinter(h)
    except Exception:
        return None
    try:
        import winreg
        key = rf"SYSTEM\CurrentControlSet\Control\Print\Monitors\Standard TCP/IP Port\Ports\{port}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
            for name in ("HostName", "IPAddress"):
                try:
                    value = str(winreg.QueryValueEx(k, name)[0]).strip()
                except OSError:
                    continue
                if value:
                    return value
    except OSError:
        pass
    m = re.fullmatch(r"(?:IP_)?(\d{1,3}(?:\.\d{1,3}){3})(?:_\d+)?", port or "")
    return m.group(1) if m else None


def toner_colour(description):
    d = description.lower()
    if "waste" in d:
        return None
    for colour in COLOURS:
        if colour in d:
            return colour
    if re.search(r"\b(k|bk)\b", d):
        return "black"
    return None


def classify_counters(names):
    """{'total' / 'black' / 'colour': value} from Ricoh counter names, only when clearly named."""
    out = {}
    for name, value in names:
        n = name.lower()
        if not isinstance(value, int) or value < 0:
            continue
        mono = any(w in n for w in ("b&w", "black & white", "black and white", "bw", "mono"))
        colour = any(w in n for w in ("full color", "full colour", "fullcolor", "colour", "color")) and not mono
        if "total" in n and mono and "black" not in out:
            out["black"] = value
        elif "total" in n and colour and "single" not in n and "two" not in n and "colour" not in out:
            out["colour"] = value
        elif (re.search(r"\bmachine total\b", n) or re.fullmatch(r"(counter\s*:?\s*)?total(\s*counter)?", n.strip(" :"))) \
                and "total" not in out:
            out["total"] = value
    return out


def copier_address(printers, pid, settings=None):
    """(address, where it came from) of a copier: its Network address in Settings (settings.json, 2026-11-18_02; it
    wins), else typed in the Data screen (toner_settings.json), else the queue's port."""
    own = str(printers.get(pid, {}).get("address") or "").strip()
    if own:
        return own, "set in Settings"
    settings = settings or load_settings()
    typed = settings["addresses"].get(pid)
    if typed:
        return typed, "typed in the Data screen"
    found = queue_address(printers[pid]["queue"])
    return (found, "from the Windows queue's port") if found else (None, "not found")


def save_address(printers, pid, address):
    """Write a printer's Network address into settings.json (2026-11-18_02), and into the printers in force."""
    import copy
    local = routing.load_local()
    mine = copy.deepcopy(local.get("printers") or printers)
    if pid not in mine:
        return
    if address:
        mine[pid]["address"] = address
    else:
        mine[pid].pop("address", None)
    local["printers"] = mine
    shipped = routing.shipped_rules()
    routing.save_local(routing.local_diff(shipped, routing.merge(shipped, local)))
    if address:
        printers[pid]["address"] = address
    else:
        printers.get(pid, {}).pop("address", None)


def read_total(address, community="public", timeout=TIMEOUT):
    """The copier's total counter (prtMarkerLifeCount), read-only, or None when it doesn't answer (Copy counter,
    2026-11-17_10)."""
    try:
        value = Snmp(address, community, timeout=timeout).get([OID_LIFE_COUNT]).get(OID_LIFE_COUNT)
    except (OSError, ValueError):
        return None
    return int(value) if isinstance(value, int) else None


def read_copier(address, community="public", timeout=TIMEOUT, page=True):
    """Everything one copier answers: {"ok", "version", "model", "counters", "toners", "raw", "error"}.
    counters: total / black / colour, each an int or None (not given). toners: colour -> percent or None."""
    result = {"ok": False, "version": None, "model": "", "counters": {"total": None, "black": None, "colour": None},
              "toners": {c: None for c in COLOURS}, "raw": {"supplies": [], "counters": [], "life": None},
              "error": None}
    if not address:
        result["error"] = "no address"
        return result
    for version in (1, 0):  # v2c, then v1
        snmp = Snmp(address, community, version, timeout)
        try:
            basics = snmp.get([OID_SYSDESCR, OID_MODEL, OID_LIFE_COUNT])
        except (OSError, ValueError, IndexError) as e:
            result["error"] = "no answer" if isinstance(e, socket.timeout) else f"{type(e).__name__}: {e}"
            continue
        result.update(ok=True, version="v2c" if version else "v1", error=None)
        break
    else:
        return result  # no SNMP answer: the page isn't read either (no toner levels, nothing recorded)
    try:
        result["model"] = str(basics.get(OID_MODEL) or basics.get(OID_SYSDESCR) or "")
        result["sysdescr"] = str(basics.get(OID_SYSDESCR) or "")
        life = basics.get(OID_LIFE_COUNT)
        result["raw"]["life"] = life
        if isinstance(life, int) and life >= 0:
            result["counters"]["total"] = life
        rows = {}
        for oid, value in snmp.walk(OID_SUPPLIES):
            column, index = oid[len(OID_SUPPLIES) + 1:].split(".", 1)
            rows.setdefault(index, {})[column] = value
        for index, row in rows.items():
            desc = str(row.get(SUP_DESC, ""))
            level, maximum = row.get(SUP_LEVEL), row.get(SUP_MAX)
            percent = None
            if isinstance(level, int) and isinstance(maximum, int) and maximum > 0 and level >= 0:
                percent = max(0, min(100, round(level * 100 / maximum)))
            colour = toner_colour(desc) if ("toner" in desc.lower() or row.get(SUP_TYPE) == 3) else None
            result["raw"]["supplies"].append({"index": index, "description": desc, "type": row.get(SUP_TYPE),
                                              "max": maximum, "level": level, "percent": percent, "colour": colour})
            if colour and result["toners"][colour] is None:
                result["toners"][colour] = percent
        names, values = {}, {}
        for oid, value in snmp.walk(OID_RICOH_COUNTERS):
            column, index = oid[len(OID_RICOH_COUNTERS) + 1:].split(".", 1)
            if column == RICOH_NAME:
                names[index] = str(value)
            elif column == RICOH_VALUE:
                values[index] = value
        pairs = [(names.get(i, f"#{i}"), values[i]) for i in values]
        result["raw"]["counters"] = pairs
        found = classify_counters(pairs)
        for key in ("total", "black", "colour"):
            if result["counters"][key] is None and key in found:
                result["counters"][key] = found[key]
    except (OSError, ValueError, IndexError) as e:
        result["error"] = f"partly read: {e}"
    if page:
        add_page_counts(result, address)
    return result


def add_page_counts(result, address):
    """The copier's counter page (counter_page.py, 2026-11-18_01) gives the B&W and colour counts the SNMP Ricoh
    counter table leaves empty: Black / Colour count in pages. result["page"]: the parsed page, or why not."""
    import counter_page
    try:
        black, colour, parsed = counter_page.read_counts(address)
    except counter_page.PageError as e:
        result["page"] = {"ok": False, "error": str(e)}
        return
    result["page"] = {"ok": True, "parsed": parsed, "black": black, "colour": colour}
    if result["counters"]["black"] is None:
        result["counters"]["black"] = black
    if result["counters"]["colour"] is None:
        result["counters"]["colour"] = colour


# ------------------------------------------------------------------ files

def _path(name):
    return routing.app_dir() / name


def _load_json(name, default):
    try:
        return json.loads(_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_json(name, data):
    path = _path(name)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load_settings():
    data = _load_json(SETTINGS_FILE, {})
    return {"community": str(data.get("community") or "public"),
            "addresses": {k: str(v) for k, v in (data.get("addresses") or {}).items() if str(v).strip()}}


def save_settings(settings):
    _save_json(SETTINGS_FILE, settings)


def _num(text):
    text = str(text or "").strip()
    return int(text) if re.fullmatch(r"-?\d+", text) else None


def read_changes():
    """Every recorded toner change, oldest first. A broken line is skipped."""
    out = []
    try:
        with open(_path(LOG_FILE), newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    out.append({"id": row["id"], "time": datetime.datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S"),
                                "copier": row["copier"], "colour": row["colour"], "total": _num(row["total"]),
                                "black": _num(row["black count"]), "colour_count": _num(row["colour count"]),
                                "before": _num(row["level before"]), "after": _num(row["level after"]),
                                "how": row["how"]})
                except (KeyError, ValueError, TypeError):
                    continue
    except OSError:
        pass
    return sorted(out, key=lambda c: c["time"])


def write_changes(changes):
    path = _path(LOG_FILE)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(LOG_COLUMNS)
        for c in sorted(changes, key=lambda c: c["time"]):
            w.writerow([c["id"], c["time"].strftime("%Y-%m-%d %H:%M:%S"), c["copier"], c["colour"],
                        "" if c["total"] is None else c["total"], "" if c["black"] is None else c["black"],
                        "" if c["colour_count"] is None else c["colour_count"],
                        "" if c["before"] is None else c["before"], "" if c["after"] is None else c["after"],
                        c["how"]])
    os.replace(tmp, path)


def near_change(changes, copier, colour, when):
    """A change of the same toner within 24 hours of `when`, or None."""
    return next((c for c in changes if c["copier"] == copier and c["colour"] == colour
                 and abs(c["time"] - when) < SAME_CHANGE), None)


def history(changes, printers):
    """{copier: {colour: {"rows": [newest first], "average": int|None, "count": n, "note": text}}}."""
    out = {}
    for pid in printers:
        out[pid] = {}
        for colour in COLOURS:
            mine = [c for c in changes if c["copier"] == pid and c["colour"] == colour]
            rows, used, note = [], [], ""
            for prev, c in zip([None] + mine, mine):
                copies = None
                if prev is not None:
                    if colour != "black" and c["colour_count"] is not None and prev["colour_count"] is not None:
                        copies = c["colour_count"] - prev["colour_count"]
                    elif colour == "black" and c["black"] is not None and prev["black"] is not None:
                        copies = c["black"] - prev["black"]  # the counter page's B&W pages (2026-11-18_01)
                    elif c["total"] is not None and prev["total"] is not None:
                        copies = c["total"] - prev["total"]
                        if colour != "black":
                            note = "counted with the total counter (no colour counter)"
                    if copies is not None:
                        used.append(copies)
                rows.append({"change": c, "copies": copies, "first": prev is None})
            out[pid][colour] = {"rows": rows[::-1], "count": len(used),
                                "average": round(sum(used) / len(used)) if used else None, "note": note}
    return out


# ------------------------------------------------------------------ spare toner stock

def load_stock(printers):
    """{"saved": bool, "copiers": {pid: {colour: {"count", "min"}}}, "taken": [change ids]}.
    A missing file: every count 0, minimum 1, not saved yet."""
    data = _load_json(STOCK_FILE, {})
    out = {"saved": bool(data.get("saved")), "copiers": {}, "taken": [str(x) for x in data.get("taken") or []]}
    for pid in printers:
        saved = (data.get("copiers") or {}).get(pid) or {}
        out["copiers"][pid] = {}
        for colour in COLOURS:
            s = saved.get(colour) or {}
            count, minimum = s.get("count"), s.get("min")
            out["copiers"][pid][colour] = {
                "count": count if isinstance(count, int) and count >= 0 else 0,
                "min": minimum if isinstance(minimum, int) and minimum >= 0 else 1}
    return out


def _log_stock(lines):
    """Add lines to toner_stock_log.csv: the old lines are kept, the file is replaced in one go."""
    path = _path(STOCK_LOG)
    old = []
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            old = [row for row in csv.reader(f)][1:]
    except OSError:
        pass
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(STOCK_COLUMNS)
        w.writerows(old)
        w.writerows(lines)
    os.replace(tmp, path)


def read_stock_log():
    try:
        with open(_path(STOCK_LOG), newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


def _stock_line(when, pid, colour, change, count, reason):
    return [when.strftime("%Y-%m-%d %H:%M:%S"), pid, colour, f"{change:+d}", count, reason]  # +3 / -1: Excel reads them as numbers


def save_stock_counts(printers, pid, new, reasons, when=None):
    """Stock… Save: new = {colour: (count, min)}, reasons = {colour: 'added' / 'counted'}."""
    when = when or datetime.datetime.now().replace(microsecond=0)
    with STOCK_LOCK:
        stock = load_stock(printers)
        lines = []
        for colour, (count, minimum) in new.items():
            cell = stock["copiers"][pid][colour]
            if count != cell["count"]:
                lines.append(_stock_line(when, pid, colour, count - cell["count"], count, reasons.get(colour, "counted")))
            cell["count"], cell["min"] = count, minimum
        stock["saved"] = True
        if lines:
            _log_stock(lines)
        _save_json(STOCK_FILE, stock)


def take_spare(printers, change, when=None):
    """A toner change used a spare: one off that copier's count (never below 0)."""
    with STOCK_LOCK:
        stock = load_stock(printers)
        cell = stock["copiers"].get(change["copier"], {}).get(change["colour"])
        if cell is None or cell["count"] <= 0:
            return  # recorded anyway; nothing to take: the screen says "None left"
        cell["count"] -= 1
        stock["taken"].append(change["id"])
        _log_stock([_stock_line(when or change["time"], change["copier"], change["colour"], -1, cell["count"],
                                "toner changed")])
        _save_json(STOCK_FILE, stock)


def give_back_spare(printers, change, when=None):
    """A recorded change was removed: its spare goes back on the shelf (only if one was taken)."""
    with STOCK_LOCK:
        stock = load_stock(printers)
        if change["id"] not in stock["taken"]:
            return
        stock["taken"].remove(change["id"])
        cell = stock["copiers"][change["copier"]][change["colour"]]
        cell["count"] += 1
        _log_stock([_stock_line(when or datetime.datetime.now().replace(microsecond=0), change["copier"],
                                change["colour"], +1, cell["count"], "change removed")])
        _save_json(STOCK_FILE, stock)


def stock_low(printers):
    """True while any spare count is at or below its minimum (the red dot on the menu)."""
    stock = load_stock(printers)
    return any(c["count"] <= c["min"] for colours in stock["copiers"].values() for c in colours.values())


# ------------------------------------------------------------------ the background reader

class TonerWatch:
    """Reads every copier at start and every EVERY seconds; records toner changes it sees."""

    def __init__(self, rules, every=EVERY, timeout=TIMEOUT):
        self.rules, self.every, self.timeout = rules, every, timeout
        self.printers = rules["printers"]
        self.lock = threading.Lock()
        self.latest = {}  # copier -> last reading (ok or not)
        self.last_good = {}  # copier -> time of the last good reading
        self.seen_this_run = set()  # copiers read OK since start: later changes are "automatic"
        self.version = 0  # goes up after every reading, so screens know to refresh
        self.wake = threading.Event()
        self.stopped = False
        state = _load_json(STATE_FILE, {})
        for pid, s in (state.get("copiers") or {}).items():
            try:
                self.last_good[pid] = datetime.datetime.fromisoformat(s["time"])
            except (KeyError, ValueError, TypeError):
                pass

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self.stopped = True
        self.wake.set()

    def read_now(self):
        self.wake.set()

    def address(self, pid, settings=None):
        """(address, where it came from): typed in the Data screen, else the queue's port."""
        return copier_address(self.printers, pid, settings)

    def _loop(self):
        while not self.stopped:
            self.read_all()
            self.wake.wait(self.every)
            self.wake.clear()

    def read_all(self):
        """Read every copier at the same time, each on its own thread; then record what changed."""
        settings = load_settings()
        found = {}

        def one(pid):
            address, where = self.address(pid, settings)
            found[pid] = dict(read_copier(address, settings["community"], self.timeout), address=address,
                              where=where)

        threads = [threading.Thread(target=one, args=(pid,), daemon=True) for pid in self.printers]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.record(found)

    def record(self, found, now=None):
        """Compare with the last readings (toner_state.json), record new toners, save the state."""
        now = now or datetime.datetime.now().replace(microsecond=0)
        with self.lock:
            state = _load_json(STATE_FILE, {"copiers": {}})
            copiers = state.setdefault("copiers", {})
            changes = read_changes()
            added = []
            for pid, r in found.items():
                self.latest[pid] = dict(r, time=now)
                if not r["ok"]:
                    continue
                self.last_good[pid] = now
                before = copiers.get(pid)
                for colour in COLOURS:
                    new = r["toners"][colour]
                    old = (before or {}).get("toners", {}).get(colour)
                    if not (isinstance(new, int) and isinstance(old, int) and new - old >= JUMP):
                        continue
                    if near_change(changes, pid, colour, now):
                        continue
                    change = {"id": uuid.uuid4().hex[:8], "time": now, "copier": pid, "colour": colour,
                              "total": r["counters"]["total"], "black": r["counters"]["black"],
                              "colour_count": r["counters"]["colour"], "before": old, "after": new,
                              "how": "automatic" if pid in self.seen_this_run else "found at start"}
                    changes.append(change)
                    added.append(change)
                self.seen_this_run.add(pid)
                copiers[pid] = {"time": now.isoformat(), "toners": r["toners"], "counters": r["counters"]}
            try:
                if added:
                    write_changes(changes)
                    for change in added:
                        take_spare(self.printers, change)  # one spare toner off the shelf
                _save_json(STATE_FILE, state)
            except OSError:
                pass  # tried again at the next reading
            self.version += 1

    def add_by_hand(self, pid, colour, total, black, colour_count, when=None):
        """Record a change typed by Tesla. Returns None, or why it wasn't added."""
        when = when or datetime.datetime.now().replace(microsecond=0)
        with self.lock:
            changes = read_changes()
            other = near_change(changes, pid, colour, when)
            if other:
                return (f"A change of the {COLOUR_NAMES[colour].lower()} toner on {self.printers[pid]['label']} "
                        f"is already recorded at {other['time']:%d/%m/%Y %H:%M} ({other['how']}). "
                        f"Changes within 24 hours count as one.")
            level = (self.latest.get(pid) or {}).get("toners", {}).get(colour)
            change = {"id": uuid.uuid4().hex[:8], "time": when, "copier": pid, "colour": colour,
                      "total": total, "black": black, "colour_count": colour_count, "before": None,
                      "after": level, "how": "by hand"}
            changes.append(change)
            write_changes(changes)
            take_spare(self.printers, change)
            self.version += 1
        return None

    def remove(self, change_id):
        with self.lock:
            changes = read_changes()
            gone = next((c for c in changes if c["id"] == change_id), None)
            write_changes([c for c in changes if c["id"] != change_id])
            if gone:
                give_back_spare(self.printers, gone)
            self.version += 1

    def check_file(self):
        """Copier check: read every copier once and write copier_check.txt (no community, no secrets)."""
        settings = load_settings()
        lines = [f"ORCA copier check, {datetime.datetime.now():%d/%m/%Y %H:%M}", ""]
        for pid, p in self.printers.items():
            address, where = self.address(pid, settings)
            r = read_copier(address, settings["community"], self.timeout)
            lines += [f"== {p['label']} ({pid}), Windows queue “{p['queue']}”",
                      f"Address used: {address or 'none'} ({where})",
                      f"Answered: {'yes, SNMP ' + r['version'] if r['ok'] else 'no (' + (r['error'] or 'no answer') + ')'}"]
            if r["ok"]:
                lines += [f"System description: {r.get('sysdescr') or 'not given'}",
                          f"Model: {r['model'] or 'not given'}",
                          f"Total counter (Printer MIB prtMarkerLifeCount): {r['raw']['life'] if r['raw']['life'] is not None else 'not given'}",
                          "As understood:"]
                for key, name in (("total", "Total count"), ("black", "Black count"), ("colour", "Colour count")):
                    v = r["counters"][key]
                    lines.append(f"  {name}: {v if v is not None else 'not given'}")
                for colour in COLOURS:
                    v = r["toners"][colour]
                    lines.append(f"  {COLOUR_NAMES[colour]} toner: {str(v) + '%' if v is not None else 'not given'}")
                lines.append("Supplies (Printer MIB prtMarkerSuppliesTable): index, type, description, max, level, understood")
                if not r["raw"]["supplies"]:
                    lines.append("  none given")
                for s in r["raw"]["supplies"]:
                    lines.append(f"  {s['index']}: type {s['type']}, “{s['description']}”, max {s['max']}, level {s['level']}"
                                 f" -> {COLOUR_NAMES.get(s['colour'], 'not a toner') if s['colour'] else 'not a toner'}"
                                 f"{', ' + str(s['percent']) + '%' if s['percent'] is not None else ''}")
                lines.append("Ricoh counters (1.3.6.1.4.1.367.3.2.1.2.19.5.1): name = value")
                if not r["raw"]["counters"]:
                    lines.append("  none given")
                lines += [f"  {name} = {value}" for name, value in r["raw"]["counters"]]
                import counter_page
                page = r.get("page") or {}
                lines.append(f"Counter page ({counter_page.PATH}): "
                             + (f"read, Black count {page['black']}, Colour count {page['colour']} (pages)"
                                if page.get("ok") else f"not readable ({page.get('error') or 'not tried'})"))
                if page.get("ok"):
                    lines += counter_page.describe(page["parsed"])
                missing = [n for k, n in (("total", "Total count"), ("black", "Black count"), ("colour", "Colour count"))
                           if r["counters"][k] is None]
                missing += [f"{COLOUR_NAMES[c]} toner level" for c in COLOURS if r["toners"][c] is None]
                lines.append("Missing: " + (", ".join(missing) if missing else "nothing"))
            lines.append("")
        path = _path(CHECK_FILE)
        path.write_text("\n".join(lines), encoding="utf-8-sig")
        return path


# ------------------------------------------------------------------ the Data screen (TonersScreen)

def _fmt(n):
    return "not given" if n is None else f"{n:,}"


class TonersScreen:
    def __init__(self, root, rules, watch, on_back):
        import costs  # ScrollFrame and the entry font
        self.costs = costs
        self.rules, self.watch, self.on_back = rules, watch, on_back
        self.printers = rules["printers"]
        self.win = win = tk.Toplevel(root)
        win.title("ORCA - Data")
        win.geometry("1300x900")
        win.minsize(1150, 600)
        win.protocol("WM_DELETE_WINDOW", self.back)
        style = ttk.Style(win)
        style.configure("Big.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Head.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Small.TLabel", font=("Segoe UI", 9), foreground=theme.MUTED)

        f = ttk.Frame(win, padding=16)
        f.grid(sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(2, weight=1)
        top = ttk.Frame(f)
        top.grid(row=0, column=0, sticky="we")
        ttk.Button(top, text="← Back", command=self.back).pack(side="left", padx=(0, 24))
        ttk.Label(top, text="Data", style="Summary.TLabel").pack(side="left")
        for text, command in (("Copier check", self.copier_check), ("Open in Excel", self.open_log),
                              ("Read now", self.read_now), ("Toner replaced…", self.replaced)):
            ttk.Button(top, text=text, command=command,
                       style="Print.TButton" if text.startswith("Toner") else "TButton").pack(side="right", padx=(8, 0))
        self.status = ttk.Label(f, text="", style="Hint.TLabel")
        self.status.grid(row=1, column=0, sticky="w", pady=(8, 8))
        self.scroll = costs.ScrollFrame(f)
        self.scroll.grid(row=2, column=0, sticky="nsew")
        self.shown_version = None
        self.fill()
        theme.dark_title_bar(win)
        self.win.after(1000, self.poll)

    def poll(self):
        """Refresh after every reading while the screen is open."""
        if not self.win.winfo_exists():
            return
        if self.watch.version != self.shown_version:
            self.fill()
        self.win.after(1000, self.poll)

    def fill(self):
        self.shown_version = self.watch.version
        self.stock = load_stock(self.printers)
        self.status.config(text="" if self.stock["saved"] else "Count your spare toners and enter them with Stock…",
                           foreground=theme.MUTED if self.stock["saved"] else theme.ERROR)
        top = self.scroll.canvas.yview()[0]
        inner = self.scroll.inner
        for w in inner.winfo_children():
            w.destroy()
        inner.columnconfigure(0, weight=1)
        now = ttk.LabelFrame(inner, text="Now", padding=12, style="Section.TLabelframe")
        now.grid(row=0, column=0, sticky="we", pady=(0, 12))
        for c, pid in enumerate(self.printers):
            now.columnconfigure(c, weight=1, uniform="copier")
            self.copier_block(now, c, pid)
        theme.on_surface(now)

        hist = history(read_changes(), self.printers)
        for r, pid in enumerate(self.printers, start=1):
            box = ttk.LabelFrame(inner, text=f"History: {self.printers[pid]['label']}", padding=12,
                                 style="Section.TLabelframe")
            box.grid(row=r, column=0, sticky="we", pady=(0, 12))
            row = 0
            for colour in COLOURS:
                h = hist[pid][colour]
                avg = (f"{h['average']:,} copies, average of {h['count']}" if h["average"] is not None
                       else "no average yet")
                ttk.Label(box, text=f"{COLOUR_NAMES[colour]}: {avg}", style="Head.TLabel").grid(
                    row=row, column=0, columnspan=5, sticky="w", pady=(6 if row else 0, 2))
                row += 1
                if h["note"]:
                    ttk.Label(box, text=h["note"], style="Small.TLabel").grid(row=row, column=0, columnspan=5, sticky="w")
                    row += 1
                if not h["rows"]:
                    ttk.Label(box, text="No change recorded", style="Hint.TLabel").grid(row=row, column=0, sticky="w")
                    row += 1
                for item in h["rows"]:
                    c = item["change"]
                    if colour == "black":
                        counter = c["black"] if c["black"] is not None else c["total"]
                    else:
                        counter = c["colour_count"] if c["colour_count"] is not None else c["total"]
                    copies = "first reading" if item["first"] else (
                        f"{item['copies']:,} copies by the toner taken out" if item["copies"] is not None
                        else "copies unknown (no counter)")
                    values = (f"{c['time']:%d/%m/%Y %H:%M}", f"counter {_fmt(counter)}", copies, c["how"])
                    for col, text in enumerate(values):
                        ttk.Label(box, text=text).grid(row=row, column=col, sticky="w", padx=(12 if col == 0 else 0, 24))
                    ttk.Button(box, text="Remove", command=lambda i=c["id"]: self.remove(i)).grid(
                        row=row, column=4, sticky="w", pady=1)
                    row += 1
            theme.on_surface(box)
        self.win.update_idletasks()
        self.scroll.canvas.yview_moveto(top)

    def copier_block(self, parent, column, pid):
        f = ttk.Frame(parent, padding=(0, 0, 18, 0))
        f.grid(row=0, column=column, sticky="nwe")
        r = self.watch.latest.get(pid)
        good = self.watch.last_good.get(pid)
        ttk.Label(f, text=self.printers[pid]["label"], style="Big.TLabel").pack(anchor="w")
        if r is None:
            state, red = "Not read yet", False
        elif r["ok"]:
            state, red = f"Connected · read {r['time']:%H:%M}", False
        else:
            state, red = "No answer" + (f" · last good reading {good:%d/%m %H:%M}" if good else ""), True
        ttk.Label(f, text=state, foreground=theme.ERROR if red else theme.MUTED).pack(anchor="w")
        line = ttk.Frame(f)
        line.pack(anchor="w", fill="x", pady=(0, 8))
        address = (r or {}).get("address")
        ttk.Label(line, text=f"Address: {address or 'not found'}", style="Small.TLabel").pack(side="left")
        ttk.Button(line, text="Address…", command=lambda: AddressDialog(self, pid)).pack(side="left", padx=(8, 0))
        ttk.Button(line, text="Stock…", command=lambda: StockDialog(self, pid)).pack(side="left", padx=(6, 0))
        counters = (r or {}).get("counters") if r and r["ok"] else None
        if counters is None and r is not None and not r["ok"]:
            counters = (_load_json(STATE_FILE, {}).get("copiers", {}).get(pid) or {}).get("counters")
        for key, name in (("total", "Total count"), ("black", "Black count"), ("colour", "Colour count")):
            line = ttk.Frame(f)
            line.pack(anchor="w", fill="x")
            ttk.Label(line, text=name, width=13).pack(side="left")
            ttk.Label(line, text=_fmt((counters or {}).get(key)), style="Head.TLabel").pack(side="left")
        levels = (r or {}).get("toners") if r and r["ok"] else None
        for colour in COLOURS:
            line = ttk.Frame(f)
            line.pack(anchor="w", fill="x", pady=(6, 0))
            ttk.Label(line, text=COLOUR_NAMES[colour], width=9).pack(side="left")
            level = (levels or {}).get(colour)
            bar = tk.Canvas(line, width=80, height=14, background=theme.FIELD, highlightthickness=0)
            bar.pack(side="left", padx=(0, 8))
            if level is not None:
                bar.create_rectangle(0, 0, int(80 * level / 100), 14, fill=BAR_COLOURS[colour], width=0)
            ttk.Label(line, text=f"{level}%" if level is not None else "not given", width=9).pack(side="left")
            spare = self.stock["copiers"][pid][colour]
            warn = "None left" if spare["count"] == 0 else "Order more" if spare["count"] <= spare["min"] else ""
            ttk.Label(line, text=f"Spare: {spare['count']}",
                      foreground=theme.ERROR if warn else theme.TEXT).pack(side="left")
            if warn:
                ttk.Label(line, text=warn, foreground=theme.ERROR, font=("Segoe UI", 9, "bold")).pack(
                    side="left", padx=(5, 0))

    # -------------------------------------------------------------- buttons

    def read_now(self):
        self.watch.read_now()
        self.status.config(text="Reading the copiers…")
        self.win.after(int(self.watch.timeout * 4000) + 1000, lambda: self.win.winfo_exists() and self.fill())

    def open_log(self):
        path = _path(LOG_FILE)
        if not path.exists():
            messagebox.showinfo(parent=self.win, title="Data", message="No toner change is recorded yet.")
            return
        try:
            os.startfile(path)
        except OSError as e:
            messagebox.showwarning(parent=self.win, title="Data", message=f"Could not open {path.name}.\n\n{e}")

    def copier_check(self):
        self.status.config(text="Copier check: reading every copier…")

        def work():
            try:
                path = self.watch.check_file()
                error = None
            except OSError as e:
                path, error = None, e
            self.win.after(0, lambda: self.check_done(path, error))

        threading.Thread(target=work, daemon=True).start()

    def check_done(self, path, error):
        if not self.win.winfo_exists():
            return
        if error:
            self.status.config(text="")
            messagebox.showwarning(parent=self.win, title="Data", message=f"Could not write {CHECK_FILE}.\n\n{error}")
            return
        self.status.config(text=f"Written: {path}")
        try:
            os.startfile(path)
        except OSError:
            pass

    def remove(self, change_id):
        c = next((c for c in read_changes() if c["id"] == change_id), None)
        if c is None:
            return
        if messagebox.askyesno(parent=self.win, title="Data",
                               message=f"Remove the {COLOUR_NAMES[c['colour']].lower()} toner change on "
                                       f"{self.printers[c['copier']]['label']} of {c['time']:%d/%m/%Y %H:%M}?"):
            self.watch.remove(change_id)
            self.fill()

    def replaced(self):
        ReplacedDialog(self)

    def back(self):
        self.win.destroy()
        self.on_back()


class AddressDialog:
    """Type a copier's network address (empty: take it from the Windows queue's port) and the SNMP community."""

    def __init__(self, screen, pid):
        self.screen, self.pid = screen, pid
        settings = load_settings()
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title("Copier address")
        dlg.resizable(False, False)
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=20)
        f.grid()
        font = screen.costs.FONT
        found = queue_address(screen.printers[pid]["queue"])
        ttk.Label(f, text=screen.printers[pid]["label"], style="Head.TLabel").grid(row=0, column=0, columnspan=2,
                                                                                  sticky="w", pady=(0, 8))
        ttk.Label(f, text="Address:").grid(row=1, column=0, sticky="w", pady=3)
        self.address = tk.StringVar(value=screen.printers[pid].get("address") or settings["addresses"].get(pid, ""))
        ttk.Entry(f, textvariable=self.address, width=22, font=font).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(f, text="SNMP community:").grid(row=2, column=0, sticky="w", pady=3)
        self.community = tk.StringVar(value=settings["community"])
        ttk.Entry(f, textvariable=self.community, width=22, font=font).grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(f, text=f"Empty address: use the Windows queue's port ({found or 'none found'}).\n"
                          f"The community is the same for every copier, usually “public”.",
                  style="Hint.TLabel", justify="left").grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        b = ttk.Frame(f)
        b.grid(row=4, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(b, text="Save", style="Print.TButton", command=self.done).pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    def done(self):
        settings = load_settings()
        address = self.address.get().strip()
        if address:
            settings["addresses"][self.pid] = address
        else:
            settings["addresses"].pop(self.pid, None)
        settings["community"] = self.community.get().strip() or "public"
        try:
            save_settings(settings)
            save_address(self.screen.printers, self.pid, address)  # Settings' Network address too (one place)
        except OSError as e:
            messagebox.showwarning(parent=self.dlg, title="Data", message=f"Could not save.\n\n{e}")
            return
        self.dlg.destroy()
        self.screen.read_now()


class StockDialog:
    """Spare toners of one copier: count (− / + / typed) and minimum per colour, Save or Cancel."""

    def __init__(self, screen, pid):
        self.screen, self.pid = screen, pid
        stock = load_stock(screen.printers)["copiers"][pid]
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title("Spare toners")
        dlg.resizable(False, False)
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=20)
        f.grid()
        font = screen.costs.FONT
        ttk.Label(f, text=f"Spare toners for {screen.printers[pid]['label']}", style="Head.TLabel").grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 8))
        for c, text in ((2, "On the shelf"), (5, "Minimum")):
            ttk.Label(f, text=text, style="Hint.TLabel").grid(row=1, column=c, sticky="w")
        self.counts, self.mins, self.typed = {}, {}, {}
        for r, colour in enumerate(COLOURS, start=2):
            ttk.Label(f, text=COLOUR_NAMES[colour], width=9).grid(row=r, column=0, sticky="w", pady=3)
            self.counts[colour] = tk.StringVar(value=str(stock[colour]["count"]))
            self.mins[colour] = tk.StringVar(value=str(stock[colour]["min"]))
            self.typed[colour] = False
            ttk.Button(f, text="−", width=3, command=lambda c=colour: self.step(c, -1)).grid(row=r, column=1, padx=2)
            e = ttk.Entry(f, textvariable=self.counts[colour], width=5, font=font, justify="center")
            e.grid(row=r, column=2, padx=2)
            e.bind("<Key>", lambda _, c=colour: self.typed.__setitem__(c, True))
            ttk.Button(f, text="+", width=3, command=lambda c=colour: self.step(c, +1)).grid(row=r, column=3, padx=2)
            ttk.Label(f, text="").grid(row=r, column=4, padx=10)
            ttk.Entry(f, textvariable=self.mins[colour], width=5, font=font, justify="center").grid(row=r, column=5)
        ttk.Label(f, text="Order more shows when the shelf is at or below the minimum.", style="Hint.TLabel").grid(
            row=6, column=0, columnspan=6, sticky="w", pady=(8, 0))
        self.error = ttk.Label(f, text="", foreground=theme.ERROR)
        self.error.grid(row=7, column=0, columnspan=6, sticky="w")
        b = ttk.Frame(f)
        b.grid(row=8, column=0, columnspan=6, sticky="e", pady=(10, 0))
        ttk.Button(b, text="Save", style="Print.TButton", command=self.done).pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    def step(self, colour, delta):
        text = self.counts[colour].get().strip()
        value = int(text) if text.isdigit() else 0
        if delta < 0:
            self.typed[colour] = True  # taking one off by hand is a correction: "counted"
        self.counts[colour].set(str(max(0, value + delta)))

    def done(self):
        new, reasons = {}, {}
        for colour in COLOURS:
            count, minimum = self.counts[colour].get().strip(), self.mins[colour].get().strip()
            if not count.isdigit() or not minimum.isdigit():
                self.error.config(text=f"{COLOUR_NAMES[colour]}: whole numbers, 0 or more.")
                return
            new[colour] = (int(count), int(minimum))
            reasons[colour] = "counted" if self.typed[colour] else "added"
        try:
            save_stock_counts(self.screen.printers, self.pid, new, reasons)
        except OSError as e:
            self.error.config(text=f"Could not save: {e}")
            return
        self.dlg.destroy()
        self.screen.fill()


class ReplacedDialog:
    """Toner replaced by hand: copier, colour, the counters (from the latest reading, can be typed over)."""

    def __init__(self, screen):
        self.screen = screen
        self.dlg = dlg = tk.Toplevel(screen.win)
        dlg.title("Toner replaced")
        dlg.resizable(False, False)
        dlg.transient(screen.win)
        f = ttk.Frame(dlg, padding=20)
        f.grid()
        printers = screen.printers
        self.labels = {p["label"]: pid for pid, p in printers.items()}
        self.copier = tk.StringVar(value=next(iter(self.labels)))
        self.colour = tk.StringVar(value="Black")
        self.vars = {k: tk.StringVar() for k in ("total", "black", "colour")}
        font = screen.costs.FONT
        ttk.Label(f, text="Copier:").grid(row=0, column=0, sticky="w", pady=3)
        cb = ttk.Combobox(f, textvariable=self.copier, values=list(self.labels), state="readonly", width=24, font=font)
        cb.grid(row=0, column=1, sticky="w", pady=3)
        cb.bind("<<ComboboxSelected>>", lambda _: self.fill_counters())
        ttk.Label(f, text="Toner:").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.colour, values=[COLOUR_NAMES[c] for c in COLOURS], state="readonly",
                     width=24, font=font).grid(row=1, column=1, sticky="w", pady=3)
        for r, (key, name) in enumerate((("total", "Total count"), ("black", "Black count"),
                                         ("colour", "Colour count")), start=2):
            ttk.Label(f, text=f"{name}:").grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(f, textvariable=self.vars[key], width=14, font=font).grid(row=r, column=1, sticky="w", pady=3)
        ttk.Label(f, text="Filled in from the latest reading. For a copier that gives no counter,\n"
                          "type the number from the copier's screen. Empty means not known.",
                  style="Hint.TLabel", justify="left").grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.error = ttk.Label(f, text="", foreground=theme.ERROR, wraplength=420, justify="left")
        self.error.grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        b = ttk.Frame(f)
        b.grid(row=7, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(b, text="Record", style="Print.TButton", command=self.done).pack(side="left")
        ttk.Button(b, text="Cancel", command=dlg.destroy).pack(side="left", padx=(8, 0))
        self.fill_counters()
        theme.dark_title_bar(dlg)
        dlg.grab_set()

    def fill_counters(self):
        pid = self.labels[self.copier.get()]
        r = self.screen.watch.latest.get(pid) or {}
        counters = r.get("counters") if r.get("ok") else (
            _load_json(STATE_FILE, {}).get("copiers", {}).get(pid) or {}).get("counters")
        for key, var in self.vars.items():
            v = (counters or {}).get(key)
            var.set("" if v is None else str(v))

    def done(self):
        values = {}
        for key, var in self.vars.items():
            text = var.get().strip().replace(",", "").replace(" ", "")
            if text and not text.isdigit():
                self.error.config(text="Counters are whole numbers.")
                return
            values[key] = int(text) if text else None
        pid = self.labels[self.copier.get()]
        colour = next(c for c, n in COLOUR_NAMES.items() if n == self.colour.get())
        why = self.screen.watch.add_by_hand(pid, colour, values["total"], values["black"], values["colour"])
        if why:
            self.error.config(text=why)
            return
        self.dlg.destroy()
        self.screen.fill()
