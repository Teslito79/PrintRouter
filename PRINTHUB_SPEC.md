# PrintHub for PrintRouter: specification

Status: 2026-11-04. Stages 1-3 built (tested with simulated copiers only; paper test at work pending). Stage 5a (product items, 3.4) built, tested with simulated copiers only. Stage 5b (website sync) not started.

## 1. Design (as given)

- Customers upload files on the PrintHub website and pay. After payment, the order is downloaded to the shop PC into `Pending Orders/<order number>/`, with one subfolder per document. Each document subfolder holds the file (PDF) and a `job.json` with its print settings. Each order has an `order.json` with the order number, delivery method and the ordered list of steps (for example PRINT, LAMINATE, SPIRAL, CUTTING).
- A new **PrintHub** button at the top of the current interface opens the PrintHub view. The existing interface stays unchanged. The PrintHub view must reuse the existing conversion, routing and printing code, not copy it.
- Jobs are routed to the 3 copiers by the existing routing rules, giving one queue per printer. Printers run in parallel. On one printer only one order prints at a time; jobs from different orders are never mixed.
- **Start printing orders** sends the first order of each printer queue. When it finishes, the app shows a button for that order's next step, e.g. **Start Spiral Process**. Pressing it means the pages were removed, which frees the printer to start its next order. Later steps work the same way until the order is marked ready for courier.
- A second full-screen window, for the monitor at the printers, shows each order number and its next step, read-only.
- Nothing prints automatically on arrival; printing always needs a button press.
- Website sync (downloading paid orders) is the **last** stage. Sample orders (PH-1001..1015) were used during stages 1-5 and removed on 2026-11-05; real orders come from the website sync.

### Stages
1. Order format
2. PrintHub view
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

