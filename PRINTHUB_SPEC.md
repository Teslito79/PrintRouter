# PrintHub for PrintRouter: specification

Status: draft, 2026-11-03. No code has been changed yet.

## 1. Design (as given)

- Customers upload files on the PrintHub website and pay. After payment, the order is downloaded to the shop PC into `orders/<order number>/`, with one subfolder per document. Each document subfolder holds the file (PDF) and a `job.json` with its print settings. Each order has an `order.json` with the order number, delivery method and the ordered list of steps (for example PRINT, LAMINATE, SPIRAL, CUTTING).
- A new **PrintHub** button at the top of the current interface opens the PrintHub view. The existing interface stays unchanged. The PrintHub view must reuse the existing conversion, routing and printing code, not copy it.
- Jobs are routed to the 3 copiers by the existing routing rules, giving one queue per printer. Printers run in parallel. On one printer only one order prints at a time; jobs from different orders are never mixed.
- **Start printing orders** sends the first order of each printer queue. When it finishes, the app shows a button for that order's next step, e.g. **Start Spiral Process**. Pressing it means the pages were removed, which frees the printer to start its next order. Later steps work the same way until the order is marked ready for courier.
- A second full-screen window, for the monitor at the printers, shows each order number and its next step, read-only.
- Nothing prints automatically on arrival; printing always needs a button press.
- Website sync (downloading paid orders) is the **last** stage. Until then, orders are fake sample folders.

### Stages
1. Order format and sample orders
2. PrintHub view on sample orders
3. Printer queues, grouping and step buttons
4. Second screen
5. Website sync

### Safety rules
Never change printer drivers, ports, preferences or the default printer. Don't install anything without asking. Don't edit files that weren't asked to be changed.

---

## 2. (a) What the app supports today

### 2.1 Per-job settings

Each file in the list has its own copy of these (`OPTIONS` in `app.py`). Defaults come from `rules.json` → `defaults`.

| Setting | Internal key | Allowed values | Default |
|---|---|---|---|
| Colour | `color` | `bw` (black & white), `color`, `auto` (each page as it is: colour pages in colour, the rest B&W, switched page by page; priced per page) | `bw` |
| Printer | `printer` | `auto` (routing rules), `C4510`, `C3000`, `C3004` | `auto` |
| Sides | `sides` | `single`, `long` (double, flip on long edge), `short` (double, flip on short edge) | `single` |
| Paper size | `paper` | `A4`, `A3`, `A5` (A5 is printed 2-up on A4 for cutting, same page twice: `a5_layout: same_page_twice`) | `A4` |
| Pages per side | `per_side` | `1`, `2`, `4`, `6`, `8`, `9`, `16` | `1` |
| Paper type | `paper_type` | Exact driver names: `Plain & Recycled`, `Plain 1 (60 to 74 g/m2)`, `Plain 2 (75 to 81 g/m2)`, `Recycled`, `Thin (52 to 59 g/m2)`, `Middle Thick (82 to 105 g/m2)`, `Thick 1(106 to 169 g/m2)`, `Thick 2(170 to 220 g/m2)`, `Thick 3(221 to 256 g/m2)`, `Thick 4(257 to 300 g/m2)`, `Cardstock`, `Coated (Glossy)`, `Coated (Matte)`, `Labels`, `Envelope`, `Bond`, `Color`, `Letterhead`, `Preprinted`, `Special 1`, `Special 2`, `Special 3` | `Plain & Recycled` |
| Tray | `tray` | `Auto Tray Select`, `Tray 1`, `Tray 2`, `Tray 3`, `Tray 4`, `Bypass Tray`, `Large Capacity Tray` | `Auto Tray Select` |
| Copies | `copies` | 1 to 999 | 1 |
| Rotate sort | `rotate` | on / off. Manual only, A4 only, Tray must be `Auto Tray Select`; forces the C4510 and sends each copy as its own job, alternating Tray 1 / Tray 4 (continues across the files in one run) | off |

Per print run (not per file):

| Setting | Allowed values | Default |
|---|---|---|
| Receipt | `one_for_all`, `one_per_file`, `counter` (add to running tab in `counter.json`), `none` | `one_for_all` |

