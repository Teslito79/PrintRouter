# Code review: PrintHub stage 5a (commit 2b1efd6)

Date: 2026-11-05. Reviewed on the work PC session, after the paper test.
Scope: `orders.py`, `printhub.py`, `driverprint.py`, `jobs.py`, `rules.json` changes in stage 5a (product items laid out in CorelDRAW).

## Paper test results (work PC, 2026-11-05)

Test orders PH-1012 (flyers, C3000), PH-1013 (business cards, C4510 Thick 4), PH-1014 (documents split over C4510 / C3004 / C3000).

- All three copiers printed from the app. Routing, layout flow (Waiting for layout -> print.pdf found -> Layout done -> Ready to print), double-sided flyers and actual-size printing of products: **OK**.
- Product rulers measured exactly 100 mm.
- A3 poster (document) measured **98 mm**: expected. Documents are fitted to the printable area (about 4 mm unprintable edge), products print at actual size. Not a bug. Possible later feature: an "Actual size" option for documents (plans, patterns), decided on the website side.

## Findings (most severe first)

1. **Large product orders can't pass Layout done** (`printhub.py:857`). Sheets are limited to 1-999 (`jobs.py:81` caps copies). 5000 flyers at 2 per sheet = 2500 sheets: Ready to print stays disabled. Fix: allow more sheets for products (split into several jobs of at most 999 copies, or raise the cap for product jobs).

2. **print.pdf can stay "being saved" forever** (`orders.py:360`). The check `time.time() - mtime < 3` is also true when the file's time is in the future (saved from a PC or network share whose clock is ahead). The item never becomes ready and the window reloads every 3 s. Fix: treat it as saving only when `0 <= age < 3`, or compare the file's size/time between two looks instead of with the clock.

3. **Every reload reopens all customer files under PDF_LOCK** (`printhub.py:228`, `orders.py` `customer_file_size`). Sizes aren't cached (colours are, in `_analysis`), and finished orders are never moved out of `orders/`, so reloads get slower and hold up sending. Fix: cache file sizes by (path, size, mtime) like `_analysis`, and add the finished-orders archive (move orders to `Finished orders/<date>/` at Ready for courier / pickup).

4. **per_sheet saved even when sheets were typed by hand** (`printhub.py:881`). Type 8 per sheet (32 sheets), then change sheets to 40: it saves "40 sheets (8 per sheet)". Fix: save per_sheet only if `ceil(quantity / per_sheet) == sheets`.

5. **Both sides can be confirmed with a 1-page print.pdf** (`printhub.py:803`). Only a warning; the cards print with blank backs. Fix: block Ready to print (or ask "Print one side only?") when Both sides is chosen and print.pdf has 1 page.

6. **Image DPI check ignores the vertical DPI** (`orders.py:335`). `dpi[0] < 30` only; a broken vertical DPI gives a false WRONG SIZE. Fix: `min(dpi) < 30`.

7. **Changed customer files / job.json aren't noticed** (`printhub.py:175`). `_signature` watches only order.json and print.pdf. Matters once website sync can update an order. Fix: include each item folder's job.json and customer files in the signature.

8. **Product details are formatted twice** (`orders.py` `main()` and `printhub.py` `product_lines`), already drifting (main() leaves out the folded size). Fix: one shared function in `orders.py`.

## Other open items from this session

- **New layout button (CorelDRAW):** not built yet. Plan: the owner saves blank templates (.cdr) per product; the app copies the matching one into the item folder as `layout.cdr` and opens it. Needs: CorelDRAW version on the work PC, and the template files (product, sheet size, pieces per sheet).
- **Layout done doesn't start printing by itself:** if printing is ON and the copier is free, the order waits until Start printing orders or Pages collected is pressed. Fix: call `start_next` for that copier after Layout done.
- **Add sample orders copies all samples:** add a way to pick which orders to add.
- **Finished-orders archive:** see finding 3.
- **Work PC:** the owner deleted the contents of `C:\PrintRouter\sample_orders` there. Restore with `git restore sample_orders` in `C:\PrintRouter`, and do NOT run `Upload changes.bat` on the work PC before that, or the samples are deleted from GitHub.
- Next stage after these fixes: stage 4 (second screen) or 5b (website sync).
