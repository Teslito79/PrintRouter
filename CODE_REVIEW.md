# Code review: PrintHub stage 5a (commit 2b1efd6)

Date: 2026-11-05. Reviewed on the work PC session, after the paper test.
Scope: `orders.py`, `printhub.py`, `driverprint.py`, `jobs.py`, `rules.json` changes in stage 5a (product items laid out in CorelDRAW).

## Paper test results (work PC, 2026-11-05)

Test orders PH-1012 (flyers, C3000), PH-1013 (business cards, C4510 Thick 4), PH-1014 (documents split over C4510 / C3004 / C3000).

- All three copiers printed from the app. Routing, layout flow (Waiting for layout -> print.pdf found -> Layout done -> Ready to print), double-sided flyers and actual-size printing of products: **OK**.
- Product rulers measured exactly 100 mm.
- A3 poster (document) measured **98 mm**: expected. Documents are fitted to the printable area (about 4 mm unprintable edge), products print at actual size. Not a bug. Possible later feature: an "Actual size" option for documents (plans, patterns), decided on the website side.

## Findings (most severe first)

**Status 2026-11-05 (home PC):** findings 1-8 fixed and tested with simulated copiers, together with "Layout done doesn't start printing by itself". The finished-orders archive is done as three folders (Pending Orders -> Orders -> Finished Orders, owner's choice), and the layout file is `print.cdr` copied from `templates/` (owner still to save `templates/blank.cdr`). Still open: picking which sample orders to add.

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

## Old work checklist (replaced 2026-11-05)

The former `WORK_TEST_CHECKLIST.txt` (steps 1-5 from 2026-11-03, done in the paper test of 2026-11-05, plus the hand-fed paper test and the first real sync added on 2026-11-05), kept as it was:

```text
PRINTROUTER - TEST AT THE WORK PC (written 2026-11-03 at home)
==============================================================

FOR CLAUDE (the chat at work): read this first
------------------------------------------------
- Project: C:\PrintRouter. Read PROJECT_SUMMARY.txt and PRINTHUB_SPEC.md after step 1.
- Since the work PC last updated, these were added at home and uploaded to GitHub:
    * Upload changes.bat / Download changes.bat: double-click scripts to sync with GitHub.
    * PrintRouter.bat now runs "git pull" before starting the app (auto-update).
    * PrintHub stages 1-3: orders.py (reads order folders), jobs.py (the print logic,
      MOVED out of app.py, used by both windows), printhub.py (PrintHub window:
      a queue per copier, Start printing orders, Pages collected, next-step buttons,
      progress in orders\<order>\status.json). sample_orders\ holds 6 test orders.
- Tested at home only: the logic was checked with simulated copiers, and the moved
  code was compared with the old code. NOTHING has printed on paper through the new
  code yet, and the driver checks (refused combinations) could not run at home.
- Safety rules: never change printer drivers, ports, preferences or the default
  printer; don't install anything without asking; don't edit files the user didn't
  ask to change; send jobs only through the normal print queue.
- If step 1 says "local changes" or "conflict": stop, look at what differs, and ask
  the user before doing anything. Work-PC edits must not be lost.


FOR ME: the steps
-----------------

STEP 1 - Get the new version (only this once)
  The work PC still has the old launcher, which doesn't update itself.
  Open PowerShell in C:\PrintRouter and type:

      git pull

  - If a GitHub sign-in window appears: choose "Sign in with your browser"
    and approve it.
  - If it says "local changes" or "conflict": STOP and ask Claude.
  - If git asks for a name/email later, run these in C:\PrintRouter:
      git config user.name "Christos"
      git config user.email "teslachr@outlook.com"
  From now on the app updates itself every time it starts.


STEP 2 - Check the normal window still prints
  (The print code moved to a new file, so check it once.)
  - Start the app the usual way (PrintRouter.bat).
  - Print one ordinary file, e.g. 2 pages, double-sided, B&W, receipt "One for all".
  - Check: it comes out right on the C4510, double-sided, and the receipt prints.


STEP 3 - PrintHub paper test
  3a. Click the "PrintHub" button (top right), then "Add sample orders".
  3b. Look for RED rows. Only PH-1005 should be red (it has deliberate mistakes).
      If any other order is red, write down what its Status column says.
      (These are printer-driver complaints that could not be checked at home.)
  3c. Press "Start printing orders". Expected:
        C4510 (downstairs) -> PH-1001 (Letter, 4 pages double-sided, 2 copies)
        MP C3004           -> PH-1002 document 02 (Report charts, colour)
        IM C3000 (upstairs)-> PH-1002 document 03 (Photos, Coated Glossy paper)
      Every page has a label at the top like "PH-1002 / 01 / Report text.pdf / page 3".
  3d. Check each stack, then press "Pages collected" on that copier's panel.
      The next order for that copier should start by itself, e.g.:
        C4510 -> PH-1002 document 01, then PH-1004 (Thick 4 cover + handout)
        C3000 -> PH-1003 (20 A5 flyers = 10 sheets of Thick 1)
  3e. In "Next steps" at the bottom, try "Start Spiral Process" and then
      "Ready for courier" on PH-1002.
  Note: the sample PDFs are low resolution on purpose, so prints look blurry.
  The test is about which copier, paper, sides and order the pages come out in.


STEP 4 - Clean up
  - Click "Open orders folder" and delete the sample folders (PH-1001 ... PH-1006),
    so they don't mix with real orders.


STEP 5 - Write down the results
  For each copier: did the right pages come out, on the right paper, single or
  double-sided as expected? Any red rows, error messages or "NOT sent"?
  Give the results to Claude, then continue with stage 4 (the second screen).


HAND-FED THICK PAPER TEST (350 gsm, turned by hand) - added 2026-11-05
  Needs: a few A4 sheets of Smooth white 350 gsm, PrintRouter updated.
  1. Load the 350 gsm sheets in the Bypass Tray of the IM C4510 (downstairs).
  2. PrintHub: press "Add sample orders". PH-1015 (Business cards x 250, Smooth
     white 350 gsm, both sides) appears in Pending Orders.
  3. Open its folder (click PH-1015, "Open folder") and rename
     example_layout.pdf to PH-1015.pdf (as if exported from CorelDRAW).
  4. Press "Layout done...". Check: Paper type is Thick 4, Sides is
     "Both sides, turned by hand". Type 4 in Sheets, press "Ready to print".
     The order moves to Orders.
  5. Press "Start printing orders". Only the FRONTS come out (4 sheets).
     The C4510 panel says: turn the stack over, put it back in the Bypass Tray,
     then press Print backs.
  6. Turn the stack over, put it back in the Bypass Tray, press "Print backs".
  7. Check:
     - it printed on the C4510, from the Bypass Tray, both times;
     - fronts and backs line up (the cards sit on top of each other);
     - the arrows on the front and the back point the SAME way (to the same
       edge of the sheet).
     If the backs come out upside down, write down how you turned the stack
     (flipped left-right or top-bottom). Don't change anything: the fix is
     decided with Claude afterwards.
  8. Press "Pages collected", then delete the PH-1015 folder from Orders.


FIRST REAL SYNC (website orders arrive by themselves) - added 2026-11-05
  Only once the website's order feed is live (the Website chat says so).
  1. In C:\PrintRouter\ADMIN make a text file named printhub_token.txt.
     Put in it, on one line, the same secret you put in Vercel as
     PRINTROUTER_TOKEN. Save. (Never send this secret in a chat.)
     In Explorer, check it is not called printhub_token.txt.txt.
  2. Start PrintRouter with the shortcut, open PrintHub. The top bar should
     say "Website: checked hh:mm, 0 new" within about a minute.
     If it says "Website sync: off", the file name is wrong.
     If it is red ("can't connect (wrong or missing token (401))"), the
     secret in the file doesn't match the one in Vercel.
  3. On the website, order and pay a test document (test card
     4242 4242 4242 4242 while the website is in test mode). Use a Word file
     this time: Office on this PC turns it into document.pdf.
  4. Within about a minute: the order appears in PrintHub. It moves to
     Orders by itself (documents only). Open its folder: the Word file and
     document.pdf are both there, and Options.txt shows the courier.
  5. On the website's /admin page the order shows as sent to the shop.
  6. Nothing prints until you press Start printing orders.
  If something is red, write down the exact text from the top bar.
```
