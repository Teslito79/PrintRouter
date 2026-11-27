"""make_xlsx: a small .xlsx for the import tests (zipfile + xml only)."""
import zipfile
from xml.sax.saxutils import escape


def make_xlsx(path, sheets):
    """A small .xlsx with inline strings (as Excel and LibreOffice save them, read by walkin_prices.read_xlsx)."""
    def col(i):
        return chr(65 + i)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/></Types>')
        rels = "".join(f'<Relationship Id="r{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                       f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + rels + "</Relationships>")
        names = "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="r{i}"/>' for i, n in enumerate(sheets, start=1))
        z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + names + "</sheets></workbook>")
        for i, rows in enumerate(sheets.values(), start=1):
            data = ""
            for r, row in enumerate(rows, start=1):
                cells = ""
                for c, v in enumerate(row):
                    if v is None or v == "":
                        continue
                    ref = f"{col(c)}{r}"
                    cells += (f'<c r="{ref}"><v>{v}</v></c>' if isinstance(v, (int, float))
                              else f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>')
                data += f'<row r="{r}">{cells}</row>'
            z.writestr(f"xl/worksheets/sheet{i}.xml", '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/'
                       'spreadsheetml/2006/main"><sheetData>' + data + "</sheetData></worksheet>")
