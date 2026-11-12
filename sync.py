"""Website sync: download the website's paid orders into Pending Orders (PRINTHUB_SPEC.md stage 5b).

Runs only when printhub_token.txt is next to the app (the work PC). Every check_seconds a
background thread asks the website for paid orders (GET /api/printrouter/orders), downloads each
new one into a hidden folder, turns Office and image files into PDF, writes order.json last,
renames the folder into Pending Orders and confirms it (POST /api/printrouter/orders/received).
An order that is already in Pending Orders, Orders or Finished Orders is only confirmed again.
Nothing here prints: orders still print only after Start printing orders.

When staff press Ready for courier, report_ready() queues a message in sync_outbox.json; it is
sent (POST /api/printrouter/orders/status) at once and again at every check until the website
answers. The outbox survives restarts.

The token is read from the file on every check and only ever sent to the website in the
Authorization header. It is never written to a log, shown, or put in an error text.
Standard library only (urllib).
"""
import datetime
import json
import os
import re
import shutil
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import convert
import jobs
import orders
import routing

TOKEN_FILE = "printhub_token.txt"
LOG_FILE = "sync_log.txt"
OUTBOX_FILE = "sync_outbox.json"  # "ready" messages waiting for the website
TIMEOUT = 30  # seconds, for every request (and every pause while downloading a file)
FIRST_CHECK = 5  # seconds after the app starts
RED_AFTER = 3  # failed tries in a row before an order is shown in red
ORDER_NUMBER = re.compile(r"^PH-\d{1,9}$")
CHUNK = 1 << 16


class SyncError(Exception):
    def __init__(self, text, code=None):
        super().__init__(text)
        self.code = code  # the website's HTTP answer, if it gave one


def _now():
    return datetime.datetime.now()


