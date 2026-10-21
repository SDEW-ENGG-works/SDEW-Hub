"""Read rows from .xlsx (openpyxl) or .xls (xlrd) the same way."""
import os


def sheets(path):
    """Yields (sheet_name, row_iterator) for every sheet. Rows are lists of values."""
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as fh:
        magic = fh.read(8)
    if magic.startswith(b"PK"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for ws in wb.worksheets:
                yield ws.title, (list(r) for r in ws.iter_rows(values_only=True))
        finally:
            wb.close()
    elif magic.startswith(b"\xd0\xcf\x11\xe0") or ext == ".xls":
        import xlrd
        book = xlrd.open_workbook(path)
        for sh in book.sheets():
            def it(sh=sh):
                for r in range(sh.nrows):
                    row = []
                    for c, v in zip(sh.row_types(r), sh.row_values(r)):
                        if c == xlrd.XL_CELL_DATE:
                            try:
                                v = xlrd.xldate.xldate_as_datetime(v, book.datemode)
                            except Exception:
                                pass
                        row.append(v)
                    yield row
            yield sh.name, it()
    else:
        raise ValueError("Not an Excel file")


def header_index(row):
    return {str(v).strip(): i for i, v in enumerate(row) if v is not None and str(v).strip()}