Hidden, decided by the app:
- **Content** (`document` / `pictures`): only for colour jobs with Printer = Auto. Average colour coverage ≥ `picture_threshold_percent` (15%) counts as pictures.
- **Confirm above** `confirm_above_sheets` (100): a print run using more sheets asks for confirmation.

### 2.2 Combinations the app blocks

A file can't print (shown in red, no price) when:
- A5 is combined with pages per side > 1.
- Rotate sort is on and the printer isn't C4510, the paper isn't A4, or the tray isn't `Auto Tray Select`.
- The printer's driver doesn't offer the paper type or the tray (read from the driver: C4510 has Tray 1-4 + Bypass; C3000 and C3004 have Tray 1-2 + Bypass; C3000 goes up to Thick 3).
- The driver would quietly drop a setting for that combination (`driverprint.refused_settings`), e.g. double-sided on Thick 4, Coated, Labels or Envelope; colour/B&W; size; paper type; tray.
- Copies are not a whole number from 1 to 999.

### 2.3 Routing rules (Printer = Auto)

The first matching rule wins (`rules.json` → `rules`):

1. Paper type `Thick 4` → **C4510** (C3000 takes up to Thick 3)
2. Black & white → **C4510**
3. Colour **document** on `Plain & Recycled`, `Plain 1`, `Plain 2`, `Recycled` or `Thin` → **C3004**
4. Colour **pictures** → **C3000**
5. Colour on any other paper → **C3000**

If nothing matches, the job goes to the fallback, **C4510**. Rotate sort always goes to C4510. A Colour = Auto job that has at least one colour page counts as colour for routing. A file with the printer picked by hand skips the rules.

### 2.4 Pricing (placeholders)

Per printed side per copy (B&W vs. colour, by A4 / A3 / A5), plus a per-sheet extra for special paper (`prices.json`). With pages per side > 1, each printed side counts as one page. Colour = Auto prices each side as colour or B&W.

---

## 3. (b) Proposed file formats

Everything lives in `orders/` next to the app (a new `orders_folder` key in `rules.json`), **not** inside `Inbox/`, because the Inbox watcher would pick up the PDFs. `orders/` goes into `.gitignore`, because the work PC updates itself with `git pull`. Sample orders are kept in a tracked `sample_orders/` folder and copied into `orders/` for testing.

```
orders/
  PH-10231/
    order.json          written by the website (last, as the "complete" marker)
    status.json         written by PrintRouter only (progress)
    01/
      job.json
      document.pdf
    02/
      job.json
      document.pdf
```

### 3.1 order.json (from the website, read-only for the app)

```json
{
  "format": 1,
  "order": "PH-10231",
  "paid_at": "2026-11-03T14:05:00+02:00",
  "delivery": "courier",
  "steps": ["PRINT", "SPIRAL", "CUTTING"],
  "documents": ["01", "02"],
  "note": "Spiral on the left edge"
}
```

| Field | Values |
|---|---|
| `format` | `1`. Lets the app refuse orders written in a format it doesn't know |
| `order` | Order number; must equal the folder name |
| `paid_at` | ISO 8601 time. Queues are ordered by this (oldest first) |
| `delivery` | `courier` or `pickup` (sets the last step: "Ready for courier" / "Ready for pickup") |
| `steps` | Ordered list from: `PRINT`, `LAMINATE`, `SPIRAL`, `CUTTING` (more can be added). `PRINT` must be first. The final "Ready" step is implied, not listed. Steps apply to the whole order |
| `documents` | Subfolder names in print order |
| `note` | Optional free text shown to staff |

Prices are not in the order files. The website is the price authority; the app doesn't compare or charge.

Customer name, address and phone stay **out** of these files. The courier label comes from the website; the PC only needs the order number.

### 3.2 job.json (one per document, from the website, read-only for the app)

Built from the settings in 2.1, using the same keys and values the app already uses internally, so the existing code can read it as is:

```json
{
  "format": 1,
  "file": "document.pdf",
  "title": "Thesis final.pdf",
  "pages": 84,
  "copies": 2,
  "color": "auto",
  "sides": "long",
  "paper": "A4",
  "per_side": 1,
  "paper_type": "Plain & Recycled"
}
```

