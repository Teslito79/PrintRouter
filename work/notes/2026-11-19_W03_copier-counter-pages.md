# Work note W03: save the copiers' real counter pages
For: the Work PC chat (C:\PrintRouter\ADMIN on the work PC)
From: the planning window (Brain), 2026-11-19

## Goal
The copy counter should count by itself from Start to Finish, with no size or sides buttons. At work, the IM C4510 showed the size and sides buttons instead. This is the fallback "pages" mode, so ORCA could not read the copier's detailed counter page. `counter_page.py` was built from Tesla's screenshots, not from the real HTML.

Save the real pages exactly as ORCA receives them, plus what ORCA makes of them, so the planning window can fix the reader at home. **Change no code here.** Only save files and write the report.

## Before you start
- Read `CLAUDE.md` (section "Work PC chat").
- Ask Tesla to close ORCA and start it again with the shortcut, so it has the latest updates. Check with `git log --oneline -3` that `564c105` or later is there.
- The copiers' addresses are 192.168.10.85 (IM C4510), .70 (IM C3000) and .14 (MP C3004). If Settings or the Data screen shows other addresses, use those and say so.
- Nothing here prints, logs in, or changes a copier setting.

## Task A: save each page as ORCA gets it
For each of the three copiers, run a short Python script with `py -3.14` from `C:\PrintRouter\ADMIN`. Write it to a temp file, not into the repo. It should:
1. Fetch the page with ORCA's own code: `counter_page.fetch(address)`. If `fetch` raises, save the error text instead.
2. Also fetch the same URL with plain `urllib.request.urlopen` and save that as well. Record the final URL after any redirect, the HTTP status and the `Content-Type` header.
3. Save the bytes **unchanged** to `work\reports\W03\<model>_raw.html`, for example `IM-C4510_raw.html`, and `<model>_urllib.html`.
4. Save `counter_page.text_of(page)` to `<model>_text.txt`.
5. Save `counter_page.parse(page)`, `counter_page.sheet_split(parse(page))` and `counter_page.describe(parse(page))` as JSON to `<model>_parsed.json`. Save any error too.
6. If the page holds frames or iframes, or loads its numbers with JavaScript (look for `<frame`, `<iframe`, `.cgi` or `.js` URLs, `XMLHttpRequest`, `fetch(`), fetch those URLs too and save each one as `<model>_extra_<n>.html`. List what you found.

## Task B: the same page in a browser
For each copier, Tesla opens `http://<address>/web/guest/en/websys/status/getUnificationCounter.cgi` in a browser.
- Take a screenshot of the page, or Tesla takes a photo. Save it as `work\reports\W03\<model>_browser.png`. Only the copier's page should be in the picture.
- Note whether the browser shows the counters straight away, or only after a click or a login. Also note whether the address bar changed.

## Task C: one known change on each copier
This shows which numbers move. On each copier, read the page (Task A step 1 only, into `<model>_before.html`), then Tesla copies, then read again (`<model>_after.html`):
- **IM C4510:** 1 A4 B&W copy, one side; then 1 A3 colour copy, one side; then 1 A4 B&W original copied on both sides (one sheet).
- **IM C3000:** 1 A4 colour copy, one side.
- **MP C3004:** 1 A3 B&W copy, one side; then 2 A4 B&W pages on one sheet, both sides.

Read the page again after each copy (`<model>_after1.html`, `_after2.html` …). Write down exactly what Tesla copied for each one. The paper can be the cheapest plain paper. Ask Tesla to throw the copies away.

## Task D: ORCA's copy counter
On the IM C4510, Tesla presses Start on the copy counter. Note what the panel says (the counting line, or the size and sides buttons). Make one A4 B&W copy and press Finish. Then Cancel, so nothing is sold. Take a screenshot of ORCA's window only.

## Report
Write `work\reports\2026-11-19_W03_report.md`:
- the files saved, per copier;
- the HTTP status, final URL and Content-Type;
- frames, iframes or scripts found;
- what Tesla copied in Task C, in order, with the file names;
- what the copy counter showed in Task D;
- anything that went wrong, with the exact error text.

Move this note to `work\done\`. Upload **only the work folder**, as `CLAUDE.md` says for the Work PC chat. Tell Tesla it's done: the planning window at home will write the fix.
