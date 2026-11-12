# Work note W02: first product order (business card + flyer + document)
For: the Work PC chat (C:\PrintRouter\ADMIN on the work PC)
From: the planning window (Brain), 2026-11-12

## Goal
The website now sells products. Go through the first product order **with Tesla**, from paying on the website to the shipped email, including the CorelDRAW layout. He does the clicking and printing; you guide him one step at a time and write down what happened. At the end, write the report.

## Before you start
- Read `CLAUDE.md` (section "Work PC chat").
- Ask Tesla to close PrintRouter and start it again with the shortcut, so it downloads the updates (at least commit 78636ce "Sync: accept product items" must be there: check with `git log --oneline -5`). The PrintHub top bar should say "Website: checked hh:mm, 0 new".
- Pending Orders, Orders and Finished Orders should be empty or hold only orders Tesla knows about. Don't delete anything he doesn't confirm.
- **Never read, print or show `printhub_token.txt`.**

## Task A: order and pay on the website
1. On https://print-hub-vert.vercel.app, Tesla adds to one basket:
   - **Business cards**: 85 x 55 mm, any paper, One side, the smallest quantity; upload one PDF (any business-card-sized design he has); note "TEST: please ignore".
   - **Flyers**: A5, any paper, the smallest quantity; upload one JPG.
   - **Documents**: one short PDF, B&W, one side, A4, 1 copy.
2. Check the "Your order" box: three lines, delivery, total, ready date. Remove and add back one item to check Remove.
3. Pay now with the test card 4242 4242 4242 4242, any future date, CVC 123.
4. Emails to teslachr@outlook.com: "New order #…" (to the owner) and "PrintHub order #…" (to the customer) both list the document and both products with options, note and file names.
5. `/admin` → New: the order shows both products with file links that open.

## Task B: the order arrives in PrintRouter
1. Within about a minute it appears in PrintHub as PH-100xx, status **"Waiting for layout (2)"**. It stays in Pending Orders.
2. Check the folder yourself: `01` the document (with `document.pdf` if it needed converting), `02` the business card, `03` the flyer. In `02` and `03`: the customer file unchanged, `Options.txt`, and the CorelDRAW file `PH-100xx-02.cdr` / `PH-100xx-03.cdr`. `Options.txt` should say which template it used: **85x55.cdr** for the card, **148x210.cdr** for the flyer.
3. `/admin`: the order moved to **In the shop**.

## Task C: lay out and print the products
For each of the two products:
1. In PrintHub, open the item's CorelDRAW file. Tesla places the customer's design, then Print → Print preview → rows and columns (cards e.g. 2 x 4 on A4; A5 flyer 1 x 2 on A4 or 1 on A5) → Apply → printer **Microsoft Print to PDF** → save as **`PH-100xx-02.pdf`** (or `-03`) in the same item folder.
2. PrintHub should notice the PDF (A4 page) and offer **Layout done**. For this test, enter **1 sheet** (saves paper). Sides: one side.
3. When both products are laid out, the order moves to **Orders** by itself.
4. **Start printing orders.** Write down which copier, tray and paper type each item went to. Tesla collects the pages, presses **Pages collected**, then **Stop after current orders**.
5. Measure one business card on the printed sheet: it should be **85 x 55 mm** (actual size, not shrunk). Measure the A5 flyer: **148 x 210 mm**.

## Task D: finish and ship
1. Go through the next steps (Cutting etc.) to **Ready for courier**. `sync_log.txt` should say "reported ready to the website"; `/admin` shows **Ready to ship**.
2. On `/admin`, **Mark shipped** with tracking `TEST789`. Tesla checks for the "is on its way" email with "Tracking number: TEST789".
3. The folder is now in Finished Orders, with a new file **`finished.txt`** holding today's date and time (the 8-day cleanup). Check that `cleanup_log.txt` exists or that nothing was wrongly deleted. Leave the folder there: it should go to the Recycle Bin by itself 8 days later.

Write down for each step: OK, or what went wrong (exact error text; screenshots or photos if possible).

## Report
Write `work\reports\2026-11-12_W02_report.md`:
```
# Report: 2026-11-12_W02_first-product-order.md
Status: Done | Partly done | Not done
## Task A
## Task B
## Task C
## Task D
## Problems found (exact error texts)
## Questions for the planning window
```
Then upload only the `work` folder as `CLAUDE.md` describes, and move this note to `work\done\`.