| Field | Allowed values | Notes |
|---|---|---|
| `file` | file name in the same folder | PDF only |
| `title` | text | The customer's original file name, shown in the list and the logs |
| `pages` | ≥ 1 | Page count the website charged for; the app counts again and flags a mismatch |
| `copies` | 1 to 999 | |
| `color` | `bw`, `color`, `auto` | |
| `sides` | `single`, `long`, `short` | |
| `paper` | `A4`, `A3`, `A5` | |
| `per_side` | `1`, `2`, `4`, `6`, `8`, `9`, `16` | Must be `1` with A5 |
| `paper_type` | the exact names in 2.1 | Website should offer only a shop-approved subset |

Deliberately **not** in job.json (the shop decides these):
- `printer`: always Auto. Staff can override it in the PrintHub view.
- `tray`: always `Auto Tray Select`. The copier picks the tray from the paper size and type sent with the job.
- `rotate`: walk-in only.
- Prices and receipts: the website charges; orders print no price receipt.

### 3.3 status.json (written by PrintRouter only)

Keeps progress across restarts, written atomically (temp file + rename, like `counter.json`). The website's files are never modified.

```json
{
  "step": 0,
  "parts": {
    "C4510": {"documents": ["01"], "state": "sent", "sent_at": "2026-11-03T15:10:02"},
    "C3004": {"documents": ["02"], "state": "waiting"}
  },
  "history": [{"time": "2026-11-03T15:09:58", "event": "print started"}]
}
```

Part states: `waiting` → `sending` → `sent` → `collected`. `step` is an index into `steps`; past the end means Ready.

---

## 4. Problems and decisions needed

### Decisions (made 2026-11-03)

1. **One order across several printers: split, collect per printer.** Routing works per document, so an order with B&W and colour documents is split across C4510, C3004 and/or C3000. Each printer's part gets its own **Pages collected** button, which frees that printer for its next order. The order's next-step button (e.g. **Start Spiral Process**) appears once **all** parts are collected.
2. **"Finished printing" = the staff press.** The app knows only when the job has been **handed to the Windows queue** (`EndDoc` in `driverprint.print_pdf`), not when the last sheet comes out. It shows "Sent" right away; **Pages collected** is the real "finished" signal. The print queue is not watched.
3. **Steps apply to the whole order.** They are listed once in `order.json`.
4. **Walk-in jobs: no change.** The normal window behaves exactly as today, even while a copier is printing an order. Staff keep walk-in pages apart from order stacks themselves.
5. **Tray: always `Auto Tray Select`.** The copier picks the tray from the paper size and type in the job. No tray map.
6. **Prices: ignored.** The website is the price authority; order files carry no prices and the app doesn't compare.
7. **Refactor of `app.py`: approved for stage 2.** The job logic (`job_for`, `rotate_problem`, `missing_options`, `refused`, `_print_one`, `_send`, `_log`) lives inside the Tk `App` class and depends on its `Item` objects. It moves into a new module (`jobs.py`) that both views call. The normal window must look and behave the same; this is checked after the move.

### Technical problems
8. **"Printers run in parallel".** The copiers print in parallel by themselves, because Windows spools each job. The app should still **send** one job at a time from one worker thread: pdfium (used to draw the pages and to analyse colour) is not safe to use from several threads at once. Sending is fast compared to printing, so this costs little.
9. **The website can't check the drivers.** Combinations the drivers refuse (double-sided on Thick 4, Coated, Labels or Envelope) must be ruled out on the website using the same lists. Proposal: the app writes a small `printhub_options.json` from `rules.json` and the driver checks, for the website to use. The app still checks every job on arrival and marks bad orders **Needs attention** instead of printing them.
10. **Paper-type names are driver strings** (`Thick 1(106 to 169 g/m2)`, with odd spacing). If a driver update renames one, website orders break. Acceptable for now; the arrival check (9) catches it.
11. **Half-downloaded orders.** Sync must download into a temporary folder and rename it into `orders/` when complete, with `order.json` written last. The app ignores folders without `order.json`. Sample orders follow the same rule.
12. **Crash during sending.** If the app closes while a part is `sending`, on restart it can't know what printed. It must ask the staff instead of resending, to avoid printing twice.
13. **Large orders.** `confirm_above_sheets` asks per print run today. For orders: ask once at **Start printing orders**, listing any order over the limit.
14. **PDF page sizes.** A PDF with A3 pages ordered as A4 is scaled down to fit. The website should warn the customer; the app shows the PDF's page size next to the ordered paper.
15. **Second screen.** Tkinter can't list monitors. Placing the window full-screen on the second monitor needs a small Windows call (`EnumDisplayMonitors` via ctypes, no install). If only one monitor is connected, it opens as a normal window.
16. **Logging.** Order jobs go to `print_log.csv` like today; the file name column starts with the order number (no new column, so old logs keep their layout).
17. **Verified queues only.** PrintHub uses the same three queues. Before going live, the order flow needs its own paper test (multi-document order, split across printers, A5, duplex).

