# PrintRouter: brief for Claude Code

Last updated 2026-11-04. Read this first. Details live in `PRINTHUB_SPEC.md` (PrintHub order flow) and `PROJECT_SUMMARY.txt` (printers, files, routing; written before PrintHub, otherwise still accurate).

## Owner and how to work with him

Christos (Tesla), runs a copy centre in Cyprus and the online shop PrintHub. Learns hands-on, not a programmer.
- Direct, short, no fluff, English. Give ONE best option with the reason.
- Whenever you report something that changes things (a commit, a push, a moved file), add one or two plain sentences on what it does, written for someone who doesn't code.
- Never ask him to paste passwords, keys or tokens into chat.
- Commit and push only as a handoff's "Commit and push" line says (see "Handoffs from the planning window"); otherwise commit nothing.

## Work PC chat

Decided with Tesla, 2026-11-06. Work notes from the planning window go through this repo's `work\` folder (`work\README.txt`).
- **Which chat are you?** If this repo is at `C:\PrintRouter\ADMIN` (the work PC), you are the **Work PC chat**: follow this section; the section "Handoffs from the planning window" does not apply to you. If it is at `C:\PrintHub\PrintRouter\ADMIN` (home PC), you are the **App window**: ignore the `work` folder completely (don't edit, move or delete anything in it; the planning window and the Work PC chat own it).
- **At the start of a session:** list `work\notes\` (not `done`) and tell Tesla in one line which notes are waiting. When Tesla says "go", do the oldest note.
- **Working with Tesla:** guide him through the note one step at a time, live. Here you **may ask Tesla** what he sees or what came out of the printer, and wait for his answer (the "Never ask Tesla anything" rule is for the App window only). Keep instructions short and plain; he is not a programmer. You may check things on this PC yourself: files, folders, `sync_log.txt`, the print queue, the list of printers, PDFs.
- **Never change code or settings:** no edits to `.py`, `.json`, `.bat`, `CLAUDE.md`, `PRINTHUB_SPEC.md` or `templates`. Bugs and wished-for changes go into the report for the planning window. All the printer safety rules in this file apply in full (never change drivers, ports, preferences or the default printer; print only through the normal print queue). Don't install anything or change system settings: if something needs that, write it in the report.
- **Secrets:** never read aloud, print, log or upload `printhub_token.txt`. Code may read it to make a request the note asks for; show only the answer.
- **Order folders** (Pending Orders, Orders, Finished Orders): delete only what Tesla confirms.
- **Report:** when the note is done (fully or not), write `work\reports\<note name>_report.md` in the format the note gives (or: Status, what was done, problems with exact error texts, questions for the planning window). Put any screenshots or test PDFs in `work\reports\` too. Move the note to `work\done\`.
- **Upload, only the work folder:** run `git pull --ff-only`, then `git add work`, `git commit -m "Work PC report: <note name>"`, then `git push`. Never `git add -A`, never add any other path, never use `Upload changes.bat`. If the pull or push fails, don't force anything: tell Tesla the report is saved on the work PC and write the error in the report.
- **The planning window (home PC)** commits only `work\notes\` and `work\files\`.

## Computers

- **Home PC:** `C:\PrintHub\PrintRouter\ADMIN` (this repo) next to `C:\PrintHub\Website` (the shop website, a separate repo and a separate Claude chat). No copiers here: Print gives an error and driver checks are missing. Good for code, window and logic work.
- **Work PC** (192.168.10.4, Windows 11, non-technical staff): `C:\PrintRouter\ADMIN` only, no website. Paper tests happen here.
- **ADMIN folder (owner, 2026-11-05):** on both PCs the whole repo (with `.git`, the order folders, Inbox, logs) lives in `ADMIN\`; the top folder holds only `PrintRouter.lnk`, a shortcut to `ADMIN\PrintRouter.bat`. Made by `Move into ADMIN folder.bat` (+ `tools\move_into_admin.ps1`), which also repoints old desktop / Start menu shortcuts. Nothing in the code or the .bat files uses a fixed path (`routing.app_dir()`, `%~dp0`). Open Claude chats for PrintRouter in the ADMIN folder, so this file is read.
- Sync: GitHub `Teslito79/PrintRouter` (private). `Upload changes.bat` (add, commit, push) and `Download changes.bat` (pull). `PrintRouter.bat` runs `git pull --ff-only` before starting, so the work PC updates itself on launch. `Pending Orders/`, `Orders/` and `Finished Orders/` are gitignored.

## Handoffs from the planning window

Changes for PrintRouter arrive as written handoff files from a separate planning window (`C:\PrintHub\Planning`), one `.md` per change, named `YYYY-MM-DD_NN_short-name.md`. They live in `C:\PrintHub\handoffs\app\` (from this repo: `..\..\handoffs\app\`), on the home PC only and outside this repo: never commit them or copy them into it. Decisions are made in the planning window only (Tesla, 2026-11-05).
- On the home PC, at the start of a session, list `..\..\handoffs\app\` (not `done\` or `reports\`) and tell Tesla in one line which handoffs are waiting. Start one when Tesla says so. On the work PC there are none.
- **Never ask Tesla anything:** no questions, no permission requests, no option menus, no "shall I commit / push?". This overrides any older line in this file about asking before installing, committing or pushing. The safety rules about printer drivers, ports, preferences and the default printer still apply in full: never change them.
- Follow a handoff's Requirements and Out of scope exactly, and check every item in its "Acceptance criteria" before calling it done. If a handoff is unclear, conflicts with this file, `PRINTHUB_SPEC.md` or the code, or something blocks it (a needed install, a missing file, a test that needs the work PC), don't guess and don't ask: stop that part, finish what can safely be finished, and describe it in the report.
- **Commit and push** only as the handoff says (its "Commit and push" line). If the handoff says nothing, commit nothing. The work PC pulls on every app start.
- Never ask for or handle secrets. **Manual steps are discussed with the planning window, not here.** Steps only Tesla can do (creating `printhub_token.txt` or any password, editing files by hand, paper tests at work) go only in the report under "Steps for Tesla", one numbered step each, with exact file names and places. Don't walk Tesla through them in this chat and don't tell him to do them here. The planning window goes through them with him. If he does a step anyway and reports back, just carry on.
- When finished (fully or not), write a report to `..\..\handoffs\app\reports\`, named like the handoff with `_report` added (e.g. `2026-11-05_05_download-website-orders_report.md`), in the format below. Then move the handoff to `..\..\handoffs\app\done\` only if its status is Done. Tell Tesla in one line: "Report written: <file name>".
- Report format:
  ```
  # Report: <handoff file name>
  Status: Done | Partly done | Not done
  ## What changed
  Plain words, a few lines. Files and commit, if any.
  ## Problems
  What went wrong or was skipped, and why. "None" if none.
  ## Steps for Tesla
  Numbered. "None" if none.
  ## Questions for the planning window
  Anything unclear that stopped work. "None" if none.
  ```
- `C:\PrintHub\PROJECT_LOG.md` lists decisions already made; read it when a handoff refers to it. Don't edit it.

## What it is

Windows desktop app, Python 3.14 + Tkinter, about 3,500 lines. Staff add files (or they arrive in `Inbox\`); the app converts to PDF, picks a Ricoh copier by rules (or by hand), sends with per-job driver settings through `driverprint.py` (PrintTicket to DEVMODE, pdfium drawing via ctypes, nothing saved to printer defaults) and prints a price receipt on the XP-80C thermal printer.

CorelDRAW templates (2026-11-06): `templates/<W>x<H>.cdr` per product size in mm; `printhub.choose_template` picks `<product id>.cdr`, then `cut_mm` WxH, then HxW, then `blank.cdr`, and Options.txt / the details show which. Size table: `PRINTHUB_SPEC.md` 3.4. Layout done fills in pieces per sheet from `rules.json` `pieces_per_sheet` (size WxH/HxW, A4/A3; Tesla, 2026-11-12), never over a saved value; `Options.txt` names them.

Look: always dark (handoff 17, 2026-11-05). Colours, the ttk style (base theme `clam`) and dark title bars are all in `theme.py`; use its constants, never hex colours in other files. Message boxes stay light (drawn by Windows).

Copiers: C4510 (Tray 1-4 + Bypass, up to 350 gsm), C3000 (colour first, up to 300 gsm; busy -> colour to the C4510), C3004 (colour documents on plain paper). Paper that isn't plain always prints from the Bypass Tray; both sides on it at 200 gsm or more (Thick 2 and heavier when only the driver type is known) is turned by hand, in PrintHub and the main window (Tesla, 2026-11-13; `PRINTHUB_SPEC.md` 2.3). **All print A3 at most, no SRA3.** Routing rules, paper types and trays: `rules.json`. Placeholder prices: `prices.json`.

There are no sample orders. To test, make temporary order folders in a temp folder (or a hidden `.test-…` folder) and delete them afterwards; never leave test orders in Pending Orders / Orders / Finished Orders.

Safety rules (always):
- Never change printer drivers, ports, preferences or the default printer.
- Don't install or uninstall anything, or change system settings. If a handoff needs that, stop that part and describe it in the report.
- Send print jobs only through normal print queue submission. Only route to queues verified on paper.
- Don't edit files he didn't ask to change. Read-only checks are fine.
- pdfium is not thread-safe: all PDF work runs under `jobs.PDF_LOCK`; on exit the app waits for it (closing mid-analysis crashed Python 0xC0000409).

## PrintHub (orders from the website)

Plan and file formats: `PRINTHUB_SPEC.md`. Stages:
1. Order format: **done** (`orders.py`). Sample orders (PH-1001..1015) were used during stages 1-5 and removed on 2026-11-05; real orders come from the website sync.
2. PrintHub view: **done** (`printhub.py`, job logic shared in `jobs.py`).
3. Copier queues, sending, Pages collected, next-step buttons: **done**, tested with simulated copiers only (commit ba30e49).
4. Second screen (read-only, full screen on the printer monitor): not started.
5. a. Product items (CorelDRAW layout, `print.pdf`, Layout done, actual-size printing): **done**, tested with simulated copiers only (on sample orders, removed 2026-11-05). Folders (owner, 2026-11-04): `Pending Orders/` receives orders (one folder per order number; each item holds the customer's files as uploaded, `Options.txt` and a blank CorelDRAW file from `templates/blank.cdr`, named after the order: `PH-10240.cdr`, or `PH-10240-01.cdr`, `-02` with several products; the matching exported `PH-10240.pdf` is what prints; old `print.cdr` / `print.pdf` still accepted); when all products are laid out (documents-only orders at once) the folder moves to `Orders/`, the only place that prints; when Ready it moves to `Finished Orders/`. Each folder there goes to the Recycle Bin 8 days (192 h) after Ready for courier (`finished.txt` written by `move_finished`, `cleanup.py` at start and hourly, `cleanup_log.txt`; `PRINTHUB_SPEC.md` 3.4b). The owner still has to save `templates/blank.cdr` from CorelDRAW. b. Website sync (`sync.py`, handoff 05): built 2026-11-05, tested against a pretend website only; the live test waits for the website's order feed (handoff `website/04`). It runs only where `printhub_token.txt` sits next to `app.py` (gitignored; Tesla creates it on the work PC himself, same value as Vercel's `PRINTROUTER_TOKEN`; never on the home PC except for a test, then delete it). Never read, print or log the token. `sync_log.txt` is gitignored. Ready for courier is reported to the website (POST `/api/printrouter/orders/status`, `sync_outbox.json` gitignored, retried at every check until 200 / 409 / 404; handoff 2026-11-06_03). New job fields `pages_verified`, `color_pages`, `finish`, `laminate_sheets`, order field `courier`, step `STAPLE`. The sync also accepts product items (`kind: product`): files downloaded as uploaded, never converted (handoff 2026-11-12_02). See below and `PRINTHUB_SPEC.md` 3.4 / stage 5.

**Pending first:** the paper test of stages 1-3 at work, using `WORK_TEST_CHECKLIST.txt` (on GitHub since 2026-11-05). Wait for his results before stage 4. Paper test of product printing at actual size: done 2026-11-05 with a sample order (since removed), 100 mm exact; `product_papers` in `rules.json` follows the owner's rule (2026-11-05): 80 gsm = Plain & Recycled, every other paper Thick 3 up to 256 gsm, Thick 4 from 257 to 300 gsm; Smooth white 350 is Thick 4 too, C4510 only (Kraft 400 no longer sold); since 2026-11-13 every non-plain paper goes to the Bypass Tray and Both sides at 200 gsm or more becomes Layout done sides `hand` ("Both sides, turned by hand": fronts = page 1 sent first, the part waits in state `turn` with a **Print backs** button, then backs = page 2; never resends fronts after a restart). The paper test for it (does the back come out the right way up?) happens with the first real product order (Tesla, 2026-11-05). Stickers, labels, envelopes and board are picked by hand. Open for the website: no FOLDING step yet (nothing above 350 gsm is sold since 2026-11-12). Also still open from before PrintHub: paper tests of the driver path (duplex, B&W, copies, A3, A5 2-up, landscape, batches), Colour = Auto, Add to counter, Rotate sort; real prices last; PyInstaller packaging.

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
