# Work note W01: first real website order, admin check, two print tests
For: the Work PC chat (C:\PrintRouter\ADMIN on the work PC)
From: the planning window (Brain), 2026-11-06

## Goal
Go through these tasks **together with Tesla** at the work PC. He does the clicking and printing, you guide him one step at a time, check what you can on this PC yourself, and write down what happened. At the end, write the report (see the end of this note).

## Before you start
- Read `CLAUDE.md` (section "Work PC chat") and `WORK_TEST_CHECKLIST.txt`.
- Ask Tesla to close PrintRouter and start it again with the shortcut (it downloads updates first). Check: the windows are dark; the PrintHub top bar says "Website: checked hh:mm, 0 new" (not "sync: off", not red). You can confirm `printhub_token.txt` exists next to `app.py` without opening it. **Never read, print or show its content.**
- Pending Orders, Orders and Finished Orders should be empty (or hold only orders Tesla knows about). Don't delete anything Tesla doesn't confirm.

## Task A: first real website order, start to finish
This is the first order to go through every step for real: website → PrintRouter → printer → admin page → shipped email.
1. On https://print-hub-vert.vercel.app Tesla orders a **short Word file** (1-2 pages): black & white, one side, A4, 1 copy, no spiral, no lamination, normal paper. Pay with the test card 4242 4242 4242 4242, any future date, CVC 123.
2. Within about a minute it appears in PrintHub as PH-1000x and moves to Orders by itself. Check the folder yourself: the Word file and `document.pdf` are both in `01`, and `Options.txt` shows the courier. Check that `document.pdf` has the right number of pages.
3. Tesla opens `/admin` on his phone: the order is in **In the shop**.
4. Press **Start printing orders**. It should print on the **IM C4510** (B&W). Tesla checks the pages: right order, nothing cut off, the label at the top. Then **Pages collected**, then **Stop after current orders**.
5. In Next steps, press **Ready for courier**. Within about a minute, `/admin` on his phone should show it under **Ready to ship**. Check `sync_log.txt` for "reported ready to the website".
6. On `/admin`, Tesla presses **Mark shipped**, types tracking `TEST456`, presses **Confirm shipped**. He checks teslachr@outlook.com for "Your PrintHub order #… is on its way" with "Tracking number: TEST456".
7. The order folder is now in Finished Orders. Ask Tesla whether to delete it (it was a test).

Write down for each step: OK or what went wrong (exact error text, screenshots if possible).

## Task B: live check of the "ready" route
Using the same token file (read it in code, never show it), send `POST https://print-hub-vert.vercel.app/api/printrouter/orders/status` with body `{"order": "PH-99999", "status": "ready"}` and header `Authorization: Bearer <token>`. Expected: **404** `{"error":"unknown order"}`. Report only the status code and the body.

## Task C: thank-you card test print (kraft)
Files: `work\files\kraft-A_sheet.pdf`, `kraft-B_sheet.pdf`, `kraft-C_sheet.pdf` (8 cards on A4 each; A = handwritten note, B = postmark, C = paper plane).
1. Ask Tesla which version he wants to test (he can print all three).
2. First on **plain paper**, actual size (100 %, no scaling), black & white, through the normal PrintRouter window. Measure one card: it should be **85 x 55 mm**.
3. Then on **Kraft 275**, Bypass Tray, paper type **Thick 4**, black only.
4. Check on the kraft: text easy to read, the thin lines (waves, stamp ring, dashed trail) solid and not broken, the black dark enough on brown.
Write down which version(s), the measured size, and how each looked. A photo of the printed cards helps.

## Task D: CorelDRAW "print to PDF" test
1. Check that the printer **Microsoft Print to PDF** exists on this PC (list the printers). If it's missing, write that down. Don't switch it on: that's a system setting for Tesla to decide with the planning window.
2. If it exists: Tesla opens `templates\85x55.cdr` in CorelDRAW, puts any test text on it, then Print → Print preview → sets rows and columns (e.g. 2 x 5 on A4) → Apply → printer "Microsoft Print to PDF" → saves as `work\reports\corel-print-test.pdf`.
3. Check the PDF yourself: page size exactly A4 (210 x 297 mm), number of cards, card size 85 x 55 mm, text sharp (vector, not a blurry image). Write the results in the report.

## Report
Write `work\reports\2026-11-06_W01_report.md`:
```
# Report: 2026-11-06_W01_first-real-order-and-tests.md
Status: Done | Partly done | Not done
## Task A
## Task B
## Task C
## Task D
## Problems found (exact error texts)
## Questions for the planning window
```
Then upload only the `work` folder as `CLAUDE.md` describes (`corel-print-test.pdf` and any screenshots included), and move this note to `work\done\`.