class WebsiteSync:
    def __init__(self, rules):
        cfg = rules.get("website", {})
        self.url = str(cfg.get("url", "")).rstrip("/")
        self.every = max(10, int(cfg.get("check_seconds", 60)))
        self.pending = orders.pending_dir(rules)
        self.ready = orders.orders_dir(rules)
        self.finished = orders.finished_dir(rules)
        self.token_path = routing.app_dir() / TOKEN_FILE
        self.log_path = routing.app_dir() / LOG_FILE
        self.outbox_path = routing.app_dir() / OUTBOX_FILE
        self.lock = threading.Lock()
        # Shown in the PrintHub window (read with status()).
        self.on = self.token_path.is_file()
        self.last_check = self.last_ok = None
        self.new = 0  # orders downloaded at the last check
        self.error = None  # why the last check couldn't reach the website
        self.failures = {}  # order number -> (failed tries in a row, reason)
        self.unconfirmed = set()  # downloaded, but the website didn't take the confirm yet
        self.notices = []  # red lines for the top bar ("PH-1: website says cancelled"), until Reload
        self.outbox = self._load_outbox()
        self.sending = threading.Lock()  # one outbox send at a time, so nothing is sent twice
        self.wake = threading.Event()
        self.thread = None

    # ------------------------------------------------------------ running

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _run(self):
        self.wake.wait(FIRST_CHECK)
        while True:
            self.wake.clear()
            try:
                self.check()
            except Exception as e:  # never let the thread die
                self._fail_check(f"unexpected error: {e}")
            self.wake.wait(self.every)

    def check_now(self):
        self.wake.set()

    def token(self):
        try:
            token = self.token_path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            return None
        return token or None

    def check(self):
        """One look at the website: download new paid orders and confirm them."""
        token = self.token()
        with self.lock:
            self.on = token is not None
        if token is None:
            return  # sync is off: no network calls at all
        try:
            self._check_orders(token)
        finally:
            self.send_outbox(token)

    def _check_orders(self, token):
        self._clean_leftovers()
        try:
            data = self._json("GET", "/api/printrouter/orders", token)
        except SyncError as e:
            self._fail_check(str(e))
            return
        if not isinstance(data, dict) or data.get("format") != 1 or not isinstance(data.get("orders"), list):
            self._fail_check("the website's answer isn't an order list (format 1)")
            return
        new = 0
        for entry in data["orders"]:
            number = entry.get("order", {}).get("order") if isinstance(entry, dict) and isinstance(
                entry.get("order"), dict) else None
            if not isinstance(number, str) or not ORDER_NUMBER.match(number):
                self.log(str(number), "skipped: not a valid order number")
                continue
            try:
                if self.exists(number):
                    if number not in self.unconfirmed:
                        self.log(number, "already here: confirming again")
                else:
                    self.download(entry, number)
                    new += 1
                    self.log(number, "downloaded into Pending Orders")
                self.unconfirmed.add(number)
                self._json("POST", "/api/printrouter/orders/received", token, {"order": number})
                self.unconfirmed.discard(number)
                self.log(number, "confirmed to the website")
                with self.lock:
                    self.failures.pop(number, None)
            except SyncError as e:
                with self.lock:
                    tries = self.failures.get(number, (0, ""))[0] + 1
                    self.failures[number] = (tries, str(e))
                self.log(number, f"failed (try {tries}): {e}")
        with self.lock:
            self.last_check = self.last_ok = _now()
            self.new, self.error = new, None

    def _fail_check(self, reason):
        with self.lock:
            self.last_check, self.error = _now(), reason
        self.log("-", f"can't connect: {reason}")

    # ------------------------------------------------------------ one order

    def exists(self, number):
        """True if the order is already in Pending Orders, Orders or Finished Orders (also as 'PH-1 (2)')."""
        for folder in (self.pending, self.ready, self.finished):
            if (folder / number).exists():
                return True
            try:
                if any(p.name.startswith(f"{number} (") for p in folder.iterdir()):
                    return True
            except OSError:
                pass
        return False

    def download(self, entry, number):
        """Download and convert into Pending Orders/.<order>.downloading, write order.json last, rename."""
        order, items = entry.get("order"), entry.get("items")
        if not isinstance(items, list) or not items:
            raise SyncError("the order has no items")
        tmp = self.pending / f".{number}.downloading"
        shutil.rmtree(tmp, ignore_errors=True)
        if tmp.exists():
            raise SyncError(f"can't remove the old {tmp.name} folder")
        tmp.mkdir(parents=True)
        try:
            for item in items:
                self._item(tmp, item)
            (tmp / "order.json").write_text(json.dumps(order, indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8")
            os.replace(tmp, self.pending / number)
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            raise e if isinstance(e, SyncError) else SyncError(str(e)) from e

    def _item(self, tmp, item):
        folder, job, files = item.get("folder"), item.get("job"), item.get("files")
        if not orders._plain_name(folder) or not isinstance(job, dict) or not isinstance(files, list):
            raise SyncError(f"item {folder!r} is incomplete")
        job = dict(job)
        kind = job.get("kind", "document")
        if kind not in ("document", "product"):
            raise SyncError(f"item {folder}: unknown kind {kind!r}")
        path = tmp / folder
        path.mkdir()
        for f in files:
            name, url = (f.get("name"), f.get("url")) if isinstance(f, dict) else (None, None)
            if not orders._plain_name(name):
                raise SyncError(f"item {folder}: bad file name {name!r}")
            self._fetch(url, path / name)
        if kind == "product":
            self._check_product(folder, job, path)
        else:
            self._convert_document(folder, job, path)
        (path / "job.json").write_text(json.dumps(job, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _check_product(self, folder, job, path):
        """A product item: the customer's files exactly as uploaded. Never converted, no document.pdf;
        job.json is written unchanged. The owner lays it out in CorelDRAW (PRINTHUB_SPEC.md 3.4)."""
        names, titles = job.get("files"), job.get("titles")
        if not isinstance(names, list) or not 1 <= len(names) <= orders.MAX_PRODUCT_FILES:
            raise SyncError(f"item {folder}: a product needs 1 to {orders.MAX_PRODUCT_FILES} files")
        if not isinstance(titles, list) or len(titles) != len(names):
            raise SyncError(f"item {folder}: files and titles don't match ({len(names)} files, "
                            f"{len(titles) if isinstance(titles, list) else 'no'} titles)")
        if len({str(n).lower() for n in names}) != len(names):
            raise SyncError(f"item {folder}: a file is listed twice")
        for name in names:
            reserved = (isinstance(name, str) and (name.lower() in ("job.json", orders.OPTIONS_TXT.lower())
                                                   or name.upper().startswith("PH-")))
            if not orders._plain_name(name) or reserved:
                raise SyncError(f"item {folder}: bad file name {name!r}")
            if Path(name).suffix.lower() not in orders.PRODUCT_FILES:
                raise SyncError(f"item {folder}: {name} isn't one of "
                                f"{', '.join(s[1:] for s in orders.PRODUCT_FILES)}")
            if not (path / name).is_file():
                raise SyncError(f"item {folder}: its file {name} wasn't in the download")

    def _convert_document(self, folder, job, path):
        """A document item: a non-PDF file becomes document.pdf (the original stays next to it)."""
        file = job.get("file")
        if not orders._plain_name(file) or not (path / file).is_file():
            raise SyncError(f"item {folder}: its file {file!r} wasn't in the download")
        if Path(file).suffix.lower() != ".pdf":
            if file.lower() == "document.pdf":
                raise SyncError(f"item {folder}: bad file name {file!r}")
            try:
                with jobs.PDF_LOCK:
                    convert.to_pdf(path / file, path / "document.pdf", job.get("paper", "A4"))
            except Exception as e:
                why = str(e)
                if "Invalid class string" in why:  # Windows' answer when Word / Excel / PowerPoint isn't there
                    why = f"can't convert {file}: Microsoft Office isn't installed on this PC"
                raise SyncError(f"item {folder}: {why}") from e
            job["file"] = "document.pdf"  # the original stays next to it

    # ------------------------------------------------------------ network

    def _check_url(self, url, website):
        """Only https (or http on this PC, for testing); the token only ever goes to the website."""
        parts = urllib.parse.urlsplit(url or "")
        local = parts.hostname in ("localhost", "127.0.0.1")
        if parts.scheme != "https" and not (parts.scheme == "http" and local):
            raise SyncError("not an https address" if website else "a file link isn't https")
        return url

    def _json(self, method, path, token, body=None):
        url = self._check_url(self.url + path, True)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "PrintRouter")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise SyncError({401: "wrong or missing token (401)", 404: "not found (404)"}.get(
                e.code, f"the website answered {e.code}"), e.code) from None
        except urllib.error.URLError as e:
            raise SyncError(f"no connection: {getattr(e, 'reason', e)}") from None
        except (TimeoutError, OSError) as e:
            raise SyncError(f"no connection: {e}") from None
        try:
            return json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            raise SyncError("the website's answer isn't JSON") from None

    def _fetch(self, url, dest):
        """Download a signed file link (no token sent: the link itself is the permission)."""
        self._check_url(url, False)
        req = urllib.request.Request(url, headers={"User-Agent": "PrintRouter"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(dest, "wb") as out:
                shutil.copyfileobj(r, out, CHUNK)
        except urllib.error.HTTPError as e:
            raise SyncError(f"{dest.name}: download answered {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SyncError(f"{dest.name}: download failed ({getattr(e, 'reason', e)})") from None

    # ------------------------------------------------------------ Ready for courier -> website

    def _load_outbox(self):
        try:
            data = json.loads(self.outbox_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            self.log("-", f"can't read {OUTBOX_FILE}: {e}")
            return []
        if not isinstance(data, list):
            return []
        return [m for m in data if isinstance(m, dict) and isinstance(m.get("order"), str)
                and m.get("status") == "ready"]

    def _save_outbox(self):
        """Write the outbox atomically (temp file + rename). Call with self.lock held."""
        tmp = self.outbox_path.with_name(f".{OUTBOX_FILE}.tmp")
        try:
            tmp.write_text(json.dumps(self.outbox, indent=1) + "\n", encoding="utf-8")
            os.replace(tmp, self.outbox_path)
        except OSError as e:
            self.log("-", f"can't write {OUTBOX_FILE}: {e}")

    def report_ready(self, number):
        """Staff pressed Ready for courier: queue the message for the website and send it now."""
        if not self.token_path.is_file():
            self.log(number, "ready: not reported, website sync is off")
            return
        with self.lock:
            if not any(m["order"] == number for m in self.outbox):
                self.outbox.append({"order": number, "status": "ready",
                                    "queued_at": _now().isoformat(timespec="seconds"), "tries": 0})
                self._save_outbox()
        self.log(number, "ready: queued for the website")
        threading.Thread(target=self.send_outbox, daemon=True).start()

    def send_outbox(self, token=None):
        """Send every queued message once. 200: done. 409 / 404: dropped and shown in red.
        Anything else (401, 500, no connection): kept for the next check."""
        token = token or self.token()
        if token is None:
            return
        with self.sending:
            with self.lock:
                waiting = [dict(m) for m in self.outbox]
            for msg in waiting:
                number = msg["order"]
                drop, note = False, None
                try:
                    self._json("POST", "/api/printrouter/orders/status", token,
                               {"order": number, "status": "ready"})
                    drop = True
                    self.log(number, "reported ready to the website")
                except SyncError as e:
                    if e.code in (409, 404):
                        drop = True
                        why = "cancelled" if e.code == 409 else "unknown order"
                        note = f"{number}: website says {why}"
                        self.log(number, f"not reported ready: website says {why} ({e.code})")
                    else:
                        self.log(number, f"report ready failed (try {int(msg.get('tries', 0)) + 1}): {e}")
                with self.lock:
                    for m in self.outbox:
                        if m["order"] == number:
                            if drop:
                                self.outbox.remove(m)
                            else:
                                m["tries"] = int(m.get("tries", 0)) + 1
                            break
                    if note:
                        self.notices.append(note)
                    self._save_outbox()

    def clear_notices(self):
        with self.lock:
            self.notices.clear()

    # ------------------------------------------------------------ tidy, log, status

    def _clean_leftovers(self):
        """Half-downloaded orders from a crash or a closed app: removed, they come again complete."""
        try:
            for p in self.pending.glob(".*.downloading"):
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass

    def log(self, number, text):
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{_now():%Y-%m-%d %H:%M:%S}  {number}  {text}\n")
        except OSError:
            pass  # the log must never stop the sync

    def status(self):
        """(text, red) for the PrintHub top bar, plus lines for orders that keep failing (shown in red)."""
        with self.lock:
            if not self.on:
                return "Website sync: off (no printhub_token.txt)", False, []
            stuck = [f"{n} can't be downloaded: {why}" for n, (tries, why) in sorted(self.failures.items())
                     if tries >= RED_AFTER] + self.notices
            waiting = f", {len(self.outbox)} waiting to report" if self.outbox else ""
            if self.last_check is None:
                return "Website: checking…" + waiting, False, stuck
            if self.error:
                ok = f"{self.last_ok:%H:%M}" if self.last_ok else "never"
                return f"Website: can't connect ({self.error}), last OK {ok}" + waiting, True, stuck
            return f"Website: checked {self.last_check:%H:%M}, {self.new} new" + waiting, False, stuck