---

## 5. Stage plan (refined)

1. **Order format and sample orders** (done 2026-11-03): `orders.py` reads and checks order folders (run `py -3.14 orders.py sample_orders` to list them). `sample_orders/` holds:
   - PH-1001: one B&W document, double-sided, 2 copies → C4510
   - PH-1002: split across all three copiers (B&W → C4510, colour document → C3004, photos on Coated → C3000), then SPIRAL
   - PH-1003: A5 flyer, Colour = Auto, Thick 1, 20 copies → C3000, then CUTTING
   - PH-1004: Thick 4 cover → C4510, plus a 2-per-side handout, then LAMINATE, CUTTING
   - PH-1005: bad order (A5 with 2 per side, unknown paper type, wrong page count) → Needs attention
   - PH-1006: no `order.json` (still downloading) → skipped

   Driver checks (refused combinations) need the copiers and run in stage 2, when jobs are routed.
2. **PrintHub view** (done 2026-11-03, driver checks still to be seen at work):
   - `jobs.py` holds the job logic moved out of `app.py` (routing, driver checks, settings text, laying out and sending, the log). Both windows use it. Checked: the old and new code give identical jobs and settings text for 279,936 setting combinations, and the moved print code differs only in its folder argument and the lock.
   - `jobs.PDF_LOCK`: all pdfium work (converting, analysing, layout, printing) runs under one lock, because pdfium is not thread-safe. On exit, the app waits for PDF work in progress, because Python crashed (0xC0000409) when it closed during an analysis.
   - `printhub.py`: the **PrintHub** button (top right of the main window) opens the PrintHub window. It lists the orders oldest first, each document with its settings, the copier Auto picks and any problem, plus the order's note, problems and sheets per copier. It reloads by itself when order folders appear or change. **Add sample orders** copies `sample_orders/` into `orders/` (under a hidden name, then renamed). No printing yet.
3. **Queues and step buttons** (done 2026-11-03, tested with simulated copiers only):
   - One panel per copier: the order it is on (sending n of m / sent / NOT sent / interrupted), its button, and the orders waiting for it. A copier's queue holds the orders that have a part for it, oldest payment first; Needs-attention orders are left out.
   - **Sending only happens on a button press.** **Start printing orders** sends the next order to every free copier and turns printing ON. While ON, **Pages collected** frees that copier and sends its next order. **Stop after current orders** turns it OFF. Orders that arrive are never sent by themselves, even while ON; press Start printing orders again.
   - When an order starts, where each of its documents goes is fixed in `status.json`, so a change to `rules.json` can't move half an order.
   - Parts are sent one at a time by one thread (the copiers still print at the same time). The document name in the Windows queue and in `print_log.csv` starts with the order number and document folder (e.g. `PH-1002 01 Report text.pdf`).
   - Failed send → **Retry**. App closed mid-send → on restart the part shows "interrupted" with **Everything printed** / **Send the rest again** (sends only the documents not recorded as sent). An unreadable `status.json` makes the order Needs attention rather than printing it again.
   - **Next steps** lists orders whose parts are all collected, with the button for the next step (**Start Spiral Process**, …, **Ready for courier / pickup**).
   - Closing the PrintHub window only hides it; closing the app while orders are being sent asks first. `confirm_above_sheets` asks before an order part over the limit is sent.
4. **Second screen**: read-only full-screen window, refreshed from the same state.
5. **Website sync**: download paid orders into `orders/` safely (11), plus `printhub_options.json` (9).
