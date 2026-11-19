# Report: Copier check on the real copiers (no note; asked by Tesla)
Status: Done

Done on 2026-11-19 at the work PC, 13:57. First test of the Data screen (`toners.py`) on the real copiers. Tesla ran ORCA → Data → **Copier check** and pasted `copier_check.txt` into the chat (a Claude Code cloud session, no direct access to the work PC). Tesla confirmed the toner readings against the copiers.

## Results

| | IM C4510 | IM C3000 | MP C3004 |
|---|---|---|---|
| Address (from queue port) | 192.168.10.85 | 192.168.10.70 | 192.168.10.14 |
| Answered | SNMP v2c | SNMP v2c | SNMP v2c |
| Firmware (sysDescr) | 2.07 | 2.20 | 1.29 |
| Total | 658,565 | 1,412,626 | 1,207,997 |
| Black | 558,533 | 1,125,805 | 883,380 |
| Colour | 100,032 | 286,821 | 324,617 |
| Toner K / C / M / Y | 91 / 30 / 47 / 34 % | 80 / 70 / 20 / **not given (-2)** | 20 / 30 / **0 / 0** % |
| Waste toner (type 4) | level 100 | level 100 | level 100 |
| Missing | nothing | Yellow toner level | nothing |

- **Counters: correct.** Black + colour = total on all three. Ricoh's counter table (`1.3.6.1.4.1.367.3.2.1.2.19.5.1`) answered nothing on all three; the fallback to the counter web page (`/web/guest/en/websys/status/getUnificationCounter.cgi`) read black and colour on all three and matches the Printer MIB total.
- **Toner levels: correct** (Tesla, 2026-11-19): the C3000 and C3004 are out of toner at the moment. The C3004 reports 0 for magenta and yellow; the **C3000 reports -2 for its empty yellow** (Printer MIB "unknown"), not 0, so ORCA shows "not given".
- Waste toner 100 on all three while all are working: read as "OK", not "full". Not used by ORCA.
- C4510 levels come in single points (91, 47, 34); C3000 and C3004 in steps of 10.

## Problems found
1. **A new toner after a -2 reading is not recorded.** `toners.py` (around line 614) records a change only when both the old and new levels are numbers and the new one is 30+ higher. The C3000's empty yellow is stored as "not given", so when the new yellow goes in (e.g. -2 → 100), nothing is recorded, and no spare is taken off. Until fixed, staff must press **Toner replaced** by hand for that toner. Suggested: treat -2 (and a missing level) after a known low level as 0 for change detection, or show "Empty or unknown" in red instead of "not given".
2. **Colour routing doesn't know a copier is out of toner.** The C3000 and C3004 are both out of colour toner now; the rules still send colour to them (C3000 colour first, C3004 colour documents). Jobs will wait or print wrong until toner arrives. Staff have to pick the C4510 by hand for colour.

## Questions for the planning window
1. Fix problem 1 as suggested?
2. Should routing use the Data screen's toner levels (e.g. a colour toner at 0 or unknown → send colour to the C4510 and show why)? Note that levels are only read every 10 minutes and the C3000 / C3004 report in steps of 10 %.
3. Show the waste toner level on the Data screen, or ignore it?

## Steps for Tesla
1. Until the C3000 and C3004 have toner again, send colour jobs to the IM C4510 by hand.
2. When the new C3000 yellow toner goes in, press **Toner replaced** for it in Data (ORCA won't record it by itself, problem 1).
