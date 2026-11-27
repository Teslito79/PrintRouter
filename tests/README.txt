ORCA's tests (2026-11-27_03)

Run them all:      py -3.14 tests\run_all.py
Also the slow one: py -3.14 tests\run_all.py --slow      (starts real ORCA processes from a temp copy of the repo)
Only some:         py -3.14 tests\run_all.py copy_counter inventory

One line per file ("copy counter: 39/39") and a total; the exit code is 0 only if everything passed. Logs of each file
go to %TEMP%\ORCA-tests\_logs\. "Earlier tests still pass" means this run is all green.

SAFETY RULES (every test, enforced in helpers.py and run_all.py)
1. Work in a fresh temp copy made by the helpers (%TEMP%\ORCA-tests\<test name>), never in ADMIN's own folders.
2. Never touch Walk-in\, the order folders, settings.json, inventory.json, toner_stock.json, costs.json, the password
   files, the logs or printhub_token.txt in the real ADMIN folder. run_all.py lists ADMIN's local (gitignored) files
   with sizes and times before and after, and reports any change as a failure; a test whose ORCA folder
   (routing.app_dir) is the real ADMIN fails.
3. Never print, and never read a real copier: printing, the receipt printer, SNMP and the counter page are faked.
4. Windows a test opens are ORCA's own and are closed at the end; pictures are of ORCA's own windows only
   (window_shot.py, PrintWindow), never the screen or the taskbar.
5. A test that starts processes ends every one it started, and only those (tests\slow\test_one_orca.py).
6. Nothing from real customers in fixtures\. Tesla's real Shopify export (Downloads\inventory_export_1.csv) is read
   (a temp copy) only if it is on the PC; the tests that need it are skipped otherwise.

LAYOUT
- test_<area>.py   one file per area (copy counter, inventory, walk-in, ...); each handoff adds its checks to its area.
- helpers.py       temp folders, the safety guard, a temp ADMIN, no printing, the price template.
- price_sheet.py, page_fixtures.py, pretend_snmp.py, xlsx_maker.py, window_shot.py, combo_shot.py: shared helpers.
- fixtures\        counter pages saved at work, price_template.xlsx (made from the repo's own Walk-in_Prices.xlsx,
                   every price empty: the same as the sheet Tesla fills in).
- slow\            tests that run real ORCA processes (only with --slow).

Plain Python, no extra packages (no pytest). Scratch folders are for throwaway work only: a test that matters
lives here.
