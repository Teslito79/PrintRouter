# PrintRouter: brief for Claude Code

Last updated 2026-11-04. Read this first. Details live in `PRINTHUB_SPEC.md` (PrintHub order flow) and `PROJECT_SUMMARY.txt` (printers, files, routing; written before PrintHub, otherwise still accurate).

## Owner and how to work with him

Christos (Tesla), runs a copy centre in Cyprus and the online shop PrintHub. Learns hands-on, not a programmer.
- Direct, short, no fluff, English. Give ONE best option with the reason.
- Every time you ask for permission (install, commit, push, run something that changes things), add one or two plain sentences on what it does, written for someone who doesn't code.
- Never ask him to paste passwords, keys or tokens into chat.
- Commit and push only when he asks.

## Computers

- **Home PC:** `C:\PrintHub\PrintRouter\ADMIN` (this repo) next to `C:\PrintHub\Website` (the shop website, a separate repo and a separate Claude chat). No copiers here: Print gives an error and driver checks are missing. Good for code, window and logic work.
- **Work PC** (192.168.10.4, Windows 11, non-technical staff): `C:\PrintRouter\ADMIN` only, no website. Paper tests happen here.
- **ADMIN folder (owner, 2026-11-05):** on both PCs the whole repo (with `.git`, the order folders, Inbox, logs) lives in `ADMIN\`; the top folder holds only `PrintRouter.lnk`, a shortcut to `ADMIN\PrintRouter.bat`. Made by `Move into ADMIN folder.bat` (+ `tools\move_into_admin.ps1`), which also repoints old desktop / Start menu shortcuts. Nothing in the code or the .bat files uses a fixed path (`routing.app_dir()`, `%~dp0`). Open Claude chats for PrintRouter in the ADMIN folder, so this file is read.
- Sync: GitHub `Teslito79/PrintRouter` (private). `Upload changes.bat` (add, commit, push) and `Download changes.bat` (pull). `PrintRouter.bat` runs `git pull --ff-only` before starting, so the work PC updates itself on launch. `Pending Orders/`, `Orders/` and `Finished Orders/` are gitignored.

## Handoffs from the planning window

Changes for PrintRouter arrive as written handoff files from a separate planning window (`C:\PrintHub\Planning`), one `.md` per change, named `YYYY-MM-DD_NN_short-name.md`. They live in `C:\PrintHub\handoffs\app\` (from this repo: `..\..\handoffs\app\`), on the home PC only and outside this repo: never commit them or copy them into it.
- On the home PC, at the start of a session, list `..\..\handoffs\app\` (not `done\`) and tell Tesla which handoffs are waiting, oldest first. On the work PC there are none; skip this.
- Implement a handoff only when Tesla says to start it. Follow its Requirements and Out of scope exactly; if something in it is unclear or conflicts with this CLAUDE.md, PRINTHUB_SPEC.md or the code, ask Tesla instead of guessing.
- Before marking a handoff done, check every item in its "Acceptance criteria".
- When done, move the file to `..\..\handoffs\app\done\` and tell Tesla in one line, so he can tell the planning window.
- `C:\PrintHub\PROJECT_LOG.md` lists decisions already made; read it when a handoff refers to it. Don't edit it.

## What it is

Windows desktop app, Python 3.14 + Tkinter, about 3,500 lines. Staff add files (or they arrive in `Inbox\`); the app converts to PDF, picks a Ricoh copier by rules (or by hand), sends with per-job driver settings through `driverprint.py` (PrintTicket to DEVMODE, pdfium drawing via ctypes, nothing saved to printer defaults) and prints a price receipt on the XP-80C thermal printer.

Copiers: C4510 (downstairs, Tray 1-4 + Bypass, Thick 4), C3000 (colour pictures, up to Thick 3), C3004 (colour documents). **All print A3 at most, no SRA3.** Routing rules, paper types and trays: `rules.json`. Placeholder prices: `prices.json`.

Safety rules (always):
- Never change printer drivers, ports, preferences or the default printer.
- Don't install or uninstall anything, or change system settings, without asking first.
- Send print jobs only through normal print queue submission. Only route to queues verified on paper.
- Don't edit files he didn't ask to change. Read-only checks are fine.
- pdfium is not thread-safe: all PDF work runs under `jobs.PDF_LOCK`; on exit the app waits for it (closing mid-analysis crashed Python 0xC0000409).

## PrintHub (orders from the website)

Plan and file formats: `PRINTHUB_SPEC.md`. Stages:
1. Order format and sample orders: **done** (`orders.py`, `sample_orders/` PH-1001..1006).
2. PrintHub view: **done** (`printhub.py`, job logic shared in `jobs.py`).
3. Copier queues, sending, Pages collected, next-step buttons: **done**, tested with simulated copiers only (commit ba30e49).
4. Second screen (read-only, full screen on the printer monitor): not started.
5. a. Product items (CorelDRAW layout, `print.pdf`, Layout done, actual-size printing): **done**, tested with simulated copiers only. Samples PH-1007..1011. Folders (owner, 2026-11-04): `Pending Orders/` receives orders (one folder per order number; each item holds the customer's files as uploaded, `Options.txt` and a blank CorelDRAW file from `templates/blank.cdr`, named after the order: `PH-10240.cdr`, or `PH-10240-01.cdr`, `-02` with several products; the matching exported `PH-10240.pdf` is what prints; old `print.cdr` / `print.pdf` still accepted); when all products are laid out (documents-only orders at once) the folder moves to `Orders/`, the only place that prints; when Ready it moves to `Finished Orders/`. The owner still has to save `templates/blank.cdr` from CorelDRAW. b. Website sync: not started. See below and `PRINTHUB_SPEC.md` 3.4 / stage 5.

**Pending first:** the paper test of stages 1-3 at work, using `WORK_TEST_CHECKLIST.txt` (on GitHub since 2026-11-05). Wait for his results before stage 4. Paper test of product printing at actual size (print `sample_orders/PH-1007/01/example_layout.pdf` and measure); `product_papers` in `rules.json` follows the owner's rule (2026-11-05): 80 gsm = Plain & Recycled, every other paper Thick 3 up to 256 gsm, Thick 4 from 257 to 300 gsm; stickers, labels, envelopes, board and 350/400 gsm are picked by hand. Open for the website: papers over 300 g/m2 (350 gsm, kraft 400 gsm) can't go through the copiers; no FOLDING step yet. Also still open from before PrintHub: paper tests of the driver path (duplex, B&W, copies, A3, A5 2-up, landscape, batches), Colour = Auto, Add to counter, Rotate sort; real prices last; PyInstaller packaging.

### Decisions for stage 5 (2026-11-04)

- **Documents** (the website's document calculator) keep the existing `job.json` and print automatically after the staff press Start printing orders, as built in stage 3.
- **Products** (business cards, flyers, invitations, menus, ... 65 products on the website, A3 and smaller) are laid out **by the owner by hand in CorelDRAW**, using his own templates (e.g. 8 business cards per A4 with cut marks). The app does no imposition. Flow to build:
  - A product order arrives with the customer's file(s) and shows as **Waiting for layout**.
  - **Open file** button opens the customer file (default PDF program / CorelDRAW).
  - He exports the laid-out sheet as `print.pdf` into the same order (document) folder; the customer original stays untouched beside it.
  - The app detects `print.pdf` and moves the order to **Ready to print**; it prints `print.pdf` exactly as is (actual size, no n-up, no scaling).
  - Sheet count: typed by him, or worked out from cards per sheet (250 cards, 8 per sheet = 32 sheets).
- Quality: never rasterise a customer PDF on the way to the printer beyond what the existing driver path does; place and print it as is.
- Wrong-sized files (e.g. 95 x 60 mm for an 85 x 55 card) are fixed by him in CorelDRAW during layout; the website should also warn customers at upload (website's job).
- The website side still has to provide the paid orders: an authenticated way for this app to fetch them (e.g. an API route with a secret, returning paid orders and signed file links), download into a temp folder and rename into `orders/` with `order.json` written last (spec item 11). The product part of `job.json` is proposed in `PRINTHUB_SPEC.md` 3.4 and still has to be agreed with the Website chat; keep the formats in `PRINTHUB_SPEC.md` and the website's CLAUDE.md in step.
