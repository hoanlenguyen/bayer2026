"""Complete source evidence from the same workbook used by the active pipeline."""
from __future__ import annotations
import hashlib
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from .datapack import workbook_path

def build_snapshot(path: Path) -> dict:
    import openpyxl
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=False)
    sheets = {}
    for sheet in workbook:
        rows, dates, formulas = [], {}, {}
        for number, row in enumerate(sheet.iter_rows(), 1):
            values = []
            for cell in row:
                value = cell.value
                if isinstance(value, (date, datetime)):
                    dates[cell.coordinate] = type(value).__name__
                    value = value.isoformat()
                if cell.data_type == "f":
                    formulas[cell.coordinate] = value
                values.append(value)
            rows.append({"row": number, "values": values})
        document = sheet.title in {"START_HERE", "Package_Overview"}
        sheets[sheet.title] = {"layout": "document" if document else "table",
            "columns": [] if document else rows[0]["values"], "rows": rows,
            "date_cells": dates, "formulas": formulas,
            "record_count": len(rows) if document else max(0, len(rows) - 1)}
    workbook.close()
    return {"schema_version": 1, "filename": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "synthetic": True, "sheets": sheets}

@lru_cache(maxsize=1)
def snapshot():
    return build_snapshot(workbook_path())

def source(sheet, row, record_id=None, fields=None):
    return {"sheet":sheet,"row":row,"record_id":record_id,"fields":fields or [],"snapshot":snapshot()["sha256"]}

@lru_cache(maxsize=None)
def records(sheet):
    s=snapshot()["sheets"][sheet]
    if s["layout"]=="document":
        return [{"values":r["values"],"_source":source(sheet,r["row"])} for r in s["rows"]]
    result=[]
    for row in s["rows"][1:]:
        data=dict(zip(s["columns"],row["values"]))
        data["_source"]=source(sheet,row["row"],data.get(s["columns"][0]))
        result.append(data)
    return result

def indexed(sheet,key):
    return {r[key]:r for r in records(sheet)}

def metadata():
    s=snapshot()
    return {"filename":s["filename"],"sha256":s["sha256"],"version":records("Change_Log")[0]["version"],
        "synthetic":True,"sheet_count":len(s["sheets"]),
        "usage_period":"January–October 2026", "sheets":{k:{"records":v["record_count"],"layout":v["layout"]} for k,v in s["sheets"].items()}}