Three folders next to the app (`pending_folder`, `orders_folder`, `finished_folder` in `rules.json`; owner's choice 2026-11-04), **not** inside `Inbox/`, because the Inbox watcher would pick up the PDFs. An order folder moves from one to the next; its `status.json` moves with it:
- **`Pending Orders/`** receives the orders from the website, one folder per order, named after the order number. Orders here are never printed. `Options.txt` and the blank CorelDRAW file (`PH-10240.cdr`) are put in here.
- **`Orders/`**: once every product item of an order has Layout done (and the order has no problems), the folder moves here by itself. An order with documents only has nothing to lay out and moves at once. Only orders in here go to the copiers. If a file in the order is still open (e.g. `print.cdr` in CorelDRAW), the move waits; the app tries again every 3 seconds and shows "Laid out, but can't move to Orders: close its files".
- **`Finished Orders/`**: when the last step (**Ready for courier / pickup**) is pressed, the whole order folder is moved here, with its `status.json`, and leaves the PrintHub list. If a file in it is still open (CorelDRAW, a PDF viewer), the move fails, the order stays listed as Ready and **Move to Finished Orders** tries again. A number that is already there gets ` (2)`.

All three are in `.gitignore`, because the work PC updates itself with `git pull`. Sample orders (PH-1001..1015) were used during stages 1-5 and removed on 2026-11-05; real orders come from the website sync. An order number found in both Pending Orders and Orders is Needs attention. (An older lowercase `orders/` folder is renamed to `Orders` on start.)

```
Pending Orders/
  PH-10240/             arrived, waiting for layout
Orders/
  PH-10231/             laid out, printing
    order.json          written by the website (last, as the "complete" marker)
    status.json         written by PrintRouter only (progress)
    01/                 a document
      job.json
      document.pdf
      Options.txt       written by PrintRouter: the print settings in plain words
    02/                 a product
      job.json
      front.pdf, back.ai, ...  the customer's designs, in the format they uploaded, never changed
      Options.txt       written by PrintRouter: product, quantity, options, cut size, files and sizes
      PH-10231.cdr      blank CorelDRAW file copied by PrintRouter from templates/ (blank.cdr or <product>.cdr),
                        named after the order; PH-10231-01.cdr, PH-10231-02.cdr ... when the order has several products
      PH-10231.pdf      exported by the owner from PH-10231.cdr: the sheet that is printed
Finished Orders/
  PH-10198/             moved here when Ready
templates/
  blank.cdr             saved once by the owner from CorelDRAW (not in the repo until he adds it)
  bcard.cdr             optional per-product layout template, named after the product id
```

`Options.txt` and the CorelDRAW file are written once, when the order is first read in Pending Orders, and never overwritten (staff may write in `Options.txt`; the CorelDRAW file holds the layout). The CorelDRAW file is named after the order (owner, 2026-11-05), so CorelDRAW suggests the matching PDF name (`PH-10231.pdf`) on export; that PDF is the sheet that prints. A customer file may not use that name. Orders laid out earlier with `print.cdr` / `print.pdf` keep working; if both `PH-10231.pdf` and `print.pdf` are there, the item asks to delete one.

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
| `steps` | Ordered list from: `PRINT`, `LAMINATE`, `SPIRAL`, `CUTTING`, `STAPLE` (more can be added; `STAPLE` shows as **Start Stapling Process**). `PRINT` must be first. The final "Ready" step is implied, not listed. Steps apply to the whole order |
| `documents` | Subfolder names in print order |
| `note` | Optional free text shown to staff |
| `courier` | Optional: `boxnow` or `acs` (from the website; shown to staff as Box Now / ACS for packing) |

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
| `pages_verified` | optional `true` / `false` | `false`: the website couldn't count the pages (Word, Excel, old PowerPoint); a page-count mismatch then says to check with the customer |
| `color_pages` | optional text, e.g. `"1-3, 7"` | The customer's colour pages for `auto`; shown to staff only (the app still decides colour per page) |
| `finish` | optional `none`, `spiral`, `staple` | Shown to staff per document |
| `laminate_sheets` | optional whole number ≥ 0 | Sheets to laminate; shown to staff when > 0 |

These four website fields (handoff 05, 2026-11-05) never change routing or printing; a wrong value adds a problem like the other fields.

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

### 3.4 Product items (decided 2026-11-04)

Products (business cards, flyers, invitations, menus, ... 65 products, A3 and smaller) are laid out **by the owner by hand in CorelDRAW**. The app does no imposition. One order can mix document items (3.2) and product items. A product item is a document subfolder like any other, listed in `documents` in `order.json`, with this `job.json`:

```json
{
  "format": 1,
  "kind": "product",
  "product": "bcard",
  "name": "Business cards",
  "quantity": 250,
  "options": {
    "Size": "85 x 55 mm",
    "Paper": "Silk 300 gsm",
    "Sides": "Both sides",
    "Finishing": "Matt lamination"
  },
  "cut_mm": [85, 55],
  "files": ["front.pdf", "back.pdf"],
  "titles": ["Logo front final.pdf", "back.pdf"],
  "note": "Use the blue version"
}
```

| Field | Values | Notes |
|---|---|---|
| `kind` | `product` | A `job.json` without `kind` (or `document`) is a document item as in 3.2 |
| `product` | product id from the website (`lib/products.ts`), e.g. `bcard` | |
| `name` | text | Product name in English, shown to staff |
| `quantity` | ≥ 1 | Pieces ordered (250 cards), not sheets |
| `options` | object: option label → chosen choice, both as **English text** | Exactly what the customer saw. Text, not list positions, so reordering or adding choices on the website can't change old orders. Shown to staff; the app does not act on them, except `Paper` and `Sides` (below) |
| `cut_mm` | `[width, height]` in mm, numbers > 0 | Finished cut size. For folded items the open (flat) size. For round or custom shapes the bounding box |
| `folded_mm` | `[width, height]`, optional | Folded size, folded items only |
| `files` | 1 to 5 file names in the same folder | Customer files as uploaded: pdf, png, jpg, jpeg, ai, eps, psd. Never modified |
| `titles` | text, same length as `files` | The customer's original file names |
| `note` | optional text | Customer's note for this item |

Not in a product `job.json`: sheets, paper type, tray, printer, prices. The shop decides these.

Steps stay in `order.json` (`steps`). The website derives them from the product and its options (e.g. a lamination choice adds `LAMINATE`, cards add `CUTTING`).

#### Product papers → driver paper types

The website's paper names (`Silk 300 gsm`) are not driver names. A table in `rules.json`, kept by the owner, maps them:

```json
"product_papers": {
  "Silk 170 gsm": "Thick 2(170 to 220 g/m2)",
  "Silk 300 gsm": "Thick 4(257 to 300 g/m2)"
}
```

Owner's rule (2026-11-05): 80 gsm is Plain & Recycled; every other paper is Thick 3 up to 256 gsm and Thick 4 from 257 gsm. Smooth white 350 gsm and Kraft 400 gsm also print as Thick 4, on the IM C4510 from the Bypass Tray (tested by Tesla, 2026-11-05). A product whose paper isn't in the table (stickers, labels, envelopes, board) shows **Paper not mapped**: staff pick the paper type by hand for that item, or add it to the table.

#### Hand-fed papers and "Both sides, turned by hand" (handoff 03, 2026-11-05)

`rules.json` → `hand_fed_papers` → `papers` lists website papers loaded by hand in the Bypass Tray (`Smooth white 350 gsm`, `Kraft 400 gsm`). For a product item on one of them:
- It is sent with tray `Bypass Tray` instead of `Auto Tray Select` (every other item keeps `Auto Tray Select`).
- The copier can't print both sides on Thick 4, so Layout done has a fourth Sides choice, **Both sides, turned by hand** (`status.json` → `layout` → `sides`: `"hand"`). It is the default when the customer ordered Both sides on a hand-fed paper. It needs the laid-out PDF with exactly 2 pages (page 1 front sheet, page 2 back sheet); otherwise Ready to print stays disabled with "Turned by hand needs PH-xxxx.pdf with 2 pages: page 1 the front, page 2 the back." For the driver check and routing it counts as one-sided; the paper used is the sheet count.
- Sending: the other documents of that copier part go first, then **page 1 × sheets** as its own job (`… fronts`, split above 999 copies as usual). The part then waits in state `turn`: the copier panel says "PH-xxxx 01: fronts sent. When they're out, turn the stack over, put it back in the Bypass Tray, then press Print backs." with one button, **Print backs**; the copier takes no other order and Pages collected doesn't show. **Print backs** sends **page 2 × sheets** (`… backs`); then the part goes on as normal (`sent`, Pages collected). Several hand-turned items in one part are done one after another.
- `status.json` keeps `fronts` (items whose fronts are out), `turn` (the item waiting for its backs) and `batch` (what the current send holds), and history records "fronts sent" / "backs sent". After a restart in `turn`, Print backs shows again and the fronts are never resent. A failed fronts or backs send shows NOT sent / Retry, and Retry resends only the step that failed. After a crash mid-send, "Everything printed" marks exactly that send as printed.
- The backs are drawn exactly as page 2 is, with no rotation. Whether they need turning is checked in the paper test, which happens with the first real product order on a hand-fed paper (Tesla, 2026-11-05); any fix is decided with Tesla then.

#### CorelDRAW templates by size (2026-11-06)

When a product item arrives, PrintHub copies one template from `templates/` into it as `PH-xxxxx.cdr` (once, never overwritten). First match wins, names compared without regard to case: `<product id>.cdr`, then `<W>x<H>.cdr` with `cut_mm` rounded to whole mm, then `<H>x<W>.cdr` (the same size turned), then `blank.cdr`. `Options.txt` and the PrintHub details show which one was used ("CorelDRAW template: 85x55.cdr", or "CorelDRAW template: blank.cdr (no template for 165 x 165 mm)"). The owner prints the laid-out sheet from CorelDRAW (Print preview: rows and columns) to "Microsoft Print to PDF" as `PH-xxxxx.pdf` in the item folder.

The website must send these `cut_mm` values when product ordering is built:

| Website size | cut_mm (open size) | Template |
|---|---|---|
| 85 x 55 mm, 85 x 55 mm flat | 85 x 55 | 85x55 |
| Folded 85 x 55 mm | 170 x 55 | 170x55 |
| 90 x 50 mm | 90 x 50 | 90x50 |
| 90 x 55 mm | 90 x 55 | 90x55 |
| Square 55 x 55 mm | 55 x 55 | 55x55 |
| 100 x 70 mm | 100 x 70 | 100x70 |
| Square 100 x 100 mm | 100 x 100 | 100x100 |
| A7 | 74 x 105 | 74x105 |
| A6, A6 flat | 105 x 148 | 105x148 |
| A5, A6 folded, A5 folded to A6, A5 folded to 1/3 A5 | 148 x 210 | 148x210 |
| A4, A4 sheet, A5 folded, A4 folded to A5, A4 folded to DL | 210 x 297 | 210x297 |
| A3, A3 sheet, A3 folded to A4, A3 folded to 1/3 A3 | 297 x 420 | 297x420 |
| DL 99 x 210 mm, 1/3 A4 | 99 x 210 | 99x210 |
| DL folded | 198 x 210 | 198x210 |
| Square 148 x 148 mm | 148 x 148 | 148x148 |
| Square 148 mm folded | 296 x 148 | 296x148 |
| Square 210 x 210 mm | 210 x 210 | 210x210 |
| 210 x 74 mm | 210 x 74 | 210x74 |
| 150 x 55 mm | 150 x 55 | 150x55 |
| Raffle 140 x 50 mm with stub | 140 x 50 | 140x50 |
| Envelope DL 110 x 220 mm | 110 x 220 | 110x220 |
| Envelope C6 114 x 162 mm | 114 x 162 | 114x162 |
| Envelope C5 162 x 229 mm | 162 x 229 | 162x229 |
| Envelope C4 229 x 324 mm | 229 x 324 | 229x324 |
| Envelope Square 165 x 165 mm | 165 x 165 | **missing** (blank.cdr) |

`420x210.cdr` isn't used by any current website size.

#### Flow in the app

1. **Waiting for layout.** The product item arrives with the customer files. The PrintHub view shows the product name, quantity, every option, `cut_mm` (and `folded_mm`), the note and the customer files with their page size in mm. A file whose size doesn't match `cut_mm` (with or without 2-3 mm bleed) is flagged, e.g. "95 x 60 mm, ordered 85 x 55 mm". The owner fixes it in CorelDRAW.
2. **Open PH-10231.cdr** opens the CorelDRAW template copied into the item (picked by size, see above); **Open <file>** opens a customer file in its default program, the same way Windows would on a double click. `Options.txt` in the folder lists what was ordered.
3. The owner lays out the sheet in `PH-10231.cdr` (e.g. 8 cards per A4 with cut marks) and exports **`PH-10231.pdf`** into the same item folder, next to the untouched customer files.
4. The app detects `print.pdf`. It counts it as complete only once its size has stopped changing and pdfium can open it. Checks: every page is A4 or A3 (within 1 mm, either orientation); anything else is a problem shown in red. Page count is shown.
5. **Sheets.** He types the number of sheets, or cards per sheet and the app works it out: 250 cards, 8 per sheet → 32 sheets (rounded up). The sheet number becomes the **copies** of `print.pdf`. If `print.pdf` already holds every sheet as its own page, he enters 1.
6. **Ready to print.** Saved in `status.json` under `layout` (sheets, time, page count of `print.pdf`). From here it is printed like a document job: actual size, no n-up, no scaling, no rasterising beyond the existing driver path.
   - Paper size: from the pages of `print.pdf` (A4 / A3).
   - Paper type: from `product_papers`.
   - Sides: `Both sides` (or `Double-sided`) → `long` (`hand` on a hand-fed paper, see above), otherwise `single`. Staff can change it at Layout done.
   - Colour: `color`. Printer: Auto (routing rules in 2.3), staff can override. Tray: `Auto Tray Select` (`Bypass Tray` for hand-fed papers).
7. An order enters the copier queues only when **all** its product items are Ready to print: then its folder moves from Pending Orders to Orders. Until then it is listed as Waiting for layout. Documents in the same order wait with it, so an order is never split in time.
8. If `print.pdf` is replaced after Ready to print but before sending, the item goes back to step 4 (check again, sheets kept but shown for confirming). After sending, a changed `print.pdf` is ignored and flagged.

Arrival check (Needs attention): unknown `kind`, missing `product`/`name`, `quantity` not a whole number ≥ 1, `options` not label → text, `cut_mm` missing or larger than A3 (297 x 420 mm), a listed file missing or of a type not in the list.

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
11. **Half-downloaded orders.** Sync must download into a temporary folder and rename it into `Pending Orders/` when complete, with `order.json` written last. The app ignores folders without `order.json`. (Sample orders, used during stages 1-5, followed the same rule; they were removed on 2026-11-05.)
12. **Crash during sending.** If the app closes while a part is `sending`, on restart it can't know what printed. It must ask the staff instead of resending, to avoid printing twice.
13. **Large orders.** `confirm_above_sheets` asks per print run today. For orders: ask once at **Start printing orders**, listing any order over the limit.
14. **PDF page sizes.** A PDF with A3 pages ordered as A4 is scaled down to fit. The website should warn the customer; the app shows the PDF's page size next to the ordered paper.
15. **Second screen.** Tkinter can't list monitors. Placing the window full-screen on the second monitor needs a small Windows call (`EnumDisplayMonitors` via ctypes, no install). If only one monitor is connected, it opens as a normal window.
16. **Logging.** Order jobs go to `print_log.csv` like today; the file name column starts with the order number (no new column, so old logs keep their layout).
17. **Verified queues only.** PrintHub uses the same three queues. Before going live, the order flow needs its own paper test (multi-document order, split across printers, A5, duplex).

---

## 5. Stage plan (refined)

1. **Order format** (done 2026-11-03): `orders.py` reads and checks order folders (run `py -3.14 orders.py "Pending Orders"` to list them). Sample orders (PH-1001..1015) were used during stages 1-5 and removed on 2026-11-05; real orders come from the website sync.

   Driver checks (refused combinations) need the copiers and run in stage 2, when jobs are routed.
2. **PrintHub view** (done 2026-11-03, driver checks still to be seen at work):
   - `jobs.py` holds the job logic moved out of `app.py` (routing, driver checks, settings text, laying out and sending, the log). Both windows use it. Checked: the old and new code give identical jobs and settings text for 279,936 setting combinations, and the moved print code differs only in its folder argument and the lock.
   - `jobs.PDF_LOCK`: all pdfium work (converting, analysing, layout, printing) runs under one lock, because pdfium is not thread-safe. On exit, the app waits for PDF work in progress, because Python crashed (0xC0000409) when it closed during an analysis.
   - `printhub.py`: the **PrintHub** button (top right of the main window) opens the PrintHub window. It lists the orders oldest first, each document with its settings, the copier Auto picks and any problem, plus the order's note, problems and sheets per copier. It reloads by itself when order folders appear or change. No printing yet. (Sample orders (PH-1001..1015) were used during stages 1-5 and removed on 2026-11-05; real orders come from the website sync.)
3. **Queues and step buttons** (done 2026-11-03, tested with simulated copiers only):
   - One panel per copier: the order it is on (sending n of m / sent / NOT sent / interrupted), its button, and the orders waiting for it. A copier's queue holds the orders that have a part for it, oldest payment first; Needs-attention orders are left out.
   - **Sending only happens on a button press.** **Start printing orders** sends the next order to every free copier and turns printing ON. While ON, **Pages collected** frees that copier and sends its next order. **Stop after current orders** turns it OFF. Orders that arrive are never sent by themselves, even while ON; press Start printing orders again.
   - When an order starts, where each of its documents goes is fixed in `status.json`, so a change to `rules.json` can't move half an order.
   - Parts are sent one at a time by one thread (the copiers still print at the same time). The document name in the Windows queue and in `print_log.csv` starts with the order number and document folder (e.g. `PH-1002 01 Report text.pdf`).
   - Failed send → **Retry**. App closed mid-send → on restart the part shows "interrupted" with **Everything printed** / **Send the rest again** (sends only the documents not recorded as sent). An unreadable `status.json` makes the order Needs attention rather than printing it again.
   - **Next steps** lists orders whose parts are all collected, with the button for the next step (**Start Spiral Process**, …, **Ready for courier / pickup**).
   - Closing the PrintHub window only hides it; closing the app while orders are being sent asks first. `confirm_above_sheets` asks before an order part over the limit is sent.
4. **Second screen**: read-only full-screen window, refreshed from the same state.
5. **Products and website sync**:
   - a. **Product items** (3.4) (done 2026-11-04, tested with simulated copiers only), built at home, no copiers or website needed: read and check product `job.json`, `product_papers` in `rules.json`, Waiting for layout / Ready to print, **Open file**, `print.pdf` detection and checks, sheet count, printing `print.pdf` through the existing queue code. Sample orders (PH-1001..1015) were used during stages 1-5 and removed on 2026-11-05; real orders come from the website sync.
     - Built: `orders.py` reads product items (`kind: product`), checks the customer files' sizes (PDF/.ai pages; PNG/JPG with a saved resolution; .eps/.psd not checked) and `print.pdf` (A4 or A3 on every page, not changed in the last 3 seconds). `printhub.py`: Waiting for layout / print.pdf found / Ready to print / Sent per item; buttons **Open <file>**, **Open folder**, **Layout done…** (pieces per sheet → sheets, paper type from `product_papers` or picked, sides; shows the copier and any driver problem before confirming). The layout is kept in `status.json` → `layout`, with the size and time of `print.pdf`; a new `print.pdf` asks for Layout done again, and after sending it is ignored and flagged.
     - `driverprint.print_pdf(..., actual_size=True)` draws product sheets at 100 %, centred on the sheet (the walk-in path still fits to the printable area). Needs a paper test: print a sheet with cut marks and measure.
     - Fixes from `CODE_REVIEW.md` (2026-11-05): products may have up to 9999 sheets, sent as several jobs of at most 999 copies ("part 1 of 3"); a print.pdf with a file time in the future counts as saved; customer file sizes are cached; pieces per sheet is kept only if it gave the sheets; Both sides with a 1-page print.pdf is blocked at Layout done; images need both DPI values; job.json and customer files are watched too; product details come from one function (`orders.product_lines`).
     - Exception to "nothing starts by itself": an order given Layout done **while printing is ON** starts on its free copiers as soon as it is in Orders. Other orders that arrive still wait for Start printing orders.
   - b. **Website sync** (built 2026-11-05, handoff 05; tested against a pretend website on the home PC, the live test waits for the website's order feed, handoff `website/04`). `sync.py`, started by the main window when the app opens:
     - Runs only when `printhub_token.txt` is next to `app.py` (one line, the same value as `PRINTROUTER_TOKEN` in Vercel; created by Tesla on the work PC only; gitignored). Without it no network call is made and PrintHub shows "Website sync: off (no printhub_token.txt)". The token is read on every check, sent only in the `Authorization: Bearer` header to the website's API (never with file downloads), and never logged or shown.
     - `rules.json` → `website`: `url`, `check_seconds` (60). First check about 5 s after start, then every `check_seconds`; urllib only, 30 s timeout; https only (http only to this PC, for tests). Errors never block the app.
     - Contract: GET `/api/printrouter/orders` → `{"format": 1, "orders": [{"order": <order.json>, "items": [{"folder", "job", "files": [{"name", "url"}]}]}]}`; POST `/api/printrouter/orders/received` `{"order": "PH-10001"}` → 200 `{"ok": true}`. 401 for a wrong token. Order numbers `PH-` + digits (from PH-10001); delivery always `courier`.
     - Per order: if the number is already in Pending Orders, Orders or Finished Orders (also `PH-… (2)`), only the confirm is sent again. Otherwise it is downloaded into `Pending Orders/.<order>.downloading` (leftovers from a closed app are removed first); a non-PDF `job.file` is converted with `convert.to_pdf` under `jobs.PDF_LOCK` into `document.pdf`, the original kept next to it, and `job.json` gets `"file": "document.pdf"`; `order.json` is written last and the folder renamed into Pending Orders, then the confirm is POSTed. A failed confirm is retried at the next check; a failed download or conversion removes the hidden folder and is tried again every check, shown in red after 3 tries in a row ("PH-10001 can't be downloaded: …"). One bad order never stops the others.
     - Top bar of the PrintHub window: "Website sync: off …", "Website: checked 14:05, 2 new" or, in red, "Website: can't connect (…), last OK 13:58". `sync_log.txt` (gitignored): time, order number, what happened.
     - Documents-only orders then move on to Orders by themselves as before; nothing prints before Start printing orders. Products from the website: not yet (format 3.4).
     - `printhub_options.json` (9): not built.
