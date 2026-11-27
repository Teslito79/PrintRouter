"""HTML fixtures of the copiers' getUnificationCounter.cgi page, built from Tesla's numbers (2026-11-18) in the
layout and labels Tesla listed. The real HTML isn't on the home PC, so these use table cells, line breaks, &nbsp;
and a menu the way Web Image Monitor pages usually do."""

HEAD = """<html><head><title>Web Image Monitor</title><script>var x = "Copier Total : 1";</script>
<style>td { padding: 2px }</style></head><body>
<div class="menu"><a href="#">Home</a> <a href="#">Status</a> <a href="#">Copier</a> <a href="#">Printer</a>
<a href="#">Fax</a> <a href="#">Scanner</a></div>
<p>Counter</p>
<p>The total/total counter shows the number of pages printed. The simplex/duplex shows the number of sheets of
paper output.</p>
"""
TAIL = "</body></html>"

ROW_NAMES = ("Full Color", "Black &amp; White", "Single Color", "Two-color")


def _row(name, total, s, d, banner):
    """One row: Total : n | Simplex A3/DLT : n Others : n (Banner : n) | Duplex ..."""
    s_a3, s_other = s
    d_a3, d_other = d
    b = lambda: f"<td>Banner&nbsp;:</td><td>0</td>" if banner else ""
    return (f"<tr><td class='name'>{name}</td>\n<td>Total</td><td>:</td><td>{total}</td>\n"
            f"<td>Simplex</td><td>A3/DLT :</td><td>{s_a3}</td><td>Others\n:</td><td>{s_other}</td>{b()}\n"
            f"<td>Duplex</td><td>A3/DLT&nbsp;:</td><td>{d_a3}</td><td>Others :</td><td>{d_other}</td>{b()}</tr>\n")


def _section(title, rows, banner, extra=""):
    out = f"<h3>{title}</h3>\n<table>{extra}<tr><th></th><th>Total</th><th>Simplex</th><th>Duplex</th></tr>\n"
    for name in ROW_NAMES:
        total, s, d = rows.get(name, (0, (0, 0), (0, 0)))
        out += _row(name, total, s, d, banner)
    return out + "</table>\n"


def big(total_counter, copier, printer=None, total_rows=None, banner=True):
    """IM C4510 (banner=True) / IM C3000 (banner=False) layout. copier / printer / total_rows:
    {"Full Color": (total, (s_a3, s_other), (d_a3, d_other)), "Black &amp; White": ...}."""
    printer = printer or {"Full Color": (5000, (100, 2000), (50, 1400)), "Black &amp; White": (9000, (10, 5000), (5, 1990))}
    total_rows = total_rows or {k: (copier.get(k, (0,))[0] + printer.get(k, (0,))[0],
                                    tuple(a + b for a, b in zip(copier.get(k, (0, (0, 0), (0, 0)))[1], printer.get(k, (0, (0, 0), (0, 0)))[1])),
                                    tuple(a + b for a, b in zip(copier.get(k, (0, (0, 0), (0, 0)))[2], printer.get(k, (0, (0, 0), (0, 0)))[2])))
                                for k in set(copier) | set(printer)}
    page = HEAD
    page += _section("Total", total_rows, banner, f"<tr><td>Total Counter</td><td>:</td><td>{total_counter}</td></tr>")
    page += _section("Copier", copier, banner)
    page += _section("Printer", printer, banner)
    page += "<h3>Fax</h3><table><tr><td>Black &amp; White</td><td>Total : 12</td></tr></table>"
    page += "<h3>Send/TX Total</h3><table><tr><td>Black &amp; White</td><td>Total : 40</td></tr></table>"
    page += "<h3>Fax Transmission</h3><table><tr><td>Total : 3</td></tr></table>"
    page += "<h3>Scanner Send</h3><table><tr><td>Black &amp; White</td><td>Total : 37</td></tr></table>"
    page += "<h3>Coverage</h3><table><tr><td>Full Color</td><td>Total : 1</td></tr></table>"
    return page + TAIL


def c4510(reading):
    """Tesla's three IM C4510 readings (1, 2, 3). Only the columns Tesla read change; the rest are made up and stay."""
    tc, bw_total, bw_s_other, fc_total, fc_s_a3 = {1: (656415, 227373, 83021, 14063, 1247),
                                                   2: (656417, 227375, 83023, 14063, 1247),
                                                   3: (656419, 227375, 83023, 14065, 1248)}[reading]
    return c4510_raw(tc, bw=(bw_total, (512, bw_s_other), (306, 71500)), fc=(fc_total, (fc_s_a3, 6100), (80, 3200)))


def c4510_raw(tc, bw, fc, single=(0, (0, 0), (0, 0)), banner=True):
    return big(tc, {"Full Color": fc, "Black &amp; White": bw, "Single Color": single}, banner=banner)


def c3000(fc=(43966, (3308, 23710), (388, 6044)), bw=(500372, (15924, 167246), (2330, 145979)), tc=1290000):
    return big(tc, {"Full Color": fc, "Black &amp; White": bw}, banner=False)


def c3004(bw=318002, fc=49919, p_bw=700000, p_fc=140076, total=1207997, other=(72281, 283975, 1)):
    page = HEAD + f"<table><tr><td>Total</td><td>:</td><td>{total}</td></tr></table>\n"
    page += (f"<h3>Copier</h3><table><tr><td>Black &amp; White</td><td>{bw}</td></tr><tr><td>Full Color</td><td>{fc}</td></tr>"
             f"<tr><td>Single Color</td><td>0</td></tr><tr><td>Two-color</td><td>0</td></tr></table>\n")
    page += (f"<h3>Printer</h3><table><tr><td>Black &amp; White</td><td>{p_bw}</td></tr><tr><td>Full Color</td><td>{p_fc}</td></tr>"
             f"<tr><td>Single Color</td><td>0</td></tr><tr><td>Two-color</td><td>0</td></tr></table>\n")
    page += "<h3>Fax</h3><table><tr><td>Black &amp; White</td><td>5</td></tr></table>"
    page += "<h3>Send/TX Total</h3><table><tr><td>Black &amp; White</td><td>9</td></tr></table>"
    page += "<h3>Fax Transmission</h3><table><tr><td>Total : 2</td></tr></table>"
    page += "<h3>Scanner Send</h3><table><tr><td>Black &amp; White</td><td>7</td></tr></table>"
    page += "<h3>Coverage</h3><table><tr><td>Full Color</td><td>Total : 1</td></tr></table>"
    page += (f"<h3>Other Function(s)</h3><table><tr><td>A3/DLT</td><td>{other[0]}</td></tr><tr><td>Duplex</td>"
             f"<td>{other[1]}</td></tr><tr><td>Banner</td><td>{other[2]}</td></tr></table>")
    return page + TAIL
