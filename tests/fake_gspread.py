"""Minimal in-memory stand-in for gspread: just enough of its API for the tests (no network, no Google account)."""
import copy

class WorksheetNotFound(Exception):
    pass

class FakeWorksheet:
    _next_id = 100
    def __init__(self, title, rows=1000, cols=26, sheet_id=None):
        self.title, self.row_count, self.col_count = title, rows, cols
        self.id = sheet_id if sheet_id is not None else FakeWorksheet._next_id
        FakeWorksheet._next_id += 1
        self.grid = {}      # (r, c) -> str
    def get_all_values(self):
        if not self.grid:
            return []
        R = max(r for r, c in self.grid) + 1
        C = max(c for r, c in self.grid) + 1
        return [[str(self.grid.get((r, c), "")) for c in range(C)] for r in range(R)]
    def clear(self):
        self.grid = {}
    def resize(self, rows=None, cols=None):
        self.row_count = rows or self.row_count
        self.col_count = cols or self.col_count
    def update(self, values, range_name="A1", value_input_option=None):
        assert range_name == "A1"
        for r, row in enumerate(values):
            for c, v in enumerate(row):
                if v != "":
                    self.grid[(r, c)] = v

class FakeSpreadsheet:
    def __init__(self):
        self.sheets = []
        self.charts = []          # {"chartId", "sheetId", "spec", "position"}
        self.batches = []
        self._chart_id = 5000
    def worksheet(self, title):
        for s in self.sheets:
            if s.title == title:
                return s
        raise WorksheetNotFound(title)
    def add_worksheet(self, title, rows, cols):
        s = FakeWorksheet(title, rows, cols); self.sheets.append(s); return s
    def fetch_sheet_metadata(self, params=None):
        out = []
        for s in self.sheets:
            entry = {"properties": {"sheetId": s.id}}
            if getattr(s, "tables", None):
                entry["tables"] = s.tables
            ch = [{"chartId": c["chartId"], "spec": {"title": c["spec"]["title"]}} for c in self.charts if c["sheetId"] == s.id]
            if ch:
                entry["charts"] = ch
            out.append(entry)
        return {"sheets": out}
    def batch_update(self, body):
        self.batches.append(copy.deepcopy(body))
        for req in body["requests"]:
            if "deleteEmbeddedObject" in req:
                oid = req["deleteEmbeddedObject"]["objectId"]
                assert any(c["chartId"] == oid for c in self.charts), "deleting unknown chart"
                self.charts = [c for c in self.charts if c["chartId"] != oid]
            elif "addChart" in req:
                ch = req["addChart"]["chart"]
                self._chart_id += 1
                self.charts.append({"chartId": self._chart_id, "sheetId": ch["position"]["overlayPosition"]["anchorCell"]["sheetId"],
                                    "spec": ch["spec"], "position": ch["position"]})
            elif "repeatCell" in req:
                rc = req["repeatCell"]; rg = rc["range"]
                ws = next(s for s in self.sheets if s.id == rg["sheetId"])
                ws.grid[(rg["startRowIndex"], rg["startColumnIndex"])] = rc["cell"]["userEnteredValue"]["stringValue"]

class FakeClient:
    def __init__(self, book): self.book = book
    def open_by_key(self, key): return self.book

def make_book(student_order, filled=None):
    """Sheet with tabs: חשיפה (week 1..15 tables). Columns B.. = student_order."""
    book = FakeSpreadsheet()
    ws = FakeWorksheet("חשיפה", rows=300, cols=14, sheet_id=1)
    ws.tables = []
    labels = ["日", "月", "火", "水", "木", "金", "土"]       # week starts Sunday
    for week in range(15):
        top = week * 9
        ws.grid[(top, 0)] = "曜日"
        for i, name in enumerate(student_order):
            ws.grid[(top, 1 + i)] = name
        for d, lab in enumerate(labels):
            ws.grid[(top + 1 + d, 0)] = lab
        ws.tables.append({"tableId": f"t{week}", "name": f"week {week + 1}",
                          "range": {"startRowIndex": top, "startColumnIndex": 0, "endColumnIndex": 1 + len(student_order)}})
    for (r, c), v in (filled or {}).items():
        ws.grid[(r, c)] = v
    book.sheets.append(ws)
    return book

def install(book):
    import sys, types
    mod = types.ModuleType("gspread")
    mod.WorksheetNotFound = WorksheetNotFound
    mod.service_account = lambda filename=None: FakeClient(book)
    mod.service_account_from_dict = lambda info: FakeClient(book)
    sys.modules["gspread"] = mod
